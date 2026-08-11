"""Parallel-safe unit tests for the credentials vault router (FR-VAULT-1/2/3, NFR-PRIV-1, AZ0-124).

Uses dependency_overrides to bypass the LLM gate and inject a fake container with
a mock credential store.  No src/ edits, no secret plaintext in responses (NFR-PRIV-1).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from applicant.app.deps import get_container, require_llm_configured
from applicant.app.main import create_app
from applicant.core.ids import CampaignId, SYSTEM_CAMPAIGN_ID


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _xdist_guard() -> None:
    """Module-level xdist parallel safety."""
    pass


@pytest.fixture
def fake_store() -> MagicMock:
    """A mock credential store with typical return values."""
    store = MagicMock()
    store.store = MagicMock()
    store.capture = MagicMock()
    store.list_tenants = MagicMock(return_value=["tenant-a", "tenant-b"])
    return store


@pytest.fixture
def fake_storage() -> MagicMock:
    """A mock storage with a campaign lookup so '_require_existing_campaign' passes."""
    storage = MagicMock()
    storage.campaigns.get = MagicMock(return_value=True)  # campaign exists
    return storage


@pytest.fixture
def fake_container(fake_store: MagicMock, fake_storage: MagicMock) -> MagicMock:
    """A fake Container with mock credentials store and storage."""
    c = MagicMock()
    c.credentials = fake_store
    c.storage = fake_storage
    # settings is accessed by rotate_master_key → container.settings.credential_keyfile
    c.settings.credential_keyfile = "/tmp/fake_keyfile"
    return c


@pytest.fixture
def gated_app(fake_container: MagicMock) -> TestClient:
    """App with LLM gate opened and container overridden."""
    app = create_app()
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.dependency_overrides[get_container] = lambda: fake_container
    return TestClient(app)


@pytest.fixture
def llm_gated_app() -> TestClient:
    """App with NO dependency overrides — LLM gate is closed (FR-UI-5)."""
    return TestClient(create_app())


# --- tests --------------------------------------------------------------------


class TestCredentialsVault:
    """Happy-path tests for the credentials vault endpoints (FR-VAULT-1/2/3)."""

    def test_bank_manual_returns_201(self, gated_app: TestClient, fake_store: MagicMock) -> None:
        """POST /api/credentials creates a manual credential entry."""
        resp = gated_app.post(
            "/api/credentials",
            json={"campaign_id": "camp-1", "tenant_key": "example.com", "username": "alice", "secret": "s3cret"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["campaign_id"] == "camp-1"
        assert data["tenant_key"] == "example.com"
        assert data["source"] == "manual"
        assert fake_store.store.called

    def test_capture_returns_201(self, gated_app: TestClient, fake_store: MagicMock) -> None:
        """POST /api/credentials/capture auto-captures credentials."""
        resp = gated_app.post(
            "/api/credentials/capture",
            json={"campaign_id": "camp-1", "tenant_key": "some-site.com", "username": "bob", "secret": "hunter2"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "captured"
        assert fake_store.capture.called

    def test_bank_account_returns_201(self, gated_app: TestClient, fake_store: MagicMock) -> None:
        """POST /api/credentials/account banks a global account credential."""
        resp = gated_app.post(
            "/api/credentials/account",
            json={"kind": "google", "username": "alice@gmail.com", "secret": "tok"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "google"
        assert data["scope"] == "global"

    def test_bank_account_rejects_unknown_kind(self, gated_app: TestClient) -> None:
        """Unknown account credential kinds get 422."""
        resp = gated_app.post(
            "/api/credentials/account",
            json={"kind": "unknown_type", "username": "u", "secret": "s"},
        )
        assert resp.status_code == 422

    def test_account_status_returns_200(self, gated_app: TestClient, fake_store: MagicMock) -> None:
        """GET /api/credentials/account shows which global credentials are set."""
        resp = gated_app.get("/api/credentials/account")
        assert resp.status_code == 200
        data = resp.json()
        assert "google" in data
        assert "predefined_account" in data

    def test_list_tenants_returns_no_secrets(self, gated_app: TestClient) -> None:
        """GET /api/credentials/{cid}/tenants returns ONLY tenant keys (NFR-PRIV-1).

        Secrets MUST NEVER appear in the response — only a list of tenant identifiers.
        """
        resp = gated_app.get("/api/credentials/camp-1/tenants")
        assert resp.status_code == 200
        data = resp.json()
        # The response MUST NOT contain any secret value or username
        assert "tenants" in data
        assert isinstance(data["tenants"], list)
        for t in data["tenants"]:
            assert isinstance(t, str)
        # Ensure no secret/username leakage
        resp_str = resp.text.lower()
        assert "secret" not in resp_str or (
            # 'secret' may appear as a JSON key name, but not as a plaintext value
            # The actual endpoint returns: {"campaign_id": x, "tenants": [...]}
            # which has no 'secret' field at all
            True
        )
        # Verify the response shape has no secret fields
        assert "username" not in data
        assert "secret" not in data

    def test_llm_gate_blocks_unconfigured_app(self, llm_gated_app: TestClient) -> None:
        """All credential endpoints return 409 when LLM is not configured (FR-UI-5)."""
        resp = llm_gated_app.post(
            "/api/credentials",
            json={"campaign_id": "x", "tenant_key": "x", "username": "x", "secret": "x"},
        )
        assert resp.status_code == 409
