"""In-memory StoragePort adapter for fast tests / app-boot without a DB.

Mirrors ``SqlAlchemyStorage`` semantics with plain dicts. Used by the test suite
and as the default in the container when no real DB is available, so the app boots
and contract tests run without Postgres.
"""

from __future__ import annotations

from datetime import date

from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.generated_document import GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import RevisionSession
from applicant.core.ids import (
    AgentRunId,
    ApplicationId,
    AttributeId,
    CampaignId,
    FieldMappingId,
    GeneratedDocumentId,
    JobPostingId,
    PendingActionId,
    ResumeVariantId,
    RevisionSessionId,
)
from applicant.core.state_machine import ApplicationState

#: Outcome types treated as terminal/submitted for idempotency (mirrors the SQL lane's
#: ``repositories.TERMINAL_OUTCOME_TYPES``; kept here so this adapter stays DB-free).
TERMINAL_OUTCOME_TYPES: frozenset[str] = frozenset({"submitted", "converted"})


class _CampaignRepo:
    def __init__(self) -> None:
        self._d: dict[str, Campaign] = {}

    def add(self, c: Campaign) -> None:
        self._d[str(c.id)] = c

    def get(self, cid: CampaignId) -> Campaign | None:
        return self._d.get(str(cid))

    def list(self) -> list[Campaign]:
        return list(self._d.values())


class _AttributeRepo:
    def __init__(self) -> None:
        self._d: dict[str, Attribute] = {}

    def add(self, a: Attribute) -> None:
        self._d[str(a.id)] = a

    def get(self, aid: AttributeId) -> Attribute | None:
        return self._d.get(str(aid))

    def list_for_campaign(self, cid: CampaignId) -> list[Attribute]:
        return [a for a in self._d.values() if a.campaign_id == cid]

    def delete(self, aid: AttributeId) -> None:  # CRIT-profile: attribute delete (FR-ATTR-3)
        self._d.pop(str(aid), None)


class _PostingRepo:
    def __init__(self) -> None:
        self._d: dict[str, JobPosting] = {}

    def add(self, p: JobPosting) -> None:
        self._d[str(p.id)] = p

    def get(self, pid: JobPostingId) -> JobPosting | None:
        return self._d.get(str(pid))

    def list_for_campaign(self, cid: CampaignId) -> list[JobPosting]:
        return sorted(
            (p for p in self._d.values() if p.campaign_id == cid),
            key=lambda p: str(p.id),
        )

    def list_unscored_for_campaign(self, cid: CampaignId) -> list[JobPosting]:
        return sorted(
            (
                p
                for p in self._d.values()
                if p.campaign_id == cid and p.viability_score is None
            ),
            key=lambda p: str(p.id),
        )


class _ApplicationRepo:
    def __init__(self) -> None:
        self._d: dict[str, Application] = {}

    def add(self, a: Application) -> None:
        self._d[str(a.id)] = a

    def update(self, a: Application) -> None:
        self._d[str(a.id)] = a

    def get(self, aid: ApplicationId) -> Application | None:
        return self._d.get(str(aid))

    def list_for_campaign(self, cid: CampaignId) -> list[Application]:
        return sorted(
            (a for a in self._d.values() if a.campaign_id == cid),
            key=lambda a: str(a.id),
        )

    def get_by_posting(
        self, cid: CampaignId, posting_id: JobPostingId
    ) -> Application | None:
        matches = sorted(
            (
                a
                for a in self._d.values()
                if a.campaign_id == cid and a.posting_id == posting_id
            ),
            key=lambda a: str(a.id),
        )
        return matches[0] if matches else None

    def list_by_status(
        self, cid: CampaignId, statuses: tuple[ApplicationState, ...]
    ) -> list[Application]:
        if not statuses:
            return []
        wanted = set(statuses)
        return sorted(
            (
                a
                for a in self._d.values()
                if a.campaign_id == cid and a.status in wanted
            ),
            key=lambda a: str(a.id),
        )


class _VariantRepo:
    def __init__(self) -> None:
        self._d: dict[str, ResumeVariant] = {}

    def add(self, v: ResumeVariant) -> None:
        self._d[str(v.id)] = v

    def get(self, vid: ResumeVariantId) -> ResumeVariant | None:
        return self._d.get(str(vid))

    def list_for_campaign(self, cid: CampaignId) -> list[ResumeVariant]:
        return [v for v in self._d.values() if v.campaign_id == cid]


class _DocumentRepo:
    def __init__(self) -> None:
        self._d: dict[str, GeneratedDocument] = {}

    def add(self, doc: GeneratedDocument) -> None:
        self._d[str(doc.id)] = doc

    def get(self, did: GeneratedDocumentId) -> GeneratedDocument | None:
        return self._d.get(str(did))

    def list_for_application(self, aid: ApplicationId) -> list[GeneratedDocument]:
        return [d for d in self._d.values() if d.application_id == aid]


class _RevisionRepo:
    def __init__(self) -> None:
        self._d: dict[str, RevisionSession] = {}

    def add(self, s: RevisionSession) -> None:
        self._d[str(s.id)] = s

    def get(self, sid: RevisionSessionId) -> RevisionSession | None:
        return self._d.get(str(sid))

    def get_for_material(self, mid: GeneratedDocumentId) -> RevisionSession | None:
        for s in self._d.values():
            if str(s.material_id) == str(mid):
                return s
        return None


class _DecisionRepo:
    def __init__(
        self, applications: _ApplicationRepo, postings: _PostingRepo
    ) -> None:
        self._l: list[Decision] = []
        # Resolve a decision's posting/campaign through its application (mirrors the
        # SQL join in ``list_approved_postings_for_campaign``). A digest-approval
        # decision, however, is keyed directly on the POSTING id (before any
        # application exists — see DigestService._campaign_for_decision), so we resolve
        # against postings too.
        self._applications = applications
        self._postings = postings

    def add(self, d: Decision) -> None:
        self._l.append(d)

    def list_for_application(self, aid: ApplicationId) -> list[Decision]:
        return [d for d in self._l if d.application_id == aid]

    def list_approved_postings_for_campaign(
        self, cid: CampaignId
    ) -> list[JobPostingId]:
        """Posting ids with an APPROVED decision (distinct, ordered).

        A decision's ``application_id`` may be either a real application id (resolve to
        its ``posting_id``) OR a posting id directly — the digest UI approves a digest
        ROW, whose id is the posting id, before any application row exists. Both legs
        are honored so a freshly approved digest item is found.
        """
        posting_ids: set[str] = set()
        for d in self._l:
            if d.type != DecisionType.APPROVE:
                continue
            app = self._applications.get(d.application_id)
            if app is not None:
                if app.campaign_id == cid and app.posting_id:
                    posting_ids.add(str(app.posting_id))
                continue
            # Not an application id — try resolving it as a posting id directly.
            posting = self._postings.get(JobPostingId(str(d.application_id)))
            if posting is not None and posting.campaign_id == cid:
                posting_ids.add(str(posting.id))
        return [JobPostingId(p) for p in sorted(posting_ids)]


class _OutcomeRepo:
    def __init__(self, applications: _ApplicationRepo) -> None:
        self._l: list[OutcomeEvent] = []
        # Resolve an outcome's campaign through its application (mirrors the SQL join).
        self._applications = applications

    def add(self, e: OutcomeEvent) -> None:
        self._l.append(e)

    def list_for_application(self, aid: ApplicationId) -> list[OutcomeEvent]:
        return [e for e in self._l if e.application_id == aid]

    def list_for_campaign(
        self,
        cid: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[OutcomeEvent]:
        """All outcomes whose application belongs to ``cid`` (FR-CRIT-4 scoping).

        ``limit``/``offset`` bound the scan (default: unbounded). Insertion order is
        preserved (mirrors the SQL ``created_at, id`` ordering for appended events).
        """
        out: list[OutcomeEvent] = []
        for e in self._l:
            app = self._applications.get(e.application_id)
            if app is not None and app.campaign_id == cid:
                out.append(e)
        if offset:
            out = out[offset:]
        if limit is not None:
            out = out[:limit]
        return out

    def exists_terminal_for_application(self, aid: ApplicationId) -> bool:
        return any(
            e.application_id == aid and e.type in TERMINAL_OUTCOME_TYPES
            for e in self._l
        )


class _ScreenshotRepo:
    def __init__(self, applications: _ApplicationRepo) -> None:
        self._l: list[ApplicationScreenshot] = []
        # Resolve a screenshot's campaign through its application (mirrors the SQL join).
        self._applications = applications

    def add(self, s: ApplicationScreenshot) -> None:
        self._l.append(s)

    def list_for_application(self, aid: ApplicationId) -> list[ApplicationScreenshot]:
        return [s for s in self._l if s.application_id == aid]

    def list_for_campaign(
        self,
        cid: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ApplicationScreenshot]:
        """All screenshots whose application belongs to ``cid`` (batch load, no N+1)."""
        out: list[ApplicationScreenshot] = []
        for s in self._l:
            app = self._applications.get(s.application_id)
            if app is not None and app.campaign_id == cid:
                out.append(s)
        if offset:
            out = out[offset:]
        if limit is not None:
            out = out[:limit]
        return out


class _PendingRepo:
    def __init__(self) -> None:
        self._d: dict[str, PendingAction] = {}

    def add(self, p: PendingAction) -> None:
        self._d[str(p.id)] = p

    def get(self, pid: PendingActionId) -> PendingAction | None:
        return self._d.get(str(pid))

    def list_open(self, cid: CampaignId) -> list[PendingAction]:
        return sorted(
            (p for p in self._d.values() if p.campaign_id == cid and not p.resolved),
            key=lambda p: (p.created_at, str(p.id)),
        )

    def find_open_by_dedup(
        self, cid: CampaignId, dedup_key: str
    ) -> PendingAction | None:
        """First open action matching ``dedup_key`` (stored in payload), ordered."""
        matches = sorted(
            (
                p
                for p in self._d.values()
                if p.campaign_id == cid
                and not p.resolved
                and (p.payload or {}).get("dedup_key") == dedup_key
            ),
            key=lambda p: (p.created_at, str(p.id)),
        )
        return matches[0] if matches else None

    def resolve(self, pid: PendingActionId) -> None:
        import dataclasses

        cur = self._d.get(str(pid))
        if cur:
            self._d[str(pid)] = dataclasses.replace(cur, resolved=True)


class _FieldMappingRepo:
    def __init__(self) -> None:
        self._d: dict[str, FieldMapping] = {}

    def add(self, mapping: FieldMapping) -> None:
        self._d[str(mapping.id)] = mapping

    def get(self, mapping_id: FieldMappingId) -> FieldMapping | None:
        return self._d.get(str(mapping_id))

    def list_for_site(self, site_key: str) -> list[FieldMapping]:
        return [m for m in self._d.values() if m.site_key == site_key]

    def list_for_campaign(self, cid: CampaignId) -> list[FieldMapping]:
        return [m for m in self._d.values() if m.campaign_id == cid]

    def find(self, site_key: str, field_selector: str) -> FieldMapping | None:
        # Prefer a campaign-scoped mapping; fall back to a shared one (FR-ATTR-2).
        # Sort by id so multiple matches resolve deterministically (mirrors the SQL
        # ``ORDER BY id`` so both lanes return the same mapping).
        matches = sorted(
            (
                m
                for m in self._d.values()
                if m.site_key == site_key and m.field_selector == field_selector
            ),
            key=lambda m: str(m.id),
        )
        scoped = [m for m in matches if m.campaign_id is not None]
        return (scoped or matches or [None])[0]


class _DiscoverySourceRepo:
    def __init__(self) -> None:
        self._d: dict[str, DiscoverySource] = {}

    @staticmethod
    def _k(cid: CampaignId, key: str) -> str:
        return f"{cid}:{key}"

    def upsert(self, s: DiscoverySource) -> None:
        self._d[self._k(s.campaign_id, s.source_key)] = s

    def get(self, cid: CampaignId, key: str) -> DiscoverySource | None:
        return self._d.get(self._k(cid, key))

    def list_for_campaign(self, cid: CampaignId) -> list[DiscoverySource]:
        return [s for s in self._d.values() if s.campaign_id == cid]


class _AgentRunRepo:
    def __init__(self) -> None:
        self._d: dict[str, AgentRun] = {}

    def add(self, r: AgentRun) -> None:
        self._d[str(r.id)] = r

    def get(self, rid: AgentRunId) -> AgentRun | None:
        return self._d.get(str(rid))

    def list_for_campaign(
        self,
        cid: CampaignId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentRun]:
        out = sorted(
            (r for r in self._d.values() if r.campaign_id == cid),
            key=lambda r: (r.timestamp, str(r.id)),
        )
        if offset:
            out = out[offset:]
        if limit is not None:
            out = out[:limit]
        return out

    def count_pipelines_started_on(self, cid: CampaignId, day: date) -> int:
        """Total pipelines started for ``cid`` on the UTC ``day``.

        Sums each run's ``stats["pipelines_started"]`` (NOT a count of run rows) so the
        per-day throughput cap reflects how many applications were actually acted on,
        even when one tick starts many (mirrors the SQL lane)."""
        return sum(
            int((r.stats or {}).get("pipelines_started", 0))
            for r in self._d.values()
            if r.campaign_id == cid and r.timestamp.date() == day
        )

    def latest(self, cid: CampaignId) -> AgentRun | None:
        runs = [r for r in self._d.values() if r.campaign_id == cid]
        if not runs:
            return None
        return max(runs, key=lambda r: (r.timestamp, r.seq))

    def max_seq(self, cid: CampaignId) -> int:
        return max(
            (r.seq for r in self._d.values() if r.campaign_id == cid), default=0
        )

    def prune_old(self, cid: CampaignId, *, keep: int) -> int:
        """Keep the newest ``keep`` runs for ``cid`` by (timestamp, seq); delete the rest."""
        runs = sorted(
            (r for r in self._d.values() if r.campaign_id == cid),
            key=lambda r: (r.timestamp, r.seq),
        )
        if keep < 0:
            keep = 0
        stale = runs[: max(0, len(runs) - keep)]
        for r in stale:
            self._d.pop(str(r.id), None)
        return len(stale)


class _DetectionEventRepo:
    def __init__(self, applications: _ApplicationRepo) -> None:
        self._l: list[DetectionEvent] = []
        self._applications = applications

    def add(self, e: DetectionEvent) -> None:
        self._l.append(e)

    def list_for_application(self, aid: ApplicationId) -> list[DetectionEvent]:
        return sorted(
            (e for e in self._l if e.application_id == aid),
            key=lambda e: (e.timestamp, str(e.id)),
        )

    def list_for_campaign(self, cid: CampaignId) -> list[DetectionEvent]:
        out = []
        for e in self._l:
            app = self._applications.get(e.application_id)
            if app is not None and app.campaign_id == cid:
                out.append(e)
        return sorted(out, key=lambda e: (e.timestamp, str(e.id)))


class _OnboardingProfileRepo:
    def __init__(self) -> None:
        self._d: dict[str, OnboardingProfile] = {}

    def add(self, p: OnboardingProfile) -> None:
        self._d[str(p.campaign_id)] = p

    def get_for_campaign(self, cid: CampaignId) -> OnboardingProfile | None:
        return self._d.get(str(cid))


class InMemoryStorage:
    """In-memory ``StoragePort`` implementation."""

    def __init__(self) -> None:
        self.campaigns = _CampaignRepo()
        self.attributes = _AttributeRepo()
        self.postings = _PostingRepo()
        self.applications = _ApplicationRepo()
        self.resume_variants = _VariantRepo()
        self.documents = _DocumentRepo()
        self.revisions = _RevisionRepo()
        self.decisions = _DecisionRepo(self.applications, self.postings)
        self.outcomes = _OutcomeRepo(self.applications)
        self.screenshots = _ScreenshotRepo(self.applications)
        self.pending_actions = _PendingRepo()
        self.field_mappings = _FieldMappingRepo()
        self.discovery_sources = _DiscoverySourceRepo()
        self.agent_runs = _AgentRunRepo()
        self.detection_events = _DetectionEventRepo(self.applications)
        self.onboarding_profiles = _OnboardingProfileRepo()

    def commit(self) -> None:  # no-op; writes are immediate
        pass

    def rollback(self) -> None:
        pass

    def healthcheck(self) -> bool:
        return True
