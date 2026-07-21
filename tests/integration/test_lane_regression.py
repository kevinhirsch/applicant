"""Lane regression tests for the companion internal-token channel.

Tests the three data lanes (Calendar A, Research B, Email C) plus the ping
endpoint by calling the workspace app directly over HTTP with the configured
shared secret.  All tests are integration-marked and skip when the companion
is not reachable (no token or no running workspace).

Mirrors the skip-guard pattern from test_migration_data_integrity.py
(_maybe_real_pg_url) and the integration structure from
test_research_endpoints.py.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from applicant.app.config import Settings

# ---------------------------------------------------------------------------
# Skip guard: check token + ping reachability at import time
# ---------------------------------------------------------------------------

def _companion_reachable() -> bool:
    """Return True if the companion workspace is reachable with the configured token."""
    s = Settings()
    if not s.applicant_internal_token:
        return False
    url = s.workspace_url.rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{url}/api/applicant/internal/ping",
                headers={"X-Applicant-Internal-Token": s.applicant_internal_token},
            )
            return resp.status_code == 200
    except Exception:
        return False

_SKIP_REASON = (
    "Companion workspace not reachable (APPLICANT_INTERNAL_TOKEN unset or "
    "workspace not running). Set APPLICANT_INTERNAL_TOKEN + WORKSPACE_URL "
    "and ensure the workspace app is up to run these tests."
)

skip_if_no_companion = pytest.mark.skipif(
    not _companion_reachable(),
    reason=_SKIP_REASON,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return Settings().workspace_url.rstrip("/")


def _headers(owner: str | None = None) -> dict[str, str]:
    s = Settings()
    headers: dict[str, str] = {"X-Applicant-Internal-Token": s.applicant_internal_token}
    if owner:
        headers["X-Applicant-Owner"] = owner
    return headers


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@skip_if_no_companion
def test_calendar_read_contract():
    """LANE A — GET /calendar/interviews returns a dict with an events list."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            f"{_base_url()}/api/applicant/internal/calendar/interviews",
            headers=_headers(),
        )
    assert resp.status_code == 200, f"calendar read failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict)
    assert "events" in data, f"missing 'events' key in calendar response: {list(data.keys())}"
    assert isinstance(data["events"], list)


@pytest.mark.integration
@skip_if_no_companion
def test_calendar_write_contract():
    """LANE A — POST /calendar/events with a minimal valid body returns ok+uid."""
    now = datetime.now(UTC).isoformat()
    body = {
        "title": "Lane Regression Test Event",
        "start": now,
        "all_day": False,
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{_base_url()}/api/applicant/internal/calendar/events",
            headers=_headers(),
            json=body,
        )
    assert resp.status_code in (200, 201), f"calendar write failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("ok") is True, f"missing ok=True in calendar write response: {data}"
    assert "uid" in data, f"missing 'uid' in calendar write response: {data}"


@pytest.mark.integration
@skip_if_no_companion
def test_calendar_write_with_dedup():
    """LANE A — POST same dedupe_key twice; second call should update, not duplicate."""
    now = datetime.now(UTC).isoformat()
    dedupe_key = f"lane-regression-dedup-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    body = {
        "title": "Dedup Test Event",
        "start": now,
        "all_day": False,
        "dedupe_key": dedupe_key,
    }
    with httpx.Client(timeout=10.0) as client:
        resp1 = client.post(
            f"{_base_url()}/api/applicant/internal/calendar/events",
            headers=_headers(),
            json=body,
        )
        assert resp1.status_code in (200, 201), f"first dedup write failed: {resp1.status_code}"
        data1 = resp1.json()
        uid1 = data1.get("uid")

        # Second write with same dedupe_key should succeed (update)
        body["title"] = "Dedup Test Event Updated"
        resp2 = client.post(
            f"{_base_url()}/api/applicant/internal/calendar/events",
            headers=_headers(),
            json=body,
        )
        assert resp2.status_code in (200, 201), f"second dedup write failed: {resp2.status_code}"
        data2 = resp2.json()
        assert data2.get("ok") is True
        uid2 = data2.get("uid")

        # Both should reference the same event (same uid) or the second should
        # indicate an update rather than a new creation
        assert uid1 == uid2 or data2.get("created") is False, (
            f"dedupe_key should update existing event: uid1={uid1}, uid2={uid2}, created={data2.get('created')}"
        )


@pytest.mark.integration
@skip_if_no_companion
def test_email_scan_contract():
    """LANE C — GET /emails/recent?limit=5 returns a dict with an emails list."""
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            f"{_base_url()}/api/applicant/internal/emails/recent?limit=5",
            headers=_headers(),
        )
    assert resp.status_code == 200, f"email scan failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "emails" in data, f"missing 'emails' key in email response: {list(data.keys())}"
    assert isinstance(data["emails"], list)


@pytest.mark.integration
@skip_if_no_companion
def test_research_run_contract():
    """LANE B — POST /research with a simple query returns the expected shape."""
    body = {
        "query": "Python programming language",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{_base_url()}/api/applicant/internal/research",
            headers=_headers(),
            json=body,
        )
    assert resp.status_code == 200, f"research run failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "query" in data, f"missing 'query' in research response: {list(data.keys())}"
    assert "summary" in data, f"missing 'summary' in research response: {list(data.keys())}"
    assert isinstance(data.get("key_findings"), list), (
        f"'key_findings' should be a list, got {type(data.get('key_findings'))}"
    )
    assert isinstance(data.get("sources"), list), (
        f"'sources' should be a list, got {type(data.get('sources'))}"
    )


@pytest.mark.integration
@skip_if_no_companion
def test_companion_ping():
    """Explicit ping test — the skip gate is the module-level check; this verifies the endpoint."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(
            f"{_base_url()}/api/applicant/internal/ping",
            headers=_headers(),
        )
    assert resp.status_code == 200, f"ping failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict)
    assert data.get("ok") is True, f"ping response missing ok=True: {data}"
