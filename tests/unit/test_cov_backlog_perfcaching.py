"""Performance audit exhaustive2/03_performance.md items #7 and #8.

#7: ``require_llm_configured`` (``app/deps.py``) drills through
``SetupService.is_setup_gate_open`` -> ``_load_tiers`` -> ``AppConfigStore.get`` — a
real SELECT against the shared boot Session on EVERY gated request, including every
45-60s poll from every surface. ``SetupService`` now caches the loaded tier ladder
in-process and invalidates it synchronously on the only write path (``_save_tiers``,
reached by ``configure_llm``/``set_tiers``), so a cache hit costs zero store access
and a write is reflected immediately (never stale).

#8: ``require_automated_work`` drills through
``SetupService.is_automated_work_allowed`` -> the container's ``_onboarding_gate``
closure, which scans EVERY campaign and computes full apply-readiness (criteria load
+ résumé check) per campaign, on every call. The container now wraps that closure in
``TTLCachedGate`` (a short TTL memo) before handing it to ``SetupService`` — NOT
inside ``SetupService`` itself, so unit tests that construct a bare ``SetupService``
with their own real-time gate closure (``tests/unit/test_apply_readiness_gate.py``)
keep seeing changes the instant the underlying data changes. Only the real,
expensive, container-wired closure is cached, and its staleness is bounded to the
TTL — proven below to reflect a genuine readiness change within the window, not
indefinitely.
"""

from __future__ import annotations

import tempfile

from applicant.adapters.storage.app_config_store import (
    AppConfigStore,
    InMemoryAppConfigStore,
)
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine
from applicant.app.config import Settings
from applicant.app.container import build_container
from applicant.application.services.setup_service import (
    DEFAULT_ONBOARDING_GATE_CACHE_TTL_S,
    SetupService,
    TTLCachedGate,
)
from applicant.core.ids import CampaignId
from applicant.ports.driving.onboarding import IntakeSection
from applicant.ports.driving.setup_wizard import LLMSettings


class _CountingConfigStore:
    """Wraps an ``AppConfigStore`` and counts ``get`` calls (perf item #7)."""

    def __init__(self, inner: AppConfigStore) -> None:
        self._inner = inner
        self.get_calls = 0

    def get(self, key: str):
        self.get_calls += 1
        return self._inner.get(key)

    def set(self, key: str, value) -> None:
        self._inner.set(key, value)


# --- item #7: tier-ladder cache in SetupService --------------------------------


def test_tier_ladder_cache_avoids_repeated_store_reads():
    """Repeated gate checks after a write must NOT re-hit the config store."""
    store = _CountingConfigStore(InMemoryAppConfigStore())
    svc = SetupService(config_store=store)

    svc.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434", api_key="", model="llama3")
    )
    calls_after_write = store.get_calls
    assert calls_after_write >= 1  # configure_llm reads current tiers once (phase 1)

    # Simulate the hot path: many gated requests each calling is_setup_gate_open()
    # (what require_llm_configured checks on every request).
    for _ in range(25):
        assert svc.is_setup_gate_open() is True

    # No additional store reads — every one of the 25 checks was served from the
    # in-process cache primed by the write.
    assert store.get_calls == calls_after_write


def test_tier_ladder_cache_reflects_write_immediately():
    """The cache must never paper over a real ladder change (write-through, #7).

    Proves the staleness bound is effectively zero for writes made through this
    SetupService instance: the very next read after a write reflects it, with no
    window in which a caller could observe the pre-write value.
    """
    svc = SetupService(config_store=InMemoryAppConfigStore())

    # Prime the cache with the "not configured" state (the gate must start closed).
    assert svc.is_setup_gate_open() is False

    svc.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434", api_key="", model="llama3")
    )

    # Reflected immediately — no TTL wait needed, because the write path invalidates
    # (overwrites) the cache synchronously.
    assert svc.is_setup_gate_open() is True

    # set_tiers (the ladder-reorder/edit path) is the other writer; also immediate.
    from applicant.ports.driving.setup_wizard import TierSettings

    svc.set_tiers(
        [
            TierSettings(
                provider="openai", base_url="", model="gpt-4o-mini", api_key="k", context_window=8192
            )
        ]
    )
    assert svc.is_setup_gate_open() is True
    assert svc.get_tiers()[0]["provider"] == "openai"


# --- item #8: TTLCachedGate (unit-level) ---------------------------------------


def test_ttl_cached_gate_avoids_repeated_calls_within_window():
    """Repeated calls within the TTL window must not re-invoke the wrapped gate."""
    calls = {"n": 0}

    def _expensive_gate() -> bool:
        calls["n"] += 1
        return True

    gate = TTLCachedGate(_expensive_gate, ttl_seconds=10.0)
    for _ in range(50):
        assert gate() is True
    assert calls["n"] == 1


def test_ttl_cached_gate_reflects_change_within_ttl_not_indefinitely_stale(monkeypatch):
    """A genuine gate-state flip must surface within the TTL window, not forever.

    Uses a fake monotonic clock (deterministic, no real sleeping) to prove both
    halves of the safety story: (1) a change made WITHIN the TTL window may still
    read stale — the explicitly-endorsed tradeoff — and (2) once the TTL elapses the
    very next call re-checks and reflects the new value. Never indefinitely stale.
    """
    import applicant.application.services.setup_service as setup_service_mod

    clock = {"t": 0.0}
    monkeypatch.setattr(setup_service_mod.time, "monotonic", lambda: clock["t"])

    state = {"ready": False}

    def _gate() -> bool:
        return state["ready"]

    gate = TTLCachedGate(_gate, ttl_seconds=5.0)

    assert gate() is False  # primes the cache at t=0

    # Onboarding completes "in the background" — the underlying data changes...
    state["ready"] = True

    # ...but a check still inside the TTL window is allowed to read stale (the
    # documented, bounded tradeoff for a gate that only ever BLOCKS, never
    # self-authorizes, automated work).
    clock["t"] = 4.9
    assert gate() is False

    # Once the TTL has elapsed, the gate MUST reflect reality again — never stuck.
    clock["t"] = 5.1
    assert gate() is True


def test_ttl_cached_gate_invalidate_forces_immediate_recheck():
    calls = {"n": 0}
    state = {"ready": False}

    def _gate() -> bool:
        calls["n"] += 1
        return state["ready"]

    gate = TTLCachedGate(_gate, ttl_seconds=999.0)
    assert gate() is False
    state["ready"] = True
    assert gate() is False  # still cached
    gate.invalidate()
    assert gate() is True  # forced recheck, no TTL wait
    assert calls["n"] == 2


# --- item #8: real container wiring (integration) -------------------------------


def _real_container():
    db = tempfile.mktemp(suffix=".db")
    url = f"sqlite:///{db}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return build_container(Settings(DATABASE_URL=url))


def _make_campaign_ready(c, cid: str) -> None:
    """Fill in the required-to-apply essentials (criteria + résumé) for `cid`."""
    c.criteria_service.edit_criteria(
        CampaignId(cid),
        changes={
            "titles": ["Software Engineer"],
            "locations": ["Remote"],
            "work_modes": ["remote"],
            "salary_floor": 120000,
            "keywords": ["python"],
        },
        confirm=True,
    )
    c.onboarding_service.save_section(cid, IntakeSection.BASE_RESUME, {"parsed": True})
    c.storage.commit()


def test_container_wires_onboarding_gate_behind_ttl_cache():
    """The container hands SetupService a TTLCachedGate, not the raw closure."""
    c = _real_container()
    assert isinstance(c.setup_service._onboarding_gate, TTLCachedGate)
    assert c.setup_service._onboarding_gate._ttl == DEFAULT_ONBOARDING_GATE_CACHE_TTL_S


def test_require_automated_work_gate_avoids_rescanning_campaigns_within_ttl(monkeypatch):
    """Repeated require_automated_work-style checks must not rescan every campaign."""
    c = _real_container()
    c.setup_service.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434", api_key="", model="llama3")
    )
    campaign = c.campaign_service.create_campaign("My job search")
    c.storage.commit()

    calls = {"n": 0}
    orig_list = c.storage.campaigns.list

    def _counting_list():
        calls["n"] += 1
        return orig_list()

    c.storage.campaigns.list = _counting_list

    for _ in range(20):
        c.setup_service.is_automated_work_allowed()

    # storage.campaigns.list() backs the expensive per-campaign readiness scan
    # inside the container's _onboarding_gate closure — it must be invoked at most
    # once across 20 polls served from the TTL cache.
    assert calls["n"] <= 1
    assert campaign is not None  # keep the fixture referenced


def test_require_automated_work_gate_opens_immediately_after_readiness_writes():
    """The real write paths (criteria save, résumé upload) invalidate the cache.

    Item #8's TTL is a defensive backstop, not the only freshness mechanism: the
    container wires ``criteria_service.edit_criteria`` and
    ``onboarding_service.ingest_base_resume``/``save_section``/``complete`` to
    invalidate the gate cache the instant they run (see ``build_container``), so
    the P0 zero-CLI acceptance flow — configure LLM, complete onboarding, save
    criteria, upload a résumé, then immediately check the gate — sees the gate
    open with NO TTL delay at all, matching
    ``tests/bdd/features/p0_oobe_gate.feature``'s real-time expectation.
    """
    c = _real_container()
    c.setup_service.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434", api_key="", model="llama3")
    )
    campaign = c.campaign_service.create_campaign("My job search")
    c.storage.commit()
    cid = str(campaign.id)

    # Not ready yet: no criteria, no résumé.
    assert c.setup_service.is_automated_work_allowed() is False

    # The essentials show up "mid-flight" (résumé upload + criteria save) — both
    # write paths are wired to invalidate the cache.
    _make_campaign_ready(c, cid)

    # Reflected on the VERY NEXT call — no TTL wait needed, exactly like the BDD
    # scenario's "Then automated work may begin" right after the UI writes.
    assert c.setup_service.is_automated_work_allowed() is True


def test_require_automated_work_gate_bounds_staleness_via_ttl_when_uninvalidated(
    monkeypatch,
):
    """A readiness change NOT reaching the invalidation hooks is still bounded by
    the TTL — never indefinitely stale.

    Simulates a write path the container does not explicitly invalidate (e.g. a
    hypothetical future call site, or a per-request-rebuilt ``criteria_service``
    under a real DB — CONC-REQ-1) by mutating the underlying campaign record
    directly, bypassing ``criteria_service``/``onboarding_service`` entirely. The
    TTL backstop must still recover within ``DEFAULT_ONBOARDING_GATE_CACHE_TTL_S``.
    """
    import applicant.application.services.setup_service as setup_service_mod

    c = _real_container()
    c.setup_service.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434", api_key="", model="llama3")
    )
    campaign = c.campaign_service.create_campaign("My job search")
    c.storage.commit()
    cid = str(campaign.id)

    clock = {"t": 0.0}
    monkeypatch.setattr(setup_service_mod.time, "monotonic", lambda: clock["t"])

    # Not ready yet: no criteria, no résumé.
    assert c.setup_service.is_automated_work_allowed() is False

    # Bypass the wrapped service methods entirely — write straight to storage, as
    # an invalidation-hook-less write path would.
    import dataclasses

    campaign_row = c.storage.campaigns.get(CampaignId(cid))
    campaign_row = dataclasses.replace(
        campaign_row,
        criteria={
            "titles": ["Software Engineer"],
            "locations": ["Remote"],
            "work_modes": ["remote"],
            "salary_floor": 120000,
            "keywords": ["python"],
        },
    )
    c.storage.campaigns.add(campaign_row)
    rec = c.setup_service._store.get(f"onboarding.{cid}") or {"intake": {}}
    rec.setdefault("intake", {})["base_resume"] = {"document_path": "/tmp/r.pdf", "parsed": True}
    c.setup_service._store.set(f"onboarding.{cid}", rec)
    c.storage.commit()

    # Still within the TTL window: reading stale-False is the documented tradeoff,
    # and — crucially for a gate that only ever BLOCKS work — it can never read a
    # false "True" here, only a safe, late "False".
    clock["t"] = DEFAULT_ONBOARDING_GATE_CACHE_TTL_S - 0.5
    assert c.setup_service.is_automated_work_allowed() is False

    # Past the TTL, the very next check re-scans and reflects reality.
    clock["t"] = DEFAULT_ONBOARDING_GATE_CACHE_TTL_S + 0.5
    assert c.setup_service.is_automated_work_allowed() is True
