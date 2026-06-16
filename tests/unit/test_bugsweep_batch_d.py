"""Bug-sweep batch D: verified browser/sandbox/stealth/security fixes.

Each test cites the requirement ID it proves and fails before its fix, passes after.
Hermetic: no real browser/network.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _open_llm_gate(client) -> None:
    assert (
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
        ).status_code
        == 204
    )


# === 1. FR-FONT: font-upload path traversal ================================
@pytest.mark.unit
class TestFontUploadPathTraversal:
    def test_traversal_name_cannot_escape_uploads_dir(self, client, tmp_path):
        # FR-FONT: a traversal `name` must NOT write outside the uploads dir.
        _open_llm_gate(client)
        evil = "../../../../tmp/pwned_by_traversal"
        files = {"file": ("font.ttf", io.BytesIO(b"\x00\x01ttf"), "font/ttf")}
        r = client.post("/api/fonts/install", data={"name": evil}, files=files)
        # Either the request is rejected, or it is contained; never a write outside.
        import pathlib

        assert not pathlib.Path("/tmp/pwned_by_traversal.ttf").exists()
        assert r.status_code in (200, 400)

    def test_traversal_filename_in_detect_is_contained(self, client):
        # FR-FONT: a traversal filename on /detect cannot escape the uploads dir.
        import pathlib

        _open_llm_gate(client)
        files = {
            "file": ("../../../../tmp/pwned_detect.txt", io.BytesIO(b"hi"), "text/plain")
        }
        r = client.post("/api/fonts/detect", files=files)
        assert not pathlib.Path("/tmp/pwned_detect.txt").exists()
        assert r.status_code in (200, 400)

    def test_safe_dest_rejects_escape(self, tmp_path):
        # Direct unit on the sanitizer: a leaf with separators stays contained.
        from applicant.app.routers.fonts import _safe_dest

        dest = _safe_dest(tmp_path, "../../etc/passwd")
        assert dest.parent == tmp_path.resolve()


# === 2. FR-SANDBOX-2: live-session token TTL / revoke / teardown ===========
@pytest.mark.unit
class TestRemoteViewTokenLifecycle:
    def test_expired_token_is_rejected(self):
        # FR-SANDBOX-2: a token past its TTL is no longer valid.
        from applicant.adapters.sandbox.remote_view import NekoRemoteView

        view = NekoRemoteView(token_ttl_seconds=0.0)  # immediate expiry
        url = view.view_url("sess-1")
        token = url.split("token=", 1)[1].split("&", 1)[0]
        assert view.token_valid("sess-1", token) is False

    def test_unexpired_token_is_accepted(self):
        from applicant.adapters.sandbox.remote_view import NekoRemoteView

        view = NekoRemoteView(token_ttl_seconds=600.0)
        url = view.view_url("sess-1")
        token = url.split("token=", 1)[1].split("&", 1)[0]
        assert view.token_valid("sess-1", token) is True

    def test_revoke_invalidates_token(self):
        # FR-SANDBOX-3/2: revoking control invalidates the live-session deep link.
        from applicant.adapters.sandbox.remote_view import NekoRemoteView

        view = NekoRemoteView(token_ttl_seconds=600.0)
        url = view.view_url("sess-1")
        token = url.split("token=", 1)[1].split("&", 1)[0]
        assert view.token_valid("sess-1", token) is True
        view.revoke_takeover("sess-1")
        assert view.token_valid("sess-1", token) is False

    def test_teardown_invalidates_token(self):
        # FR-SANDBOX-2: a torn-down session's deep link must stop working.
        from applicant.adapters.sandbox.local_sandbox import LocalSandbox
        from applicant.core.ids import ApplicationId, new_id

        sandbox = LocalSandbox()
        session = sandbox.provision(ApplicationId(new_id()))
        token = session.remote_view_url.split("token=", 1)[1].split("&", 1)[0]
        view = sandbox.remote_view()
        assert view.token_valid(session.session_id, token) is True
        sandbox.teardown(session.session_id)
        assert view.token_valid(session.session_id, token) is False


# === 3. FR-STEALTH-4: datacenter-egress refusal reachable via config =======
@pytest.mark.unit
class TestEgressAttestation:
    def test_non_attested_residential_proxy_refuses(self):
        # FR-STEALTH-4: residential-proxy mode WITHOUT attestation refuses to launch.
        from applicant.adapters.browser.stealth import (
            DatacenterEgressRefused,
            EgressPolicy,
        )

        policy = EgressPolicy.from_settings(
            mode="residential-proxy", proxy_url="http://maybe-dc:8080", residential=False
        )
        with pytest.raises(DatacenterEgressRefused):
            policy.validate()

    def test_attested_residential_proxy_passes(self):
        from applicant.adapters.browser.stealth import EgressPolicy

        policy = EgressPolicy.from_settings(
            mode="residential-proxy", proxy_url="http://home:8080", residential=True
        )
        policy.validate()  # no raise

    def test_direct_mode_is_residential_without_attestation(self):
        from applicant.adapters.browser.stealth import EgressPolicy

        policy = EgressPolicy.from_settings(mode="direct", proxy_url="", residential=False)
        policy.validate()  # the host's own connection is residential by definition


# === 4. FR-STEALTH-3: per-tenant profile dir threaded into the source ======
@pytest.mark.unit
def test_per_tenant_user_data_dir_passed_to_source():
    # FR-STEALTH-3: the resolved per-tenant user_data_dir reaches the page source.
    from applicant.adapters.browser.patchright_browser import PatchrightBrowser
    from applicant.core.ids import ApplicationId, new_id
    from applicant.ports.driven.browser_automation import PageState

    captured: dict = {}

    def factory(ats, fingerprint, *, user_data_dir=""):
        captured["user_data_dir"] = user_data_dir

        class _Src:
            def open(self, url):
                pass

            def current(self):
                return PageState(url="https://acme.wd1.myworkdayjobs.com/x")

        return _Src()

    browser = PatchrightBrowser(source_factory=factory)
    browser.open(ApplicationId(new_id()), "https://acme.wd1.myworkdayjobs.com/x")
    assert captured["user_data_dir"], "a per-tenant user_data_dir was threaded through"
    assert "acme" in captured["user_data_dir"]


# === 7. FR-LOG-4/§7: auto-detect over an EMERGENCY_DATA_HANDOFF app -> 409 ==
@pytest.mark.unit
def test_detect_on_handoff_app_returns_409_not_500(client):
    from applicant.core.entities.application import Application
    from applicant.core.ids import (
        ApplicationId,
        CampaignId,
        JobPostingId,
        new_id,
    )
    from applicant.core.state_machine import ApplicationState

    _open_llm_gate(client)
    container = client.app.state.container
    aid = new_id()
    app = Application(
        id=ApplicationId(aid),
        campaign_id=CampaignId(new_id()),
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.EMERGENCY_DATA_HANDOFF,
        root_url="https://acme.myworkdayjobs.com/x",
    )
    container.storage.applications.add(app)
    container.storage.commit()
    # Force auto-detection to fire (the browser need not be on a confirmation page).
    container.submission_service.detect_submission = lambda _aid: True
    r = client.post(f"/api/outcomes/applications/{aid}/detect")
    # An AUTO/FINISHED_BY_ENGINE transition is illegal for a handoff app (only
    # ->SUBMITTED_BY_USER is legal) — surfaced as 409, never an uncaught 500.
    assert r.status_code == 409


# === 8. FR-PREFILL-5: authorize-engine-finish actually clicks submit =======
@pytest.mark.unit
def test_authorize_engine_finish_clicks_before_recording(client):
    # The remote router is gated behind the full automated-work gate.
    from applicant.core.ids import new_id
    from tests.conftest import open_automated_work_gate

    open_automated_work_gate(client)
    container = client.app.state.container

    clicks: list = []
    orig_click = container.browser.click_final_submit

    def spy(application_id, *, engine_submit_authorized=False):
        clicks.append((str(application_id), engine_submit_authorized))
        return orig_click(application_id, engine_submit_authorized=engine_submit_authorized)

    container.browser.click_final_submit = spy
    aid = new_id()
    r = client.post(f"/api/remote/applications/{aid}/authorize-engine-finish")
    assert r.status_code == 201, r.text
    assert clicks, "click_final_submit must be invoked before recording the outcome"
    assert clicks[0][1] is True  # boundary-gated, authorized=True
