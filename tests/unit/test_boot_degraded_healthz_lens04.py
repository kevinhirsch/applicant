"""Lens 04 (exhaustive2) audit — finding #48: an aggregate "boot degraded" signal.

Every guarded boot step in ``app/lifespan.py`` (capability report, durable-
workflow recovery, DB healthcheck, dormant-surface seed, audit-log start,
system-campaign seed) is individually wrapped in
``except Exception: log.warning(...)`` and continues — so one slow/failing
step never blocks the others. But before this fix there was no aggregate
signal reaching ``/healthz``: a deploy where several warm-up/init steps
silently failed still reported ``{"status": "ok"}`` with no way for an
operator (or an automated deploy check) to see it.

``app/lifespan.py`` now keeps a process-lived ``BootHealth`` record (module-
level singleton, same pattern as ``_shutdown_requested``) that every guarded
step records its own outcome into, reset once per boot so a stale failure from
a previous process/test boot never leaks forward. ``/healthz`` in
``app/main.py`` reads it via ``get_boot_health()`` and surfaces
``checks["boot"]`` (per-step statuses) and ``checks["boot_degraded"]`` (the
flattened list of failed step names) — purely informational, same
"surfaced, not gated on" contract as ``checks["capabilities_degraded"]``
(lens04 #38): a boot-step failure never flips the top-level ``status``/``ok``
away from green.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import applicant.app.lifespan as lifespan_mod
from applicant.app.lifespan import get_boot_health
from applicant.app.main import create_app


def test_boot_health_all_ok_on_a_clean_boot():
    """A boot with no injected failures reports every recorded step as ok and
    an empty failed list — the baseline the failure tests below diverge from.
    """
    app = create_app()
    with TestClient(app) as c:
        res = c.get("/healthz")

    body = res.json()
    assert res.status_code == 200
    assert body["status"] == "ok"
    assert "boot" in body["checks"]
    assert body["checks"]["boot_degraded"] == []
    assert body["checks"]["boot"], "expected at least one recorded boot step"
    assert all(status.startswith("ok") for status in body["checks"]["boot"].values())


def test_boot_step_failure_is_recorded_and_surfaced_without_hard_failing_healthz(monkeypatch):
    """The crux of #48: inject a failure into one guarded boot step
    (dormant-surface seeding) and assert it shows up in ``checks.boot`` /
    ``checks.boot_degraded`` — while healthz itself still reports 200/"ok",
    since a boot-step warm-up failure is informational, not a hard-fail gate.
    """

    def _boom(_session):
        raise RuntimeError("dormant surface seed exploded")

    monkeypatch.setattr(lifespan_mod, "seed_dormant_surfaces", _boom)

    app = create_app()
    with TestClient(app) as c:
        res = c.get("/healthz")

    body = res.json()
    # Never a hard failure for a boot warm-up/init step.
    assert res.status_code == 200
    assert body["status"] == "ok"

    boot = body["checks"]["boot"]
    assert "dormant_surfaces" in boot
    assert boot["dormant_surfaces"].startswith("failed")
    assert "dormant surface seed exploded" in boot["dormant_surfaces"]

    assert body["checks"]["boot_degraded"] == ["dormant_surfaces"]


def test_boot_health_resets_between_boots(monkeypatch):
    """A failure recorded in one boot must not leak into the next boot's
    (or, in tests, the next ``create_app()``'s) /healthz response — otherwise
    a since-fixed transient failure would read as permanently degraded.
    """

    def _boom(_session):
        raise RuntimeError("transient failure")

    monkeypatch.setattr(lifespan_mod, "seed_dormant_surfaces", _boom)
    app = create_app()
    with TestClient(app) as c:
        c.get("/healthz")
    assert get_boot_health()["degraded"] is True

    monkeypatch.undo()  # restore the real seed_dormant_surfaces for the next boot

    app2 = create_app()
    with TestClient(app2) as c:
        res = c.get("/healthz")

    body = res.json()
    assert body["checks"]["boot_degraded"] == []
    assert "dormant_surfaces" in body["checks"]["boot"]
    assert body["checks"]["boot"]["dormant_surfaces"] == "ok"
