"""#299 — pre-application company research feeds material generation.

Proves the CORE integration of issue #299 bullet 1: the same capped/deduped/cached
``ResearchService`` the agent loop escalates to is wired into ``MaterialService`` so
on-demand cover-letter generation folds a company-research block into the generation
context — config-gated, budget-aware, and best-effort (a no-op, byte-identical to
research-off, when the channel is unavailable / the budget is spent / it is disabled).

Hermetic: the LLM and the ResearchService are faked (no network, no real model). The
fake LLM records the exact prompt it is handed and echoes the researched company fact,
so we can assert the research actually REACHES generation (in the prompt) and the
generated material USES it (the stored document references it).
"""

from __future__ import annotations

import pytest

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.application.services.research_service import ResearchService
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id

# A distinctive, research-only fact: it is NOT in the candidate's base source, so its
# presence in the generated body proves the research context reached generation.
_RESEARCH_FACT = "Acme runs an open-source robotics platform used in 40 countries."


class _EchoResearchLLM:
    """Configured LLM that records prompts and weaves the research block back in.

    Returns the candidate's base claim plus the researched company fact, so the
    generated cover letter both passes the (entity-shaped) fabrication guard against
    the research-augmented source AND visibly USES the research.
    """

    def __init__(self) -> None:
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, **kwargs):
        from applicant.ports.driven.llm import LLMResult

        user = ""
        for m in messages:
            if m.role == "system":
                self.system_prompts.append(m.content)
            elif m.role == "user":
                self.user_prompts.append(m.content)
                user += m.content
        # Always state the candidate's true, supported claim. Only weave in the
        # company fact when the research block actually reached the prompt — so the
        # research-off / budget-spent paths produce a body that still passes the
        # fabrication guard (no Acme claim invented out of thin air).
        body = "I built data pipelines in Python."
        if _RESEARCH_FACT in user:
            body += " I am drawn to your mission because " + _RESEARCH_FACT
        return LLMResult(text=body, tier=2, model="fake")


class _RecordingResearch:
    """Capped/cached ResearchService over a fake workspace, recording each run."""

    class _WS:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def available(self) -> bool:
            return True

        def run_research(self, **kwargs) -> dict:
            self.calls.append(kwargs)
            return {
                "query": kwargs["query"],
                "summary": "Acme background brief.",
                "key_findings": [_RESEARCH_FACT],
                "sources": [{"url": "https://acme.example", "title": "Acme"}],
            }


def _seed_application(storage, *, company="Acme", role="Backend Engineer"):
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title=role,
            company=company,
            source_url="https://jobs.example/role",
        )
    )
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=pid, role_name=role)
    )
    storage.commit()
    return cid, aid


def _make_service(storage, *, llm, research, enabled=True) -> MaterialService:
    return MaterialService(
        storage,
        llm=llm,
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
        research_service=research,
        research_enabled=enabled,
    )


@pytest.mark.unit
def test_research_context_reaches_cover_letter_generation():
    """The company research is run and folded into the generation prompt + body."""
    storage = InMemoryStorage()
    ws = _RecordingResearch._WS()
    research = ResearchService(workspace=ws)
    llm = _EchoResearchLLM()
    svc = _make_service(storage, llm=llm, research=research)
    cid, aid = _seed_application(storage)

    doc = svc.generate_cover_letter(
        cid, aid, "I built data pipelines in Python.", ["Python"], campaign_default=True
    )

    # Research actually ran, scoped to the company (one fresh workspace call).
    assert len(ws.calls) == 1
    assert ws.calls[0]["company"] == "Acme"
    # The research block reached the LLM prompt (the user message carries the source).
    assert llm.user_prompts, "generation never reached the LLM"
    assert _RESEARCH_FACT in "\n".join(llm.user_prompts)
    # The generated material USES the company-specific detail (and survived the
    # fabrication guard because the research was added to the check source).
    assert doc is not None
    assert "Acme" in (doc.content or "")


@pytest.mark.unit
def test_research_disabled_is_a_silent_noop():
    """research_enabled=False ⇒ no research run, generation byte-identical to before."""
    storage = InMemoryStorage()
    ws = _RecordingResearch._WS()
    research = ResearchService(workspace=ws)
    llm = _EchoResearchLLM()
    svc = _make_service(storage, llm=llm, research=research, enabled=False)
    cid, aid = _seed_application(storage)

    svc.generate_cover_letter(cid, aid, "I built data pipelines in Python.", ["Python"])
    assert ws.calls == []  # never touched the research channel


@pytest.mark.unit
def test_research_budget_exhaustion_degrades_gracefully():
    """When the per-campaign research budget is spent, generation still succeeds
    (best-effort) without the research block — the cap is never weakened."""
    storage = InMemoryStorage()
    ws = _RecordingResearch._WS()
    research = ResearchService(workspace=ws, max_calls=0)  # no budget at all
    llm = _EchoResearchLLM()
    svc = _make_service(storage, llm=llm, research=research)
    cid, aid = _seed_application(storage)

    doc = svc.generate_cover_letter(cid, aid, "I built data pipelines in Python.", ["Python"])
    # Budget cap honoured: no fresh run charged.
    assert ws.calls == []
    assert research.calls_made(cid) == 0
    # Generation still produced a document (degraded, no research block).
    assert doc is not None


@pytest.mark.unit
def test_research_unavailable_channel_is_a_noop():
    """An unavailable workspace channel ⇒ no research, no crash."""
    storage = InMemoryStorage()

    class _OffWS:
        def available(self) -> bool:
            return False

        def run_research(self, **kwargs):  # pragma: no cover - never called
            raise AssertionError("must not run when channel is off")

    research = ResearchService(workspace=_OffWS())
    svc = _make_service(storage, llm=_EchoResearchLLM(), research=research)
    cid, aid = _seed_application(storage)
    doc = svc.generate_cover_letter(cid, aid, "I built data pipelines in Python.", ["Python"])
    assert doc is not None


@pytest.mark.unit
def test_research_cache_is_shared_across_generations():
    """A second generation for the same company reuses the cached brief for free
    (no second workspace call), proving the SAME capped/cached service is in play."""
    storage = InMemoryStorage()
    ws = _RecordingResearch._WS()
    research = ResearchService(workspace=ws)
    svc = _make_service(storage, llm=_EchoResearchLLM(), research=research)
    cid, aid1 = _seed_application(storage)
    # Second application, SAME company → same normalized research query.
    _cid2, aid2 = _seed_application(storage, company="Acme")
    # Both run under the first campaign so the cache key (campaign, query) matches.
    svc.generate_cover_letter(cid, aid1, "Built pipelines in Python.", ["Python"])
    # Re-seed a second application under the SAME campaign + company.
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title="Backend Engineer",
            company="Acme",
            source_url="https://jobs.example/role",
        )
    )
    aid_same = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid_same, campaign_id=cid, posting_id=pid, role_name="Backend Engineer")
    )
    storage.commit()
    svc.generate_cover_letter(cid, aid_same, "Built pipelines in Python.", ["Python"])
    # Only ONE fresh research run despite two generations for the same company.
    assert len(ws.calls) == 1
