"""Settings > Automation config-store persistence + router wiring for the LAST
two dark-engine audit §B8 knobs, held back until a proper in-product consent
surface existed (08_engine_dark_matrix.md item 83/89), wired into the SAME
``AutomationPrefsIn`` pattern the other 25 B8 knobs already use:

  * 83 -- ``captcha_strategy`` (mirrors ``CAPTCHA_STRATEGY``, default "human";
    "human"/"avoid"/"service") and ``captcha_service`` (mirrors
    ``CAPTCHA_SERVICE``, default "capsolver"; "capsolver"/"2captcha"/
    "anticaptcha"). ``captcha_api_key`` is the SECRET solver API key
    (mirrors ``CAPTCHA_API_KEY``): sealed in the credential vault exactly
    like the sandbox-connection secrets (``configure_sandbox_connection``'s
    Proxmox token secret / RDP password), NEVER stored in the plain
    config-store record, and NEVER echoed back by ``get_automation_prefs`` --
    only a computed ``captcha_api_key_configured`` boolean is.
  * 89 -- ``egress_mode`` (mirrors ``EGRESS_MODE``, default "direct";
    "direct"/"residential-proxy"), ``egress_residential`` (mirrors
    ``EGRESS_RESIDENTIAL``, default False), and ``egress_proxy_url`` (mirrors
    ``EGRESS_PROXY_URL``, default ""). The proxy URL is SSRF-validated via the
    same ``validate_operator_url`` helper the discovery-proxy list (item 101)
    and Apprise/ntfy URLs use, and -- like ``discovery_proxies``, which has
    the identical embedded-credential shape (``http://user:pass@host``) --
    it is PLAIN-STORED, not vaulted, matching that field's own precedent.

Two layers of coverage, matching the shape of the other B8 batches:

  1. ``SetupService.get_automation_prefs``/``set_automation_prefs`` directly
     (config-store persistence, vaulting, and validation), and
  2. ``GET``/``PUT /api/setup/automation`` through a real app so the
     env-default merge in the router (``get_automation_prefs`` in
     ``setup.py``) is proven, not just the service.

Each assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted (file-copy backup, not ``git stash`` -- shared
across sibling worktrees in this session), then GREEN again after restoring.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.credentials.pg_credential_store import InMemoryCredentialStore
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.main import create_app
from applicant.application.services.setup_service import (
    _CAPTCHA_API_KEY_REF,
    SetupService,
)
from applicant.core.errors import InvalidInput


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


def _svc_with_vault(tmp_path, store=None):
    creds = InMemoryCredentialStore(str(tmp_path / "master.key"))
    return SetupService(config_store=store or InMemoryAppConfigStore(), credentials=creds), creds


# ── SetupService: persistence + validation ─────────────────────────────────


def test_get_automation_prefs_is_empty_before_anything_is_saved():
    svc = _svc()
    prefs = svc.get_automation_prefs()
    for key in (
        "captcha_strategy",
        "captcha_service",
        "captcha_api_key",
        "captcha_api_key_ref",
        "captcha_api_key_configured",
        "egress_mode",
        "egress_residential",
        "egress_proxy_url",
    ):
        assert key not in prefs


def test_set_then_get_round_trips_non_secret_knobs():
    svc = _svc()
    svc.set_automation_prefs(
        captcha_strategy="avoid",
        captcha_service="2captcha",
        egress_mode="residential-proxy",
        egress_residential=True,
        egress_proxy_url="http://proxy.example.com:8080",
    )
    prefs = svc.get_automation_prefs()
    assert prefs["captcha_strategy"] == "avoid"
    assert prefs["captcha_service"] == "2captcha"
    assert prefs["egress_mode"] == "residential-proxy"
    assert prefs["egress_residential"] is True
    assert prefs["egress_proxy_url"] == "http://proxy.example.com:8080"


def test_egress_proxy_url_may_embed_credentials():
    """Same embedded-credential shape discovery_proxies allows (item 101)."""
    svc = _svc()
    svc.set_automation_prefs(
        egress_proxy_url="http://myuser:mypass@residential-proxy.example.com:8080"
    )
    prefs = svc.get_automation_prefs()
    assert prefs["egress_proxy_url"] == (
        "http://myuser:mypass@residential-proxy.example.com:8080"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"captcha_strategy": "solve-for-me"},
        {"captcha_service": "recaptcha-inc"},
        {"egress_mode": "datacenter"},
        {"egress_mode": "residential_proxy"},  # underscore typo, not the real value
    ],
)
def test_invalid_enum_values_are_rejected(kwargs):
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(**kwargs)
    # Rejected write must not partially land.
    assert svc.get_automation_prefs() == {}


def test_egress_proxy_url_rejects_a_disallowed_scheme():
    """SSRF guard (item 12): matches how discovery_proxies (item 101) and
    Apprise/ntfy URLs behave -- ``InvalidInput`` (a ``DomainError``, mapped to
    422 at the router), not a plain ``ValueError``."""
    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.set_automation_prefs(egress_proxy_url="file:///etc/passwd")
    assert svc.get_automation_prefs() == {}


def test_egress_proxy_url_rejects_the_cloud_metadata_address():
    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.set_automation_prefs(
            egress_proxy_url="http://169.254.169.254/latest/meta-data/"
        )
    assert svc.get_automation_prefs() == {}


def test_empty_egress_proxy_url_is_allowed():
    """Empty string is legitimate: "no proxy configured" / direct egress."""
    svc = _svc()
    svc.set_automation_prefs(egress_mode="direct", egress_proxy_url="")
    prefs = svc.get_automation_prefs()
    assert prefs["egress_proxy_url"] == ""


def test_partial_save_leaves_existing_knobs_untouched():
    svc = _svc()
    svc.set_automation_prefs(egress_timezone="America/New_York", egress_mode="direct")
    svc.set_automation_prefs(captcha_strategy="avoid")
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"  # untouched
    assert prefs["egress_mode"] == "direct"  # untouched by the second call
    assert prefs["captcha_strategy"] == "avoid"  # newly set
    assert "egress_proxy_url" not in prefs  # never touched


def test_state_persists_across_instances_over_the_same_store():
    """Simulated restart (FR-OOBE-1 pattern): a fresh SetupService over the
    same AppConfigStore must see the prior save (non-secret fields)."""
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_automation_prefs(
        captcha_strategy="avoid", egress_mode="residential-proxy", egress_residential=True
    )
    svc2 = _svc(store)
    prefs = svc2.get_automation_prefs()
    assert prefs["captcha_strategy"] == "avoid"
    assert prefs["egress_mode"] == "residential-proxy"
    assert prefs["egress_residential"] is True


# ── SECURITY: the captcha API key is a SECRET, vaulted like the sandbox
#    connection's Proxmox token / RDP password, never plain-stored or echoed ─


def test_captcha_api_key_is_sealed_in_the_vault_not_the_config_store(tmp_path):
    svc, creds = _svc_with_vault(tmp_path)
    svc.set_automation_prefs(captcha_strategy="service", captcha_api_key="sk-super-secret-123")

    # The general accessor NEVER surfaces the raw key or its vault-ref marker.
    prefs = svc.get_automation_prefs()
    assert "captcha_api_key" not in prefs
    assert "captcha_api_key_ref" not in prefs
    assert prefs["captcha_api_key_configured"] is True
    assert prefs["captcha_strategy"] == "service"

    # It really is sealed in the vault, resolvable only internally.
    from applicant.core.ids import CampaignId

    cred = creds.retrieve(CampaignId("__system__"), _CAPTCHA_API_KEY_REF)
    assert cred is not None
    assert cred.secret == "sk-super-secret-123"
    assert svc.resolve_captcha_api_key() == "sk-super-secret-123"


def test_captcha_api_key_never_appears_in_the_plain_config_store_record(tmp_path):
    """Reach into the raw store (bypassing the filtered accessor) to prove the
    plaintext key never lands in the plain config-store JSON at all -- only a
    non-secret vault-ref marker does."""
    svc, creds = _svc_with_vault(tmp_path)
    svc.set_automation_prefs(captcha_api_key="sk-do-not-leak")
    raw = svc._store.get("automation.prefs") or {}
    assert "sk-do-not-leak" not in str(raw)
    assert raw.get("captcha_api_key_ref") == _CAPTCHA_API_KEY_REF
    assert "captcha_api_key" not in raw


def test_captcha_api_key_configured_is_false_until_one_is_saved(tmp_path):
    svc, _ = _svc_with_vault(tmp_path)
    assert svc.get_automation_prefs().get("captcha_api_key_configured", False) is False
    svc.set_automation_prefs(captcha_api_key="sk-abc")
    assert svc.get_automation_prefs()["captcha_api_key_configured"] is True


def test_blank_captcha_api_key_leaves_an_already_vaulted_key_untouched(tmp_path):
    """A save of an unrelated field (or an explicitly blank key) must not wipe
    an already-configured key -- mirrors the tier-ladder api_key_ref convention
    (blank api_key + a ref keeps the sealed key across an unrelated edit)."""
    svc, creds = _svc_with_vault(tmp_path)
    svc.set_automation_prefs(captcha_api_key="sk-original")
    # Save an unrelated field.
    svc.set_automation_prefs(captcha_strategy="avoid")
    assert svc.get_automation_prefs()["captcha_api_key_configured"] is True
    assert svc.resolve_captcha_api_key() == "sk-original"
    # An explicit blank string is ALSO a no-op (never wipes).
    svc.set_automation_prefs(captcha_api_key="")
    assert svc.resolve_captcha_api_key() == "sk-original"


def test_captcha_api_key_reseal_replaces_the_prior_key(tmp_path):
    svc, creds = _svc_with_vault(tmp_path)
    svc.set_automation_prefs(captcha_api_key="sk-first")
    svc.set_automation_prefs(captcha_api_key="sk-second")
    assert svc.resolve_captcha_api_key() == "sk-second"


def test_captcha_api_key_without_a_vault_wired_is_held_inline_but_never_logged(caplog):
    """No credential store wired (mirrors the sandbox-connection / tier-ladder
    fallback for hermetic tests): the key is held inline in the config-store
    record so ``resolve_captcha_api_key`` still works, but it is STILL never
    surfaced by the general accessor and never appears in a log line."""
    svc = _svc()
    svc.set_automation_prefs(captcha_api_key="sk-inline-test-key")
    assert svc.resolve_captcha_api_key() == "sk-inline-test-key"
    prefs = svc.get_automation_prefs()
    assert "captcha_api_key" not in prefs
    assert prefs["captcha_api_key_configured"] is True
    for record in caplog.records:
        assert "sk-inline-test-key" not in record.getMessage()


# ── Router: GET/PUT /api/setup/automation over a real app ──────────────────


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_get_defaults_to_settings_values_when_nothing_persisted(client):
    prefs = client.get("/api/setup/automation").json()
    assert prefs["captcha_strategy"] == "human"
    assert prefs["captcha_service"] == "capsolver"
    assert prefs["captcha_api_key_configured"] is False
    assert prefs["egress_mode"] == "direct"
    assert prefs["egress_residential"] is False
    assert prefs["egress_proxy_url"] == ""


def test_put_persists_and_round_trips_non_secret_fields_on_next_get(client):
    put = client.put(
        "/api/setup/automation",
        json={
            "captcha_strategy": "avoid",
            "captcha_service": "anticaptcha",
            "egress_mode": "residential-proxy",
            "egress_residential": True,
            "egress_proxy_url": "http://proxy.example.com:8080",
        },
    )
    assert put.status_code == 204

    prefs = client.get("/api/setup/automation").json()
    assert prefs["captcha_strategy"] == "avoid"
    assert prefs["captcha_service"] == "anticaptcha"
    assert prefs["egress_mode"] == "residential-proxy"
    assert prefs["egress_residential"] is True
    assert prefs["egress_proxy_url"] == "http://proxy.example.com:8080"


def test_put_captcha_api_key_is_never_returned_by_a_subsequent_get(client):
    """CRITICAL (SECURITY): the key travels one-way. Once saved, no GET response
    -- ever -- includes the raw value, only the boolean flag."""
    put = client.put(
        "/api/setup/automation",
        json={"captcha_strategy": "service", "captcha_api_key": "sk-live-secret-999"},
    )
    assert put.status_code == 204

    resp = client.get("/api/setup/automation")
    body_text = resp.text
    assert "sk-live-secret-999" not in body_text
    prefs = resp.json()
    assert "captcha_api_key" not in prefs
    assert prefs["captcha_api_key_configured"] is True


def test_put_rejects_invalid_captcha_strategy_with_400(client):
    resp = client.put("/api/setup/automation", json={"captcha_strategy": "solve-for-me"})
    assert resp.status_code == 400
    assert "Captcha strategy" in resp.json()["detail"]


def test_put_rejects_invalid_captcha_service_with_400(client):
    resp = client.put("/api/setup/automation", json={"captcha_service": "recaptcha-inc"})
    assert resp.status_code == 400
    assert "Captcha solving service" in resp.json()["detail"]


def test_put_rejects_invalid_egress_mode_with_400(client):
    resp = client.put("/api/setup/automation", json={"egress_mode": "datacenter"})
    assert resp.status_code == 400
    assert "Egress mode" in resp.json()["detail"]


def test_put_rejects_malformed_egress_proxy_url_with_422(client):
    """SSRF guard: ``InvalidInput`` (DomainError) -> 422, distinct from the
    plain-``ValueError``-derived 400s above (matches item 101's own behavior).
    ``egress_proxy_url`` uses the SINGULAR ``validate_operator_url`` (one URL,
    not a comma-separated list), whose message differs slightly from the
    plural ``validate_operator_urls`` used by ``discovery_proxies``."""
    resp = client.put(
        "/api/setup/automation", json={"egress_proxy_url": "file:///etc/passwd"}
    )
    assert resp.status_code == 422
    assert "must be an http(s) URL" in resp.json()["detail"]


def test_put_rejects_egress_proxy_url_targeting_the_cloud_metadata_address(client):
    resp = client.put(
        "/api/setup/automation",
        json={"egress_proxy_url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert resp.status_code == 422
