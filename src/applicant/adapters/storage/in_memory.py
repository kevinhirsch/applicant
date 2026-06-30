"""In-memory StoragePort adapter for fast tests / app-boot without a DB.

Mirrors ``SqlAlchemyStorage`` semantics with plain dicts. Used by the test suite
and as the default in the container when no real DB is available, so the app boots
and contract tests run without Postgres.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.follow_up import FollowUpStatus
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

    def delete(self, cid: CampaignId) -> int:
        return 1 if self._d.pop(str(cid), None) is not None else 0


class _AttributeRepo:
    def __init__(self) -> None:
        self._d: dict[str, Attribute] = {}
        # PII retention (#363): when each attribute was recorded, so a retention
        # sweep can prune parsed PII / EEO answers older than the window.
        self._ts: dict[str, datetime] = {}

    def add(self, a: Attribute, *, recorded_at: datetime | None = None) -> None:
        self._d[str(a.id)] = a
        self._ts[str(a.id)] = recorded_at or datetime.now(UTC)

    def get(self, aid: AttributeId) -> Attribute | None:
        return self._d.get(str(aid))

    def list_for_campaign(self, cid: CampaignId) -> list[Attribute]:
        return [a for a in self._d.values() if a.campaign_id == cid]

    def delete(self, aid: AttributeId) -> None:  # CRIT-profile: attribute delete (FR-ATTR-3)
        self._d.pop(str(aid), None)
        self._ts.pop(str(aid), None)

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, a in self._d.items() if a.campaign_id == cid]
        for k in stale:
            del self._d[k]
            self._ts.pop(k, None)
        return len(stale)

    def prune_recorded_before(self, cutoff: datetime) -> int:
        """Delete attributes recorded before ``cutoff`` (PII retention, #363)."""
        stale = [k for k, ts in self._ts.items() if ts < cutoff]
        for k in stale:
            self._d.pop(k, None)
            del self._ts[k]
        return len(stale)


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

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, p in self._d.items() if p.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


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

    def ids_for_campaign(self, cid: CampaignId) -> set[str]:
        return {str(a.id) for a in self._d.values() if a.campaign_id == cid}

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, a in self._d.items() if a.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


class _VariantRepo:
    def __init__(self) -> None:
        self._d: dict[str, ResumeVariant] = {}

    def add(self, v: ResumeVariant) -> None:
        self._d[str(v.id)] = v

    def get(self, vid: ResumeVariantId) -> ResumeVariant | None:
        return self._d.get(str(vid))

    def list_for_campaign(self, cid: CampaignId) -> list[ResumeVariant]:
        return [v for v in self._d.values() if v.campaign_id == cid]

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, v in self._d.items() if v.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


class _DocumentRepo:
    def __init__(self) -> None:
        self._d: dict[str, GeneratedDocument] = {}

    def add(self, doc: GeneratedDocument) -> None:
        self._d[str(doc.id)] = doc

    def get(self, did: GeneratedDocumentId) -> GeneratedDocument | None:
        return self._d.get(str(did))

    def list_for_application(self, aid: ApplicationId) -> list[GeneratedDocument]:
        return [d for d in self._d.values() if d.application_id == aid]

    def list_for_campaign(self, cid: CampaignId) -> list[GeneratedDocument]:
        return [d for d in self._d.values() if d.campaign_id == cid]

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, d in self._d.items() if d.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


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

    def delete_for_materials(self, material_ids: set[str]) -> int:
        stale = [
            k for k, s in self._d.items() if str(s.material_id) in material_ids
        ]
        for k in stale:
            del self._d[k]
        return len(stale)


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

    def delete_for_applications(self, application_ids: set[str]) -> int:
        before = len(self._l)
        self._l = [
            d for d in self._l if str(d.application_id) not in application_ids
        ]
        return before - len(self._l)

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

    def delete_for_applications(self, application_ids: set[str]) -> int:
        before = len(self._l)
        self._l = [
            e for e in self._l if str(e.application_id) not in application_ids
        ]
        return before - len(self._l)


class _ScreenshotRepo:
    def __init__(self, applications: _ApplicationRepo) -> None:
        self._l: list[ApplicationScreenshot] = []
        # Resolve a screenshot's campaign through its application (mirrors the SQL join).
        self._applications = applications

    def add(self, s: ApplicationScreenshot) -> None:
        self._l.append(s)

    def list_for_application(self, aid: ApplicationId) -> list[ApplicationScreenshot]:
        return [s for s in self._l if s.application_id == aid]

    def delete_for_applications(self, application_ids: set[str]) -> int:
        before = len(self._l)
        self._l = [
            s for s in self._l if str(s.application_id) not in application_ids
        ]
        return before - len(self._l)

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

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, p in self._d.items() if p.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


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

    def delete_for_campaign(self, cid: CampaignId) -> int:
        # Only per-campaign mappings carry PII-adjacent values; globally-learned
        # mappings (campaign_id is None) are reusable schema and are NOT purged.
        stale = [k for k, mp in self._d.items() if mp.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


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

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, s in self._d.items() if s.campaign_id == cid]
        for k in stale:
            del self._d[k]
        return len(stale)


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

    def delete_for_campaign(self, cid: CampaignId) -> int:
        stale = [k for k, r in self._d.items() if r.campaign_id == cid]
        for k in stale:
            del self._d[k]
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

    def delete_for_applications(self, application_ids: set[str]) -> int:
        before = len(self._l)
        self._l = [
            e for e in self._l if str(e.application_id) not in application_ids
        ]
        return before - len(self._l)

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
        # PII retention (#363): when each intake (identity/EEO/history) was recorded.
        self._ts: dict[str, datetime] = {}

    def add(self, p: OnboardingProfile, *, recorded_at: datetime | None = None) -> None:
        self._d[str(p.campaign_id)] = p
        self._ts[str(p.campaign_id)] = recorded_at or datetime.now(UTC)

    def get_for_campaign(self, cid: CampaignId) -> OnboardingProfile | None:
        return self._d.get(str(cid))

    def delete_for_campaign(self, cid: CampaignId) -> int:
        self._ts.pop(str(cid), None)
        return 1 if self._d.pop(str(cid), None) is not None else 0

    def list_all(self) -> list[OnboardingProfile]:
        return list(self._d.values())

    def prune_recorded_before(self, cutoff: datetime) -> int:
        """Delete onboarding intakes recorded before ``cutoff`` (PII retention, #363)."""
        stale = [k for k, ts in self._ts.items() if ts < cutoff]
        for k in stale:
            self._d.pop(k, None)
            del self._ts[k]
        return len(stale)

_MUTATING_PREFIXES = ("add", "update", "upsert", "delete", "resolve", "prune")


def _capture_dict_undo(
    d: dict, name: str, args: tuple, kwargs: dict
) -> Callable[[], None] | None:
    """Capture undo information for a mutation on a dict-based repo.

    Returns a callable that, when invoked, reverses the mutation.
    Returns ``None`` if the operation cannot be generically unwound.
    """
    if name in ("add", "update", "upsert"):
        # These methods take an entity with `.id`
        entity = args[0]
        key = str(entity.id)
        old = d.get(key)
        def _undo(*, _k=key, _old=old):
            if _old is not None:
                d[_k] = _old
            else:
                d.pop(_k, None)
        return _undo
    elif name in ("delete", "resolve"):
        # These methods take an id-like object (key = str(args[0]))
        key = str(args[0])
        old = d.get(key)
        def _undo(*, _k=key, _old=old):
            if _old is not None:
                d[_k] = _old
        return _undo
    elif name == "delete_for_campaign":
        cid = args[0]
        stale = {k: v for k, v in d.items() if v.campaign_id == cid}
        def _undo(*, _stale=stale):
            d.update(_stale)
        return _undo
    elif name.startswith("prune"):
        return None
    return None


def _capture_list_undo(
    lst: list, name: str, args: tuple
) -> Callable[[], None] | None:
    """Capture undo information for a mutation on a list-based repo."""
    if name == "add":
        entity = args[0]
        idx = len(lst)
        def _undo(*, _idx=idx):
            if _idx < len(lst):
                lst.pop(_idx)
        return _undo
    elif name == "delete_for_applications":
        before = list(lst)
        def _undo(*, _before=before):
            lst[:] = _before
        return _undo
    return None


class _StageProxy:
    """Wraps a repo so mutating methods record undo information.

    Writes are applied IMMEDIATELY (backward-compatible with existing tests).
    Each mutation records an *undo action* in the shared ``_staged`` list.
    ``commit()`` discards the undo log (writes are finalized).
    ``rollback()`` replays undos in reverse order, then clears the log.

    Read-only methods pass through unchanged.
    """

    def __init__(self, inner: object, staged: list[Callable[[], None]]) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_staged", staged)

    def __getattr__(self, name: str):
        inner = object.__getattribute__(self, "_inner")
        staged = object.__getattribute__(self, "_staged")
        attr = getattr(inner, name)
        if not callable(attr):
            return attr
        if name.startswith(_MUTATING_PREFIXES):

            def staged_call(*args, _orig=attr, _name=name, **kwargs):
                inner = object.__getattribute__(self, "_inner")
                staged = object.__getattribute__(self, "_staged")
                d = getattr(inner, "_d", None)
                lst = getattr(inner, "_l", None)

                # For prune operations, deep-copy the entire state before mutation
                if _name.startswith("prune"):
                    import copy as _copy
                    if d is not None:
                        snapshot = _copy.deepcopy(d)
                        def _undo(*, _snap=snapshot, _d=d):
                            _d.clear()
                            _d.update(_snap)
                        staged.append(_undo)
                    elif lst is not None:
                        snapshot = _copy.deepcopy(lst)
                        def _undo(*, _snap=snapshot, _lst=lst):
                            _lst[:] = _snap
                        staged.append(_undo)
                    return _orig(*args, **kwargs)

                # For non-prune mutations, capture targeted undo
                undo = None
                if d is not None:
                    undo = _capture_dict_undo(d, _name, args, kwargs)
                elif lst is not None:
                    undo = _capture_list_undo(lst, _name, args)

                result = _orig(*args, **kwargs)

                if undo is not None:
                    staged.append(undo)
                else:
                    staged.append(lambda: None)

                return result

            return staged_call
        return attr



class _SubmissionSnapshotRepo:
    def __init__(self, applications):
        self._d = {}
        self._applications = applications
    def add(self, s): self._d[str(s.id)] = s
    def get(self, sid): return self._d.get(str(sid))
    def get_for_application(self, aid): return next((s for s in self._d.values() if s.application_id == aid), None)
    def list_for_campaign(self, cid): return [s for s in self._d.values() if (a := self._applications.get(s.application_id)) and a.campaign_id == cid]
    def delete_for_application(self, aid): return bool(sum(1 for k in list(self._d.keys()) if self._d[k].application_id == aid and self._d.pop(k, None) or 0))
    def delete_for_applications(self, aids): return sum(1 for k in list(self._d.keys()) if str(self._d[k].application_id) in aids and self._d.pop(k, None) or 0)

class _RejectionSignalRepo:
    def __init__(self, applications):
        self._l = []
        self._applications = applications
    def add(self, s): self._l.append(s)
    def list_for_application(self, aid): return sorted([s for s in self._l if s.application_id == aid], key=lambda s: s.detected_at)
    def list_for_campaign(self, cid): return sorted([s for s in self._l if (a := self._applications.get(s.application_id)) and a.campaign_id == cid], key=lambda s: s.detected_at)
    def delete_for_applications(self, aids):
        n = len(self._l)
        self._l = [s for s in self._l if str(s.application_id) not in aids]
        return n - len(self._l)

class _GhostingSignalRepo:
    def __init__(self, applications):
        self._l = []
        self._applications = applications
    def add(self, s): self._l.append(s)
    def list_for_application(self, aid): return sorted([s for s in self._l if s.application_id == aid], key=lambda s: s.detected_at)
    def list_for_campaign(self, cid): return sorted([s for s in self._l if s.campaign_id == cid], key=lambda s: s.detected_at)
    def delete_for_applications(self, aids):
        n = len(self._l)
        self._l = [s for s in self._l if str(s.application_id) not in aids]
        return n - len(self._l)

class _FollowUpRepo:
    def __init__(self, applications):
        self._d = {}
        self._applications = applications
    def add(self, f): self._d[str(f.id)] = f
    def get(self, fid): return self._d.get(str(fid))
    def list_for_application(self, aid): return sorted([f for f in self._d.values() if f.application_id == aid], key=lambda f: f.created_at)
    def list_for_campaign(self, cid): return sorted([f for f in self._d.values() if (a := self._applications.get(f.application_id)) and a.campaign_id == cid], key=lambda f: f.created_at)
    def list_due(self, now): return sorted([f for f in self._d.values() if f.scheduled_at and f.scheduled_at <= now and f.status == FollowUpStatus.SCHEDULED], key=lambda f: f.scheduled_at)
    def delete_for_applications(self, aids): return sum(1 for k in list(self._d.keys()) if str(self._d[k].application_id) in aids and self._d.pop(k, None) or 0)

class _PortfolioAttachmentRepo:
    def __init__(self, applications):
        self._d = {}
        self._applications = applications
    def add(self, a): self._d[str(a.id)] = a
    def get(self, aid): return self._d.get(str(aid))
    def list_for_application(self, aid): return sorted([a for a in self._d.values() if a.application_id == aid], key=lambda a: a.created_at)
    def list_for_campaign(self, cid): return sorted([a for a in self._d.values() if a.application_id and (app := self._applications.get(a.application_id)) and app.campaign_id == cid], key=lambda a: a.created_at)
    def delete(self, aid): return self._d.pop(str(aid), None) is not None
    def delete_for_application(self, aid): return sum(1 for k in list(self._d.keys()) if self._d[k].application_id == aid and self._d.pop(k, None) or 0)
    def delete_for_applications(self, aids): return sum(1 for k in list(self._d.keys()) if str(self._d[k].application_id) in aids and self._d.pop(k, None) or 0)

class InMemoryStorage:
    """In-memory ``StoragePort`` implementation.

    Writes are applied immediately (backward-compatible).
    ``commit()`` finalizes pending changes by discarding the undo log.
    ``rollback()`` discards uncommitted changes by replaying undos.
    """

    def __init__(self) -> None:
        self._staged: list[Callable[[], None]] = []
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
        self.submission_snapshots = _SubmissionSnapshotRepo(self.applications)
        self.rejection_signals = _RejectionSignalRepo(self.applications)
        self.ghosting_signals = _GhostingSignalRepo(self.applications)
        self.follow_ups = _FollowUpRepo(self.applications)
        self.portfolio_attachments = _PortfolioAttachmentRepo(self.applications)
        self._wrap_repos()

    def _wrap_repos(self) -> None:
        """Wrap every sub-repo with a _StageProxy so writes are staged."""
        s = self._staged
        self.campaigns = _StageProxy(self.campaigns, s)
        self.attributes = _StageProxy(self.attributes, s)
        self.postings = _StageProxy(self.postings, s)
        self.applications = _StageProxy(self.applications, s)
        self.resume_variants = _StageProxy(self.resume_variants, s)
        self.documents = _StageProxy(self.documents, s)
        self.revisions = _StageProxy(self.revisions, s)
        self.decisions = _StageProxy(self.decisions, s)
        self.outcomes = _StageProxy(self.outcomes, s)
        self.screenshots = _StageProxy(self.screenshots, s)
        self.pending_actions = _StageProxy(self.pending_actions, s)
        self.field_mappings = _StageProxy(self.field_mappings, s)
        self.discovery_sources = _StageProxy(self.discovery_sources, s)
        self.agent_runs = _StageProxy(self.agent_runs, s)
        self.detection_events = _StageProxy(self.detection_events, s)
        self.onboarding_profiles = _StageProxy(self.onboarding_profiles, s)
        self.submission_snapshots = _StageProxy(self.submission_snapshots, s)
        self.rejection_signals = _StageProxy(self.rejection_signals, s)
        self.ghosting_signals = _StageProxy(self.ghosting_signals, s)
        self.follow_ups = _StageProxy(self.follow_ups, s)
        self.portfolio_attachments = _StageProxy(self.portfolio_attachments, s)

    def commit(self) -> None:
        """Finalize pending changes by discarding the undo log."""
        self._staged.clear()

    def rollback(self) -> None:
        """Discard uncommitted changes by replaying undos in reverse."""
        for undo in reversed(self._staged):
            undo()
        self._staged.clear()

    def healthcheck(self) -> bool:
        return True

    def purge_campaign(self, cid: CampaignId) -> dict[str, int]:
        """Cascade-delete every row belonging to ``cid`` (#363, FR-CRIT-4, NFR-PRIV-1).

        Erases the PII-bearing + derived rows for a campaign in one pass: the
        onboarding intake (identity/EEO/history), the per-campaign attribute cloud
        (parsed PII + EEO answers), résumé variants, generated materials, and every
        application-scoped child (decisions/outcomes/screenshots/detection events/
        redline sessions), plus postings, field mappings, discovery sources, agent
        runs, pending actions, and finally the campaign row itself. Banked credentials
        are erased separately via the credential store (sealed off-storage). Returns a
        per-store deletion count so the caller can verify a complete purge.
        """
        app_ids = self.applications.ids_for_campaign(cid)
        material_ids = {str(d.id) for d in self.documents.list_for_campaign(cid)}
        counts: dict[str, int] = {
            "onboarding_profiles": self.onboarding_profiles.delete_for_campaign(cid),
            "attributes": self.attributes.delete_for_campaign(cid),
            "revisions": self.revisions.delete_for_materials(material_ids),
            "documents": self.documents.delete_for_campaign(cid),
            "resume_variants": self.resume_variants.delete_for_campaign(cid),
            "decisions": self.decisions.delete_for_applications(app_ids),
            "outcomes": self.outcomes.delete_for_applications(app_ids),
            "screenshots": self.screenshots.delete_for_applications(app_ids),
            "detection_events": self.detection_events.delete_for_applications(app_ids),
            "submission_snapshots": self.submission_snapshots.delete_for_applications(app_ids),
            "rejection_signals": self.rejection_signals.delete_for_applications(app_ids),
            "ghosting_signals": self.ghosting_signals.delete_for_applications(app_ids),
            "follow_ups": self.follow_ups.delete_for_applications(app_ids),
            "portfolio_attachments": self.portfolio_attachments.delete_for_applications(app_ids),
            "applications": self.applications.delete_for_campaign(cid),
            "postings": self.postings.delete_for_campaign(cid),
            "field_mappings": self.field_mappings.delete_for_campaign(cid),
            "discovery_sources": self.discovery_sources.delete_for_campaign(cid),
            "agent_runs": self.agent_runs.delete_for_campaign(cid),
            "pending_actions": self.pending_actions.delete_for_campaign(cid),
            "campaigns": self.campaigns.delete(cid),
        }
        return counts

    def prune_pii_older_than(self, cutoff: datetime) -> dict[str, int]:
        """Prune PII (attributes + onboarding intakes) recorded before ``cutoff``.

        Retention policy (#363): only the PII-bearing stores are swept; in-window PII
        is retained. Returns a per-store deletion count.
        """
        return {
            "attributes": self.attributes.prune_recorded_before(cutoff),
            "onboarding_profiles": self.onboarding_profiles.prune_recorded_before(
                cutoff
            ),
        }
