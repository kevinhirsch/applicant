"""Reusable hermetic end-to-end pipeline harness (#364).

Exposes :func:`run_pipeline_to_stop_boundary` — a single entrypoint that assembles
the REAL engine services and drives a seeded campaign all the way through the
autonomous pipeline to the human-in-the-loop stop-boundary:

    discovery-output -> viability scoring -> daily digest -> approve
    -> tailor/material-review -> pre-fill -> STOP-BOUNDARY (awaiting final approval)

and reports what happened as a small dict::

    {
        "digest_scored":     True,   # the real ScoringService scored postings and
                                     #   the real DigestService built a non-empty digest
        "materials_tailored": True,  # the pipeline's material step generated + linked a
                                     #   tailored résumé variant for the approved item
        "awaiting_review":    True,  # the application parked at the human-review gate
        "auto_submitted":     False, # review-before-submit held: NO outcome was recorded
    }

This is the assembly proven by ``tests/e2e/test_pipeline_journey.py`` (real
``ScoringService(llm=None)`` + ``LocalEmbedding``, real ``DigestService`` /
``CriteriaService`` / ``AgentLoop`` over the file-backed checkpoint-shim
orchestrator), lifted into a reusable function and extended with the material leg so
a tailored variant is actually generated. Only the irreducible external boundaries
are faked at their service seams:

* the browser **pre-fill** (it would launch a real stealth browser) — a fake that
  honors the same ``PrefillResult.state`` contract the loop persists, landing the
  application at the final-approval gate exactly as production does and NEVER at a
  submitted/terminal state; and
* the résumé-**rendering** material adapter — a tiny truthful material service that
  forks a real ``ResumeVariant`` row (the FR-RESUME-1 output) without shelling out to
  LaTeX/LibreOffice.

It runs in the DEFAULT hermetic lane (no DB / network / browser) and is importable
from the systemic-hole BDD spec for #364.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.resume_variant import ResumeFitScoring, ResumeVariant
from applicant.core.ids import (
    CampaignId,
    DecisionId,
    JobPostingId,
    ResumeVariantId,
    new_id,
)
from applicant.core.state_machine import ApplicationState

# Terminal states the pipeline must NOT self-advance into (the stop-boundary).
_SUBMITTED_STATES = {
    ApplicationState.SUBMITTED_BY_USER,
    ApplicationState.FINISHED_BY_ENGINE,
}


class _PrefillResult:
    def __init__(self, state: ApplicationState) -> None:
        self.state = state


class _GatePrefill:
    """The browser pre-fill at its service seam (the ONE non-hermetic leg).

    Honors the same ``PrefillResult.state`` contract the loop persists, so the
    assembled pipeline lands at ``AWAITING_FINAL_APPROVAL`` exactly as production
    does. It NEVER returns a submitted/terminal state: the loop must not
    self-authorize past the human-in-the-loop gate.
    """

    def __init__(self) -> None:
        self.calls = 0

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls += 1
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)


class _TruthfulMaterial:
    """The résumé-rendering material adapter at its service seam.

    The REAL ``MaterialService`` tailors a résumé toward the JD and shells out to
    LaTeX / LibreOffice to RENDER it — the rendering binaries are the irreducible
    boundary. This forks a genuine, truthful ``ResumeVariant`` row (the FR-RESUME-1
    output the loop links to the application and the review gate inspects) without
    the render step. The forked variant is marked ``approved`` so the pipeline
    advances PAST material-review to the canonical final-approval stop-boundary —
    the variant is still produced from the candidate's TRUE source text only, never
    fabricated content.
    """

    def __init__(self, storage) -> None:
        self._storage = storage
        self.generated: list[str] = []

    def true_attribute_text(self, campaign_id, _selector: str = "") -> str:
        # The candidate's truthful source the variant is tailored FROM.
        return (
            "Kevin Hirsch — staff software engineer with deep Python, FastAPI, "
            "and distributed-systems experience shipping platforms at scale."
        )

    def select_or_generate(
        self, campaign_id, posting_id, jd_terms, true_source, application_id=None
    ):
        # Fork a real variant row tailored to the JD terms (truthful: derived from the
        # candidate's own source). Approved so the pipeline proceeds to the human
        # final-approval gate (the canonical stop-boundary) rather than parking at
        # MATERIAL_REVIEW; either way nothing is auto-submitted.
        variant = ResumeVariant(
            id=ResumeVariantId(new_id()),
            campaign_id=campaign_id,
            storage_path=f"/variants/{posting_id}.tex",
            targeted_jd_signature=" ".join(sorted(jd_terms)),
            approved=True,
        )
        self._storage.resume_variants.add(variant)
        self._storage.commit()
        self.generated.append(str(variant.id))
        fit = ResumeFitScoring(
            variant_id=variant.id,
            posting_id=posting_id,
            coverage=0.85,
        )

        class _Selection:
            pass

        sel = _Selection()
        sel.variant = variant
        sel.fit = fit
        sel.generated = True
        return sel

    def cover_letter_warranted(self, campaign_default: bool = False) -> bool:
        return False


def _seed_campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(
            id=cid,
            name="E2E harness",
            run_mode=RunMode.CONTINUOUS,
            throughput_target=15,
            criteria={
                "titles": ["Python Engineer"],
                "locations": ["Remote"],
                "work_modes": ["remote"],
                "keywords": ["python", "fastapi"],
                "salary_floor": 120000,
            },
        )
    )
    return cid


def _seed_posting(storage, cid: CampaignId, *, title: str, description: str) -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title=title,
            company="Acme",
            description=description,
            source_url=f"http://jobs/{new_id()}",
        )
    )
    return pid


def run_pipeline_to_stop_boundary() -> dict:
    """Assemble + drive the real pipeline to the human-review stop-boundary.

    Returns a dict describing the run (see the module docstring). Hermetic: no DB,
    no network, no browser — only the pre-fill browser and the résumé-render adapter
    are faked at their service seams.
    """
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    scoring = ScoringService(storage, llm=None, embedding=embedding)
    criteria = CriteriaService(storage)
    digest = DigestService(
        storage,
        notification=None,
        scoring=scoring,
        criteria=criteria,
        pending_actions=None,
    )
    prefill = _GatePrefill()
    material = _TruthfulMaterial(storage)

    # A temp dir for the durable checkpoint shim (file-backed, in-process — not a DB).
    with tempfile.TemporaryDirectory() as ckpt_dir:
        orchestrator = CheckpointShimOrchestrator(ckpt_dir)
        loop = AgentLoop(
            storage=storage,
            agent_run_service=AgentRunService(storage),
            scoring_service=scoring,
            digest_service=digest,
            criteria_service=criteria,
            prefill_service=prefill,
            material_service=material,
            orchestrator=orchestrator,
        )

        cid = _seed_campaign(storage)
        # DISCOVERY output: an on-criteria role and an off-criteria one so the real
        # lexical scorer must discriminate (discovery's network fetch is the only
        # non-hermetic part; its OUTPUT — postings in storage — is what the rest of
        # the pipeline consumes, so we seed that output directly).
        match_pid = _seed_posting(
            storage, cid, title="Python Engineer",
            description="Build python fastapi services",
        )
        _seed_posting(
            storage, cid, title="Warehouse Associate",
            description="Lift boxes in a depot",
        )
        storage.commit()

        # SCORE + DIGEST: the real DigestService scores every posting via the real
        # ScoringService and assembles the digest (only viable rows survive).
        delivered = digest.deliver(cid, criteria.get_criteria(cid))
        rows = delivered.get("payload", {}).get("rows", [])
        scores = {
            p.title: p.viability_score for p in storage.postings.list_for_campaign(cid)
        }
        digest_scored = bool(rows) and all(v is not None for v in scores.values())

        # APPROVE the viable role (the user's decision) -> APPROVED application.
        storage.decisions.add(
            Decision(
                id=DecisionId(new_id()),
                application_id=str(match_pid),
                type=DecisionType.APPROVE,
            )
        )
        storage.commit()

        # PRE-FILL + MATERIAL -> STOP-BOUNDARY: one tick advances the approved item
        # through the durable pipeline (real services; only the browser + render faked).
        loop.tick(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

        apps = storage.applications.list_for_campaign(cid)
        materials_tailored = bool(material.generated) and any(
            getattr(a, "resume_variant_id", None) is not None for a in apps
        )
        awaiting_review = any(
            a.status is ApplicationState.AWAITING_FINAL_APPROVAL for a in apps
        )
        # The stop-boundary holds iff NOTHING was auto-submitted: no recorded outcome
        # and no application walked into a terminal submitted state.
        auto_submitted = any(
            storage.outcomes.list_for_application(a.id) for a in apps
        ) or any(a.status in _SUBMITTED_STATES for a in apps)

    return {
        "digest_scored": digest_scored,
        "materials_tailored": materials_tailored,
        "awaiting_review": awaiting_review,
        "auto_submitted": auto_submitted,
    }


if __name__ == "__main__":  # pragma: no cover - manual smoke
    result = run_pipeline_to_stop_boundary()
    print(result)
    assert result["digest_scored"] is True
    assert result["materials_tailored"] is True
    assert result["awaiting_review"] is True
    assert result["auto_submitted"] is False
