"""Lens 04 (exhaustive2) audit — findings #1 and #38: honest `/healthz` signals.

#1 — In-memory storage fallback previously read as satisfied. When the
configured DB is unreachable at boot, the container silently degrades to
``InMemoryStorage(is_fallback=True)`` (``src/applicant/app/container.py``,
``_build_storage``) and its ``healthcheck()`` deliberately returns ``False`` for
that instance (``adapters/storage/in_memory.py``, marked ``#312``). But
``/healthz`` only ever reported ``checks["database"] == "in-memory"`` on the
no-engine path with no further signal — a data-losing fallback looked
identical to the legitimate "no Postgres configured for this dev/test boot"
case. ``checks["database_persistence"]`` now consults the storage's own
``healthcheck()`` and reports ``"degraded: ..."`` for a real fallback, ``"ok"``
otherwise — added as a NEW field so the existing contract (top-level
``status``/``ok`` staying green on the no-engine path — see
``test_healthz_readiness.py::test_healthz_ok_on_in_memory_boot``) is preserved.

#38 — A missing optional capability (browser binary, TeX, LibreOffice, ...) was
only visible as free-text per-capability strings inside ``checks.capabilities``
and explicitly does not affect ok/degraded. ``checks["capabilities_degraded"]``
flattens that into a plain list of capability names that are not "ok" so an
operator (or an automated deploy check) can see a degraded image at a glance —
still never failing healthz hard for an optional-capability gap.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import applicant.app.main as main_mod
from applicant.app.main import create_app

# ---------------------------------------------------------------------------
# #1 — storage-fallback honesty
# ---------------------------------------------------------------------------


def test_database_persistence_degraded_when_storage_is_a_fallback():
    """A fallback in-memory storage must read as degraded, not merely "in-memory"."""
    app = create_app()

    class _FallbackStorage:
        def healthcheck(self) -> bool:
            return False  # what InMemoryStorage(is_fallback=True).healthcheck() returns

    # Container is frozen after construction; bypass with object.__setattr__ for
    # the test, same pattern as test_healthz_readiness.py.
    object.__setattr__(app.state.container, "storage", _FallbackStorage())

    with TestClient(app) as c:
        res = c.get("/healthz")

    # Backward compatible: the coarse ok/degraded gate is UNCHANGED on the
    # no-engine path (dev/hermetic boots with no reachable Postgres legitimately
    # stay green — this is not touched).
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "in-memory"

    # New honest signal: the fallback is visible and never reads as "ok".
    persistence = body["checks"]["database_persistence"]
    assert "degraded" in persistence
    assert persistence != "ok"
    assert "capabilities" in body["checks"]


def test_database_persistence_ok_when_storage_is_not_a_fallback():
    """A storage whose own healthcheck() passes reports persistence as ok."""
    app = create_app()

    class _HealthyStorage:
        def healthcheck(self) -> bool:
            return True

    object.__setattr__(app.state.container, "storage", _HealthyStorage())

    with TestClient(app) as c:
        res = c.get("/healthz")

    assert res.status_code == 200
    assert res.json()["checks"]["database_persistence"] == "ok"


def test_database_persistence_fails_safe_when_storage_has_no_healthcheck():
    """No usable healthcheck() signal => fail safe to "degraded", never "ok"."""
    app = create_app()

    object.__setattr__(app.state.container, "storage", object())

    with TestClient(app) as c:
        res = c.get("/healthz")

    assert "degraded" in res.json()["checks"]["database_persistence"]


def test_default_hermetic_boot_reports_fallback_persistence_as_degraded():
    """End-to-end (no fakes): the real ``InMemoryStorage(is_fallback=True)`` built
    when ``DATABASE_URL`` is unreachable must surface as degraded persistence.

    Requires the hermetic ``DATABASE_URL`` from CLAUDE.md's green-increment
    command so ``engine`` is actually ``None`` in this process; skips instead of
    false-failing if a real Postgres happens to be reachable.
    """
    app = create_app()
    if getattr(app.state.container, "engine", None) is not None:
        pytest.skip("a real Postgres is reachable in this environment")

    with TestClient(app) as c:
        res = c.get("/healthz")

    assert res.status_code == 200
    body = res.json()
    assert body["checks"]["database"] == "in-memory"
    assert "degraded" in body["checks"]["database_persistence"]


# ---------------------------------------------------------------------------
# #38 — capability-gap honesty
# ---------------------------------------------------------------------------


def test_capabilities_degraded_lists_non_ok_capabilities(monkeypatch):
    """checks.capabilities_degraded flattens the non-"ok" capability names."""
    app = create_app()

    monkeypatch.setattr(
        main_mod,
        "capability_status",
        lambda **_kwargs: {
            "tex": "NOT FOUND (using stub PDF)",
            "libreoffice": "ok (/usr/bin/soffice)",
            "browser": "disabled (BROWSER_REAL not set — using in-memory fake)",
            "postgres": "ok (connected)",
        },
    )

    with TestClient(app) as c:
        res = c.get("/healthz")

    body = res.json()
    assert body["checks"]["capabilities"]["tex"].startswith("NOT FOUND")
    assert sorted(body["checks"]["capabilities_degraded"]) == ["browser", "tex"]
    # Optional-capability gaps never fail healthz hard.
    assert res.status_code == 200
    assert body["status"] == "ok"


def test_capabilities_degraded_empty_when_all_capabilities_ok(monkeypatch):
    """A fully-capable deploy reports an empty degraded list."""
    app = create_app()

    monkeypatch.setattr(
        main_mod,
        "capability_status",
        lambda **_kwargs: {
            "tex": "ok (/usr/bin/lualatex)",
            "libreoffice": "ok (/usr/bin/soffice)",
            "browser": "ok (camoufox: /usr/bin/camoufox)",
            "postgres": "ok (connected)",
        },
    )

    with TestClient(app) as c:
        res = c.get("/healthz")

    assert res.json()["checks"]["capabilities_degraded"] == []


def test_missing_browser_binary_does_not_fail_healthz(monkeypatch):
    """Missing capabilities (lens04 #38's scenario) are surfaced, not gated on."""
    app = create_app()

    monkeypatch.setattr(
        main_mod,
        "capability_status",
        lambda **_kwargs: {
            "tex": "ok (/usr/bin/lualatex)",
            "libreoffice": "ok (/usr/bin/soffice)",
            "browser": "NOT FOUND (BROWSER_REAL=true but no camoufox/chrome binary on PATH)",
            "postgres": "ok (connected)",
        },
    )

    with TestClient(app) as c:
        res = c.get("/healthz")

    body = res.json()
    assert res.status_code == 200
    assert body["status"] == "ok"
    assert "browser" in body["checks"]["capabilities_degraded"]
