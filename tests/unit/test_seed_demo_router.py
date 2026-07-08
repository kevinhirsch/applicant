"""Hermetic coverage for the demo-seed HTTP router gate + status endpoint (P0-2).

The seed router is the operator/front-door entry point for the ``DEMO_MODE``
dataset. Two invariants matter and are asserted here without a DB:

* the ROUTER GATE (``_seed_enabled`` / ``require_seed_enabled``) is unreachable —
  404, "route doesn't exist" — unless ``DEMO_MODE=1`` (or the back-compat alias
  ``APPLICANT_ALLOW_SEED=1``) is set RIGHT NOW in the process env; and
* the status endpoint reports ``demo_active`` off the demo campaign row, so the
  front-door banner knows whether seeded data is loaded.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.routers import dev_seed as router
from applicant.application.services import dev_seed as seed

# ── the DEMO_MODE gate ──────────────────────────────────────────────────────


def test_seed_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    assert router._seed_enabled() is False


def test_demo_mode_enables_the_gate(monkeypatch):
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
    assert router._seed_enabled() is True


def test_allow_seed_alias_still_enables_the_gate(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("APPLICANT_ALLOW_SEED", "1")
    assert router._seed_enabled() is True


def test_non_one_values_do_not_enable(monkeypatch):
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    for value in ("0", "true", "yes", ""):
        monkeypatch.setenv("DEMO_MODE", value)
        assert router._seed_enabled() is False


def test_require_seed_enabled_404s_when_unset(monkeypatch):
    """The dependency must 404 (route effectively absent) when demo mode is off —
    so a production deploy carries no visible trace of a seed affordance."""
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("APPLICANT_ALLOW_SEED", raising=False)
    with pytest.raises(HTTPException) as exc:
        router.require_seed_enabled()
    assert exc.value.status_code == 404


def test_require_seed_enabled_passes_when_demo_mode_set(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    assert router.require_seed_enabled() is None  # no raise


# ── the status endpoint (banner state) ──────────────────────────────────────


def test_status_reports_inactive_on_empty_storage():
    out = router.status(storage=InMemoryStorage())
    assert out["demo_active"] is False
    assert out["counts"] == {}
    assert out["campaign_id"] == seed.DEMO_CAMPAIGN_ID


def test_status_reports_active_after_seeding():
    storage = InMemoryStorage()
    seed.persist(storage, seed.build_demo_bundle())

    out = router.status(storage=storage)
    assert out["demo_active"] is True
    assert out["counts"]["applications"] >= 5
    assert out["counts"]["postings"] >= 5
    assert out["counts"]["pending_actions"] >= 2
