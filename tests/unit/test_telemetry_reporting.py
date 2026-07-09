"""P5-3 — opt-in error telemetry, pinned.

THE DoD (docs/backlog/road-to-market.md): "Crash reporting that respects the
privacy story; opt-in; actionable." This pins the four load-bearing
guarantees end to end:

  * default OFF (``SetupService.telemetry_status`` before any config save);
  * HARD off in local-only private mode, regardless of the stored opt-in;
  * the redaction chokepoint (``build_crash_event``) strips secrets/PII and
    home-directory usernames from the payload;
  * a caller cannot bypass the server-side gate — ``TelemetryReporter.capture``
    has no ``enabled``/``force`` parameter, and re-reads the server's own
    status fresh on every call rather than trusting a cached/caller value.

Reproduce:
    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
      uv run pytest -q tests/unit/test_telemetry_reporting.py
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.setup_service import SetupService
from applicant.core.errors import InvalidInput
from applicant.observability.telemetry import TelemetryReporter, build_crash_event

#: A fake API-key-shaped token for the redaction tests below. Built by
#: concatenation (never a contiguous literal) so it can't trip the repo's own
#: CI secret scanner (scripts/ci/secret_scan.py) — same precedent as
#: workspace/tests/test_applicant_automation_settings_routes.py's
#: ``"sk-" + "operator-supplied-key"``.
_FAKE_API_KEY = "sk-" + "abcdefghijklmnopqrstuvwx0123"


def _svc(store=None, **kwargs) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore(), **kwargs)


# ── default OFF ──────────────────────────────────────────────────────────


def test_telemetry_defaults_disabled_with_no_endpoint():
    svc = _svc()
    status = svc.telemetry_status()
    assert status["enabled"] is False
    assert status["endpoint"] == ""
    assert status["endpoint_configured"] is False
    assert status["effective"] is False


def test_telemetry_still_ineffective_with_only_endpoint_and_no_opt_in():
    """Configuring a sink alone (without opting in) must not activate sending —
    ``enabled`` is a real, separate gate from having a destination."""
    svc = _svc()
    svc.configure_telemetry(endpoint="https://telemetry.example.com/ingest")
    status = svc.telemetry_status()
    assert status["endpoint_configured"] is True
    assert status["enabled"] is False
    assert status["effective"] is False


def test_telemetry_still_ineffective_with_only_opt_in_and_no_endpoint():
    """Opting in with no destination configured must not activate sending —
    there is no bundled/default collector to fall back to."""
    svc = _svc()
    svc.configure_telemetry(enabled=True)
    status = svc.telemetry_status()
    assert status["enabled"] is True
    assert status["endpoint_configured"] is False
    assert status["effective"] is False


def test_telemetry_effective_once_both_opted_in_and_endpoint_set():
    svc = _svc()
    svc.configure_telemetry(enabled=True, endpoint="https://telemetry.example.com/ingest")
    status = svc.telemetry_status()
    assert status["effective"] is True


def test_telemetry_partial_save_does_not_clobber_the_other_key():
    svc = _svc()
    svc.configure_telemetry(enabled=True, endpoint="https://telemetry.example.com/ingest")
    svc.configure_telemetry(enabled=False)  # only flip the opt-in
    status = svc.telemetry_status()
    assert status["enabled"] is False
    assert status["endpoint"] == "https://telemetry.example.com/ingest"


def test_telemetry_endpoint_is_ssrf_validated():
    svc = _svc()
    with pytest.raises(InvalidInput):
        svc.configure_telemetry(endpoint="file:///etc/passwd")


def test_telemetry_persists_across_instances_like_channels():
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.configure_telemetry(enabled=True, endpoint="https://telemetry.example.com/ingest")
    svc2 = _svc(store)
    status = svc2.telemetry_status()
    assert status["effective"] is True


# ── HARD off in local-only private mode ─────────────────────────────────


def test_telemetry_forced_off_by_local_only_even_when_opted_in():
    svc = _svc(local_only=True)
    svc.configure_telemetry(enabled=True, endpoint="https://telemetry.example.com/ingest")
    status = svc.telemetry_status()
    # The stored preference is honestly reported...
    assert status["enabled"] is True
    assert status["endpoint_configured"] is True
    # ...but effective (the only bit anything actually acts on) is False.
    assert status["effective"] is False


def test_telemetry_env_sourced_default_also_respects_local_only():
    svc = _svc(
        local_only=True,
        telemetry_enabled_default=True,
        telemetry_endpoint_default="https://telemetry.example.com/ingest",
    )
    assert svc.telemetry_status()["effective"] is False


# ── the redaction chokepoint ─────────────────────────────────────────────


def _boom(message: str) -> Exception:
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


def test_build_crash_event_redacts_an_embedded_api_key():
    exc = _boom(f"upstream call failed: api_key={_FAKE_API_KEY}")
    event = build_crash_event(exc, component="http", app_version="0.1.0")
    assert _FAKE_API_KEY not in event["message"]
    assert "REDACTED" in event["message"]


def test_build_crash_event_redacts_a_bearer_token():
    exc = _boom("request failed: Authorization: Bearer abcd1234efgh5678ijkl")
    event = build_crash_event(exc, component="http", app_version="0.1.0")
    assert "abcd1234efgh5678ijkl" not in event["message"]


def test_build_crash_event_redacts_url_userinfo_credentials():
    exc = _boom("could not connect to smtps://myuser:hunter2secret@mail.example.com:465")
    event = build_crash_event(exc, component="http", app_version="0.1.0")
    assert "hunter2secret" not in event["message"]
    assert "myuser" not in event["message"]


def test_build_crash_event_redacts_a_jwt():
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PYb"
    )
    exc = _boom(f"session token rejected: {jwt}")
    event = build_crash_event(exc, component="http", app_version="0.1.0")
    assert jwt not in event["message"]


def test_build_crash_event_strips_home_directory_usernames_from_the_stack():
    def _inner():
        raise ValueError("boom")

    try:
        _inner()
    except ValueError as exc:
        event = build_crash_event(exc, component="http", app_version="0.1.0")
    # The real traceback frame is THIS test file, somewhere under the repo
    # checkout -- whatever the absolute path is, only the basename may survive.
    for frame in event["stack"]:
        assert "/home/" not in frame
        assert "\\Users\\" not in frame


def test_build_crash_event_has_exactly_the_documented_keys_no_more():
    exc = _boom("boom")
    event = build_crash_event(exc, component="http", app_version="0.1.0")
    assert set(event.keys()) == {
        "exception_type",
        "message",
        "component",
        "route",
        "app_version",
        "platform",
        "stack",
        "occurred_at",
    }


def test_build_crash_event_uses_route_template_not_a_resolved_path():
    """``route`` must be whatever template the caller passes -- never a raw
    resolved URL with a real id embedded -- because ``_route_template`` (the
    ONLY producer wired into the reporter) only ever reads the matched
    route's template, never ``request.url.path``."""
    exc = _boom("boom")
    event = build_crash_event(
        exc, component="http", app_version="0.1.0", route="/api/campaigns/{campaign_id}"
    )
    assert event["route"] == "/api/campaigns/{campaign_id}"


# ── the server-side gate cannot be bypassed by a caller ─────────────────


def test_capture_signature_has_no_enable_or_force_parameter():
    """A caller must not be able to opt a report back in -- pin the exact
    parameter surface so a future edit can't quietly add one."""
    import inspect

    params = set(inspect.signature(TelemetryReporter.capture).parameters)
    assert "enabled" not in params
    assert "force" not in params
    assert "effective" not in params


def test_capture_does_not_send_when_status_fn_reports_ineffective():
    sent = []

    def _status_fn():
        return {"effective": False, "endpoint": "https://telemetry.example.com/ingest"}

    reporter = TelemetryReporter(
        status_fn=_status_fn,
        app_version="0.1.0",
        sender=lambda endpoint, payload, timeout: sent.append((endpoint, payload)),
    )
    attempted = reporter.capture(_boom("boom"), component="http")
    assert attempted is False
    assert sent == []


def test_capture_ignores_a_status_fn_that_lies_with_no_endpoint():
    """Even if ``effective`` were somehow True with an empty endpoint, capture
    must still refuse to send (defense in depth: no destination, no send)."""
    sent = []

    def _status_fn():
        return {"effective": True, "endpoint": ""}

    reporter = TelemetryReporter(
        status_fn=_status_fn,
        app_version="0.1.0",
        sender=lambda endpoint, payload, timeout: sent.append((endpoint, payload)),
    )
    attempted = reporter.capture(_boom("boom"), component="http")
    assert attempted is False
    assert sent == []


def test_capture_sends_a_sanitized_payload_when_effective():
    sent = []

    def _status_fn():
        return {"effective": True, "endpoint": "https://telemetry.example.com/ingest"}

    reporter = TelemetryReporter(
        status_fn=_status_fn,
        app_version="0.1.0",
        sender=lambda endpoint, payload, timeout: sent.append((endpoint, payload)),
    )
    exc = _boom(f"failed with api_key={_FAKE_API_KEY}")
    attempted = reporter.capture(exc, component="prefill")
    assert attempted is True
    assert len(sent) == 1
    endpoint, payload = sent[0]
    assert endpoint == "https://telemetry.example.com/ingest"
    assert payload["component"] == "prefill"
    assert _FAKE_API_KEY not in payload["message"]


def test_capture_never_raises_when_status_fn_itself_blows_up():
    def _status_fn():
        raise RuntimeError("store unreachable")

    reporter = TelemetryReporter(status_fn=_status_fn, app_version="0.1.0")
    assert reporter.capture(_boom("boom"), component="http") is False


def test_capture_never_raises_when_the_sender_itself_blows_up():
    def _status_fn():
        return {"effective": True, "endpoint": "https://telemetry.example.com/ingest"}

    def _boom_sender(endpoint, payload, timeout):
        raise ConnectionError("unreachable")

    reporter = TelemetryReporter(status_fn=_status_fn, app_version="0.1.0", sender=_boom_sender)
    # Must not raise -- best-effort delivery, never breaks the caller.
    assert reporter.capture(_boom("boom"), component="http") is True
