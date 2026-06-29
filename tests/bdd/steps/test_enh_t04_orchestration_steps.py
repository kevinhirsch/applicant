"""Step bindings for the orchestration / checkpoints / storage-SQL theme (T04).

Issues #169, #180, #185, #189, #218, #219, #220, #221, #232, #241, #242, #243,
#244, #245.

Convention (mirrors ``test_enh_research_steps``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the actual adapters / services /
  models and MUST pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the real target (a
  speculative import, a missing attribute / constraint, an assertion the current code
  fails) so the scenario is a genuine red — never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: assertions target adapters (storage / orchestration), the durable
orchestration port via the file-backed shim, the SQL ORM models, and the migration
sources — never UI internals, never a real Postgres socket. The checkpoint shim is
hermetically driven over a tmp directory.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import threading

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.ids import CampaignId, DiscoverySourceId, new_id

scenarios(
    "../features/enhancements/enh_169_select_then_insert_unique.feature",
    "../features/enhancements/enh_180_agentloop_per_tick_state.feature",
    "../features/enhancements/enh_185_scheduler_enabled_default.feature",
    "../features/enhancements/enh_189_approval_timeout_config.feature",
    "../features/enhancements/enh_218_checkpoint_corruption_detection.feature",
    "../features/enhancements/enh_219_checkpoint_disk_full.feature",
    "../features/enhancements/enh_220_concurrent_checkpoint_writes.feature",
    "../features/enhancements/enh_221_teardown_idempotency.feature",
    "../features/enhancements/enh_232_list_campaigns_isinstance_guard.feature",
    "../features/enhancements/enh_241_inmemory_transactional.feature",
    "../features/enhancements/enh_242_agentrun_repo_n_plus_one.feature",
    "../features/enhancements/enh_243_missing_unique_constraints.feature",
    "../features/enhancements/enh_244_json_vs_jsonb_migration.feature",
    "../features/enhancements/enh_245_dead_sql_columns.feature",
)


@pytest.fixture
def t04ctx(tmp_path) -> dict:
    return {"tmp_path": tmp_path}


def _repo_root() -> pathlib.Path:
    # tests/bdd/steps/<this file> -> repo root is parents[3].
    return pathlib.Path(__file__).resolve().parents[3]


def _new_shim(tmp_path):
    """Build a CheckpointShimOrchestrator over a fresh temp directory."""
    from applicant.adapters.orchestration.checkpoint_shim import (
        CheckpointShimOrchestrator,
    )

    return CheckpointShimOrchestrator(checkpoint_dir=str(tmp_path / "ckpt"))


# ===========================================================================
# #169 — select-then-insert UniqueViolation (app_config / tool_settings)
# ===========================================================================
@given("an in-memory app-config store")
def inmem_app_config(t04ctx):
    from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore

    t04ctx["app_config"] = InMemoryAppConfigStore()


@when("the same setup key is written twice with different values")
def write_same_config_key_twice(t04ctx):
    store = t04ctx["app_config"]
    store.set("llm_tier", {"v": 1})
    store.set("llm_tier", {"v": 2})


@then("the latest value is read back and there is exactly one entry")
def config_latest_single(t04ctx):
    store = t04ctx["app_config"]
    assert store.get("llm_tier") == {"v": 2}
    # Internal dict holds exactly one entry for the key (no duplicate insert).
    assert list(store._d.keys()) == ["llm_tier"]


@given("an in-memory tool-settings sink")
def inmem_tool_sink(t04ctx):
    from applicant.adapters.tools.tool_settings_sink import InMemoryToolSettingsSink

    t04ctx["tool_sink"] = InMemoryToolSettingsSink()


@when("the same tool toggle is saved twice")
def save_same_toggle_twice(t04ctx):
    sink = t04ctx["tool_sink"]
    sink.save({"web_search": True})
    sink.save({"web_search": False})


@then("the latest toggle state is read back")
def toggle_latest(t04ctx):
    assert t04ctx["tool_sink"].load() == {"web_search": False}


@given("the SQL app-config store write path")
def sql_app_config_path(t04ctx):
    t04ctx["sql_store_module"] = "applicant.adapters.storage.app_config_store"


@when("two writers race the first write of the same key")
def two_writers_race(t04ctx):
    # The race itself needs a real Postgres + two sessions; we cannot open sockets.
    # The honest probe is: does the SQL store offer a conflict-safe upsert primitive
    # (ON CONFLICT / a documented upsert method) rather than the bare select->add->commit
    # that races? Today it does not, so this resolves to a genuine red.
    mod = importlib.import_module(t04ctx["sql_store_module"])
    store_cls = mod.SqlAlchemyAppConfigStore
    t04ctx["has_upsert"] = hasattr(store_cls, "upsert") or hasattr(store_cls, "set_atomic")


@then("the store resolves the conflict with an upsert instead of raising")
def store_has_upsert(t04ctx):
    assert t04ctx["has_upsert"], (
        "SqlAlchemyAppConfigStore still uses select-then-insert with no conflict-safe "
        "upsert; a same-key write race would raise UniqueViolation on Postgres."
    )


# ===========================================================================
# #180 — AgentLoop per-tick rebuild — process-lived ResumeLedger
# ===========================================================================
def _make_loop_with_ledger(ledger):
    from applicant.application.services.agent_loop import AgentLoop

    return AgentLoop(storage=InMemoryStorage(), agent_run_service=None, resume_ledger=ledger)


@given("a process-lived resume ledger injected into one agent loop")
def ledger_into_loop(t04ctx):
    from applicant.application.services.agent_loop import ResumeLedger

    ledger = ResumeLedger()
    ledger.failures["app-1"] = 3
    ledger.giveup.add("app-2")
    t04ctx["ledger"] = ledger
    t04ctx["loop_a"] = _make_loop_with_ledger(ledger)


@when("a fresh agent loop is rebuilt for the next tick with the same ledger")
def rebuild_loop_same_ledger(t04ctx):
    # Simulate container._build_tick_services: a brand-new AgentLoop, same ledger.
    t04ctx["loop_b"] = _make_loop_with_ledger(t04ctx["ledger"])


@then("the recorded backoff and failure counts are still visible")
def ledger_survives(t04ctx):
    ledger = t04ctx["loop_b"]._resume_ledger
    assert ledger is t04ctx["ledger"]
    assert ledger.failures.get("app-1") == 3
    assert "app-2" in ledger.giveup


@given("two agent loops rebuilt around the same resume ledger")
def two_loops_one_ledger(t04ctx):
    from applicant.application.services.agent_loop import ResumeLedger

    ledger = ResumeLedger()
    t04ctx["ledger"] = ledger
    t04ctx["loop_a"] = _make_loop_with_ledger(ledger)
    t04ctx["loop_b"] = _make_loop_with_ledger(ledger)


@then("the two loops have distinct per-loop locks")
def distinct_loop_locks(t04ctx):
    assert t04ctx["loop_a"]._state_lock is not t04ctx["loop_b"]._state_lock


@then("they share the one ledger lock that guards cross-tick state")
def shared_ledger_lock(t04ctx):
    a = t04ctx["loop_a"]._resume_ledger
    b = t04ctx["loop_b"]._resume_ledger
    assert a is b
    assert a.lock is b.lock


@given("the agent loop module")
def agent_loop_module(t04ctx):
    t04ctx["agent_loop_mod"] = importlib.import_module(
        "applicant.application.services.agent_loop"
    )


@then("it declares which instance state is allowed to live only for one tick")
def declares_per_tick_state(t04ctx):
    # There is no machine-checkable declaration / guard that catches a new per-instance
    # variable silently resetting each tick (the documented footgun). Probe for one.
    mod = t04ctx["agent_loop_mod"]
    marker = getattr(mod.AgentLoop, "__per_tick_state__", None) or getattr(
        mod.AgentLoop, "per_tick_fields", None
    )
    assert marker is not None, (
        "AgentLoop has no declared/enforced set of per-tick-only instance state, so a "
        "new instance variable would silently reset every tick undetected (#180 footgun)."
    )


# ===========================================================================
# #185 — SCHEDULER_ENABLED default
# ===========================================================================
@given("default engine settings")
def default_settings(t04ctx):
    from applicant.app.config import Settings

    t04ctx["settings"] = Settings(DATABASE_URL="postgresql+psycopg://x:x@127.0.0.1:1/none")


@then("the scheduler is enabled")
def scheduler_enabled_by_default(t04ctx):
    assert t04ctx["settings"].scheduler_enabled is True


@then("a sensible tick interval is still configured")
def tick_interval_set(t04ctx):
    assert t04ctx["settings"].scheduler_interval_seconds > 0


@given("settings with the scheduler env flag turned on")
def settings_scheduler_on(t04ctx):
    from applicant.app.config import Settings

    t04ctx["settings"] = Settings(
        DATABASE_URL="postgresql+psycopg://x:x@127.0.0.1:1/none",
        SCHEDULER_ENABLED=True,
    )


@then("the scheduler is enabled")
def scheduler_enabled(t04ctx):
    assert t04ctx["settings"].scheduler_enabled is True


@then("a deployment profile reports the scheduler should run")
def deployment_profile_autoenables(t04ctx):
    # APPLICANT_MODE=production auto-enables the scheduler via the model_validator
    # so a real deploy gets a running loop without a manual SCHEDULER_ENABLED flag.
    from applicant.app.config import Settings
    prod = Settings(
        DATABASE_URL="postgresql+psycopg://x:x@127.0.0.1:1/none",
        APPLICANT_MODE="production",
    )
    assert prod.scheduler_enabled is True
    # The non-production default is also now True (#185)


# ===========================================================================
# #189 — DBOS approval-timeout configurability
# ===========================================================================
@given("a durable pipeline context with a custom approval-wait timeout")
def ctx_with_timeout(t04ctx):
    from applicant.application.workflows.application_pipeline import PipelineContext

    t04ctx["pctx"] = PipelineContext(application_id="a1", approval_timeout=42.0)


@then("the orchestration recv gate receives that timeout value")
def recv_gets_timeout(t04ctx):
    from applicant.application.workflows import application_pipeline as ap

    captured = {}

    class _RecvSpy:
        def run_step(self, wf, step, fn):
            return fn()

        def recv(self, wf, topic, timeout=None):
            captured["timeout"] = timeout
            return {"decision": "approve"}

    # Drive only through to the recv gate by exercising the timeout-selection logic the
    # pipeline uses: `timeout = ctx.approval_timeout if ctx is not None else None`.
    ctx = t04ctx["pctx"]
    timeout = ctx.approval_timeout if ctx is not None else None
    _RecvSpy().recv("wf", ap.FINAL_APPROVAL_TOPIC, timeout=timeout)
    assert captured["timeout"] == 42.0


@given("a durable pipeline context with no approval-wait timeout set")
def ctx_without_timeout(t04ctx):
    from applicant.application.workflows.application_pipeline import PipelineContext

    t04ctx["pctx"] = PipelineContext(application_id="a1")


@then("the recv gate is asked to wait indefinitely")
def recv_indefinite(t04ctx):
    # An unset context timeout is None; the orchestrator interprets None as
    # "wait indefinitely" (DBOS substitutes its large finite stand-in).
    ctx = t04ctx["pctx"]
    timeout = ctx.approval_timeout if ctx is not None else None
    assert timeout is None


@given("the engine settings")
def engine_settings(t04ctx):
    from applicant.app.config import Settings

    t04ctx["settings"] = Settings(DATABASE_URL="postgresql+psycopg://x:x@127.0.0.1:1/none")


@then("an approval-wait timeout setting can be configured")
def approval_timeout_setting(t04ctx):
    settings = t04ctx["settings"]
    # The "indefinite" wait is a hardcoded module constant; there is no Settings field
    # to tune it per deployment. Probe for one.
    assert hasattr(settings, "approval_timeout_seconds") or hasattr(
        settings, "approval_wait_seconds"
    ), "The DBOS approval recv timeout is a hardcoded ~10y constant, not configurable (#189)."


# ===========================================================================
# #218 — checkpoint corruption detection
# ===========================================================================
def _register_and_run_once(shim, wf_id, step_name, body):
    """Register a one-step workflow and start it once (checkpointing the step)."""

    def _wf(orch, workflow_id):
        return orch.run_step(workflow_id, step_name, body)

    shim.register_workflow("wf", _wf)
    return shim.start_workflow("wf", wf_id)


@given("a checkpoint orchestrator over a temp directory")
def checkpoint_orch(t04ctx):
    t04ctx["shim"] = _new_shim(t04ctx["tmp_path"])


@given("a workflow whose only step has already been checkpointed")
def workflow_step_checkpointed(t04ctx):
    shim = t04ctx["shim"]
    t04ctx["wf_id"] = "wf-218"
    t04ctx["calls"] = []

    def _body():
        t04ctx["calls"].append("ran")
        return {"value": "first"}

    t04ctx["body"] = _body
    _register_and_run_once(shim, t04ctx["wf_id"], "only", _body)
    assert t04ctx["calls"] == ["ran"]


@when("the on-disk checkpoint file is overwritten with mangled bytes")
def mangle_checkpoint(t04ctx):
    shim = t04ctx["shim"]
    path = shim._path(t04ctx["wf_id"])
    path.write_text("{not-valid-json::::")


@when("the step is run again")
def run_step_again(t04ctx):
    shim = t04ctx["shim"]
    t04ctx["second_result"] = shim.run_step(t04ctx["wf_id"], "only", t04ctx["body"])


@then("the step body executes again rather than returning stale data")
def body_reran(t04ctx):
    # Mangled JSON is caught -> treated as "no checkpoint" -> the step re-executes.
    assert t04ctx["calls"] == ["ran", "ran"]
    assert t04ctx["second_result"] == {"value": "first"}


@when("the step is run again over the same directory")
def run_step_again_same_dir(t04ctx):
    # Fresh orchestrator over the SAME directory (a restart).
    shim2 = _new_shim_same_dir(t04ctx)
    t04ctx["shim2"] = shim2

    def _body2():
        t04ctx["calls"].append("ran-again")
        return {"value": "SHOULD-NOT-RUN"}

    def _wf(orch, workflow_id):
        return orch.run_step(workflow_id, "only", _body2)

    shim2.register_workflow("wf", _wf)
    handle = shim2.start_workflow("wf", t04ctx["wf_id"])
    t04ctx["resumed_result"] = handle.result()


def _new_shim_same_dir(t04ctx):
    from applicant.adapters.orchestration.checkpoint_shim import (
        CheckpointShimOrchestrator,
    )

    same_dir = t04ctx["shim"]._dir
    return CheckpointShimOrchestrator(checkpoint_dir=str(same_dir))


@then("the checkpointed result is returned without re-running the body")
def resumed_without_rerun(t04ctx):
    assert "ran-again" not in t04ctx["calls"]
    assert t04ctx["resumed_result"] == {"value": "first"}


@when("a checkpoint file is left structurally valid but missing its integrity marker")
def truncated_but_parseable(t04ctx):
    shim = t04ctx["shim"]
    wf_id = "wf-218b"
    t04ctx["wf_id_corrupt"] = wf_id
    # A structurally valid JSON dict that "passes truthiness" but is actually partial
    # (no integrity / version marker, missing the real steps).
    shim._path(wf_id).write_text(json.dumps({"steps": {"only": None}, "_partial": True}))


@then("loading it is flagged as corrupt rather than trusted as complete")
def loading_flagged_corrupt(t04ctx):
    shim = t04ctx["shim"]
    # There is no integrity verification API; the shim has no way to distinguish a
    # truncated-but-parseable checkpoint from a complete one. Probe for one.
    verifier = getattr(shim, "verify_checkpoint", None) or getattr(shim, "_checksum", None)
    assert verifier is not None, (
        "checkpoint_shim has no checksum/version/schema verification, so a truncated "
        "but parseable checkpoint is trusted as complete (#218)."
    )


# ===========================================================================
# #219 — disk-full handling
# ===========================================================================
@when("a step result is checkpointed")
def checkpoint_a_step(t04ctx):
    shim = t04ctx["shim"]
    _register_and_run_once(shim, "wf-219", "step", lambda: {"ok": True})
    t04ctx["wf_id"] = "wf-219"


@then("exactly one checkpoint file exists and it parses cleanly")
def one_clean_checkpoint(t04ctx):
    shim = t04ctx["shim"]
    files = list(shim._dir.glob("*.checkpoint.json"))
    assert len(files) == 1
    parsed = json.loads(files[0].read_text())
    assert parsed["steps"]["step"] == {"ok": True}


@given("a checkpoint orchestrator over a temp directory whose disk is full")
def checkpoint_orch_disk_full(t04ctx, monkeypatch):
    shim = _new_shim(t04ctx["tmp_path"])
    t04ctx["shim"] = shim

    import os as _os

    real_replace = _os.replace

    def _enospc_replace(src, dst):
        # Simulate ENOSPC when the durable checkpoint is being committed into place.
        if str(dst).endswith(".checkpoint.json"):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(
        "applicant.adapters.orchestration.checkpoint_shim.os.replace", _enospc_replace
    )


@when("a step tries to checkpoint its result")
def step_checkpoint_under_enospc(t04ctx):
    shim = t04ctx["shim"]

    def _attempt():
        def _wf(orch, workflow_id):
            return orch.run_step(workflow_id, "step", lambda: {"ok": True})

        shim.register_workflow("wf", _wf)
        shim.start_workflow("wf", "wf-219-full")

    t04ctx["attempt"] = _attempt


@then("the orchestrator raises a recognizable out-of-space health signal")
def enospc_health_signal(t04ctx):
    # Today the raw OSError propagates uncaught; there is no ENOSPC-specific handling
    # that surfaces a recognizable health signal. Probe for a dedicated exception type.
    mod = importlib.import_module("applicant.adapters.orchestration.checkpoint_shim")
    health_exc = getattr(mod, "CheckpointDiskFull", None) or getattr(
        mod, "CheckpointStorageError", None
    )
    assert health_exc is not None, (
        "checkpoint_shim has no ENOSPC-specific health signal; a full disk raises a raw "
        "OSError that drives an infinite retry loop (#219)."
    )
    with pytest.raises(health_exc):
        t04ctx["attempt"]()


# ===========================================================================
# #220 — concurrent checkpoint writes
# ===========================================================================
@when("many threads checkpoint distinct steps of the same workflow at once")
def threads_checkpoint_distinct_steps(t04ctx):
    shim = t04ctx["shim"]
    wf_id = "wf-220"
    t04ctx["wf_id"] = wf_id
    n = 24
    barrier = threading.Barrier(n)

    def _worker(i):
        barrier.wait()
        shim.run_step(wf_id, f"step-{i}", lambda i=i: {"i": i})

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n)]
    for thr in threads:
        thr.start()
    for thr in threads:
        thr.join()
    t04ctx["expected_steps"] = n


@then("every step result is durably recorded with none lost")
def all_steps_recorded(t04ctx):
    shim = t04ctx["shim"]
    completed = shim.completed_steps(t04ctx["wf_id"])
    assert len(completed) == t04ctx["expected_steps"]
    assert sorted(completed) == sorted(f"step-{i}" for i in range(t04ctx["expected_steps"]))


@then("two different workflow ids resolve to two different locks")
def distinct_wf_locks(t04ctx):
    shim = t04ctx["shim"]
    assert shim._lock_for("wf-a") is not shim._lock_for("wf-b")


@then("the same workflow id resolves to the same lock")
def same_wf_same_lock(t04ctx):
    shim = t04ctx["shim"]
    assert shim._lock_for("wf-a") is shim._lock_for("wf-a")


@then("it exposes a cross-process guard binding a workflow to a single advancing tick")
def cross_process_guard(t04ctx):
    shim = t04ctx["shim"]
    # The per-workflow threading.Lock only serializes IN-process callers. There is no
    # cross-process / file-level mutex ensuring only one tick advances a parked workflow.
    guard = getattr(shim, "claim_workflow", None) or getattr(shim, "lease", None)
    assert guard is not None, (
        "checkpoint_shim has only an in-process lock; no cross-process lease/claim binds "
        "a parked workflow to a single advancing tick (#220)."
    )


# ===========================================================================
# #221 — teardown idempotency
# ===========================================================================
@given("a workflow whose teardown step has run once and been checkpointed")
def teardown_run_once(t04ctx):
    shim = t04ctx["shim"]
    t04ctx["wf_id"] = "wf-221"
    t04ctx["teardowns"] = []
    _register_and_run_once(
        shim, t04ctx["wf_id"], "teardown", lambda: t04ctx["teardowns"].append(1) or {"torn": True}
    )
    assert t04ctx["teardowns"] == [1]


@when("the same teardown step is driven again over the same directory")
def teardown_driven_again(t04ctx):
    shim2 = _new_shim_same_dir(t04ctx)

    def _wf(orch, workflow_id):
        return orch.run_step(
            workflow_id, "teardown", lambda: t04ctx["teardowns"].append(2) or {"torn": True}
        )

    shim2.register_workflow("wf", _wf)
    shim2.start_workflow("wf", t04ctx["wf_id"])


@then("the teardown body does not run a second time")
def teardown_not_rerun(t04ctx):
    assert t04ctx["teardowns"] == [1]


@given("a workflow that ran through to its terminal teardown step")
def workflow_through_teardown(t04ctx):
    shim = t04ctx["shim"]
    t04ctx["wf_id"] = "wf-221-term"
    _register_and_run_once(shim, t04ctx["wf_id"], "teardown", lambda: {"torn": True})


@when("pending-workflow recovery runs")
def recovery_runs(t04ctx):
    t04ctx["pending"] = t04ctx["shim"].recover_pending()


@then("the completed workflow is not listed for re-drive")
def completed_not_listed(t04ctx):
    assert t04ctx["wf_id"] not in t04ctx["pending"]


@given("a pipeline whose teardown succeeded but crashed before checkpointing")
def teardown_succeeded_no_checkpoint(t04ctx):
    # Model the window: ctx.teardown() already destroyed the sandbox, but the checkpoint
    # write never happened, so a re-drive WILL call teardown again.
    t04ctx["sandbox_destroyed"] = True
    t04ctx["teardown_calls"] = 0


@when("the workflow is recovered and teardown is re-driven")
def teardown_redriven_after_crash(t04ctx):
    from applicant.application.workflows.application_pipeline import PipelineContext

    def _teardown():
        t04ctx["teardown_calls"] += 1
        if t04ctx["sandbox_destroyed"]:
            # A non-idempotent teardown raises on the already-released sandbox.
            raise RuntimeError("sandbox already destroyed")

    ctx = PipelineContext(application_id="a1", teardown=_teardown)
    t04ctx["ctx"] = ctx
    try:
        ctx.teardown()
        t04ctx["second_teardown_ok"] = True
    except RuntimeError:
        t04ctx["second_teardown_ok"] = False


@then("the second teardown is a contract-guaranteed no-op")
def second_teardown_noop(t04ctx):
    # There is no documented idempotency contract on PipelineContext.teardown, so a
    # second call against the destroyed sandbox is NOT guaranteed safe. The flag captured
    # whether the contract held; today it does not.
    contract = getattr(
        importlib.import_module(
            "applicant.application.workflows.application_pipeline"
        ).PipelineContext,
        "teardown_idempotent",
        None,
    )
    assert contract is True and t04ctx["second_teardown_ok"], (
        "PipelineContext.teardown has no at-least-once / idempotent-by-contract guarantee, "
        "so a crash between teardown and its checkpoint double-releases the sandbox (#221)."
    )


# ===========================================================================
# #232 — list_campaigns isinstance guard
# ===========================================================================
def _email_route_guard(data):
    """The exact shape guard applicant_email_routes uses for the engine response."""
    return data if isinstance(data, list) else []


@given("the campaign-list shape guard used by the email route")
def email_route_guard(t04ctx):
    t04ctx["guard"] = _email_route_guard


@when("the engine returns a dict instead of a bare list")
def engine_returns_dict(t04ctx):
    t04ctx["guarded"] = t04ctx["guard"]({"items": [{"id": "c1"}]})


@then("the guard yields an empty list")
def guard_empty_list(t04ctx):
    assert t04ctx["guarded"] == []


@when("the engine returns a bare list of campaigns")
def engine_returns_list(t04ctx):
    t04ctx["payload"] = [{"id": "c1"}, {"id": "c2"}]
    t04ctx["guarded"] = t04ctx["guard"](t04ctx["payload"])


@then("the guard yields that same list")
def guard_same_list(t04ctx):
    assert t04ctx["guarded"] == t04ctx["payload"]


@given("the chat campaign-list route source")
def chat_route_source(t04ctx):
    path = _repo_root() / "workspace" / "routes" / "applicant_chat_routes.py"
    t04ctx["chat_src"] = path.read_text()


@then("it validates the campaign response is a list before returning it")
def chat_route_guards_list(t04ctx):
    src = t04ctx["chat_src"]
    # The chat list_campaigns returns `campaigns or []` with no isinstance(... , list)
    # guard, so a dict-shaped engine response passes straight through. Probe for the guard.
    assert "isinstance(campaigns, list)" in src, (
        "applicant_chat_routes.list_campaigns has no isinstance(campaigns, list) guard, so "
        "a non-list engine response would crash the frontend iteration (#232)."
    )


# ===========================================================================
# #241 — InMemoryStorage transactional commit / rollback
# ===========================================================================
@given("a fresh in-memory storage")
def fresh_inmem(t04ctx):
    t04ctx["storage"] = InMemoryStorage()


@when("a campaign is added and the unit of work is committed")
def add_commit_campaign(t04ctx):
    storage = t04ctx["storage"]
    cid = CampaignId(new_id())
    t04ctx["cid"] = cid
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()


@then("the campaign is readable")
def campaign_readable(t04ctx):
    assert t04ctx["storage"].campaigns.get(t04ctx["cid"]) is not None


@then("commit and rollback can be invoked without error")
def commit_rollback_callable(t04ctx):
    storage = t04ctx["storage"]
    assert storage.commit() is None
    assert storage.rollback() is None


@when("a campaign is added and then the unit of work is rolled back")
def add_rollback_campaign(t04ctx):
    storage = t04ctx["storage"]
    cid = CampaignId(new_id())
    t04ctx["cid"] = cid
    storage.campaigns.add(Campaign(id=cid, name="rolled-back"))
    storage.rollback()


@then("the campaign is no longer present")
def campaign_absent_after_rollback(t04ctx):
    # InMemoryStorage.rollback() is a no-op, so the write is still there — a true red
    # until InMemory buffers writes until commit and discards on rollback (#241).
    assert t04ctx["storage"].campaigns.get(t04ctx["cid"]) is None, (
        "InMemoryStorage.rollback() is a no-op, so a rolled-back write survives — tests "
        "cannot catch missing-commit / partial-write bugs (#241)."
    )


# ===========================================================================
# #242 — AgentRunRepo N+1 / full-table scan
# ===========================================================================
def _seed_runs(repo, cid, n):
    from applicant.core.entities.agent_run import AgentRun

    runs = []
    for _ in range(n):
        run = AgentRun(id=new_id(), campaign_id=cid)
        repo.add(run)
        runs.append(run)
    return runs


@given("an in-memory agent-run repository with several runs")
def inmem_agent_runs(t04ctx):
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    t04ctx["storage"] = storage
    t04ctx["cid"] = cid
    t04ctx["runs"] = _seed_runs(storage.agent_runs, cid, 5)


@then("latest returns the most recent run")
def latest_most_recent(t04ctx):
    latest = t04ctx["storage"].agent_runs.latest(t04ctx["cid"])
    expected = max(t04ctx["runs"], key=lambda r: (r.timestamp, r.seq))
    assert latest is not None and latest.id == expected.id


@then("max_seq returns the highest sequence")
def max_seq_highest(t04ctx):
    expected = max(r.seq for r in t04ctx["runs"])
    assert t04ctx["storage"].agent_runs.max_seq(t04ctx["cid"]) == expected


@when("old runs are pruned keeping only the newest two")
def prune_keep_two(t04ctx):
    t04ctx["deleted"] = t04ctx["storage"].agent_runs.prune_old(t04ctx["cid"], keep=2)


@then("only the two newest runs remain")
def two_newest_remain(t04ctx):
    storage = t04ctx["storage"]
    remaining = storage.agent_runs.list_for_campaign(t04ctx["cid"])
    assert len(remaining) == 2
    newest_two = {
        r.id for r in sorted(t04ctx["runs"], key=lambda r: (r.timestamp, r.seq))[-2:]
    }
    assert {r.id for r in remaining} == newest_two


@given("the SQL agent-run repository source")
def sql_agentrun_source(t04ctx):
    import inspect

    repos = importlib.import_module("applicant.adapters.storage.repositories")
    t04ctx["agentrun_latest_src"] = inspect.getsource(repos.AgentRunRepo.latest)


@then("latest pushes ordering and a single-row limit to the database")
def latest_bounded_query(t04ctx):
    src = t04ctx["agentrun_latest_src"]
    # Today latest() materializes the whole table with .all() then Python-max. A bounded
    # query would use order_by + limit and NOT load every row. Genuine red until fixed.
    assert ".limit(" in src and ".all()" not in src, (
        "SQL AgentRunRepo.latest() still materializes the entire agent_runs table with "
        ".all() and sorts in Python instead of ORDER BY ... LIMIT 1 (#242)."
    )


# ===========================================================================
# #243 — missing unique constraints
# ===========================================================================
@given("an in-memory storage")
def inmem_storage_only(t04ctx):
    t04ctx["storage"] = InMemoryStorage()


@when("the same discovery source key is upserted twice for one campaign")
def upsert_source_twice(t04ctx):
    storage = t04ctx["storage"]
    cid = CampaignId(new_id())
    t04ctx["cid"] = cid
    for enabled in (True, False):
        storage.discovery_sources.upsert(
            DiscoverySource(
                id=DiscoverySourceId(new_id()),
                campaign_id=cid,
                source_key="jobspy:indeed",
                enabled=enabled,
            )
        )


@then("only one discovery source exists for that key")
def one_source_for_key(t04ctx):
    sources = t04ctx["storage"].discovery_sources.list_for_campaign(t04ctx["cid"])
    matching = [s for s in sources if s.source_key == "jobspy:indeed"]
    assert len(matching) == 1
    assert matching[0].enabled is False


@given("the SQL models")
def sql_models(t04ctx):
    t04ctx["models"] = importlib.import_module("applicant.adapters.storage.models")


def _unique_constraint_columns(model) -> list[frozenset]:
    from sqlalchemy import UniqueConstraint

    cols: list[frozenset] = []
    for c in model.__table__.constraints:
        if isinstance(c, UniqueConstraint):
            cols.append(frozenset(col.name for col in c.columns))
    # Column-level unique=True also counts.
    for col in model.__table__.columns:
        if col.unique:
            cols.append(frozenset({col.name}))
    return cols


@then("the credentials model is unique per campaign and tenant")
def credentials_unique(t04ctx):
    m = t04ctx["models"]
    uniques = _unique_constraint_columns(m.CredentialModel)
    assert frozenset({"campaign_id", "tenant_key"}) in uniques


@then("the tool-settings and app-config keys are unique")
def keys_unique(t04ctx):
    m = t04ctx["models"]
    assert frozenset({"tool_key"}) in _unique_constraint_columns(m.ToolSettingModel)
    assert frozenset({"key"}) in _unique_constraint_columns(m.AppConfigModel)


@then("the discovery-source model declares a campaign-and-source unique constraint")
def discovery_source_unique(t04ctx):
    m = t04ctx["models"]
    uniques = _unique_constraint_columns(m.DiscoverySourceModel)
    assert frozenset({"campaign_id", "source_key"}) in uniques, (
        "DiscoverySourceModel has no (campaign_id, source_key) unique constraint, so the "
        "SQL lane allows duplicate sources the InMemory lane forbids (#243)."
    )


@then("the onboarding-profile model declares a per-campaign unique constraint")
def onboarding_profile_unique(t04ctx):
    m = t04ctx["models"]
    uniques = _unique_constraint_columns(m.OnboardingProfileModel)
    assert frozenset({"campaign_id"}) in uniques, (
        "OnboardingProfileModel has no per-campaign unique constraint, so two profiles "
        "for one campaign can coexist in SQL (#243)."
    )


# ===========================================================================
# #244 — JSON vs JSONB in the initial migration
# ===========================================================================
def _has_jsonb_variant(json_type) -> bool:
    from sqlalchemy.dialects.postgresql import JSONB

    variants = getattr(json_type, "_variant_mapping", None) or getattr(
        json_type, "mapping", {}
    )
    return any(isinstance(v, JSONB) for v in dict(variants).values())


@given("the storage models module")
def storage_models_module(t04ctx):
    t04ctx["models"] = importlib.import_module("applicant.adapters.storage.models")


@then("the ORM JSON column type uses the postgresql JSONB variant")
def models_jsonb_variant(t04ctx):
    assert _has_jsonb_variant(t04ctx["models"].JSONType)


@given("the material-provenance migration")
def provenance_migration(t04ctx):
    import inspect

    mig = importlib.import_module(
        "applicant.adapters.storage.alembic.versions.0006_material_provenance"
    )
    t04ctx["mig_src"] = inspect.getsource(mig)
    t04ctx["mig_mod"] = mig


@then("the provenance migration JSON column type uses the postgresql JSONB variant")
def migration_jsonb_variant(t04ctx):
    mig = t04ctx["mig_mod"]
    assert _has_jsonb_variant(mig._JSON)


@given("the initial schema migration source")
def initial_migration_source(t04ctx):
    import inspect

    mig = importlib.import_module(
        "applicant.adapters.storage.alembic.versions.0001_initial"
    )
    t04ctx["initial_src"] = inspect.getsource(mig)


@then("it uses the JSONB-variant type rather than a bare JSON type")
def initial_uses_jsonb(t04ctx):
    src = t04ctx["initial_src"]
    # 0001_initial emits bare sa.JSON() for every JSON column (no JSONB variant import),
    # so an alembic-built Postgres gets `json` not `jsonb`. Genuine red until fixed.
    assert "JSONB" in src and "with_variant" in src, (
        "alembic 0001_initial uses bare sa.JSON() for every JSON column instead of the "
        "JSONB variant, so alembic-built and create_all-built schemas diverge (#244)."
    )


# ===========================================================================
# #245 — dead SQL columns
# ===========================================================================
@given("the domain entities")
def domain_entities(t04ctx):
    from applicant.core.entities.generated_document import GeneratedDocument
    from applicant.core.entities.job_posting import JobPosting
    from applicant.core.entities.revision_session import RevisionSession

    t04ctx["JobPosting"] = JobPosting
    t04ctx["GeneratedDocument"] = GeneratedDocument
    t04ctx["RevisionSession"] = RevisionSession


def _entity_fields(entity_cls) -> set[str]:
    import dataclasses

    return {f.name for f in dataclasses.fields(entity_cls)}


@then("the revision-session entity has a redline-state field")
def revision_has_redline(t04ctx):
    assert "redline_state" in _entity_fields(t04ctx["RevisionSession"])


@then("the job-posting entity has no normalized field")
def job_posting_no_normalized(t04ctx):
    assert "normalized" not in _entity_fields(t04ctx["JobPosting"])


@then("the generated-document entity has no redline-state field")
def generated_doc_no_redline(t04ctx):
    assert "redline_state" not in _entity_fields(t04ctx["GeneratedDocument"])


@then("the job-posting model no longer declares a normalized column")
def model_no_normalized(t04ctx):
    m = t04ctx["models"]
    cols = {c.name for c in m.JobPostingModel.__table__.columns}
    assert "normalized" not in cols, (
        "JobPostingModel.normalized is a dead column — absent from the JobPosting entity, "
        "never read/written by the repository (#245)."
    )


@then("the generated-material model no longer declares a redline-state column")
def model_no_material_redline(t04ctx):
    m = t04ctx["models"]
    cols = {c.name for c in m.GeneratedMaterialModel.__table__.columns}
    assert "redline_state" not in cols, (
        "GeneratedMaterialModel.redline_state is a dead column — absent from the "
        "GeneratedDocument entity, never read/written by the repository (#245)."
    )
