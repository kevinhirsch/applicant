"""DigestService (FR-DIG-1..6, FR-FB-1).

# STAGE B — owned by Phase 1.

Builds the daily digest, delivers it across channels, and records
approve/decline-with-feedback decisions that close the learning loop:

- one **row per viable role**: summary, link, work mode, viability score, and a
  human-readable **why-suggested** rationale (FR-DIG-3/4);
- an explicit **empty-day note** when nothing cleared the bar (FR-DIG-6) so silence is
  never ambiguous, plus what was searched and why;
- **delivery** = email payload + webpage payload + a Discord "ready" ping; the digest
  is EXEMPT from the Applicant visual style — it has its own template (FR-DIG-2);
- **approve** / **decline-with-feedback** record a ``Decision`` whose feedback +
  criteria-delta round-trip into ``LearningService`` and the next run's criteria via
  ``CriteriaService`` (FR-DIG-5, FR-FB-1), and notify-idempotency expires the other
  channels (FR-NOTIF-3).
"""

from __future__ import annotations

import html
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from applicant.core.entities.application import Application
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.errors import InvalidInput, NotFound
from applicant.core.ids import ApplicationId, CampaignId, DecisionId, JobPostingId, new_id
from applicant.core.rules.jd_match import compute_jd_match
from applicant.core.state_machine import ApplicationState
from applicant.observability.logging import get_logger

log = get_logger(__name__)

EMPTY_DAY_NOTE = "No new viable roles today — criteria unchanged, discovery still running."

#: Rolling lookback window for the weekly recap (audit Top-25 #18): "applications
#: sent" + "best-performing source" over the trailing 7 days, delivered through the
#: SAME notification fan-out the daily digest already uses (reuse, not a second
#: pipeline). Scheduling/idempotency for the weekly cadence live in the scheduler,
#: mirroring the daily digest guard (IDEM-1) and the status-update/essentials-nudge
#: per-day guards.
RECAP_WINDOW_DAYS = 7

#: Cap on how many role rows the digest EMAIL renders inline. A campaign can
#: surface 1000+ viable roles; rendering one HTML row each makes a multi-MB email
#: that mail clients truncate and that is slow to build. We render the top-N by
#: viability score (desc) and append a footer pointing at the portal for the rest.
MAX_EMAIL_ROWS = 50

#: URL schemes safe to emit as a clickable anchor href in the digest. Anything
#: else (``javascript:``, ``data:``, ``vbscript:`` ...) is neutralized so a
#: scraped ``source_url`` cannot smuggle a script-executing link (SECURITY).
_SAFE_URL_SCHEMES = ("http://", "https://")


def _safe_href(url) -> str:
    """Return an http/https-only, HTML-escaped href, or ``#`` if disallowed.

    The link comes from untrusted scraped rows (JobSpy/SearXNG/RSS) so a
    ``javascript:``/``data:`` scheme must never reach the emitted anchor.
    """
    raw = str(url or "").strip()
    if raw.lower().startswith(_SAFE_URL_SCHEMES):
        return html.escape(raw, quote=True)
    return "#"


def _subject_safe(text: str) -> str:
    """Collapse whitespace/newlines so scraped title/company can't smuggle a
    second header line (mail header injection) into the digest subject."""
    return " ".join(str(text or "").split())


def _digest_subject(payload: dict, top_row: dict | None) -> str:
    """Lens 10 #30: an informative digest subject instead of always the same string.

    Degrades gracefully with what ``build_digest_payload``/``render_email`` already
    have in hand (row count + the highest-scored row) — no re-query, no new
    dependency: zero matches keeps the existing empty-day variant, one match uses
    singular grammar, and 2+ matches lead with the count and name the top match's
    role/company so ten digests in an inbox are no longer indistinguishable.
    """
    if payload["empty"]:
        return "Daily digest — no new matches today"
    count = len(payload["rows"])
    noun = "match" if count == 1 else "matches"
    subject = f"Your daily digest — {count} new {noun}"
    if top_row:
        title = _subject_safe(top_row.get("title") or "")
        company = _subject_safe(top_row.get("company") or "")
        top_match = f"{title} at {company}".strip() if title and company else title or company
        if top_match:
            subject += f" (top: {top_match})"
    return subject


def _preheader_html(text: str, *, already_escaped: bool = False) -> str:
    """Hidden preview-text span (audit lens 10 #31).

    Most inbox lists (Gmail, Outlook, Apple Mail...) show a short snippet next
    to the subject, taken from the first bit of visible text in the body. With
    no preheader that snippet is whatever raw markup happens to render first;
    this hides a short, deliberate summary so the inbox preview is useful.
    Zero size/opacity + ``mso-hide`` keeps it invisible in the rendered body
    while mail clients' snippet logic still reads it.
    """
    safe = text if already_escaped else html.escape(str(text or ""))
    return (
        "<span style='display:none;font-size:0;line-height:0;max-height:0;"
        "max-width:0;opacity:0;overflow:hidden;mso-hide:all;'>"
        f"{safe}</span>"
    )


def _criteria_fingerprint(criteria: SearchCriteria | None) -> tuple | None:
    """Cheap, hashable snapshot of the criteria fields a score depends on.

    Pure in-memory comparison (no IO) so a mid-day criteria edit invalidates the
    ``DigestCache`` entry on the very next call instead of serving scores built
    against the old criteria until midnight.
    """
    if criteria is None:
        return None
    adjustments = getattr(criteria, "learned_adjustments", None) or {}
    return (
        criteria.human_readable,
        criteria.titles,
        criteria.locations,
        criteria.work_modes,
        criteria.salary_floor,
        criteria.keywords,
        tuple(sorted(adjustments.items())),
    )


@dataclass
class DigestCache:
    """Process-lived cache of BUILT digest rows, keyed per campaign (perf audit #6).

    ``build_digest`` loops every posting in the campaign and scores each one —
    the docstring on the row-building path itself anticipates "1000+ viable
    roles" — on EVERY ``GET /api/digest/{campaign_id}``, which the Portal loads
    on every open. Even when ``ScoringService.score_for_digest`` reuses a
    persisted score (unchanged criteria), it still recomputes ``_learning_sig``
    per posting, which loads the campaign's learning model from storage once per
    ROW — an unbounded per-request query fan-out that scales with campaign size.

    A digest does not need to be rebuilt more than once per campaign per day
    under normal circumstances: new postings arrive via the scheduler's
    discovery tick, not synchronously with a GET. This cache stores the scored
    ``(posting, row-without-warnings)`` pairs for a campaign and reuses them
    across calls within the SAME UTC day, for the SAME posting count, for the
    SAME criteria — any of those changing (day rolls over, a new posting lands,
    the user edits criteria) invalidates the entry and the next call rebuilds.

    Deliberately EXCLUDES the presubmit-safety warnings (see
    ``DigestService._presubmit_warnings``) — those are recomputed fresh on
    every single call, cache hit or not, because they read OTHER mutable state
    (the campaign's own applications) that can change intraday as the
    autonomous loop submits approved roles; caching them could serve a stale
    "no warning" and hide a real duplicate-application/scam signal.

    ``DigestService`` is rebuilt every request (CONC-REQ-1,
    ``container._build_request_services``) and every scheduler tick
    (``container._build_tick_services``), so an instance attribute would reset
    on every single call — the exact failure mode CLAUDE.md documents for the
    resume backoff ledger (``ResumeLedger``) and the digest-delivery guard
    (``DigestLedger``) in ``agent_loop.py``. Like those, ONE ``DigestCache``
    lives for the whole process (built in ``container.py``) and is injected
    into every ``DigestService`` construction site.
    """

    _entries: dict[str, tuple[date, int, tuple | None, list]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def get(
        self, campaign_id, *, day: date, count: int, criteria_fp: tuple | None
    ) -> list | None:
        with self.lock:
            entry = self._entries.get(str(campaign_id))
        if entry is None:
            return None
        e_day, e_count, e_fp, pairs = entry
        if e_day == day and e_count == count and e_fp == criteria_fp:
            return pairs
        return None

    def put(
        self,
        campaign_id,
        *,
        day: date,
        count: int,
        criteria_fp: tuple | None,
        pairs: list,
    ) -> None:
        with self.lock:
            self._entries[str(campaign_id)] = (day, count, criteria_fp, pairs)


class DigestService:
    def __init__(
        self,
        storage,
        notification,
        scoring=None,
        *,
        learning=None,
        criteria=None,
        notification_service=None,
        pending_actions=None,
        presubmit_safety_params: dict | None = None,
        digest_cache: DigestCache | None = None,
    ) -> None:
        self._storage = storage
        self._notification = notification
        self._scoring = scoring
        self._learning = learning
        self._criteria = criteria
        self._notification_service = notification_service
        self._pending = pending_actions
        # G07: same settings-driven thresholds AgentLoop's presubmit safety gate uses
        # (container.py builds ONE dict and threads it to both) so a digest warning
        # reflects the SAME operator-configured age/cooldown as the pipeline block —
        # not a silently-stale hardcoded default. ``None`` (legacy/test callers that
        # don't pass it) falls back to presubmit_safety's own module defaults.
        self._presubmit_safety_params = presubmit_safety_params
        # #6 (perf audit): container.py builds ONE process-lived DigestCache and
        # threads it here so a cache hit survives the per-request/per-tick rebuild
        # (see DigestCache's docstring). A caller that doesn't pass one (most unit
        # tests, and any legacy construction site) gets a private instance-local
        # cache — correct in isolation, it just can't be shared across separate
        # DigestService instances, so those call sites see the pre-existing
        # every-call-is-fresh behavior in practice.
        self._digest_cache = digest_cache if digest_cache is not None else DigestCache()

    # --- digest assembly (FR-DIG-3/4) -------------------------------------
    def _resolve_criteria(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None
    ) -> SearchCriteria | None:
        """Load the campaign's saved criteria when a caller omits it (FR-DIG-3/4).

        The front-door ``GET /api/digest/{id}`` and ``render_webpage`` build the
        digest without threading criteria, so without this fallback every posting
        was re-scored against *no* criteria — a uniform neutral 75 that ignored the
        onboarding-seeded + learned search criteria entirely (the same failure the
        agent loop's ``_criteria_for`` already guards against). Resolve it from the
        injected criteria service; a load failure degrades to ``None`` (neutral)
        rather than 500-ing the digest hot path.
        """
        if criteria is not None or self._criteria is None:
            return criteria
        try:
            return self._criteria.get_criteria(campaign_id)
        except Exception:
            return None

    def build_digest(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None = None
    ) -> list[dict]:
        """Assemble digest rows for every viable posting in the campaign.

        #6 (perf audit): the expensive part — fetching every posting and scoring
        it — is cached per (campaign, day, posting count, criteria) via
        ``DigestCache`` (see its docstring for why an instance attribute cannot
        do this and why the cache key is what it is). A cache HIT skips
        ``list_for_campaign`` and every ``score_fn`` call entirely.

        The presubmit-safety ``warnings`` are the one part deliberately NOT
        cached: they are recomputed fresh on every call, cache hit or not,
        because ``check_duplicate_application`` reads the campaign's OTHER
        applications, which can flip from "not a duplicate" to "duplicate"
        intraday as the autonomous loop submits approved roles — caching a
        "no warning" verdict could hide a real one for the rest of the day.
        """
        criteria = self._resolve_criteria(campaign_id, criteria)
        rows: list[dict] = []
        for posting, row in self._scored_pairs(campaign_id, criteria):
            row = dict(row)
            # Product-gaps backlog: the duplicate-application guard and the
            # scam/ghost-job check already exist (presubmit_safety.py) but were only
            # invoked by AgentLoop._process_approvals — AFTER the user approves, right
            # before the pipeline starts — and only to silently skip. That is too late
            # to inform the decision: surface the SAME checks here, read-only, so the
            # digest row itself carries a plain-language warning BEFORE approval. A
            # warning never excludes a row from the digest (unlike the pipeline block).
            row["warnings"] = self._presubmit_warnings(campaign_id, posting)
            rows.append(row)
        return rows

    def _scored_pairs(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None
    ) -> list[tuple]:
        """``(posting, row-without-warnings)`` pairs, cache-checked per campaign.

        Falls back to an uncached rebuild whenever the storage adapter doesn't
        expose ``postings.count_for_campaign`` (some lightweight test double) —
        degrades to the pre-cache behavior rather than raising, since the
        fingerprint is the cache's freshness check, not a correctness
        requirement of the row-building logic itself.
        """
        cache = self._digest_cache
        count_fn = (
            getattr(self._storage.postings, "count_for_campaign", None)
            if cache is not None
            else None
        )
        if cache is None or count_fn is None:
            return self._build_scored_pairs(campaign_id, criteria)
        day = datetime.now(UTC).date()
        count = count_fn(campaign_id)
        criteria_fp = _criteria_fingerprint(criteria)
        cached = cache.get(campaign_id, day=day, count=count, criteria_fp=criteria_fp)
        if cached is not None:
            return cached
        pairs = self._build_scored_pairs(campaign_id, criteria)
        cache.put(campaign_id, day=day, count=count, criteria_fp=criteria_fp, pairs=pairs)
        return pairs

    def _build_scored_pairs(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None
    ) -> list[tuple]:
        """Fetch + score every posting in the campaign (the actual hot-path cost)."""
        postings = self._storage.postings.list_for_campaign(campaign_id)
        # P1-8: the candidate's own résumé/profile text, read ONCE per build (this
        # method only runs on a DigestCache miss) so every row can carry the
        # deterministic keyword-coverage chip without a per-row profile query.
        resume_text = self._profile_resume_text(campaign_id)
        pairs: list[tuple] = []
        for posting in postings:
            row = {
                "posting_id": posting.id,
                "title": posting.title,
                "company": posting.company,
                "summary": f"{posting.title} at {posting.company}",
                "link": posting.source_url,
                "work_mode": posting.work_mode,
                "salary": posting.salary,
                "source": posting.source_key,
            }
            if self._scoring is not None:
                # Prefer the reuse-aware digest scorer (bounds LLM cost across repeated
                # digest GETs); fall back to plain score_posting for lightweight doubles.
                score_fn = getattr(self._scoring, "score_for_digest", None) or self._scoring.score_posting
                scoring = score_fn(posting, criteria)
                if not self._scoring.is_viable(scoring):
                    continue  # below threshold; excluded from the digest (FR-AGENT-3)
                row["viability_score"] = round(scoring.score * 100)
                row["why_suggested"] = scoring.rationale
            else:
                # ROBUST: ``JobPostingModel.viability_score`` is nullable and the
                # no-scoring branch has no score yet. Emit a numeric 0.0 (not None) so
                # any downstream numeric comparison / sort on this row's score never
                # raises ``TypeError: '>=' not supported between ... and NoneType`` on
                # the digest hot path. The rationale still says scoring is pending.
                row["viability_score"] = 0.0
                row["why_suggested"] = "scoring pending"
            self._attach_keyword_match(row, posting, resume_text)
            pairs.append((posting, row))
        return pairs

    def _profile_resume_text(self, campaign_id: CampaignId) -> str:
        """The candidate's own résumé/profile text for keyword coverage (P1-8).

        Mirrors ``MaterialService``'s ground-truth accessors — the uploaded base
        résumé's raw text plus the flattened attribute-cloud values — without
        pulling the whole material stack into the digest. Best-effort: any failure
        degrades to ``""`` so the digest hot path never breaks; an empty result
        means the coverage chip is simply OMITTED (no résumé on file must render
        as no coverage claim, never as a fabricated 0%).
        """
        parts: list[str] = []
        repo = getattr(self._storage, "onboarding_profiles", None)
        if repo is not None:
            try:
                profile = repo.get_for_campaign(campaign_id)
                intake = getattr(profile, "intake", None) or {}
                base = intake.get("base_resume", {}) if isinstance(intake, dict) else {}
                parts.append(str(base.get("raw_text", "") or ""))
            except Exception:  # pragma: no cover - defensive; never break the digest
                pass
        attrs_repo = getattr(self._storage, "attributes", None)
        if attrs_repo is not None:
            try:
                for attr in attrs_repo.list_for_campaign(campaign_id):
                    val = getattr(attr, "value", None)
                    if val:
                        parts.append(str(val))
            except Exception:  # pragma: no cover - defensive; never break the digest
                pass
        return "\n".join(p for p in parts if p).strip()

    def _attach_keyword_match(self, row: dict, posting, resume_text: str) -> None:
        """Deterministic résumé <-> JD keyword coverage for one digest row (P1-8).

        Reuses the SAME pure ``core.rules.jd_match`` scorer the redline review's
        match line already uses (no LLM, no fabrication risk), computed alongside
        the model-driven viability score so the digest card can show BOTH "how
        well this role fits you" and "how well your résumé covers its keywords".
        Attached only when there is a résumé on file AND the posting yields at
        least one extractable keyword — an absent chip is honest absence, never a
        fabricated score (H-series). Guarded: a failure only omits the chip.
        """
        if not resume_text:
            return
        try:
            posting_text = (
                f"{getattr(posting, 'title', '') or ''}\n"
                f"{getattr(posting, 'description', '') or ''}"
            )
            match = compute_jd_match(resume_text, posting_text)
            # Shape-guard INSIDE the try: a malformed/None matcher result for
            # one posting must only omit that row's chip — the caller's loop has
            # no per-posting guard, so an escaped KeyError here would abort the
            # digest for EVERY posting in the campaign.
            matched = match.get("matched") if isinstance(match, dict) else None
            missing = match.get("missing") if isinstance(match, dict) else None
            score = match.get("score") if isinstance(match, dict) else None
        except Exception:  # pragma: no cover - defensive; never break the digest
            log.warning("digest_keyword_match_failed", exc_info=True)
            return
        if not matched and not missing:
            return  # no extractable keywords -> no chip (never a fabricated 0%)
        row["keyword_coverage"] = score
        row["keyword_matched"] = matched
        row["keyword_missing"] = missing

    def _presubmit_warnings(self, campaign_id: CampaignId, posting) -> list[dict]:
        """Human-readable presubmit-safety warnings for one digest row.

        Reuses ALL FOUR ``presubmit_safety`` checks unchanged (same reasons/
        thresholds/param keys ``AgentLoop._process_approvals`` enforces at
        pipeline-start — see that call site) but catches ``PresubmitBlock``
        instead of letting it stop anything — a digest warning informs, it does
        not block. Any unexpected failure degrades to "no warning" rather than
        breaking the digest hot path (mirrors every other best-effort branch in
        this file).

        Dark-engine audit #43: ``check_per_company_volume_cap`` / ``check_eligibility``
        were already fully implemented and already wired into the pipeline-start
        gate, but — like the scam/duplicate checks before this file's first pass —
        were never surfaced as a pre-approval signal. This closes that gap the
        same way: read-only, additive to the two checks already wired here.
        """
        from applicant.application.services.presubmit_safety import (
            PresubmitBlock,
            check_duplicate_application,
            check_eligibility,
            check_per_company_volume_cap,
            check_scam_or_ghost_job,
        )

        params = self._presubmit_safety_params or {}
        warnings: list[dict] = []
        try:
            check_scam_or_ghost_job(
                posting, max_age_days=params.get("max_age_days", 90)
            )
        except PresubmitBlock as exc:
            warnings.append({"check": exc.check, "message": exc.reason})
        except Exception:  # pragma: no cover - defensive
            log.warning("digest_presubmit_scam_check_failed", exc_info=True)
        try:
            check_duplicate_application(
                campaign_id,
                posting,
                self._storage,
                cooldown_days=params.get("duplicate_cooldown_days", 30),
            )
        except PresubmitBlock as exc:
            warnings.append({"check": exc.check, "message": exc.reason})
        except Exception:  # pragma: no cover - defensive
            log.warning("digest_presubmit_duplicate_check_failed", exc_info=True)
        try:
            check_per_company_volume_cap(
                campaign_id,
                posting,
                self._storage,
                max_per_day=params.get("max_apps_per_company_per_day", 3),
            )
        except PresubmitBlock as exc:
            warnings.append({"check": exc.check, "message": exc.reason})
        except Exception:  # pragma: no cover - defensive
            log.warning("digest_presubmit_volume_cap_check_failed", exc_info=True)
        # Mirrors AgentLoop: eligibility is the one check gated behind a settings
        # flag (an operator may not have filled in work-authorization intake yet,
        # in which case the check would just be noise).
        if params.get("eligibility_enabled", True):
            try:
                check_eligibility(campaign_id, posting, self._storage)
            except PresubmitBlock as exc:
                warnings.append({"check": exc.check, "message": exc.reason})
            except Exception:  # pragma: no cover - defensive
                log.warning("digest_presubmit_eligibility_check_failed", exc_info=True)
        return warnings

    def build_digest_payload(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None = None
    ) -> dict:
        """Full digest payload incl. the empty-day note (FR-DIG-6)."""
        criteria = self._resolve_criteria(campaign_id, criteria)
        rows = self.build_digest(campaign_id, criteria)
        searched = self._searched_summary(campaign_id, criteria)
        return {
            "campaign_id": campaign_id,
            "rows": rows,
            "empty": not rows,
            "note": (
                f"{EMPTY_DAY_NOTE} Searched: {searched}." if not rows else None
            ),
            "searched": searched,
        }

    def _searched_summary(
        self, campaign_id: CampaignId, criteria: SearchCriteria | None
    ) -> str:
        """A short 'here's what I searched and why' line for the empty-day note."""
        sources = [
            s.source_key
            for s in self._storage.discovery_sources.list_for_campaign(campaign_id)
            if s.enabled
        ]
        titles = list(criteria.titles) if criteria else []
        bits = []
        if titles:
            bits.append("titles=" + ", ".join(titles))
        if sources:
            bits.append("sources=" + ", ".join(sorted(sources)))
        return "; ".join(bits) or "default criteria across the enabled sources"

    # --- delivery (FR-DIG-1/2) --------------------------------------------
    def render_email(self, campaign_id: CampaignId, criteria=None, *, payload: dict | None = None) -> dict:
        """Email payload — its OWN template, exempt from the Applicant style (FR-DIG-2).

        #13: accepts an already-built ``payload`` so ``deliver`` builds + scores the
        digest ONCE and passes it in, instead of ``render_email`` re-scoring the full
        set a second time per delivery.

        Lens 10 #31 / P1-4: the body is an INLINE-styled, single-column, branded
        card list — no ``<style>`` block (mail clients strip those) and no flex/grid
        (mail clients don't support either); table-based layout is kept for the
        widest client compatibility. A hidden preheader span leads the body so the
        inbox-list preview text is a real summary. P1-4 polish: an "Applicant"
        masthead, a lead summary line, and a footer explaining where these matches
        came from and where to change delivery (Settings → Notifications) — so the
        daily email reads as a product, not a dump (it doubles as the marketing
        asset for the launch material).

        NOTE for tests/consumers: each role card opens with the literal ``<tr><td>``
        marker (no attributes) and every wrapper cell carries attributes, so
        ``html.count("<tr><td>")`` remains an exact card count.
        """
        if payload is None:
            payload = self.build_digest_payload(campaign_id, criteria)
        lines: list[str] = []
        top_row: dict | None = None
        # Shared shell: neutral canvas, centered 640px column, text masthead.
        shell_open = (
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
            "border='0' style='width:100%;background-color:#f4f5f6;'>"
            "<tr><td align='center' style='padding:24px 12px;'>"
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
            "border='0' style='width:100%;max-width:640px;font-family:Arial,Helvetica,"
            "sans-serif;text-align:left;'>"
            "<tr><td style='padding:0 6px 14px;'>"
            "<span style='font-size:18px;font-weight:bold;color:#111111;"
            "letter-spacing:0.4px;'>Applicant</span>"
            "<span style='font-size:12px;color:#8a8f98;'> &nbsp;&middot;&nbsp; "
            "your job search, working for you</span>"
            "</td></tr>"
            "<tr><td style='background-color:#ffffff;border:1px solid #e4e6ea;"
            "border-radius:10px;padding:22px;'>"
        )
        shell_close = (
            "</td></tr>"
            "<tr><td style='padding:14px 6px 0;font-size:11.5px;line-height:1.6;"
            "color:#8a8f98;'>"
            "Applicant searched your enabled sources against your criteria and "
            "scored every role before it reached you. Nothing is ever submitted "
            "without your approval. Change how — and when — these updates reach "
            "you in Settings &rarr; Notifications."
            "</td></tr>"
            "</table>"
            "</td></tr></table>"
        )
        heading = (
            "<h1 style='margin:0 0 6px;font-size:20px;line-height:1.3;"
            "color:#111111;'>Your daily digest</h1>"
        )
        if payload["empty"]:
            note = str(payload["note"] or "")
            lines.append(_preheader_html(note))
            lines.append(shell_open)
            lines.append(heading)
            lines.append(
                "<p style='margin:0;font-size:13.5px;line-height:1.6;color:#555555;'>"
                f"<em>{html.escape(note)}</em></p>"
            )
            lines.append(shell_close)
        else:
            all_rows = payload["rows"]
            total = len(all_rows)
            # Cap the inline table to the top-N rows by viability score (desc) so a
            # campaign with 1000+ viable roles never renders a multi-MB email. The
            # remainder is reachable in the portal (footer line below). ``sorted`` is
            # stable, so ties keep build_digest order. Scores may be float or int.
            top_rows = sorted(
                all_rows,
                key=lambda r: float(r.get("viability_score") or 0),
                reverse=True,
            )[:MAX_EMAIL_ROWS]
            # lens 10 #30: the highest-scored row also seeds the subject line's
            # "top match" callout below — reuse the SAME sort instead of a second pass.
            top_row = top_rows[0] if top_rows else None
            first_summary = html.escape(str(top_rows[0]["summary"] or "")) if top_rows else ""
            preheader = f"{total} new role match{'es' if total != 1 else ''} today" + (
                f" — including {first_summary}." if first_summary else "."
            )
            lines.append(_preheader_html(preheader, already_escaped=True))
            lines.append(shell_open)
            lines.append(heading)
            noun = "role cleared" if total == 1 else "roles cleared"
            lines.append(
                "<p style='margin:0 0 16px;font-size:13.5px;line-height:1.6;"
                f"color:#555555;'>{total} new {noun} your bar today — the best "
                "matches are below, ranked by score. Review and approve them in "
                "the app; nothing goes out without you.</p>"
            )
            lines.append(
                "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
                "border='0' style='width:100%;'>"
            )
            for r in top_rows:
                # SECURITY: every interpolated cell is untrusted scraped data
                # (title/company/rationale/work-mode/url) so escape it and bound
                # the href to an http/https allowlist — no stored XSS in the
                # emailed/rendered digest.
                summary = html.escape(str(r["summary"] or ""))
                work_mode = html.escape(str(r["work_mode"] or "-"))
                score = html.escape(str(r["viability_score"]))
                why = html.escape(str(r["why_suggested"] or ""))
                href = _safe_href(r["link"])
                lines.append(
                    "<tr><td>"
                    "<table role='presentation' width='100%' cellpadding='0' "
                    "cellspacing='0' border='0' style='width:100%;margin:0 0 12px;"
                    "border:1px solid #dddddd;border-radius:8px;'>"
                    "<tr><td style='padding:16px;'>"
                    f"<div style='font-size:16px;font-weight:bold;color:#111111;'>{summary}</div>"
                    "<div style='font-size:13px;color:#555555;margin:4px 0 0;'>"
                    f"{work_mode} &middot; Score {score}</div>"
                    f"<div style='font-size:13px;color:#555555;margin:4px 0 0;'>{why}</div>"
                    "<div style='margin:12px 0 0;'>"
                    f"<a href='{href}' style='display:inline-block;padding:8px 14px;"
                    "background-color:#2f6fed;color:#ffffff;text-decoration:none;"
                    "border-radius:4px;font-size:13px;'>Open role</a>"
                    "</div>"
                    "</td></tr>"
                    "</table>"
                    "</td></tr>"
                )
            lines.append("</table>")
            # Footer: when more roles cleared the bar than we rendered, point the
            # reader at the portal for the rest instead of bloating the email.
            if total > MAX_EMAIL_ROWS:
                remaining = total - MAX_EMAIL_ROWS
                lines.append(
                    "<p style='font-size:13px;color:#555555;'><em>"
                    f"Showing the top {MAX_EMAIL_ROWS} of {total} matches "
                    f"by score — view the remaining {remaining} in the portal."
                    "</em></p>"
                )
            lines.append(shell_close)
        return {
            "subject": _digest_subject(payload, top_row),
            "html": "\n".join(lines),
            "campaign_id": campaign_id,
            "row_count": len(payload["rows"]),
        }

    def render_webpage(self, campaign_id: CampaignId, criteria=None) -> dict:
        """Webpage payload (rows + note) — own digest template (FR-DIG-2)."""
        return self.build_digest_payload(campaign_id, criteria)

    def deliver(self, campaign_id: CampaignId, criteria=None) -> dict:
        """Deliver the digest: SEND the email + webpage + a Discord 'ready' ping (FR-DIG-2).

        The rendered email body is actually pushed through the notification port's
        email channel (no longer pull-only) alongside the webpage payload and the
        Discord/in-app ready ping. Also materializes a digest-approval pending action
        per viable row so the portal lists them (FR-UI-3). Returns the assembled
        payloads + the notify handle + whether the email was sent.
        """
        # #13: build + score the digest ONCE and reuse the payload for the email body
        # (previously ``render_email`` re-built + re-scored the full set per delivery).
        payload = self.build_digest_payload(campaign_id, criteria)
        email = self.render_email(campaign_id, criteria, payload=payload)
        # Materialize the durable per-row pending actions BEFORE any external ping
        # (FR-UI-3): the portal items must survive even if a notifier/email send
        # raises, so the "ready" ping never points at a digest with no acted-on
        # rows persisted.
        if self._pending is not None:
            # The digest row is a POSTING, not an Application — no application row
            # exists yet, so ``application_id`` stays ``None`` (a posting id would
            # IntegrityError on Postgres: no matching ``applications.id``).
            # perf lens 03 #32: one query + one commit for the WHOLE batch of viable
            # rows, instead of one dedup SELECT + one commit per row
            # (``materialize_digest_approvals`` reuses the exact dedup key / shape
            # ``digest_approval`` -> ``materialize`` would have produced per row).
            self._pending.materialize_digest_approvals(campaign_id, payload["rows"])
        handle = None
        email_sent = False
        if self._notification_service is not None:
            try:
                handle = self._notification_service.notify_digest_ready(
                    str(campaign_id), count=len(payload["rows"])
                )
                # Actually send the rendered email body to the email channel (FR-DIG-2).
                # IDEM-1: a per-(campaign, UTC day) dedup key makes the email send
                # idempotent so a re-driven/duplicate delivery never sends two digest
                # emails for the same campaign+day.
                from datetime import UTC, datetime

                dedup_key = (
                    f"digest_email:{campaign_id}:{datetime.now(UTC).date().isoformat()}"
                )
                email_sent = self._notification_service.send_digest_email(
                    subject=email["subject"],
                    html=email["html"],
                    deep_link=f"/digest?campaign={campaign_id}",
                    dedup_key=dedup_key,
                )
            except Exception:  # external send must not break digest delivery
                log.warning("digest_deliver_notify_failed", exc_info=True)
        return {
            "payload": payload,
            "email": email,
            "email_sent": email_sent,
            "notify_handle": handle,
            "delivered_channels": (
                self._notification.configured_channels()
                if hasattr(self._notification, "configured_channels")
                else []
            ),
        }

    # --- decisions (FR-DIG-3/5, FR-FB-1) ----------------------------------
    def _application_for(self, target_id, *, status: ApplicationState) -> ApplicationId:
        """Resolve a digest target to a real application row (FR-DIG-3).

        Digest rows are POSTINGS until pursued, so the front-door approve/decline
        sends a *posting* id. A ``Decision`` needs an existing ``applications`` row
        (its FK), so a not-yet-pursued posting must be promoted to an application
        first — otherwise the decision insert hits a foreign-key violation (-> 500).
        If ``target_id`` is already an application, it is returned unchanged (status
        untouched). If it is a posting, find-or-create its application at ``status``
        (APPROVED so the loop pursues it, or DECLINED for a terminal decline),
        mirroring AgentLoop._ensure_application. Unknown id -> NotFound (404).
        """
        if self._storage.applications.get(target_id) is not None:
            return target_id  # already an application
        posting = self._storage.postings.get(JobPostingId(str(target_id)))
        if posting is None:
            raise NotFound(f"No posting or application for id '{target_id}'.")
        existing = self._storage.applications.get_by_posting(posting.campaign_id, posting.id)
        if existing is not None:
            return existing.id
        app = Application(
            id=ApplicationId(new_id()),
            campaign_id=posting.campaign_id,
            posting_id=posting.id,
            status=status,
            job_title=posting.title,
            work_mode=posting.work_mode,
            root_url=posting.source_url,
        )
        self._storage.applications.add(app)
        self._storage.commit()
        return app.id

    def approve(self, application_id: ApplicationId) -> Decision:
        app_id = self._application_for(application_id, status=ApplicationState.APPROVED)
        decision = Decision(
            id=DecisionId(new_id()),
            application_id=app_id,
            type=DecisionType.APPROVE,
        )
        self._storage.decisions.add(decision)
        self._storage.commit()
        self._close_loop(decision, target_id=application_id)
        return decision

    def decline(
        self,
        application_id: ApplicationId,
        feedback_text: str = "",
        criteria_delta: dict | None = None,
    ) -> Decision:
        """Record a decline carrying feedback + a criteria delta for learning.

        FR-FB-1: decline feedback is MANDATORY — a blank/whitespace-only feedback
        text is rejected so the learning loop never closes on silent declines.
        """
        if not feedback_text or not feedback_text.strip():
            # FR-FB-1 (MINOR): raise the domain ``InvalidInput`` so the global handler
            # maps it (422), instead of a plain ``ValueError`` that would surface as 500.
            raise InvalidInput(
                "Decline feedback is required: say briefly why this role "
                "is not a fit so the next run learns."
            )
        app_id = self._application_for(application_id, status=ApplicationState.DECLINED)
        decision = Decision(
            id=DecisionId(new_id()),
            application_id=app_id,
            type=DecisionType.DECLINE,
            feedback_text=feedback_text,
            criteria_delta=criteria_delta or {},
        )
        self._storage.decisions.add(decision)
        self._storage.commit()
        self._close_loop(decision, target_id=application_id)
        return decision

    # --- close the learning + criteria + idempotency loop -----------------
    def _close_loop(self, decision: Decision, *, target_id: ApplicationId | None = None) -> None:
        """Run the post-commit side effects guarded so none can 500 the request.

        The ``Decision`` is already committed by the caller. Notifier idempotency,
        pending-action resolution, and learning/criteria are best-effort: a
        downstream failure must NOT leave the loop half-closed or surface a 500
        (mirrors SubmissionService's "learning must never break the action"). Each
        independent side effect is isolated so one failure can't skip the others.

        ``target_id`` is the id the user actually acted on — the digest POSTING id, on
        which ``deliver`` keyed the pending action + notification. It is distinct from
        ``decision.application_id`` (the promoted application row that satisfies the
        Decision FK), so pending/notification/campaign are resolved by ``target_id``
        to still match; learning reads ``decision`` (which resolves either id).
        """
        resolve_id = target_id if target_id is not None else decision.application_id
        campaign_id = self._campaign_for_decision(resolve_id)
        # Idempotency: acting expires the other channels (FR-NOTIF-3).
        if self._notification_service is not None:
            try:
                self._notification_service.acted(str(resolve_id))
                # Acting on any digest item also expires the campaign's digest-ready
                # ping, whose dedup key is per-campaign (FR-NOTIF-3/FR-DIG-2).
                if campaign_id is not None:
                    self._notification_service.acted_digest(str(campaign_id))
            except Exception:  # pragma: no cover - defensive; notifier must not 500
                log.warning("digest_close_loop_notify_failed", exc_info=True)
        # Resolve the digest-approval pending item (FR-UI-3). The digest row id the
        # user acts on is the POSTING id (the same id ``deliver`` keys the pending
        # action on), not the promoted application row — so resolve by ``target_id``.
        if self._pending is not None and campaign_id is not None:
            try:
                self._pending.resolve_by_dedup(
                    campaign_id, f"digest_approval:{resolve_id}"
                )
            except Exception:  # pragma: no cover - defensive
                log.warning("digest_close_loop_pending_failed", exc_info=True)
        try:
            if decision.type is DecisionType.APPROVE:
                self._record_approval_yield(decision)
                # FR-LEARN-2: fold the approved posting's features as a POSITIVE taste
                # decision so feature_stats accrues ``...:approve`` buckets, not just
                # the source-yield approvals leg + decline buckets.
                self._learn_from_approval(decision)
            if decision.type is DecisionType.DECLINE:
                self._learn_from_decline(decision)
        except Exception:  # learning must never break the recorded decision
            log.warning("digest_close_loop_learning_failed", exc_info=True)

    def _record_approval_yield(self, decision: Decision) -> None:
        """Record the APPROVALS leg of the source-yield funnel (FR-DISC-5/FR-LEARN-6).

        A digest approval is keyed on the posting id; resolve its source so the
        learned per-source weight reflects real approvals, not just raw matches.
        """
        if self._learning is None:
            return
        source_key, campaign_id = self._source_for_decision(decision.application_id)
        if source_key and campaign_id is not None:
            self._learning.record_source_event(campaign_id, source_key, "approvals")

    def _learn_from_approval(self, decision: Decision) -> None:
        """Fold the approved posting's features as a POSITIVE taste decision (FR-LEARN-2).

        Mirrors how a decline folds a NEGATIVE taste signal, but ``approved=True`` so
        per-feature ``...:approve`` buckets accrue for the flavor of role the user keeps
        approving. Routed through the per-campaign-locked atomic fold (Batch F) so this
        load->fold->persist can't lose-update against a concurrent funnel/decline fold.
        """
        if self._learning is None:
            return
        posting, campaign_id = self._posting_for_decision(decision.application_id)
        if posting is None or campaign_id is None:
            return
        features = self._posting_features(posting)
        if not features:
            return
        atomic = getattr(self._learning, "fold_decision_atomic", None)
        if atomic is not None:
            atomic(campaign_id, approved=True, features=features)
        else:  # pragma: no cover - all wired learning services expose the atomic API
            model = self._learning.load_model(campaign_id)
            model = self._learning.record_decision(model, approved=True, features=features)
            self._learning.persist_model(model)

    @staticmethod
    def _posting_features(posting) -> dict:
        """Cheap, deterministic taste features for an approved posting (FR-LEARN-2/7)."""
        features: dict[str, str] = {}
        title = (getattr(posting, "title", None) or "").strip().lower()
        if title:
            features[f"role:{title}"] = title
        work_mode = (getattr(posting, "work_mode", None) or "").strip().lower()
        if work_mode:
            features[f"work_mode:{work_mode}"] = work_mode
        source_key = (getattr(posting, "source_key", None) or "").strip().lower()
        if source_key:
            features[f"source:{source_key}"] = source_key
        return features

    def _posting_for_decision(self, decision_id: ApplicationId):
        """Resolve (posting, campaign_id) for a digest/application decision id."""
        from applicant.core.ids import JobPostingId

        app = self._storage.applications.get(decision_id)
        if app is not None and app.posting_id is not None:
            posting = self._storage.postings.get(app.posting_id)
            if posting is not None:
                return posting, posting.campaign_id
        try:
            posting = self._storage.postings.get(JobPostingId(str(decision_id)))
        except Exception:
            posting = None
        if posting is not None:
            return posting, posting.campaign_id
        return None, None

    def _source_for_decision(self, decision_id: ApplicationId):
        """Resolve (source_key, campaign_id) for a digest/application decision id."""
        from applicant.core.ids import JobPostingId

        app = self._storage.applications.get(decision_id)
        if app is not None and app.posting_id is not None:
            posting = self._storage.postings.get(app.posting_id)
            if posting is not None:
                return posting.source_key, posting.campaign_id
        try:
            posting = self._storage.postings.get(JobPostingId(str(decision_id)))
        except Exception:
            posting = None
        if posting is not None:
            return posting.source_key, posting.campaign_id
        return None, None

    def _learn_from_decline(self, decision: Decision) -> None:
        campaign_id = self._campaign_for_decision(decision.application_id)
        if campaign_id is None:
            return
        # Fold the feedback into the learning model (FR-DIG-5, FR-LEARN-3).
        # CONC-4: route through the per-campaign-locked atomic fold so this
        # load->fold->persist of the shared learning_state can't lose-update against a
        # concurrent funnel record (approval/submission/match) for the same campaign.
        if self._learning is not None:
            atomic = getattr(self._learning, "ingest_decline_atomic", None)
            if atomic is not None:
                atomic(
                    campaign_id,
                    feedback_text=decision.feedback_text,
                    criteria_delta=decision.criteria_delta,
                )
            else:  # pragma: no cover - all wired learning services expose the atomic API
                model = self._learning.load_model(campaign_id)
                model = self._learning.ingest_decline_feedback(
                    model,
                    feedback_text=decision.feedback_text,
                    criteria_delta=decision.criteria_delta,
                )
                self._learning.persist_model(model)
        # Bias the NEXT run's criteria from the structured delta (FR-DIG-5, FR-CRIT-3).
        if self._criteria is not None and decision.criteria_delta:
            self._criteria.apply_learned_adjustment(
                campaign_id,
                adjustment=decision.criteria_delta,
                rationale=f"declined: {decision.feedback_text}" or "decline feedback",
            )

    def _campaign_for_application(self, application_id: ApplicationId) -> CampaignId | None:
        app = self._storage.applications.get(application_id)
        return app.campaign_id if app is not None else None

    def _campaign_for_decision(self, decision_id: ApplicationId) -> CampaignId | None:
        """Resolve the campaign for a digest decision id.

        The digest row id the user approves/declines is the POSTING id (what
        ``deliver`` materializes the pending action on). It may also be a real
        application id. Look in both so the pending-action resolve never silently
        no-ops (the FR-UI-3 portal leak fix).
        """
        campaign_id = self._campaign_for_application(decision_id)
        if campaign_id is not None:
            return campaign_id
        from applicant.core.ids import JobPostingId

        try:
            posting = self._storage.postings.get(JobPostingId(str(decision_id)))
        except Exception:
            posting = None
        return posting.campaign_id if posting is not None else None

    # --- weekly recap (Top-25 #18) -----------------------------------------
    #
    # Aggregates a trailing-7-day window: applications actually SENT (the durable
    # submission-snapshot's ``captured_at`` — the stop-boundary evidence of a real
    # submit, FR-LOG-4 — not a posting's discovery/creation time) and the campaign's
    # best-performing discovery source (reusing ``LearningService.source_ranking``,
    # the SAME conversion-weighted ranking that backs the operator-visible Insights
    # "Best sources" surface — FR-DISC-5/FR-LEARN-6 — rather than a new stat).
    #
    # Interview/offer outcomes are DELIBERATELY OMITTED, not fabricated as zero:
    # ``OutcomeEvent`` (core/entities/outcome_event.py) recognizes "interview_invited"
    # and "offer" in its catalogue, but (a) nothing in the engine today ever records
    # one — no route/service creates those outcome types, so they are always empty —
    # and (b) the entity carries no timestamp, so even a manually-inserted one could
    # not be windowed to "this week". Reporting "0 interviews" every week would imply
    # a working tracker that silently never finds anything; omitting the line is the
    # truthful degrade (mirrors StatusUpdateService's "absent source contributes
    # nothing", FR-AGENT-5).
    def build_weekly_recap(self, campaign_id: CampaignId, *, now: datetime | None = None) -> dict:
        """Aggregate the trailing-7-day recap for ``campaign_id`` (read-only)."""
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        window_start = now - timedelta(days=RECAP_WINDOW_DAYS)
        applications_sent = self._applications_sent_between(campaign_id, window_start, now)
        best_source = self._best_source_for_recap(campaign_id)
        return {
            "campaign_id": campaign_id,
            "window_start": window_start,
            "window_end": now,
            "applications_sent": applications_sent,
            "best_source": best_source,
        }

    def _applications_sent_between(
        self, campaign_id: CampaignId, start: datetime, end: datetime
    ) -> int:
        """Count real submissions in ``[start, end)`` from the submission-snapshot log.

        The snapshot is written once, at the stop-boundary, for every real submit
        (auto-detected or one-tap mark-submitted) — the durable evidence of what was
        actually sent (#372), unlike an ``Application`` row's ``created_at`` (set at
        discovery/promotion time, before any submit).
        """
        try:
            snapshots = self._storage.submission_snapshots.list_for_campaign(campaign_id)
        except Exception:  # pragma: no cover - defensive: recap must never 500/crash
            return 0
        count = 0
        for snap in snapshots:
            captured = getattr(snap, "captured_at", None)
            if captured is None:
                continue
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=UTC)
            if start <= captured < end:
                count += 1
        return count

    def _best_source_for_recap(self, campaign_id: CampaignId) -> str | None:
        """The top-ranked discovery source with SOME recorded yield, or ``None``.

        Reuses ``LearningService.source_ranking`` (FR-DISC-5) — the exact
        conversion-weighted ranking the Insights "Best sources" surface reads
        (``LearningService.build_summary``) — instead of computing a second,
        divergent notion of "best". A source with zero recorded matches/approvals/
        submissions is skipped rather than named "best" (no fabrication): a fresh
        campaign with no funnel data yet yields ``None``.
        """
        if self._learning is None:
            return None
        try:
            model = self._learning.load_model(campaign_id)
            ranked = self._learning.source_ranking(model)
        except Exception:  # pragma: no cover - defensive: recap must never 500/crash
            return None
        for key in ranked:
            stats = model.source_yield_stats.get(key, {})
            if any(int(stats.get(leg, 0) or 0) for leg in ("matches", "approvals", "submissions")):
                return key
        return None

    def render_weekly_recap_message(
        self, campaign_id: CampaignId, *, recap: dict | None = None
    ) -> dict:
        """Compose the plain-language, first-person weekly recap notification body."""
        if recap is None:
            recap = self.build_weekly_recap(campaign_id)
        sent = int(recap["applications_sent"])
        best_source = recap["best_source"]
        if sent:
            body = f"This week I sent {sent} application{'s' if sent != 1 else ''} on your behalf."
        else:
            body = "This week I didn't send any new applications on your behalf — I'm still searching."
        if best_source:
            body += f" Your best-performing source so far is {best_source}."
        return {
            "subject": "Your weekly recap",
            "body": body,
            "campaign_id": campaign_id,
            "applications_sent": sent,
            "best_source": best_source,
        }

    def deliver_weekly_recap(self, campaign_id: CampaignId, *, now: datetime | None = None) -> str | None:
        """Build + push one weekly recap through the EXISTING notification fan-out.

        Reuses ``NotificationService`` — the SAME in-app inbox + opt-in Discord/email
        fan-out the daily digest ready-ping and email already flow through — not a
        second delivery pipeline. Returns the notify handle, or ``None`` when no
        notifier is wired (degrades to a no-op, mirrors ``StatusUpdateService.emit``).
        Cadence/idempotency (once per campaign per week) live in the scheduler, which
        calls this at most once per (campaign, ISO week) — this method itself is safe
        to call repeatedly (each call just re-notifies; the notifier's own per-week
        dedup key is a second line of defense, FR-NOTIF-3).
        """
        now = now or datetime.now(UTC)
        recap = self.build_weekly_recap(campaign_id, now=now)
        message = self.render_weekly_recap_message(campaign_id, recap=recap)
        if self._notification_service is None:
            return None
        notify = getattr(self._notification_service, "notify_weekly_recap", None)
        if notify is None:  # pragma: no cover - defensive (older notifier)
            return None
        try:
            return notify(
                str(campaign_id),
                body=message["body"],
                week_start=recap["window_start"].date(),
                deep_link=f"/digest?campaign={campaign_id}",
            )
        except Exception:  # external send must not break the recap
            log.warning("weekly_recap_deliver_failed", exc_info=True)
            return None
