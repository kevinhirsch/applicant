"""Regression coverage for wiring ``PrefillService.emergency_handoff`` into a real
fill-failure path + exposing it through the ``remote`` router (dark-engine audit
item 35, FR-PREFILL-7).

Before this change ``emergency_handoff`` was dead code: it assembled the
would-have-been-filled values, landed ``EMERGENCY_DATA_HANDOFF``, and emitted a
pending action, but nothing ever called it. ``flag_probable_wrong_ats`` (the
near-empty-fill / "wrong ATS" branch, #177) already reached the SAME external
outcome by duplicating that logic inline with a hard-coded ``[]`` attribute list
(see the old code's own comment: "the same handoff payload the emergency path
offers"). This suite proves two things:

1. ``flag_probable_wrong_ats`` now genuinely DELEGATES to ``emergency_handoff`` —
   proven by feeding it real (non-empty) campaign attributes through
   ``_continue_pages`` and observing the handoff values actually resolve from
   them (impossible under the old hard-coded ``[]``), while every existing
   ``wrong_ats`` contract (kind, title, match-rate payload) is unchanged.
2. The engine's new ``GET /api/remote/applications/{id}/emergency-handoff``
   route surfaces whatever pending handoff a run produced, or an honest
   ``available: False`` when there is none.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.prefill_service import PrefillResult, PrefillService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.ids import ApplicationId, AttributeId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField, PageState


class _MismatchBrowser:
    """An in-memory browser whose single generic form DETECTS fields but maps
    almost none — a probable wrong-ATS / near-empty fill (#177). One field label
    ("First Name") DOES match a stored attribute name so a test can prove real
    attributes reach the handoff assembly once threaded through the loop.
    """

    URL = "https://careers.unsupported-ats.example/apply/9"

    def __init__(self, fields):
        self._fields = list(fields)

    def current_state(self, aid):  # noqa: ARG002
        return PageState(url=self.URL, fields=tuple(self._fields))

    def detect_fields(self, aid):  # noqa: ARG002
        return list(self._fields)

    def fill_field(self, *a, **k):  # pragma: no cover - unmapped optional fields skip
        raise AssertionError("no field should be filled in this near-empty-fill scenario")

    def is_account_create_page(self, aid):  # noqa: ARG002
        return False

    def is_final_submit_page(self, aid):  # noqa: ARG002
        return True

    def advance(self, aid):  # noqa: ARG002
        return None

    def screenshot(self, aid):  # noqa: ARG002
        return "screenshot://mismatch/1"


def _mismatch_fields():
    return [
        DetectedField("#fname", "First Name", "text", required=False),
        DetectedField("#mystery", "Mystery Field", "text", required=False),
    ]


def _service(storage, browser):
    return PrefillService(
        storage=storage,
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        llm=None,
    )


def _app(cid):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.PREFILLING,
    )


@pytest.mark.unit
class TestFlagProbableWrongAtsDelegatesToEmergencyHandoff:
    def test_real_attributes_reach_the_handoff_assembly(self):
        """The wrong-ATS branch is a genuine invocation of ``emergency_handoff``,
        not a parallel duplicate: real campaign attributes passed into the walk
        now resolve into the copy/paste handoff values. Under the pre-fix code
        (hard-coded ``[]``) this field could never resolve, no matter what
        attributes the caller supplied."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        browser = _MismatchBrowser(_mismatch_fields())
        service = _service(storage, browser)
        app = _app(cid)
        attrs = [Attribute(id=AttributeId(new_id()), campaign_id=cid, name="First Name", value="Kevin")]
        result = PrefillResult(application_id=app.id, state=app.status)

        outcome = service._continue_pages(app, attrs, result, cautious=False)

        assert outcome.state is ApplicationState.EMERGENCY_DATA_HANDOFF
        assert outcome.wrong_ats_flagged is True
        assert outcome.handoff_values["First Name"] == "Kevin"
        # The unmapped field never resolves (no matching attribute) — proves the
        # assembly is real field resolution, not an echo of the input.
        assert "Mystery Field" not in outcome.handoff_values

    def test_wrong_ats_pending_action_contract_is_unchanged(self):
        """kind/title/diagnostic payload keys stay exactly what #177 shipped —
        the delegation to ``emergency_handoff`` must not change the wrong-ATS
        pending action's own identity or its match-rate diagnostics."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        browser = _MismatchBrowser(_mismatch_fields())
        service = _service(storage, browser)
        app = _app(cid)
        result = PrefillResult(application_id=app.id, state=app.status)

        service._continue_pages(app, [], result, cautious=False)

        pending = storage.pending_actions.list_open(cid)
        flagged = [p for p in pending if p.kind == "wrong_ats"]
        assert flagged, "the wrong_ats pending action must still be emitted"
        action = flagged[0]
        assert action.title == "Pre-fill matched too few fields — review needed"
        assert action.payload["reason"] == "probable_wrong_ats"
        assert action.payload["fields_detected"] == 2
        assert action.payload["fields_filled"] == 0
        assert action.payload["match_rate"] == 0.0
        assert "handoff_values" in action.payload

    def test_emergency_handoff_pending_action_kind_is_untouched(self):
        """A direct ``emergency_handoff`` call (the hard-fill-failure path) still
        lands its OWN ``emergency_handoff``-kind pending action, distinct from
        ``wrong_ats`` — the shared assembly must not blur the two identities."""
        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        browser = _MismatchBrowser(_mismatch_fields())
        service = _service(storage, browser)
        app = _app(cid)
        attrs = [Attribute(id=AttributeId(new_id()), campaign_id=cid, name="First Name", value="Priya")]

        result = service.emergency_handoff(app, attrs)

        assert result.state is ApplicationState.EMERGENCY_DATA_HANDOFF
        assert result.handoff_values["First Name"] == "Priya"
        pending = storage.pending_actions.list_open(cid)
        kinds = {p.kind for p in pending}
        assert "emergency_handoff" in kinds
        assert "wrong_ats" not in kinds


# ---------------------------------------------------------------------------
# Route: GET /api/remote/applications/{id}/emergency-handoff
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client():
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


@pytest.mark.unit
class TestEmergencyHandoffRoute:
    def test_unknown_application_404(self, app_client):
        res = app_client.get("/api/remote/applications/does-not-exist/emergency-handoff")
        assert res.status_code == 404
        # Assert the route's OWN "Unknown application" detail, not merely a 404 —
        # a missing route also 404s (FastAPI's own "Not Found"), which would let
        # this test pass even if the route were never registered.
        assert res.json()["detail"] == "Unknown application"

    def test_no_open_handoff_reports_unavailable(self, app_client):
        from applicant.core.ids import CampaignId as _CID

        container = app_client.app.state.container
        storage = container.storage
        cid = _CID(new_id())
        aid = ApplicationId(new_id())
        storage.applications.add(
            Application(
                id=aid,
                campaign_id=cid,
                posting_id=JobPostingId(new_id()),
                status=ApplicationState.APPROVED,
            )
        )
        storage.commit()

        res = app_client.get(f"/api/remote/applications/{aid}/emergency-handoff")
        assert res.status_code == 200
        body = res.json()
        assert body["available"] is False
        assert body["handoff_values"] == {}

    def test_open_handoff_surfaces_values_and_kind(self, app_client):
        from applicant.core.ids import CampaignId as _CID

        container = app_client.app.state.container
        storage = container.storage
        cid = _CID(new_id())
        aid = ApplicationId(new_id())
        storage.applications.add(
            Application(
                id=aid,
                campaign_id=cid,
                posting_id=JobPostingId(new_id()),
                status=ApplicationState.PREFILLING,
            )
        )
        storage.commit()
        attrs = [
            Attribute(id=AttributeId(new_id()), campaign_id=cid, name="First Name", value="Kevin")
        ]
        # Swap in a controlled fake browser (mirrors test_cov_remote.py's
        # container-attribute overrides) so the assembled handoff values are
        # deterministic rather than whatever the real fake ATS flow's default
        # (never-navigated) page state happens to expose.
        container.prefill_service._browser = _MismatchBrowser(_mismatch_fields())
        container.prefill_service.emergency_handoff(storage.applications.get(aid), attrs)

        res = app_client.get(f"/api/remote/applications/{aid}/emergency-handoff")
        assert res.status_code == 200
        body = res.json()
        assert body["available"] is True
        assert body["kind"] == "emergency_handoff"
        assert body["handoff_values"]["First Name"] == "Kevin"
        assert body["state"] == ApplicationState.EMERGENCY_DATA_HANDOFF.value
