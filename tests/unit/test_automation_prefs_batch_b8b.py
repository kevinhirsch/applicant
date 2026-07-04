"""Settings > Automation config-store persistence + router wiring for dark-engine
audit items 92/93/94/95/96/100/101/103/104, wired into the SAME ``AutomationPrefsIn``
pattern items 82/84/85/86/87/88/90/91/97/98/99/102/105/106/107 already established
(see ``test_automation_prefs_batch_b8.py``):

  * 92 -- ``sandbox_backend`` (mirrors ``SANDBOX_BACKEND``, default "local";
    "local"/"proxmox-windows") and ``stealth_persona`` (mirrors
    ``STEALTH_PERSONA``, default ""; ""/"linux"/"native").
  * 93 -- ``browser_engine`` (mirrors ``BROWSER_ENGINE``, default "camoufox";
    "camoufox"/"chromium") and ``browser_channel`` (mirrors ``BROWSER_CHANNEL``,
    default "chrome"; "chrome"/"chromium").
  * 94 -- ``chat_tools``/``loop_tools`` (mirror ``CHAT_TOOLS``/``LOOP_TOOLS``,
    default "off" each; "off"/"auto").
  * 95 -- ``material_research_enabled`` (mirrors ``MATERIAL_RESEARCH_ENABLED``,
    default False).
  * 96 -- ``computer_use_backend`` (mirrors ``COMPUTER_USE_BACKEND``, default
    "noop"; "noop"/"cua"), ``computer_use_mode`` (mirrors
    ``COMPUTER_USE_MODE``, default "som"; "som"/"ax"), and
    ``computer_use_approvals`` (mirrors ``COMPUTER_USE_APPROVALS``, default
    "manual"; "manual"/"session").
  * 100 -- ``curation_schedule``/``status_update_schedule`` (mirror
    ``CURATION_SCHEDULE``/``STATUS_UPDATE_SCHEDULE``, default "off" each) and
    ``essentials_nudge_schedule`` (mirrors ``ESSENTIALS_NUDGE_SCHEDULE``,
    default "daily"); all three "off"/"daily".
  * 101 -- ``discovery_proxies`` (mirrors ``DISCOVERY_PROXIES``, default "";
    comma-separated proxy list, SSRF-checked like Apprise/ntfy URLs).
  * 103 -- ``takeover_desktop`` (mirrors ``TAKEOVER_DESKTOP``, default
    "cinnamon"; cinnamon/xfce/gnome/pantheon) and ``remote_view_backend``
    (mirrors ``REMOTE_VIEW_BACKEND``, default "webtop"; webtop/neko).
  * 104 -- ``resume_render`` (mirrors ``RESUME_RENDER``, default "auto";
    auto/on/off).

Two layers of coverage, matching ``test_automation_prefs_batch_b8.py``'s shape:

  1. ``SetupService.get_automation_prefs``/``set_automation_prefs`` directly
     (config-store persistence + validation), and
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

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.main import create_app
from applicant.application.services.setup_service import SetupService


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


# ── SetupService: persistence + validation ─────────────────────────────────


def test_get_automation_prefs_is_empty_before_anything_is_saved():
    svc = _svc()
    prefs = svc.get_automation_prefs()
    for key in (
        "sandbox_backend",
        "stealth_persona",
        "browser_engine",
        "browser_channel",
        "chat_tools",
        "loop_tools",
        "material_research_enabled",
        "computer_use_backend",
        "computer_use_mode",
        "computer_use_approvals",
        "curation_schedule",
        "status_update_schedule",
        "essentials_nudge_schedule",
        "discovery_proxies",
        "takeover_desktop",
        "remote_view_backend",
        "resume_render",
    ):
        assert key not in prefs


def test_set_then_get_round_trips_all_new_knobs():
    svc = _svc()
    svc.set_automation_prefs(
        sandbox_backend="proxmox-windows",
        stealth_persona="native",
        browser_engine="chromium",
        browser_channel="chromium",
        chat_tools="auto",
        loop_tools="auto",
        material_research_enabled=True,
        computer_use_backend="cua",
        computer_use_mode="ax",
        computer_use_approvals="session",
        curation_schedule="daily",
        status_update_schedule="daily",
        essentials_nudge_schedule="off",
        discovery_proxies="http://proxy1.example.com:8080,http://proxy2.example.com:8080",
        takeover_desktop="xfce",
        remote_view_backend="neko",
        resume_render="on",
    )
    prefs = svc.get_automation_prefs()
    assert prefs["sandbox_backend"] == "proxmox-windows"
    assert prefs["stealth_persona"] == "native"
    assert prefs["browser_engine"] == "chromium"
    assert prefs["browser_channel"] == "chromium"
    assert prefs["chat_tools"] == "auto"
    assert prefs["loop_tools"] == "auto"
    assert prefs["material_research_enabled"] is True
    assert prefs["computer_use_backend"] == "cua"
    assert prefs["computer_use_mode"] == "ax"
    assert prefs["computer_use_approvals"] == "session"
    assert prefs["curation_schedule"] == "daily"
    assert prefs["status_update_schedule"] == "daily"
    assert prefs["essentials_nudge_schedule"] == "off"
    assert prefs["discovery_proxies"] == (
        "http://proxy1.example.com:8080,http://proxy2.example.com:8080"
    )
    assert prefs["takeover_desktop"] == "xfce"
    assert prefs["remote_view_backend"] == "neko"
    assert prefs["resume_render"] == "on"


def test_empty_stealth_persona_and_discovery_proxies_are_allowed():
    """Empty string is a legitimate value for both: stealth_persona "" means
    "auto-derive from the sandbox backend" and discovery_proxies "" means
    "direct egress, no proxy" -- neither should be rejected as invalid."""
    svc = _svc()
    svc.set_automation_prefs(stealth_persona="", discovery_proxies="")
    prefs = svc.get_automation_prefs()
    assert prefs["stealth_persona"] == ""
    assert prefs["discovery_proxies"] == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sandbox_backend": "not-a-backend"},
        {"stealth_persona": "windows"},
        {"browser_engine": "safari"},
        {"browser_channel": "firefox"},
        {"chat_tools": "always"},
        {"loop_tools": "always"},
        {"computer_use_backend": "real"},
        {"computer_use_mode": "vision"},
        {"computer_use_approvals": "never"},
        {"curation_schedule": "weekly"},
        {"status_update_schedule": "hourly"},
        {"essentials_nudge_schedule": "monthly"},
        {"takeover_desktop": "kde"},
        {"remote_view_backend": "vnc"},
        {"resume_render": "force"},
    ],
)
def test_invalid_enum_values_are_rejected(kwargs):
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(**kwargs)
    # Rejected write must not partially land.
    assert svc.get_automation_prefs() == {}


def test_discovery_proxies_rejects_a_disallowed_scheme():
    """SSRF guard (item 12): a file:// entry is rejected the same way Apprise/ntfy
    URLs are -- ``InvalidInput`` (a ``DomainError``, mapped to 422 at the router),
    not a plain ``ValueError``."""
    from applicant.core.errors import InvalidInput

    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.set_automation_prefs(discovery_proxies="file:///etc/passwd")
    assert svc.get_automation_prefs() == {}


def test_discovery_proxies_rejects_the_cloud_metadata_address():
    from applicant.core.errors import InvalidInput

    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.set_automation_prefs(discovery_proxies="http://169.254.169.254/latest/meta-data/")
    assert svc.get_automation_prefs() == {}


def test_partial_save_of_new_knobs_leaves_existing_knobs_untouched():
    svc = _svc()
    svc.set_automation_prefs(egress_timezone="America/New_York", sandbox_backend="local")
    svc.set_automation_prefs(resume_render="off")
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"  # untouched
    assert prefs["sandbox_backend"] == "local"  # untouched by the second call
    assert prefs["resume_render"] == "off"  # newly set
    assert "browser_engine" not in prefs  # never touched


def test_state_persists_across_instances_over_the_same_store():
    """Simulated restart (FR-OOBE-1 pattern): a fresh SetupService over the
    same AppConfigStore must see the prior save."""
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_automation_prefs(
        chat_tools="auto",
        material_research_enabled=True,
        takeover_desktop="gnome",
    )
    svc2 = _svc(store)
    prefs = svc2.get_automation_prefs()
    assert prefs["chat_tools"] == "auto"
    assert prefs["material_research_enabled"] is True
    assert prefs["takeover_desktop"] == "gnome"


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
    """Before any operator save, GET must reflect the real env-sourced
    ``Settings`` defaults (config.py), not a fabricated/omitted value."""
    prefs = client.get("/api/setup/automation").json()
    assert prefs["sandbox_backend"] == "local"
    assert prefs["stealth_persona"] == ""
    assert prefs["browser_engine"] == "camoufox"
    assert prefs["browser_channel"] == "chrome"
    assert prefs["chat_tools"] == "off"
    assert prefs["loop_tools"] == "off"
    assert prefs["material_research_enabled"] is False
    assert prefs["computer_use_backend"] == "noop"
    assert prefs["computer_use_mode"] == "som"
    assert prefs["computer_use_approvals"] == "manual"
    assert prefs["curation_schedule"] == "off"
    assert prefs["status_update_schedule"] == "off"
    assert prefs["essentials_nudge_schedule"] == "daily"
    assert prefs["discovery_proxies"] == ""
    assert prefs["takeover_desktop"] == "cinnamon"
    assert prefs["remote_view_backend"] == "webtop"
    assert prefs["resume_render"] == "auto"


def test_put_persists_and_round_trips_on_next_get(client):
    put = client.put(
        "/api/setup/automation",
        json={
            "sandbox_backend": "proxmox-windows",
            "stealth_persona": "native",
            "browser_engine": "chromium",
            "browser_channel": "chromium",
            "chat_tools": "auto",
            "loop_tools": "auto",
            "material_research_enabled": True,
            "computer_use_backend": "cua",
            "computer_use_mode": "ax",
            "computer_use_approvals": "session",
            "curation_schedule": "daily",
            "status_update_schedule": "daily",
            "essentials_nudge_schedule": "off",
            "discovery_proxies": "http://proxy.example.com:8080",
            "takeover_desktop": "pantheon",
            "remote_view_backend": "neko",
            "resume_render": "off",
        },
    )
    assert put.status_code == 204

    prefs = client.get("/api/setup/automation").json()
    assert prefs["sandbox_backend"] == "proxmox-windows"
    assert prefs["stealth_persona"] == "native"
    assert prefs["browser_engine"] == "chromium"
    assert prefs["browser_channel"] == "chromium"
    assert prefs["chat_tools"] == "auto"
    assert prefs["loop_tools"] == "auto"
    assert prefs["material_research_enabled"] is True
    assert prefs["computer_use_backend"] == "cua"
    assert prefs["computer_use_mode"] == "ax"
    assert prefs["computer_use_approvals"] == "session"
    assert prefs["curation_schedule"] == "daily"
    assert prefs["status_update_schedule"] == "daily"
    assert prefs["essentials_nudge_schedule"] == "off"
    assert prefs["discovery_proxies"] == "http://proxy.example.com:8080"
    assert prefs["takeover_desktop"] == "pantheon"
    assert prefs["remote_view_backend"] == "neko"
    assert prefs["resume_render"] == "off"


@pytest.mark.parametrize(
    "body,message_fragment",
    [
        ({"sandbox_backend": "not-a-backend"}, "Sandbox backend"),
        ({"stealth_persona": "windows"}, "Stealth persona"),
        ({"browser_engine": "safari"}, "Browser engine"),
        ({"browser_channel": "firefox"}, "Browser channel"),
        ({"chat_tools": "always"}, "Assistant tool autonomy"),
        ({"loop_tools": "always"}, "Loop tool autonomy"),
        ({"computer_use_backend": "real"}, "Desktop-assist backend"),
        ({"computer_use_mode": "vision"}, "Desktop-assist capture mode"),
        ({"computer_use_approvals": "never"}, "Desktop-assist approval posture"),
        ({"curation_schedule": "weekly"}, "Curation cadence"),
        ({"status_update_schedule": "hourly"}, "Status-update cadence"),
        ({"essentials_nudge_schedule": "monthly"}, "Essentials-nudge cadence"),
        ({"takeover_desktop": "kde"}, "Takeover desktop"),
        ({"remote_view_backend": "vnc"}, "Remote-view backend"),
        ({"resume_render": "force"}, "Resume render mode"),
    ],
)
def test_put_rejects_invalid_values_with_400(client, body, message_fragment):
    resp = client.put("/api/setup/automation", json=body)
    assert resp.status_code == 400
    assert message_fragment in resp.json()["detail"]


def test_put_rejects_malformed_discovery_proxy_with_422(client):
    """``discovery_proxies`` is SSRF-checked via ``validate_operator_urls`` (item
    12), which raises the domain ``InvalidInput`` -- mapped to 422 by the global
    handler, distinct from the plain-``ValueError``-derived 400s above (matches
    how the existing Apprise/ntfy URL fields behave)."""
    resp = client.put(
        "/api/setup/automation", json={"discovery_proxies": "file:///etc/passwd"}
    )
    assert resp.status_code == 422
    assert "disallowed scheme" in resp.json()["detail"]
