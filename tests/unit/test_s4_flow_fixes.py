"""Sweep-4 (s4-flow) fixes — fail-before/pass-after regression tests.

Each test cites the requirement ID for the bug it pins:

  1.  FR-RESUME-1/8, FR-DUR-1  — autonomous material-review flow completes end-to-end.
  2.  FR-PREFILL-6, §7         — BLOCKED_DETECTION re-drives via a legal PREFILLING transition.
  3.  FR-PREFILL-5            — account-handoff takeover link keeps the ``app=`` continuity.
  4.  FR-RESUME-8            — review gate covers an unapproved GENERATED resume variant.
  5.  FR-ANSWER-1/NFR-PRIV-1 — factual screening answer is question-scoped, not the whole cloud.
  6.  CONC-REQ-1            — per-request Session-backed storage; no-DB path still boots.
  7.  FR-NOTIF-4            — redline link points at the served /review surface.
  8.  FR-AGENT-2            — _viable_count scores against campaign criteria.
  9.  FR-AGENT-1            — daily-acted budget charged only after a pipeline actually starts.
  12. SECURITY + config     — EGRESS_MODE validator + SSRF guard for operator URLs.
  13. INFO                  — admin history/logs limit clamped.
  MINOR FR-FB-1            — blank decline feedback raises the domain InvalidInput (422).
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
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    DecisionId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState


# --- shared fakes / helpers ----------------------------------------------
class _FakeScoring:
    def __init__(self):
        self.criteria_seen: list = []

    def score_posting(self, posting, criteria=None):
        from applicant.core.entities.viability_scoring import ViabilityScoring

        self.criteria_seen.append(criteria)
        return ViabilityScoring(posting_id=posting.id, score=0.9, rationale="fit")

    def score_viability(self, pid, criteria=None):
        return None

    def is_viable(self, scoring):
        return True


class _FakeDigest:
    def deliver(self, campaign_id, criteria=None):
        return {"payload": {"rows": []}}


class _SpyNotifier:
    def __init__(self):
        self.sent: list = []
        self.expired: list = []

    def notify(self, n):
        self.sent.append(n)
        return "h"

    def expire(self, k):
        self.expired.append(k)


def _make_campaign(storage, *, run_mode=RunMode.CONTINUOUS):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", run_mode=run_mode))
    return cid


def _approve_posting(storage, cid, *, title="Python Engineer"):
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid, campaign_id=cid, title=title, company="Acme", source_url="http://x")
    )
    storage.decisions.add(
        Decision(id=DecisionId(new_id()), application_id=str(pid), type=DecisionType.APPROVE)
    )
    return pid


# ============================================================ #1 material flow
@pytest.mark.unit
def test_material_review_flow_completes_end_to_end(tmp_path):
    """#1 (FR-RESUME-1/8, FR-DUR-1): generate material -> material_review pending
    action + notification exist -> approving the variant advances the pipeline past
    the recv gate (submit recorded + teardown runs + sandbox released).

    FAIL-BEFORE: _prepare_material_for hardcoded review_approved=False under a
    constant checkpoint key, so the pipeline parked at MATERIAL_REVIEW forever and
    nothing (no pending action, no approve path) let it advance.
    """
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)
    notifier = _SpyNotifier()

    class _Capacity:
        def __init__(self):
            self.released: list = []

        def admit_sandbox(self, work_id):
            return True

        def release_sandbox(self, work_id):
            self.released.append(work_id)

        def yield_for_block(self, work_id, state):
            pass

    class _Submission:
        def __init__(self):
            self.recorded: list = []

        def record_submission(self, application, *, source, **kw):
            from applicant.core.entities.outcome_event import OutcomeEvent
            from applicant.core.ids import OutcomeEventId

            self.recorded.append(str(application.id))
            return OutcomeEvent(
                id=OutcomeEventId(new_id()),
                application_id=application.id,
                type="submitted",
                source=source,
            )

    class _Prefill:
        def prefill_application(self, application, url, attributes=None, *, cautious=True):
            class _R:
                state = ApplicationState.AWAITING_FINAL_APPROVAL

            return _R()

    pas = PendingActionsService(storage)
    material = MaterialService(
        storage,
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
        notifications=NotificationService(notifier),
        pending_actions=pas,
    )
    capacity = _Capacity()
    submission = _Submission()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=_Prefill(),
        material_service=material,
        submission_service=submission,
        capacity_service=capacity,
        orchestrator=orch,
    )
    now = datetime(2026, 6, 16, tzinfo=UTC)

    # First tick: generate material, park at MATERIAL_REVIEW.
    result = loop.run_once(cid, now=now)
    app = storage.applications.list_for_campaign(cid)[0]
    assert str(app.id) in result.handoffs

    # A material_review pending action + a review notification exist for the user.
    pending = pas.list_pending(cid)
    assert any(p.kind == "material_review" for p in pending)
    assert notifier.sent  # review-ready notification fired

    # The generated variant is linked to the app + unapproved.
    variants = storage.resume_variants.list_for_campaign(cid)
    assert variants and not variants[0].approved
    assert storage.applications.get(app.id).resume_variant_id == variants[0].id

    # Approve the variant (the HTTP approve_variant path).
    material.approve_variant(variants[0].id)

    # Deliver the final-approval decision to the durable gate, then re-drive.
    orch.send(f"application:{app.id}", "final_approval", {"decision": "finished_by_engine"})
    loop.run_once(cid, now=now)

    # The pipeline advanced past the recv gate: submit recorded + sandbox released.
    assert str(app.id) in submission.recorded
    assert str(app.id) in capacity.released


# ============================================================ #2 detection resume
class _ResumeSpyPrefill:
    def __init__(self):
        self.calls: list[str] = []

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls.append("prefill_application")
        # Mirror the real bug: a full restart from a blocked state is illegal.
        application.with_status(ApplicationState.SANDBOX_PROVISIONING)

        class _R:
            state = ApplicationState.AWAITING_FINAL_APPROVAL

        return _R()

    def resume_after_detection(self, application, attributes=None, *, cautious=True):
        self.calls.append("resume_after_detection")
        # Legal BLOCKED_DETECTION -> PREFILLING transition (proves legality).
        application.with_status(ApplicationState.PREFILLING)

        class _R:
            state = ApplicationState.AWAITING_FINAL_APPROVAL

        return _R()


@pytest.mark.unit
def test_blocked_detection_redrives_via_legal_prefilling_transition(tmp_path):
    """#2 (FR-PREFILL-6, §7): a BLOCKED_DETECTION app re-drives through
    resume_after_detection (BLOCKED_DETECTION -> PREFILLING, legal) and progresses —
    not via the full-restart prefill_application (-> SANDBOX_PROVISIONING, illegal).

    FAIL-BEFORE: the loop routed BLOCKED_DETECTION to prefill_application, whose first
    move SANDBOX_PROVISIONING is illegal from BLOCKED_DETECTION; the exception was
    swallowed and the app stranded.
    """
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    pid = _approve_posting(storage, cid)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=pid,
        status=ApplicationState.BLOCKED_DETECTION,
        root_url="http://x",
    )
    storage.applications.add(app)
    storage.commit()

    spy = _ResumeSpyPrefill()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=spy,
        orchestrator=orch,
    )
    loop.run_once(cid, now=datetime(2026, 6, 16, tzinfo=UTC))
    assert "resume_after_detection" in spy.calls
    assert "prefill_application" not in spy.calls


@pytest.mark.unit
def test_resume_after_detection_uses_legal_transition():
    """#2: PrefillService.resume_after_detection starts at PREFILLING (legal from
    BLOCKED_DETECTION) and never touches SANDBOX_PROVISIONING."""
    from applicant.application.services.prefill_service import PrefillService

    # A minimal browser stub: the first page is the final-submit page so the loop ends.
    class _Browser:
        def current_state(self, aid):
            class _S:
                url = "http://x"
                detection_signals = ()
                status = None
                body = None
                expected_host = None

            return _S()

        def is_account_create_page(self, aid):
            return False

        def is_final_submit_page(self, aid):
            return True

        def detect_fields(self, aid):
            return []

        def screenshot(self, aid):
            return "s"

        def advance(self, aid):
            return None

    class _Detection:
        def evaluate(self, aid, signals):
            return None

    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.BLOCKED_DETECTION,
    )
    storage.applications.add(app)
    storage.commit()
    pf = PrefillService(
        storage=storage,
        browser=_Browser(),
        detection=_Detection(),
        sandbox=None,
        credentials=None,
    )
    result = pf.resume_after_detection(app, [], cautious=False)
    # Reached the final-approval gate without an IllegalStateTransition.
    assert result.state is ApplicationState.AWAITING_FINAL_APPROVAL


# ============================================================ #3 account handoff app=
@pytest.mark.unit
def test_account_handoff_keeps_app_continuity_in_session_url():
    """#3 (FR-PREFILL-5): a first-page account-create handoff persists a pending
    action whose payload session_url carries ``app=`` (the bound url), not the
    pre-binding snapshot.

    FAIL-BEFORE: _account_handoff received session.remote_view_url (pre-binding, no
    ``&app=``) instead of result.sandbox_session_url (bound).
    """
    from applicant.application.services.prefill_service import PrefillService

    bound_url = "https://sandbox.local/webtop/sess-1?app=http%3A%2F%2Fjobs"
    snapshot_url = "https://sandbox.local/webtop/sess-1"

    class _Session:
        session_id = "sess-1"
        remote_view_url = snapshot_url

    class _RemoteView:
        def bind_application_url(self, sid, url):
            pass

        def view_url(self, sid):
            return bound_url

    class _Sandbox:
        def provision(self, aid):
            return _Session()

        def remote_view(self):
            return _RemoteView()

    class _Browser:
        def open(self, aid, url):
            pass

        def is_account_create_page(self, aid):
            return True

        def current_state(self, aid):
            class _S:
                url = "http://jobs"
                detection_signals = ()
                status = None
                body = None
                expected_host = None

            return _S()

        def detect_fields(self, aid):
            return []

        def screenshot(self, aid):
            return "s"

    class _Detection:
        def evaluate(self, aid, signals):
            return None  # no detection -> straight to account handoff

    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
    )
    storage.applications.add(app)
    storage.commit()
    pf = PrefillService(
        storage=storage,
        browser=_Browser(),
        detection=_Detection(),
        sandbox=_Sandbox(),
        credentials=None,
    )
    result = pf.prefill_application(app, "http://jobs", [], cautious=True)
    assert result.state is ApplicationState.AWAITING_ACCOUNT_HUMAN_STEP
    pa = storage.pending_actions.get(result.pending_action_id)
    assert "app=" in (pa.payload.get("session_url") or "")


# ============================================================ #4 review gate variant
@pytest.mark.unit
def test_review_gate_blocks_unapproved_generated_variant():
    """#4 (FR-RESUME-8): an app with an unapproved GENERATED resume variant (and no
    documents) is NOT submittable.

    FAIL-BEFORE: ensure_submittable built ReviewableMaterial only from documents, so
    an unapproved generated variant was invisible and could be submitted unreviewed.
    """
    from applicant.application.services.submission_service import SubmissionService
    from applicant.core.entities.resume_variant import ResumeVariant
    from applicant.core.errors import ReviewRequired
    from applicant.core.ids import ResumeVariantId

    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    vid = ResumeVariantId(new_id())
    storage.resume_variants.add(
        ResumeVariant(id=vid, campaign_id=cid, storage_path="v.tex", approved=False)
    )
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.AWAITING_FINAL_APPROVAL,
            resume_variant_id=vid,
        )
    )
    storage.commit()

    sub = SubmissionService(storage)
    with pytest.raises(ReviewRequired):
        sub.ensure_submittable(aid)

    # Once approved, the gate opens.
    import dataclasses

    storage.resume_variants.add(
        dataclasses.replace(storage.resume_variants.get(vid), approved=True)
    )
    storage.commit()
    sub.ensure_submittable(aid)  # no raise


# ============================================================ #5 factual scoping
@pytest.mark.unit
def test_factual_answer_is_question_scoped_not_whole_cloud():
    """#5 (FR-ANSWER-1/NFR-PRIV-1): a factual answer over a FULL flattened true_source
    returns only the question-relevant fact, never the whole attribute cloud/PII.

    FAIL-BEFORE: the FACTUAL branch did ``answer = true_source.strip()`` which, in the
    live loop, dumped the entire flattened cloud (resume + PII) into the form field.
    """
    storage = InMemoryStorage()
    svc = MaterialService(storage, resume_tailoring=LatexTailor())
    flattened = "\n".join(
        [
            "SSN 123-45-6789",
            "Eight years of Python experience",
            "Lives in Berlin",
            "Salary expectation confidential",
        ]
    )
    doc = svc.generate_screening_answer(
        CampaignId(new_id()), new_id(), "How many years of Python?", flattened, essay=False
    )
    # Only the Python-relevant line is surfaced; the PII / unrelated lines are not.
    assert "Python" in doc.content
    assert "SSN" not in doc.content
    assert "Berlin" not in doc.content
    assert doc.content != flattened


@pytest.mark.unit
def test_factual_answer_single_fact_passthrough():
    """#5: a one-fact true_source (BDD/contract lane) is still returned verbatim."""
    storage = InMemoryStorage()
    svc = MaterialService(storage, resume_tailoring=LatexTailor())
    doc = svc.generate_screening_answer(
        CampaignId(new_id()), new_id(), "How many years of Python?", "Eight years.", essay=False
    )
    assert doc.content == "Eight years."


# ============================================================ #6 per-request session
@pytest.mark.unit
def test_no_db_path_still_boots_and_storage_dep_resolves():
    """#6 (CONC-REQ-1): with no DB configured the app boots and get_storage falls back
    to the shared in-memory storage (request_services_factory is None)."""
    from fastapi.testclient import TestClient

    from applicant.app.main import create_app

    app = create_app()
    container = app.state.container
    # No DB in the hermetic lane -> no per-request factory; in-memory storage shared.
    assert container.request_services_factory is None
    with TestClient(app) as client:
        assert client.get("/api/setup/status").status_code == 200


@pytest.mark.unit
def test_request_services_factory_yields_distinct_session_backed_storages():
    """#6 (CONC-REQ-1): when a DB IS configured, the per-request factory builds a
    DISTINCT SqlAlchemyStorage (its own Session) per call so concurrent requests do
    not interleave on one non-thread-safe Session."""
    calls: list = []

    class _FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    def _session_factory():
        s = _FakeSession()
        calls.append(s)
        return s

    class _FakeStorage:
        def __init__(self, session):
            self._session = session

    # Drive the deps generator directly with a stub container exposing the factory.
    from applicant.app.deps import get_request_services

    def _factory():
        session = _session_factory()
        return {"_session": session, "storage": _FakeStorage(session)}

    class _Container:
        request_services_factory = staticmethod(_factory)

    class _ReqState:
        pass

    class _Req:
        state = _ReqState()

    # Two independent "requests": each gets its own Session-backed storage + close.
    storages = []
    for _ in range(2):
        req = _Req()
        gen = get_request_services(req, _Container())
        services = next(gen)
        storages.append(services["storage"])
        gen.close()  # triggers the finally -> session.close()

    assert storages[0] is not storages[1]
    assert storages[0]._session is not storages[1]._session
    assert all(s.closed for s in calls)  # each per-request Session was closed


# ============================================================ #7 redline link
@pytest.mark.unit
def test_redline_link_targets_served_review_surface():
    """#7 (FR-NOTIF-4): redline_link returns the served /review surface."""
    from applicant.application.services.final_approval_service import redline_link

    assert redline_link("app-9") == "/review?application=app-9"
    assert "/redline" not in redline_link("app-9")


# ============================================================ #8 viable count criteria
@pytest.mark.unit
def test_viable_count_scores_with_campaign_criteria(tmp_path):
    """#8 (FR-AGENT-2): _viable_count's fallback score_posting receives the campaign
    criteria, not None.

    FAIL-BEFORE: score_posting(posting) was called with no criteria, scoring against
    empty defaults.
    """
    from applicant.core.entities.search_criteria import SearchCriteria

    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage, run_mode=RunMode.UNTIL_N_VIABLE)
    storage.postings.add(
        JobPosting(id=JobPostingId(new_id()), campaign_id=cid, title="R", company="A", source_url="u")
    )

    crit = SearchCriteria(campaign_id=cid, titles=("engineer",))

    class _Criteria:
        def get_criteria(self, campaign_id):
            return crit

    scoring = _FakeScoring()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=scoring,
        criteria_service=_Criteria(),
        orchestrator=orch,
    )
    n = loop._viable_count(cid)
    assert n == 1
    assert crit in scoring.criteria_seen  # criteria was threaded into scoring


# ============================================================ #9 record_acted ordering
@pytest.mark.unit
def test_daily_budget_not_charged_when_admission_deferred(tmp_path):
    """#9 (FR-AGENT-1): when sandbox admission is deferred (capacity full), the daily
    acted budget is NOT charged for the app that never started.

    FAIL-BEFORE: _record_acted ran BEFORE _start_pipeline, so a deferred start still
    burned the day's budget.
    """
    storage = InMemoryStorage()
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    cid = _make_campaign(storage)
    _approve_posting(storage, cid)

    class _FullCapacity:
        def admit_sandbox(self, work_id):
            return False  # always full -> every start is deferred

        def release_sandbox(self, work_id):
            pass

    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=_FakeScoring(),
        digest_service=_FakeDigest(),
        prefill_service=None,
        capacity_service=_FullCapacity(),
        orchestrator=orch,
    )
    now = datetime(2026, 6, 16, tzinfo=UTC)
    result = loop.run_once(cid, now=now)
    assert result.pipelines_started == []
    # No budget consumed for the deferred (never-started) application.
    assert loop.acted_today(cid, now) == 0


# ============================================================ #12 egress + SSRF
@pytest.mark.unit
def test_egress_mode_validator_rejects_typo():
    """#12 (SECURITY): an invalid EGRESS_MODE is rejected at config load."""
    from pydantic import ValidationError

    from applicant.app.config import Settings

    Settings(EGRESS_MODE="residential-proxy")  # valid
    Settings(EGRESS_MODE="DIRECT")  # normalized
    with pytest.raises(ValidationError):  # pydantic wraps the ValueError
        Settings(EGRESS_MODE="residential_proxy")  # underscore typo -> rejected


@pytest.mark.unit
def test_ssrf_guard_blocks_metadata_allows_localhost():
    """#12 (SECURITY): operator-URL guard blocks 169.254.169.254 + non-http(s), but
    ALLOWS localhost / private endpoints (local Ollama, internal SearXNG)."""
    from applicant.application.services.setup_service import (
        validate_operator_url,
        validate_operator_urls,
    )
    from applicant.core.errors import InvalidInput

    # Allowed: local Ollama + private endpoints.
    assert validate_operator_url("http://localhost:11434/v1")
    assert validate_operator_url("http://10.0.0.5:8080")
    assert validate_operator_url("") == ""  # empty passes through unchanged

    # Blocked: cloud metadata address + non-http schemes.
    with pytest.raises(InvalidInput):
        validate_operator_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(InvalidInput):
        validate_operator_url("file:///etc/passwd")
    with pytest.raises(InvalidInput):
        validate_operator_url("gopher://evil/")
    # Comma-separated list: the metadata entry is rejected.
    with pytest.raises(InvalidInput):
        validate_operator_urls("mailto://x@y.com, http://169.254.169.254/")


@pytest.mark.unit
def test_ssrf_guard_blocks_ipv6_mapped_metadata_address():
    """#12 (SECURITY): the metadata block must also cover the IPv6-mapped IPv4 forms
    of 169.254.169.254 — ``::ffff:169.254.169.254`` and its packed ``::ffff:a9fe:a9fe``
    spelling parse as IPv6Address that does NOT ``==`` the plain IPv4, so without
    normalization the metadata guard is trivially bypassed (instance-credential SSRF)."""
    from applicant.application.services.setup_service import (
        validate_operator_url,
        validate_operator_urls,
    )
    from applicant.core.errors import InvalidInput

    for host in ("[::ffff:169.254.169.254]", "[::ffff:a9fe:a9fe]"):
        with pytest.raises(InvalidInput):
            validate_operator_url(f"http://{host}/latest/meta-data/", field="base URL")
        with pytest.raises(InvalidInput):
            validate_operator_urls(f"http://{host}/")

    # A legitimate private/loopback IPv6 (e.g. local Ollama bound to ::1) still passes.
    assert validate_operator_url("http://[::1]:11434/v1")


@pytest.mark.unit
def test_setup_service_rejects_metadata_llm_base_url():
    """#12: configure_llm rejects an LLM base_url that targets cloud metadata."""
    from applicant.application.services.setup_service import SetupService
    from applicant.core.errors import InvalidInput
    from applicant.ports.driving.setup_wizard import LLMSettings

    svc = SetupService()
    with pytest.raises(InvalidInput):
        svc.configure_llm(
            LLMSettings(
                provider="ollama",
                base_url="http://169.254.169.254/v1",
                api_key="",
                model="llama3.1",
            )
        )
    # A legitimate local Ollama base_url is accepted.
    svc.configure_llm(
        LLMSettings(
            provider="ollama",
            base_url="http://localhost:11434/v1",
            api_key="",
            model="llama3.1",
        )
    )
    assert svc.is_setup_gate_open()


# ============================================================ #13 admin clamp
@pytest.mark.unit
def test_admin_history_limit_is_clamped():
    """#13 (INFO): the admin history endpoint clamps a huge limit to 1000."""
    from fastapi.testclient import TestClient

    from applicant.app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        cid = client.post("/api/campaigns", json={"name": "C"}).json()["id"]
        captured: dict = {}
        real = app.state.container.admin_query_service.application_history

        def _spy(campaign_id, *, limit):
            captured["limit"] = limit
            return real(campaign_id, limit=limit)

        app.state.container.admin_query_service.application_history = _spy
        r = client.get(f"/api/admin/history/{cid}?limit=999999")
        assert r.status_code == 200
        assert captured["limit"] == 1000


# ============================================================ MINOR FR-FB-1
@pytest.mark.unit
def test_blank_decline_feedback_raises_invalid_input():
    """MINOR (FR-FB-1): blank decline feedback raises the domain InvalidInput (so the
    global handler maps it to 422), not a plain ValueError."""
    from applicant.application.services.digest_service import DigestService
    from applicant.core.errors import InvalidInput

    storage = InMemoryStorage()

    class _Scoring:
        threshold = 70

    digest = DigestService(storage, _SpyNotifier(), _Scoring())
    with pytest.raises(InvalidInput):
        digest.decline(ApplicationId(new_id()), feedback_text="   ")
