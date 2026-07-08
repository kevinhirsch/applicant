"""P1-10 (issue #662) — multi-campaign base profiles: two campaigns can differ.

Pins the engine-side DoD of the multi-campaign story:

* the fabrication guard's ground truth scopes to the campaign's OWN base
  profile — the attribute cloud rows AND the uploaded base-résumé text are both
  read per campaign, so a fact that is true in campaign A is still flagged as
  unsupported in campaign B (never cross-pollinated);
* each campaign's root (base) variant is its own — variant listing and lineage
  never cross campaigns;
* two campaigns run side by side with SEPARATE digests and SEPARATE pacing:
  the throughput ledger and the once-per-day digest guard are both keyed
  per (campaign, UTC day).

No schema change was needed: ``Campaign`` scoping has been in the data model
since Phase 4a (FR-CRIT-4); this story un-locked the surface and pinned the
isolation behaviours below.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.errors import TruthfulnessViolation
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    DecisionId,
    JobPostingId,
    OnboardingProfileId,
    ResumeVariantId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


def _campaign(storage, *, name="C", target=15) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name=name, throughput_target=target))
    return cid


def _add_attribute(storage, cid, name, value) -> None:
    storage.attributes.add(
        Attribute(id=AttributeId(new_id()), campaign_id=cid, name=name, value=value)
    )
    storage.commit()


def _add_base_resume(storage, cid, raw_text) -> None:
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=cid,
            intake={"base_resume": {"raw_text": raw_text}},
        )
    )
    storage.commit()


def _add_variant(storage, cid, *, parent=None, approved=True) -> ResumeVariant:
    v = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path=f"variants/{new_id()}.tex",
        parent_id=parent,
        approved=approved,
    )
    storage.resume_variants.add(v)
    storage.commit()
    return v


# === fabrication guard scoping (DoD: guard ground truth per campaign) ======
@pytest.mark.unit
def test_fabrication_ground_truth_scopes_to_the_campaigns_own_base_profile(storage):
    """A fact supported by campaign A's base profile (its own base-résumé text
    AND its own attribute cloud) is still a fabrication for campaign B under
    the STRICT policy — the guard derives ground truth per campaign, never
    from a sibling campaign's profile."""
    svc = MaterialService(
        storage,
        llm=None,
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
        truth_policy="strict",
    )
    cid_a = _campaign(storage, name="Eng-track")
    cid_b = _campaign(storage, name="PM-track")
    # Campaign A's base profile knows Kubernetes twice over: an attribute-cloud
    # row and the uploaded base résumé's raw text. Campaign B knows neither.
    _add_attribute(storage, cid_a, "skill:k8s", "Kubernetes")
    _add_base_resume(storage, cid_a, "Led Kubernetes platform migrations at Acme.")
    _add_base_resume(storage, cid_b, "Drove product roadmaps and Salesforce rollouts.")

    truth_a = svc.true_attribute_text(cid_a)
    truth_b = svc.true_attribute_text(cid_b)

    # Supported in A (own campaign's profile) -> passes.
    svc.assert_no_fabrication(truth_a, "Worked with Kubernetes.")
    # The SAME claim under campaign B's ground truth -> strict hard-block.
    with pytest.raises(TruthfulnessViolation):
        svc.assert_no_fabrication(truth_b, "Worked with Kubernetes.")
    # And B's own fact never leaks into A's ground truth either.
    with pytest.raises(TruthfulnessViolation):
        svc.assert_no_fabrication(truth_a, "Rolled out Salesforce.")


@pytest.mark.unit
def test_flagged_facts_review_surface_scopes_to_the_documents_campaign(storage):
    """The review surface recomputes flagged facts from the STORED document's
    own campaign (server-side, never caller-supplied): identical draft text is
    clean in the campaign whose base profile supports it and flagged in the
    one whose profile does not (BALANCED surfaces, never blocks)."""
    from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
    from applicant.core.ids import GeneratedDocumentId

    svc = MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    cid_a = _campaign(storage, name="Eng-track")
    cid_b = _campaign(storage, name="PM-track")
    _add_base_resume(storage, cid_a, "Led Kubernetes platform migrations at Acme.")
    _add_base_resume(storage, cid_b, "Drove product roadmaps for enterprise accounts.")

    def _store(cid):
        doc = GeneratedDocument(
            id=GeneratedDocumentId(new_id()),
            campaign_id=cid,
            application_id=ApplicationId(new_id()),
            type=DocumentType.COVER_LETTER,
            content="I deployed workloads on Kubernetes.",
            approved=False,
        )
        storage.documents.add(doc)
        storage.commit()
        return doc

    out_a = svc.flagged_facts_for_document(_store(cid_a).id)
    out_b = svc.flagged_facts_for_document(_store(cid_b).id)
    assert "Kubernetes" not in out_a["flagged"]  # supported by A's own base résumé
    assert "Kubernetes" in out_b["flagged"]  # unsupported in B -> surfaced for review


# === per-campaign base variants (DoD: root variant is the campaign's base) ==
@pytest.mark.unit
def test_each_campaigns_root_variant_is_its_own_base(storage):
    cid_a = _campaign(storage)
    cid_b = _campaign(storage)
    root_a = _add_variant(storage, cid_a)
    root_b = _add_variant(storage, cid_b)
    child_a = _add_variant(storage, cid_a, parent=root_a.id)

    assert root_a.is_root and root_b.is_root
    # Variant listing is campaign-scoped: neither campaign sees the other's base.
    ids_a = {v.id for v in storage.resume_variants.list_for_campaign(cid_a)}
    ids_b = {v.id for v in storage.resume_variants.list_for_campaign(cid_b)}
    assert ids_a == {root_a.id, child_a.id}
    assert ids_b == {root_b.id}

    # Lineage walks to the campaign's OWN root, never across campaigns.
    svc = MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )
    chain = svc.lineage(child_a)
    assert [v.id for v in chain] == [child_a.id, root_a.id]


# === side-by-side runs (DoD: separate digests + separate pacing) ============
class _FakeScoring:
    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="strong fit")

    def score_viability(self, pid, criteria=None):
        return None

    def is_viable(self, scoring):
        return True


class _RecordingDigest:
    """Records which campaign each delivery was for (separate digests DoD)."""

    def __init__(self):
        self.delivered: list[str] = []

    def deliver(self, campaign_id, criteria=None):
        self.delivered.append(str(campaign_id))
        return {"payload": {"rows": []}}


class _PrefillResult:
    def __init__(self, state):
        self.state = state


class _FakePrefill:
    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)


def _approve_posting(storage, cid, *, title="Engineer"):
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company="Acme", source_url="http://x")
    )
    storage.decisions.add(
        Decision(id=DecisionId(new_id()), application_id=str(pid), type=DecisionType.APPROVE)
    )
    return pid


@pytest.mark.unit
def test_two_campaigns_run_side_by_side_with_separate_digests_and_pacing(storage, tmp_path):
    """Two active campaigns advance independently in the same process: each has
    its own once-per-(campaign, day) digest delivery and its own per-day
    throughput ledger — one campaign exhausting its budget never throttles or
    silences the other."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid_a = _campaign(storage, name="Eng-track", target=2)
    cid_b = _campaign(storage, name="PM-track", target=3)
    # Distinct base profiles per campaign (the DoD's "different base résumés").
    _add_base_resume(storage, cid_a, "Kubernetes platform engineer.")
    _add_base_resume(storage, cid_b, "Enterprise product manager.")
    for i in range(5):
        _approve_posting(storage, cid_a, title=f"Eng-{i}")
        _approve_posting(storage, cid_b, title=f"PM-{i}")

    digest = _RecordingDigest()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=digest,
        prefill_service=_FakePrefill(),
        submission_service=None,
        capacity_service=None,
        sandbox=None,
        orchestrator=orch,
    )
    # acted_today derives the persisted count from agent_runs stamped with the
    # real wall clock, so anchor "now" to today's UTC date.
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    result_a = loop.run_once(cid_a, now=now)
    result_b = loop.run_once(cid_b, now=now)

    # Separate pacing: each campaign spent ITS OWN daily budget (2 vs 3).
    assert loop.acted_today(cid_a, now) == 2
    assert loop.acted_today(cid_b, now) == 3
    assert len(result_a.pipelines_started) == 2
    assert len(result_b.pipelines_started) == 3

    # Separate digests: one delivery per campaign, tagged with that campaign.
    assert sorted(digest.delivered) == sorted([str(cid_a), str(cid_b)])

    # A second run the SAME day re-delivers neither digest (per-campaign,
    # per-day guard) and adds no pipelines for the exhausted budgets.
    loop.run_once(cid_a, now=now)
    loop.run_once(cid_b, now=now)
    assert sorted(digest.delivered) == sorted([str(cid_a), str(cid_b)])
    assert loop.acted_today(cid_a, now) == 2
    assert loop.acted_today(cid_b, now) == 3
