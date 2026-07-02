"""Coverage: product-gaps backlog #20 (screening-answer library) + #30
(interview-prep generation), ``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``.

**Screening-answer library (#20).** ``MaterialService.generate_screening_answer``
already generates + reviews a screening answer per-application (FR-ANSWER-1), but
had no persistence a *future* application could reuse: users answer the same
common questions ("Why do you want to work here?", "Notice period?") over and
over. This adds a reusable, campaign-scoped answer bank (parallel to the résumé
variant library, FR-RESUME-6) that a generation quietly builds over time, plus a
``reuse_screening_answer`` entry point that reuses a stored answer for a NEW
application instead of a fresh LLM call -- while still re-verifying it against
the fabrication guard at the persistence boundary (NFR-TRUTH-1, fail-closed,
never bypassed by reuse).

**Interview prep (#30).** Given an application that has reached the
``interview_invited`` outcome signal (the outcome-loop work), generates a
plain-language "things to review before your interview" brief by reusing the
SAME company-research channel cover-letter generation already draws on
(``_company_research_context`` / the shared ``ResearchService``, #299 -- no
second research pipeline) plus the posting's own purely-extractive stated
requirements.

Hermetic: ``InMemoryStorage``, no LLM/DB/network. The router section additionally
proves end-to-end reachability through ``POST /api/documents/*`` via a real
``TestClient(create_app())`` (mirrors ``test_cov_documents.py``).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.material_service import MaterialService
from applicant.application.services.research_service import ResearchService
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent
from applicant.core.errors import TruthfulnessViolation
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, OutcomeEventId, new_id
from applicant.core.rules.materials import normalize_screening_question

# === normalize_screening_question (pure) ===================================


@pytest.mark.unit
class TestNormalizeScreeningQuestion:
    def test_case_and_trailing_punctuation_collapse_to_the_same_key(self):
        a = normalize_screening_question("Why do you want to work here?")
        b = normalize_screening_question("why do you want to work here")
        assert a == b == "why do you want to work here"

    def test_internal_whitespace_is_collapsed(self):
        assert (
            normalize_screening_question("Why   do you\twant to work here?")
            == "why do you want to work here"
        )

    def test_blank_question_normalizes_to_empty_key(self):
        assert normalize_screening_question("") == ""
        assert normalize_screening_question("   ") == ""

    def test_distinct_questions_never_collide(self):
        assert normalize_screening_question("Why this company?") != normalize_screening_question(
            "What is your notice period?"
        )


# === MaterialService fixtures ===============================================


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def svc(storage) -> MaterialService:
    return MaterialService(
        storage, llm=None, resume_tailoring=LatexTailor(), embedding=LocalEmbedding()
    )


def _seed_application(storage, *, company="Acme", role="Backend Engineer", description=""):
    cid = CampaignId(new_id())
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title=role,
            company=company,
            source_url="https://jobs.example/role",
            description=description,
        )
    )
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=pid, role_name=role)
    )
    storage.commit()
    return cid, aid


def _mark_interview_invited(storage, application_id) -> None:
    storage.outcomes.add(
        OutcomeEvent(
            id=OutcomeEventId(new_id()), application_id=application_id, type="interview_invited"
        )
    )
    storage.commit()


# === screening-answer library builds over time (#20) ========================


@pytest.mark.unit
class TestScreeningAnswerLibraryPersistence:
    def test_generating_an_essay_answer_saves_it_to_the_library(self, svc, storage):
        cid, aid = _seed_application(storage)
        svc.generate_screening_answer(
            cid, aid, "Why do you want to work here?", "I love building pipelines.", essay=None
        )
        items = svc.list_screening_answer_library(cid)
        assert len(items) == 1
        assert items[0]["question"] == "Why do you want to work here?"
        assert items[0]["essay"] is True

    def test_generating_a_factual_answer_saves_it_to_the_library(self, svc, storage):
        cid, aid = _seed_application(storage)
        svc.generate_screening_answer(
            cid, aid, "How many years of Python?", "Eight years.", essay=None
        )
        items = svc.list_screening_answer_library(cid)
        assert len(items) == 1
        assert items[0]["answer"] == "Eight years."
        assert items[0]["essay"] is False

    def test_sensitive_answers_are_never_saved_to_the_library(self, svc, storage):
        # FR-ATTR-6/NFR-PRIV-1: EEO/demographic answers are policy-driven and must
        # never leak into a cross-application store.
        cid, aid = _seed_application(storage)
        svc.generate_screening_answer(
            cid, aid, "What is your race/ethnicity?", "irrelevant PII", essay=None
        )
        assert svc.list_screening_answer_library(cid) == []

    def test_a_repeated_question_upserts_the_same_entry_not_a_duplicate(self, svc, storage):
        cid, aid = _seed_application(storage)
        svc.generate_screening_answer(
            cid, aid, "Why this company?", "I admire the mission.", essay=None
        )
        svc.generate_screening_answer(
            cid, aid, "why this company?", "I admire the mission and the team.", essay=None
        )
        items = svc.list_screening_answer_library(cid)
        assert len(items) == 1  # same normalized key -> one entry, latest wins
        assert items[0]["answer"] == "I admire the mission and the team."

    def test_library_is_scoped_per_campaign(self, svc, storage):
        cid1, aid1 = _seed_application(storage)
        cid2, aid2 = _seed_application(storage)
        svc.generate_screening_answer(
            cid1, aid1, "Why this company?", "Campaign one reasons.", essay=None
        )
        assert svc.list_screening_answer_library(cid1) != []
        assert svc.list_screening_answer_library(cid2) == []


# === reuse_screening_answer (#20) ===========================================


@pytest.mark.unit
class TestReuseScreeningAnswer:
    def test_no_match_returns_none(self, svc, storage):
        cid, aid = _seed_application(storage)
        assert svc.reuse_screening_answer(cid, aid, "Never asked before?") is None

    def test_reuse_for_a_new_application_stores_the_same_answer_unapproved(self, svc, storage):
        cid, aid1 = _seed_application(storage)
        svc.generate_screening_answer(
            cid, aid1, "Why do you want to work here?", "I love building pipelines.", essay=None
        )
        # A second, DIFFERENT application in the SAME campaign asks the same
        # question (differently phrased/punctuated) later.
        pid2 = JobPostingId(new_id())
        storage.postings.add(
            JobPosting(
                id=pid2,
                campaign_id=cid,
                title="Backend Engineer",
                company="Acme",
                source_url="https://jobs.example/role-2",
            )
        )
        aid2 = ApplicationId(new_id())
        storage.applications.add(
            Application(id=aid2, campaign_id=cid, posting_id=pid2, role_name="Backend Engineer")
        )
        storage.commit()
        doc = svc.reuse_screening_answer(cid, aid2, "why do you want to work here")
        assert doc is not None
        assert doc.application_id == aid2
        assert doc.approved is False  # still routed through the review gate
        assert "pipelines" in (doc.content or "")

    def test_reuse_never_bypasses_the_truthfulness_guard(self, svc, storage):
        # A library entry can, in principle, go stale (edited manually, or a
        # future campaign's true source no longer supports it). Reuse must
        # RE-VERIFY at the persistence boundary, exactly like a fresh
        # generation -- never trust the stored text as pre-cleared.
        from applicant.core.entities.screening_answer_library import (
            ScreeningAnswerLibraryEntry,
        )
        from applicant.core.ids import ScreeningAnswerLibraryEntryId

        cid, aid = _seed_application(storage)
        storage.screening_answer_library.upsert(
            ScreeningAnswerLibraryEntry(
                id=ScreeningAnswerLibraryEntryId(new_id()),
                campaign_id=cid,
                question_key=normalize_screening_question("Years of Kubernetes?"),
                question_text="Years of Kubernetes?",
                answer_text="Five years running Kubernetes clusters at scale.",
                essay=False,
            )
        )
        # The candidate's true attribute cloud (built from onboarding/attributes,
        # here empty) never mentions Kubernetes -- a factual reuse must fail
        # closed rather than silently publish an unsupported claim.
        with pytest.raises(TruthfulnessViolation):
            svc.reuse_screening_answer(cid, aid, "years of kubernetes?")

    def test_missing_repo_degrades_to_none_not_a_crash(self, storage):
        # An adapter that hasn't wired the library repo (defensive future-proofing)
        # must never break reuse -- it just means "nothing to reuse".
        svc = MaterialService(storage, llm=None, resume_tailoring=LatexTailor())
        cid, aid = _seed_application(storage)
        del storage.screening_answer_library  # simulate an unwired adapter
        assert svc.reuse_screening_answer(cid, aid, "anything?") is None


# === interview prep (#30) ===================================================


class _RecordingResearch:
    class _WS:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def available(self) -> bool:
            return True

        def run_research(self, **kwargs) -> dict:
            self.calls.append(kwargs)
            return {
                "query": kwargs["query"],
                "summary": "Acme is a fast-growing robotics company.",
                "key_findings": ["Acme runs an open-source robotics platform."],
                "sources": [{"url": "https://acme.example", "title": "Acme"}],
            }


@pytest.mark.unit
class TestGenerateInterviewPrep:
    def test_returns_none_without_an_interview_invited_signal(self, svc, storage):
        cid, aid = _seed_application(storage, description="Own the deployment pipeline.")
        # No outcome event recorded at all -- must never fabricate a brief for an
        # application that was never actually invited to interview.
        assert svc.generate_interview_prep(cid, aid) is None

    def test_returns_none_for_a_non_interview_signal(self, svc, storage):
        cid, aid = _seed_application(storage, description="Own the deployment pipeline.")
        storage.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=aid, type="rejected")
        )
        storage.commit()
        assert svc.generate_interview_prep(cid, aid) is None

    def test_brief_includes_company_role_and_extracted_requirements(self, svc, storage):
        cid, aid = _seed_application(
            storage,
            company="Acme",
            role="Backend Engineer",
            description="Own the deployment pipeline. Mentor junior engineers. 5+ years Python required.",
        )
        _mark_interview_invited(storage, aid)
        brief = svc.generate_interview_prep(cid, aid)
        assert brief is not None
        assert brief["company"] == "Acme"
        assert brief["role"] == "Backend Engineer"
        assert any("deployment pipeline" in r for r in brief["key_requirements"])
        assert any("Python" in r for r in brief["key_requirements"])
        assert brief["notes"]  # plain-language notes present

    def test_reuses_the_same_research_service_cover_letters_use(self, storage):
        # #299 / no-second-pipeline: interview prep must escalate through the
        # SAME capped/deduped/cached ResearchService, not a fresh channel.
        ws = _RecordingResearch._WS()
        research = ResearchService(workspace=ws)
        svc = MaterialService(
            storage,
            llm=None,
            resume_tailoring=LatexTailor(),
            embedding=LocalEmbedding(),
            research_service=research,
        )
        cid, aid = _seed_application(storage, company="Acme", description="Ship reliable systems.")
        _mark_interview_invited(storage, aid)
        brief = svc.generate_interview_prep(cid, aid)
        assert brief is not None
        assert len(ws.calls) == 1
        assert ws.calls[0]["company"] == "Acme"
        assert "robotics platform" in brief["company_research"]

    def test_key_requirements_are_purely_extractive_never_llm_authored(self, svc, storage):
        # llm=None throughout this fixture -- if key_requirements ever silently
        # started going through generation, this would be the first thing to
        # break (there is no LLM wired to answer it).
        cid, aid = _seed_application(
            storage, description="Design scalable APIs. Write clean, tested code."
        )
        _mark_interview_invited(storage, aid)
        brief = svc.generate_interview_prep(cid, aid)
        assert brief is not None
        joined = " ".join(brief["key_requirements"])
        assert "Design scalable APIs" in joined
        assert "Write clean, tested code" in joined

    def test_unknown_application_returns_none(self, svc, storage):
        cid = CampaignId(new_id())
        assert svc.generate_interview_prep(cid, ApplicationId(new_id())) is None


# === router reachability (POST /api/documents/*) ============================


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


@pytest.mark.unit
class TestScreeningAnswerLibraryRouter:
    def test_library_starts_empty_then_reflects_a_generation(self, client):
        cid, aid = "camp-lib-1", "app-lib-1"
        empty = client.get(f"/api/documents/screening-answer-library/{cid}")
        assert empty.status_code == 200
        assert empty.json() == {"campaign_id": cid, "items": []}

        made = client.post(
            "/api/documents/screening-answer",
            json={
                "campaign_id": cid,
                "application_id": aid,
                "question": "Why do you want to work here?",
                "true_source": "I love building data platforms.",
            },
        )
        assert made.status_code == 201

        listing = client.get(f"/api/documents/screening-answer-library/{cid}")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 1
        assert items[0]["question"] == "Why do you want to work here?"

    def test_reuse_not_found_reports_found_false(self, client):
        res = client.post(
            "/api/documents/screening-answer-library/reuse",
            json={
                "campaign_id": "camp-lib-2",
                "application_id": "app-lib-2",
                "question": "Never asked before?",
            },
        )
        assert res.status_code == 201
        assert res.json() == {"found": False}

    def test_reuse_hits_and_creates_a_new_reviewable_document(self, client):
        cid = "camp-lib-3"
        # Reuse re-derives its OWN truthfulness ground truth server-side (never the
        # original one-off true_source override) -- seed it into the attribute
        # cloud so the fail-closed re-verification at the persistence boundary
        # (NFR-TRUTH-1) actually has something to support the reused claim.
        from applicant.core.entities.attribute import Attribute
        from applicant.core.ids import AttributeId, CampaignId

        storage = client.app.state.container.storage
        storage.attributes.add(
            Attribute(
                id=AttributeId(new_id()),
                campaign_id=CampaignId(cid),
                name="Notice Period",
                value="Two weeks.",
            )
        )
        storage.commit()

        made = client.post(
            "/api/documents/screening-answer",
            json={
                "campaign_id": cid,
                "application_id": "app-lib-3a",
                "question": "What's your notice period?",
                "true_source": "Two weeks.",
                "essay": False,
            },
        )
        assert made.status_code == 201

        reused = client.post(
            "/api/documents/screening-answer-library/reuse",
            json={
                "campaign_id": cid,
                "application_id": "app-lib-3b",
                "question": "what's your notice period?",
            },
        )
        assert reused.status_code == 201
        body = reused.json()
        assert body["found"] is True
        assert body["approved"] is False
        assert body["id"] != made.json()["id"]  # a distinct new document


@pytest.mark.unit
class TestInterviewPrepRouter:
    def test_not_generated_before_the_interview_invited_signal(self, client):
        cid, aid = "camp-prep-1", "app-prep-1"
        res = client.get(f"/api/documents/interview-prep/{cid}/{aid}")
        assert res.status_code == 200
        assert res.json() == {"generated": False}

    def test_generated_once_the_application_has_the_signal(self, client):
        cid, aid = "camp-prep-2", "app-prep-2"
        storage = client.app.state.container.storage
        from applicant.core.entities.application import Application
        from applicant.core.entities.job_posting import JobPosting
        from applicant.core.entities.outcome_event import OutcomeEvent
        from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, OutcomeEventId

        pid = JobPostingId(new_id())
        storage.postings.add(
            JobPosting(
                id=pid,
                campaign_id=CampaignId(cid),
                title="Backend Engineer",
                company="Acme",
                source_url="https://jobs.example/role",
                description="Own the deployment pipeline. 5+ years Python required.",
            )
        )
        storage.applications.add(
            Application(
                id=ApplicationId(aid),
                campaign_id=CampaignId(cid),
                posting_id=pid,
                role_name="Backend Engineer",
            )
        )
        storage.outcomes.add(
            OutcomeEvent(
                id=OutcomeEventId(new_id()),
                application_id=ApplicationId(aid),
                type="interview_invited",
            )
        )
        storage.commit()

        res = client.get(f"/api/documents/interview-prep/{cid}/{aid}")
        assert res.status_code == 200
        body = res.json()
        assert body["generated"] is True
        assert body["company"] == "Acme"
        assert body["role"] == "Backend Engineer"
        assert any("Python" in r for r in body["key_requirements"])
