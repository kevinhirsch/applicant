"""Regression tests for exhaustive-audit lens 04, findings #6 and #15
(``workspace/src/applicant_features.py``).

#6  — A transient engine hiccup (the healthz ping failing, or the
    setup-status/dormant-surfaces fetch erroring) must not be reported the
    same as "genuinely never configured": previously-confirmed sections
    should degrade to the soft ``STATE_CONFIGURED`` ("unreachable right
    now"), not the hard ``STATE_LOCKED`` used for un-set-up sections.

#15 — ``compute_features()`` (as called, uncustomized, by
    ``GET /api/applicant/features`` on every render) must not fan out fresh
    blocking engine calls on every single call; a short-TTL cache should let
    a burst of near-simultaneous renders share one fetch, and expire so a
    config change is picked up within a few seconds.

Both fixes live entirely in ``src/applicant_features.py``; the cache is keyed
off the default (uncustomized) call path only, so passing an explicit
``transport`` -- as every *other* hermetic test in this suite does -- bypasses
it and stays fully deterministic. These tests therefore monkeypatch the
lower-level engine functions themselves (``engine_available_sync``/
``get_sync``) so they can exercise the real cached/default call path
(``transport=None``) without hitting the network.
"""

import pytest
import src.applicant_features as af
from src.applicant_engine import EngineError


@pytest.fixture(autouse=True)
def _clean_caches():
    """Isolate each test from the module-level caches (and from each other)."""
    af._result_cache.clear()
    af._last_known.clear()
    yield
    af._result_cache.clear()
    af._last_known.clear()


FULLY_CONFIGURED = {
    "llm_configured": True,
    "channels_configured": True,
    "onboarding_complete": True,
    "gate_open": True,
}

ALL_LIVE = [
    {"key": "redline_surface", "status": "live"},
    {"key": "attribute_editor", "status": "live"},
    {"key": "criteria_editor", "status": "live"},
    {"key": "chatbot", "status": "live"},
    {"key": "digest_in_app", "status": "live"},
]


def _patch_engine(monkeypatch, *, healthz_ok, status=None, dormant=None, raise_status=False, raise_dormant=False):
    """Monkeypatch the two engine functions ``compute_features`` calls, so the
    default (cached) call path can be exercised without a real transport.
    """
    calls = {"healthz": 0, "status": 0, "dormant": 0}

    def fake_available_sync(*, base_url=None, transport=None):
        calls["healthz"] += 1
        return healthz_ok

    def fake_get_sync(path, *, base_url=None, params=None, transport=None):
        if path == "/api/setup/status":
            calls["status"] += 1
            if raise_status:
                raise EngineError("boom: setup status")
            return status if status is not None else {}
        if path == "/api/dormant-surfaces":
            calls["dormant"] += 1
            if raise_dormant:
                raise EngineError("boom: dormant surfaces")
            return dormant if dormant is not None else []
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(af, "engine_available_sync", fake_available_sync)
    monkeypatch.setattr(af, "get_sync", fake_get_sync)
    return calls


# -- #6: soft-degrade on a transient blip, instead of false-locking --------


def test_setup_status_blip_falls_back_to_last_known_not_locked(monkeypatch):
    """Warm the last-known cache with a fully-configured, healthy fetch, then
    force the TTL to have expired and simulate the setup-status call erroring
    (engine still answers healthz, but that one fetch blips). Previously-
    confirmed sections must fall back to the last-known-good data rather than
    reporting a hard STATE_LOCKED as if nothing had ever been configured. The
    engine itself is still up (healthz succeeded), so with the preserved
    config data the section reads as fully STATE_ACTIVE -- exactly the
    "preserve the last-known configured state" strategy the finding calls
    out as acceptable.
    """
    monkeypatch.setattr(af, "_FEATURES_CACHE_TTL_SECONDS", 0.0)

    _patch_engine(monkeypatch, healthz_ok=True, status=FULLY_CONFIGURED, dormant=ALL_LIVE)
    warm = af.compute_features()
    assert warm["engine_available"] is True
    assert warm["sections"]["documents"]["state"] == af.STATE_ACTIVE

    # Now the engine answers healthz, but the setup-status fetch itself blips.
    _patch_engine(monkeypatch, healthz_ok=True, raise_status=True, dormant=ALL_LIVE)
    out = af.compute_features()

    assert out["engine_available"] is True
    # Never a hard lock: the last-known-good config data is preserved through
    # the blip instead of being treated as "not configured".
    assert out["sections"]["documents"]["state"] != af.STATE_LOCKED
    assert out["sections"]["documents"]["state"] == af.STATE_ACTIVE


def test_engine_down_after_warm_falls_back_to_configured_not_locked(monkeypatch):
    """Same as above but the whole engine goes unreachable (healthz fails)
    after a previous successful, fully-configured fetch. Known-configured
    sections should read as a soft "configured" (unreachable right now), and
    ``engine_available`` should still truthfully report the outage.
    """
    monkeypatch.setattr(af, "_FEATURES_CACHE_TTL_SECONDS", 0.0)

    _patch_engine(monkeypatch, healthz_ok=True, status=FULLY_CONFIGURED, dormant=ALL_LIVE)
    warm = af.compute_features()
    assert warm["sections"]["chat"]["state"] == af.STATE_ACTIVE

    _patch_engine(monkeypatch, healthz_ok=False)
    out = af.compute_features()

    assert out["engine_available"] is False
    assert out["sections"]["chat"]["state"] == af.STATE_CONFIGURED
    assert out["sections"]["chat"]["state"] != af.STATE_LOCKED


def test_genuinely_unconfigured_section_stays_locked_through_a_blip(monkeypatch):
    """The fallback must not paper over sections that were never configured:
    with no prior successful fetch (or previously LOCKED), a blip should
    still leave them LOCKED, not fabricate a configured state.
    """
    monkeypatch.setattr(af, "_FEATURES_CACHE_TTL_SECONDS", 0.0)

    # Warm run: engine up, but nothing configured -- gated sections lock.
    _patch_engine(monkeypatch, healthz_ok=True, status={}, dormant=ALL_LIVE)
    warm = af.compute_features()
    assert warm["sections"]["documents"]["state"] == af.STATE_LOCKED

    # Engine now blips entirely.
    _patch_engine(monkeypatch, healthz_ok=False)
    out = af.compute_features()
    assert out["sections"]["documents"]["state"] == af.STATE_LOCKED


def test_first_ever_call_with_engine_down_stays_locked(monkeypatch):
    """No prior successful fetch at all -- the genuinely-unknown case must
    still degrade to LOCKED (nothing to fall back to), matching the existing
    engine-down behaviour in test_applicant_features.py.
    """
    monkeypatch.setattr(af, "_FEATURES_CACHE_TTL_SECONDS", 0.0)
    _patch_engine(monkeypatch, healthz_ok=False)

    out = af.compute_features()
    assert out["engine_available"] is False
    assert out["sections"]["documents"]["state"] == af.STATE_LOCKED


# -- #15: short-TTL cache so repeated renders don't each fan out 3 calls ---


def test_repeated_quick_renders_share_one_set_of_engine_calls(monkeypatch):
    calls = _patch_engine(monkeypatch, healthz_ok=True, status=FULLY_CONFIGURED, dormant=ALL_LIVE)

    first = af.compute_features()
    second = af.compute_features()

    assert first == second
    # Two "renders" back to back within the TTL -> the underlying engine
    # calls happened only once, not twice.
    assert calls == {"healthz": 1, "status": 1, "dormant": 1}


def test_cache_refreshes_after_ttl_expires(monkeypatch):
    monkeypatch.setattr(af, "_FEATURES_CACHE_TTL_SECONDS", 0.02)
    calls = _patch_engine(monkeypatch, healthz_ok=True, status=FULLY_CONFIGURED, dormant=ALL_LIVE)

    af.compute_features()
    assert calls["healthz"] == 1

    import time

    time.sleep(0.05)

    af.compute_features()
    # After the short TTL has elapsed, a fresh render fetches again.
    assert calls["healthz"] == 2


def test_cache_reflects_config_change_after_ttl(monkeypatch):
    """The cache must never serve data staler than the TTL: once it expires,
    a genuine configuration change must show up.
    """
    monkeypatch.setattr(af, "_FEATURES_CACHE_TTL_SECONDS", 0.02)

    _patch_engine(monkeypatch, healthz_ok=True, status={}, dormant=ALL_LIVE)
    before = af.compute_features()
    assert before["sections"]["documents"]["state"] == af.STATE_LOCKED

    import time

    time.sleep(0.05)

    _patch_engine(monkeypatch, healthz_ok=True, status=FULLY_CONFIGURED, dormant=ALL_LIVE)
    after = af.compute_features()
    assert after["sections"]["documents"]["state"] == af.STATE_ACTIVE


def test_explicit_transport_bypasses_the_cache(monkeypatch):
    """Hermetic callers that pass an explicit transport (every other test in
    this suite) must never be affected by the cache -- each call recomputes.
    """
    import httpx

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/setup/status":
            return httpx.Response(200, json=FULLY_CONFIGURED)
        if path == "/api/dormant-surfaces":
            return httpx.Response(200, json=ALL_LIVE)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    af.compute_features(base_url="http://api:8000", transport=transport)
    af.compute_features(base_url="http://api:8000", transport=transport)

    # 2 renders * 3 calls each (healthz + status + dormant) = 6; no caching.
    assert calls["n"] == 6
