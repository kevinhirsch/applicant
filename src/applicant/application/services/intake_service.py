"""IntakeService — save a job from any page (P1-9, competitive: capture).

Takes ONE posting URL the user pasted (or sent via the bookmarklet), fetches the
page through the injected fetcher (the network boundary lives in
``adapters/discovery/url_intake.py``), and runs the result through the SAME
pipeline discovery results take: dedup → persist as a campaign-scoped
``JobPosting`` → viability scoring → a digest-approval pending action, so the
captured role shows up scored in Pending immediately and in the digest tagged
"added by you" (``USER_ADDED_SOURCE_KEY``).

Honesty (H-series): when the page could not actually be read (fetch disabled in
the offline lane, network failure, non-HTML response) the saved row is derived
from the URL itself and the response says so — a degraded capture never renders
as a fully-parsed one.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from applicant.core.entities.job_posting import USER_ADDED_SOURCE_KEY, JobPosting
from applicant.core.errors import InvalidInput
from applicant.core.events import JobDiscovered, event_bus
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Same near-duplicate cosine threshold DiscoveryService uses (FR-DISC-3) so a
#: pasted role that discovery already found is recognized, not double-tracked.
_DEDUP_THRESHOLD = 0.97


def _normalized_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _host(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    return host.removeprefix("www.")


def _title_from_url(url: str) -> str:
    """A readable, clearly URL-derived title when the page could not be read."""
    try:
        path = urlsplit(url).path or ""
    except ValueError:
        path = ""
    segments = [s for s in path.split("/") if s]
    slug = unquote(segments[-1]) if segments else ""
    words = [w for w in slug.replace("_", "-").split("-") if w and not w.isdigit()]
    pretty = " ".join(w.capitalize() for w in words[:10])
    host = _host(url)
    if pretty:
        return pretty
    return f"Job posting at {host}" if host else "Job posting"


class IntakeService:
    def __init__(
        self,
        storage,
        fetcher,
        embedding,
        *,
        scoring=None,
        pending_actions=None,
        criteria=None,
    ) -> None:
        self._storage = storage
        self._fetcher = fetcher
        self._embedding = embedding
        self._scoring = scoring
        self._pending = pending_actions
        self._criteria = criteria

    # --- the one use-case -------------------------------------------------
    def save_url(self, campaign_id: CampaignId, url: str) -> dict:
        """Capture one posting URL into the campaign's reviewed pipeline."""
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise InvalidInput(
                "That doesn't look like a web address I can open — paste the "
                "full link to the job posting (it should start with http:// or https://)."
            )
        existing = list(self._storage.postings.list_for_campaign(campaign_id))
        dup = self._find_url_duplicate(existing, url)
        if dup is not None:
            return self._duplicate_response(dup, reason="url")

        metadata, fetched, note = self._fetch_metadata(url)
        title = str(metadata.get("title") or "").strip() or _title_from_url(url)
        company = str(metadata.get("company") or "").strip() or (_host(url) or "unknown")

        near = self._find_near_duplicate(existing, title, company)
        if near is not None:
            return self._duplicate_response(near, reason="similar")

        posting = JobPosting(
            id=JobPostingId(new_id()),
            campaign_id=campaign_id,
            title=title,
            company=company,
            source_url=url,
            location=(str(metadata.get("location") or "").strip() or None),
            work_mode=(str(metadata.get("work_mode") or "").strip() or None),
            salary=(str(metadata.get("salary") or "").strip() or None),
            description=str(metadata.get("description") or ""),
            source_key=USER_ADDED_SOURCE_KEY,
        )
        self._storage.postings.add(posting)
        self._storage.commit()
        event_bus.emit(JobDiscovered(campaign_id=campaign_id, posting_id=posting.id))

        score, why = self._score(posting)
        self._materialize_pending(posting, score)
        return {
            "saved": True,
            "duplicate": False,
            "posting_id": str(posting.id),
            "campaign_id": str(campaign_id),
            "title": posting.title,
            "company": posting.company,
            "source": USER_ADDED_SOURCE_KEY,
            "viability_score": score,
            "why_suggested": why,
            # H-series: fetched=False + note tells the user the page itself was
            # NOT read and the row is derived from the link alone.
            "fetched": fetched,
            "note": note,
        }

    # --- helpers ------------------------------------------------------------
    def _fetch_metadata(self, url: str) -> tuple[dict, bool, str | None]:
        """(metadata, actually_read_the_page, honesty_note)."""
        try:
            metadata = self._fetcher.fetch(url) or {}
        except Exception as exc:  # noqa: BLE001 - a fetch failure degrades, honestly
            log.warning("url_intake_fetch_failed", url=url, error=str(exc))
            return {}, False, (
                "I couldn't read that page, so I saved it using the link itself. "
                "You can still review and approve it as usual."
            )
        if metadata.get("title"):
            return metadata, True, None
        return metadata, False, (
            "I couldn't read the posting's details from that page, so I saved it "
            "using the link itself. You can still review and approve it as usual."
        )

    def _find_url_duplicate(self, existing: list[JobPosting], url: str):
        target = _normalized_url(url)
        for p in existing:
            if _normalized_url(getattr(p, "source_url", "")) == target:
                return p
        return None

    def _find_near_duplicate(self, existing: list[JobPosting], title: str, company: str):
        """Same embedding near-dup check discovery runs (FR-DISC-3)."""
        sig = f"{title} {company}"
        for p in existing:
            try:
                if self._embedding.similarity(sig, f"{p.title} {p.company}") >= _DEDUP_THRESHOLD:
                    return p
            except Exception:  # pragma: no cover - a flaky embedding must not block a save
                return None
        return None

    def _duplicate_response(self, posting: JobPosting, *, reason: str) -> dict:
        score = getattr(posting, "viability_score", None)
        return {
            "saved": False,
            "duplicate": True,
            "duplicate_reason": reason,
            "posting_id": str(posting.id),
            "campaign_id": str(posting.campaign_id),
            "title": posting.title,
            "company": posting.company,
            "source": posting.source_key,
            "viability_score": (round(score * 100) if score is not None else None),
            "note": "This role is already being tracked — no second copy was created.",
        }

    def _score(self, posting: JobPosting) -> tuple[int | None, str]:
        """Score the fresh posting through the existing viability path (guarded)."""
        if self._scoring is None:
            return None, "scoring pending"
        criteria = None
        if self._criteria is not None:
            try:
                criteria = self._criteria.get_criteria(posting.campaign_id)
            except Exception:  # pragma: no cover - criteria load must not block a save
                criteria = None
        try:
            scoring = self._scoring.score_viability(posting.id, criteria)
            return round(scoring.score * 100), scoring.rationale
        except Exception:  # pragma: no cover - scoring must never lose the capture
            log.warning("url_intake_scoring_failed", posting_id=str(posting.id), exc_info=True)
            return None, "scoring pending"

    def _materialize_pending(self, posting: JobPosting, score: int | None) -> None:
        """Same digest-approval pending item the digest deliver path creates, so
        the captured role appears in Pending immediately (guarded)."""
        if self._pending is None:
            return
        try:
            self._pending.digest_approval(
                posting.campaign_id,
                posting_id=str(posting.id),
                title=f"Review: {posting.title} at {posting.company}",
                link=posting.source_url,
                score=score,
            )
        except Exception:  # pragma: no cover - the pending item is best-effort
            log.warning("url_intake_pending_failed", posting_id=str(posting.id), exc_info=True)
