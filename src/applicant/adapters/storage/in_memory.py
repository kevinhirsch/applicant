"""In-memory StoragePort adapter for fast tests / app-boot without a DB.

Mirrors ``SqlAlchemyStorage`` semantics with plain dicts. Used by the test suite
and as the default in the container when no real DB is available, so the app boots
and contract tests run without Postgres.
"""

from __future__ import annotations

from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision
from applicant.core.entities.generated_document import GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    PendingActionId,
    ResumeVariantId,
)


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


class _PostingRepo:
    def __init__(self) -> None:
        self._d: dict[str, JobPosting] = {}

    def add(self, p: JobPosting) -> None:
        self._d[str(p.id)] = p

    def get(self, pid: JobPostingId) -> JobPosting | None:
        return self._d.get(str(pid))

    def list_for_campaign(self, cid: CampaignId) -> list[JobPosting]:
        return [p for p in self._d.values() if p.campaign_id == cid]


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
        return [a for a in self._d.values() if a.campaign_id == cid]


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


class _DecisionRepo:
    def __init__(self) -> None:
        self._l: list[Decision] = []

    def add(self, d: Decision) -> None:
        self._l.append(d)

    def list_for_application(self, aid: ApplicationId) -> list[Decision]:
        return [d for d in self._l if d.application_id == aid]


class _OutcomeRepo:
    def __init__(self) -> None:
        self._l: list[OutcomeEvent] = []

    def add(self, e: OutcomeEvent) -> None:
        self._l.append(e)

    def list_for_application(self, aid: ApplicationId) -> list[OutcomeEvent]:
        return [e for e in self._l if e.application_id == aid]


class _PendingRepo:
    def __init__(self) -> None:
        self._d: dict[str, PendingAction] = {}

    def add(self, p: PendingAction) -> None:
        self._d[str(p.id)] = p

    def get(self, pid: PendingActionId) -> PendingAction | None:
        return self._d.get(str(pid))

    def list_open(self, cid: CampaignId) -> list[PendingAction]:
        return [p for p in self._d.values() if p.campaign_id == cid and not p.resolved]

    def resolve(self, pid: PendingActionId) -> None:
        import dataclasses

        cur = self._d.get(str(pid))
        if cur:
            self._d[str(pid)] = dataclasses.replace(cur, resolved=True)


class InMemoryStorage:
    """In-memory ``StoragePort`` implementation."""

    def __init__(self) -> None:
        self.campaigns = _CampaignRepo()
        self.attributes = _AttributeRepo()
        self.postings = _PostingRepo()
        self.applications = _ApplicationRepo()
        self.resume_variants = _VariantRepo()
        self.documents = _DocumentRepo()
        self.decisions = _DecisionRepo()
        self.outcomes = _OutcomeRepo()
        self.pending_actions = _PendingRepo()

    def commit(self) -> None:  # no-op; writes are immediate
        pass

    def rollback(self) -> None:
        pass

    def healthcheck(self) -> bool:
        return True
