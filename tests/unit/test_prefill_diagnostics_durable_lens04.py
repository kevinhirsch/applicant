"""Lens 04 #39 / DISC-3: the pre-fill diagnostics ring must survive a tick rebuild.

The 24/7 scheduler rebuilds a fresh ``PrefillService`` every tick (per-tick Session
isolation, ``container._build_tick_services``). Before this fix, the operator-visible
silent-degradation diagnostics ring (``PrefillService._record_diagnostic`` /
``diagnostics()``) was a plain ``list`` on ``self`` — process-lived state living on an
instance that gets thrown away every tick, exactly the #180 footgun the docs warn
about. In practice this meant the admin ``/api/admin/prefill-diagnostics`` route (which
reads the ONE never-rebuilt ``container.prefill_service`` singleton) could never show
anything a real tick's pre-fill run had recorded: the tick-built ``PrefillService`` that
actually drives pre-fill recorded its diagnostics on ITS OWN list, which vanished the
moment that tick's services were discarded.

The fix threads ONE process-lived ``PrefillDiagnosticsRing`` (built once in
container.py, mirroring ``routine_store``/``resume_ledger``/``digest_ledger``) into
every ``PrefillService`` construction — the shared singleton, every per-tick rebuild,
and every per-request rebuild — so a diagnostic recorded through any one of them is
immediately visible through all the others.

Builds a real SQLite-backed container (so the DB-only tick/request factories exist,
mirroring ``tests/unit/test_cov_container.py``), drives the SAME kind of assertions
against the pre-fill diagnostics ring specifically.
"""

from __future__ import annotations

import tempfile

import pytest

from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine
from applicant.app.config import Settings
from applicant.app.container import build_container
from applicant.application.services.prefill_service import (
    PrefillDiagnosticsRing,
    PrefillService,
)


@pytest.fixture
def sqlite_container():
    """A container wired against a real SQLite DB (so the tick/request factories exist)."""
    db = tempfile.mktemp(suffix=".db")
    url = f"sqlite:///{db}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = Settings(DATABASE_URL=url)
    return build_container(settings)


def _tick_prefill_service(container):
    """Build one tick's isolated service bundle and return its PrefillService.

    Mirrors ``test_cov_container.py::test_scheduler_tick_factory_builds_isolated_bundle``
    (``scheduler._tick_services_factory`` -> a fresh, Session-isolated bundle whose
    ``AgentLoop`` carries the tick's own ``PrefillService`` as ``_prefill``). Returns
    ``(prefill_service, session)`` so the caller can close the tick's session after use.
    """
    factory = container.scheduler._tick_services_factory
    assert factory is not None
    services = factory()
    return services["agent_loop"]._prefill, services["_session"]


# --- the core revert-verify case: diagnostics survive a per-tick rebuild -----------


def test_diagnostic_recorded_in_one_tick_is_visible_in_the_next_tick(sqlite_container):
    message = "Every credential scope failed for tenant 'workday' (vault unreachable): boom"

    # Tick 1: record a diagnostic through THAT tick's own (rebuilt) PrefillService.
    pf_tick1, session1 = _tick_prefill_service(sqlite_container)
    try:
        pf_tick1._record_diagnostic(message)
    finally:
        session1.close()

    # Before the fix, ``pf_tick1``'s diagnostics list is discarded along with the rest
    # of tick 1's per-tick services -- nothing else would ever see it. The container's
    # own never-rebuilt ``prefill_service`` singleton (what the admin route reads) must
    # see it immediately, since it shares the same process-lived ring.
    assert sqlite_container.prefill_service.diagnostics() == [message]

    # Tick 2: a FRESH PrefillService is built (a new instance, proving the rebuild
    # actually happened) but its diagnostics() must still show tick 1's entry.
    pf_tick2, session2 = _tick_prefill_service(sqlite_container)
    try:
        assert pf_tick2 is not pf_tick1
        assert pf_tick2.diagnostics() == [message]

        # Record a second diagnostic in tick 2.
        message2 = "LLM unavailable during field mapping: rate limited"
        pf_tick2._record_diagnostic(message2)
    finally:
        session2.close()

    # Both diagnostics persist into tick 3, and are visible via the singleton too.
    pf_tick3, session3 = _tick_prefill_service(sqlite_container)
    try:
        assert pf_tick3.diagnostics() == [message, message2]
    finally:
        session3.close()
    assert sqlite_container.prefill_service.diagnostics() == [message, message2]


def test_request_scoped_prefill_service_shares_the_same_ring(sqlite_container):
    """The per-request rebuild (CONC-REQ-1) must also read/write the shared ring."""
    services = sqlite_container.request_services_factory()
    try:
        rs_prefill = services["prefill_service"]
        rs_prefill._record_diagnostic("Browser error during login: transient")
    finally:
        services["_session"].close()

    assert sqlite_container.prefill_service.diagnostics() == [
        "Browser error during login: transient"
    ]

    pf_tick, tick_session = _tick_prefill_service(sqlite_container)
    try:
        assert pf_tick.diagnostics() == ["Browser error during login: transient"]
    finally:
        tick_session.close()


def test_dedup_contract_is_preserved_across_the_shared_ring(sqlite_container):
    """An immediate repeat is still dropped, now enforced by the shared ring itself."""
    pf_tick1, session1 = _tick_prefill_service(sqlite_container)
    try:
        pf_tick1._record_diagnostic("Browser error during login: transient")
        pf_tick1._record_diagnostic("Browser error during login: transient")
    finally:
        session1.close()

    assert sqlite_container.prefill_service.diagnostics() == [
        "Browser error during login: transient"
    ]


# --- unit-level checks on PrefillDiagnosticsRing / PrefillService wiring itself ----


def test_prefill_service_without_injected_ring_still_defaults_to_a_fresh_instance():
    """Legacy/unit construction (no container) keeps working exactly as before."""
    pf = PrefillService(
        storage=None, browser=None, detection=None, sandbox=None, credentials=None
    )
    pf._record_diagnostic("standalone diagnostic")
    assert pf.diagnostics() == ["standalone diagnostic"]


def test_two_prefill_services_without_an_injected_ring_do_not_share_state():
    """Two standalone constructions (no shared ring passed) stay isolated."""
    pf_a = PrefillService(
        storage=None, browser=None, detection=None, sandbox=None, credentials=None
    )
    pf_b = PrefillService(
        storage=None, browser=None, detection=None, sandbox=None, credentials=None
    )
    pf_a._record_diagnostic("only on a")
    assert pf_a.diagnostics() == ["only on a"]
    assert pf_b.diagnostics() == []


def test_injecting_the_same_ring_into_two_services_shares_diagnostics():
    """Two independently-constructed services sharing one ring see each other's writes
    -- the exact mechanism container.py now relies on."""
    ring = PrefillDiagnosticsRing()
    pf_a = PrefillService(
        storage=None,
        browser=None,
        detection=None,
        sandbox=None,
        credentials=None,
        diagnostics_ring=ring,
    )
    pf_b = PrefillService(
        storage=None,
        browser=None,
        detection=None,
        sandbox=None,
        credentials=None,
        diagnostics_ring=ring,
    )
    pf_a._record_diagnostic("recorded via a")
    assert pf_b.diagnostics() == ["recorded via a"]
    pf_b._record_diagnostic("recorded via b")
    assert pf_a.diagnostics() == ["recorded via a", "recorded via b"]


def test_ring_caps_and_dedupes_directly():
    ring = PrefillDiagnosticsRing(max_size=3)
    ring.record("a")
    ring.record("a")  # immediate dup dropped
    ring.record("b")
    ring.record("c")
    ring.record("d")  # over cap -> oldest dropped
    assert ring.list() == ["b", "c", "d"]
