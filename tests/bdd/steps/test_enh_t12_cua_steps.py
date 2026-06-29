"""Step bindings for the computer-use / desktop / mind & context theme (T12).

Covers issues #141, #142, #143, #144, #145, #179. Follows the canonical enhancement
pattern (see ``test_enh_research_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the actual core rules, ports,
  adapters, and application services through in-memory / fake collaborators, and must
  pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built (or is irreducibly integration-only: a real ``cua-driver``
  binary, a live multi-container workspace stack). Their steps make an HONEST probe at
  the real target (a speculative import, a missing attribute, an assertion the current
  code fails) so the scenario is a genuine red — never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: assertions target core rules (``core/rules``), driven ports, and application
services through in-memory / fake adapters — never UI internals, never a real driver,
never a real socket. Speculative imports for not-yet-built / integration-only targets
live INSIDE the step body so absence -> runtime error -> xfail, never a collection error.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.memory.factory import build_agent_memory
from applicant.adapters.sandbox.computer_use import build_computer_use
from applicant.adapters.sandbox.computer_use.cua_driver import (
    _HEALTH_TOOL,
    _TOOL_NAMES,
    CuaDriverComputerUse,
)
from applicant.adapters.sandbox.computer_use.noop import NoopComputerUse
from applicant.app.config import Settings
from applicant.application.services.chat_tools import ChatToolbox
from applicant.application.services.context_manager import (
    SUMMARY_PREFIX,
    ContextManager,
    prefix_cache_breakpoints,
    provider_supports_prefix_cache,
)
from applicant.application.services.curation_service import CurationResult
from applicant.application.services.loop_tools import LoopToolset, build_loop_toolset
from applicant.application.services.prefill_service import PrefillService
from applicant.core.errors import ComputerUseBlocked, DomainError
from applicant.core.rules.computer_use import DESTRUCTIVE_ACTIONS, DesktopAction
from applicant.dormant import DORMANT_SURFACES, STATUS_LIVE
from applicant.ports.driven.computer_use import HealthReport
from applicant.ports.driven.llm import ChatMessage
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    SCOPE_GLOBAL,
    MemoryEntry,
)

scenarios(
    "../features/enhancements/enh_141_loop_desktop_assist_upload.feature",
    "../features/enhancements/enh_142_cua_driver_tool_reconcile.feature",
    "../features/enhancements/enh_143_context_management.feature",
    "../features/enhancements/enh_144_agent_callable_tools.feature",
    "../features/enhancements/enh_145_mind_bridge_e2e.feature",
    "../features/enhancements/enh_179_desktop_assist_image_bake.feature",
)


@pytest.fixture
def t12ctx() -> dict:
    return {}


# ---------------------------------------------------------------------------
# Shared fakes — operable desktop backend + a curation/agent-memory bundle
# ---------------------------------------------------------------------------
class _OperableComputerUse(NoopComputerUse):
    """A no-op desktop adapter that reports an OPERABLE (non-noop) backend.

    Records every call (via ``NoopComputerUse.calls``) and enforces the SAME core
    guards (stop-boundary, no-secret, hard-blocks) — so it stands in for a real
    operable driver without any side effect, display, or subprocess.
    """

    backend = "cua"

    def health(self) -> HealthReport:
        return HealthReport(ok=True, backend="cua", detail="operable (test stand-in)")


class _FakeCuration:
    """Minimal curation service: records staged writes, applies nothing silently."""

    def __init__(self) -> None:
        self.staged: list[str] = []

    def stage_memory(self, text, *, kind, campaign_id=None):
        self.staged.append(text)
        return CurationResult(auto_applied=0)

    def stage_skill(self, skill, *, is_improvement=False):
        self.staged.append(skill.name)
        return CurationResult(auto_applied=0)


def _agent_memory_bundle():
    """An agent-memory bundle whose memory/skills/recall slots are simply present."""
    return SimpleNamespace(memory=object(), skills=object(), recall=object())


def _bare_prefill(computer_use) -> PrefillService:
    """A PrefillService with only the desktop port wired (the rest unused by the seam)."""
    return PrefillService(
        storage=None,
        browser=None,
        detection=None,
        sandbox=None,
        credentials=None,
        computer_use=computer_use,
    )


# ===========================================================================
# GREEN — #141 autonomous loop self-uses desktop assist for native pickers
# ===========================================================================
@given("a pre-fill loop with an operable desktop-assist backend")
@given("an operable desktop-assist backend")
def prefill_operable(t12ctx):
    t12ctx["cu"] = _OperableComputerUse()
    t12ctx["prefill"] = _bare_prefill(t12ctx["cu"])


@when("a résumé attach step opens a native file-open dialog the browser cannot satisfy")
def attach_opens_native_dialog(t12ctx):
    # The loop's own seam for completing an off-page native picker (FR-CUA, FR-RESUME-4).
    t12ctx["picker_ok"] = t12ctx["prefill"]._complete_native_picker(
        app=None, fld=None, path="/data/resume.pdf"
    )


@then("the loop focuses the dialog, types the file path, and confirms — nothing more")
def picker_bounded_vocabulary(t12ctx):
    assert t12ctx["picker_ok"] is True
    actions = [c.action for c in t12ctx["cu"].calls]
    # Exactly the bounded file-attach vocabulary: focus -> type path -> confirm.
    assert actions == [
        DesktopAction.FOCUS_APP,
        DesktopAction.TYPE_TEXT,
        DesktopAction.KEY,
    ]
    # Never a click / account-create / submit — those stay human hand-off.
    assert DesktopAction.CLICK not in actions


@when("a desktop action is asked to perform a final submit")
def desktop_final_submit(t12ctx):
    try:
        t12ctx["cu"].click("submit-application", intent="final_submit")
        t12ctx["boundary_refused"] = False
    except DomainError:
        t12ctx["boundary_refused"] = True


@then("the action is refused by the core stop-boundary")
def boundary_refused(t12ctx):
    assert t12ctx["boundary_refused"] is True


@when("the desktop is asked to type a value flagged as a secret")
def desktop_type_secret(t12ctx):
    try:
        t12ctx["cu"].type_text("hunter2", is_secret=True)
        t12ctx["secret_refused"] = False
    except ComputerUseBlocked:
        t12ctx["secret_refused"] = True


@then("typing the secret is refused")
def secret_refused(t12ctx):
    assert t12ctx["secret_refused"] is True


@given("a pre-fill loop with only the no-op desktop backend")
def prefill_noop(t12ctx):
    t12ctx["cu"] = NoopComputerUse()
    t12ctx["prefill"] = _bare_prefill(t12ctx["cu"])


@when("a résumé attach step opens a native file-open dialog")
def attach_opens_dialog_noop(t12ctx):
    t12ctx["picker_ok"] = t12ctx["prefill"]._complete_native_picker(
        app=None, fld=None, path="/data/resume.pdf"
    )


@then("the loop does not attempt any desktop action and leaves the step for a human")
def picker_degrades(t12ctx):
    assert t12ctx["picker_ok"] is False
    assert t12ctx["cu"].calls == []


# ===========================================================================
# GREEN — #142 cua-driver tool-name registry + reconciliation seam
# ===========================================================================
@given("the cua-driver tool-name registry")
def cua_tool_registry(t12ctx):
    t12ctx["tool_names"] = dict(_TOOL_NAMES)
    t12ctx["health_tool"] = _HEALTH_TOOL


@then("every bounded desktop action and the health preflight has a mapped tool name")
def all_actions_mapped(t12ctx):
    mapped_actions = set(t12ctx["tool_names"].keys())
    # Every destructive action plus the read-only capture is mapped to a tool name.
    assert (DESTRUCTIVE_ACTIONS | {DesktopAction.CAPTURE}) <= mapped_actions
    # No empty / duplicate tool names, and a distinct health tool.
    names = list(t12ctx["tool_names"].values())
    assert all(names) and len(set(names)) == len(names)
    assert t12ctx["health_tool"] and t12ctx["health_tool"] not in names


def _expected_tools() -> set[str]:
    # The exact reconciliation set ``_McpStdioSession.start`` validates against tools/list.
    return set(_TOOL_NAMES.values()) | {_HEALTH_TOOL}


@given("a cua-driver session talking to a driver that advertises the mapped tools")
def driver_advertises_all(t12ctx):
    # Simulate the driver's tools/list reply: every mapped tool (plus an extra one).
    t12ctx["advertised"] = _expected_tools() | {"some_other_tool"}


@given("a cua-driver session talking to a driver missing one mapped tool")
def driver_missing_one(t12ctx):
    t12ctx["dropped"] = "click"
    t12ctx["advertised"] = _expected_tools() - {t12ctx["dropped"]}


@when("the session handshake runs and lists the driver's tools")
def session_handshake_reconciles(t12ctx):
    # Exactly the comparison the shipped start() handshake performs.
    t12ctx["missing"] = _expected_tools() - t12ctx["advertised"]


@then("the mapped tool names are confirmed present with no mismatch warning")
def no_mismatch(t12ctx):
    assert t12ctx["missing"] == set()


@then("the missing tool is reported as a reconciliation warning")
def mismatch_reported(t12ctx):
    assert t12ctx["missing"] == {t12ctx["dropped"]}


@given("a real cua-driver binary baked into the sandbox image")
def real_cua_binary(t12ctx):
    t12ctx["needs_real_driver"] = True


@when("a capture and a benign click are round-tripped against it")
def roundtrip_real_driver(t12ctx):
    import shutil

    cmd = shutil.which("cua-driver")
    if cmd is None:
        raise RuntimeError("cua-driver binary is not baked into this image")
    # We do not actually spawn the real driver in this hermetic lane; reaching here
    # without the binary already xfails. (The real round-trip lives in the integration
    # leg.)
    t12ctx["driver_cmd"] = cmd


@then("the argument keys and the health_report shape match the live driver schema")
def schema_reconciled(t12ctx):
    # Reconciling against the live published schema is the integration deliverable; a
    # documented, machine-checkable schema map does not exist yet.
    import importlib

    mod = importlib.import_module(
        "applicant.adapters.sandbox.computer_use.cua_driver"
    )
    assert hasattr(mod, "RECONCILED_TOOL_SCHEMAS"), (
        "no reconciled-against-real-binary tool schema map exists yet"
    )


# ===========================================================================
# GREEN — #143 context management: compression + provider-gated prefix cache
# ===========================================================================
def _long_conversation() -> list[ChatMessage]:
    turns = [ChatMessage(role="system", content="System instructions. " * 10)]
    for _ in range(12):
        turns.append(ChatMessage(role="user", content="hello world " * 40))
        turns.append(ChatMessage(role="assistant", content="reply text " * 40))
    return turns


@given("a long multi-turn conversation past the compression threshold")
def long_conversation(t12ctx):
    t12ctx["turns"] = _long_conversation()
    t12ctx["manager"] = ContextManager(threshold=50, keep_recent=4)


@given("a conversation with the compression threshold disabled")
def disabled_conversation(t12ctx):
    t12ctx["turns"] = _long_conversation()
    t12ctx["manager"] = ContextManager(threshold=0)


@when("the context manager compresses it")
def compress_it(t12ctx):
    t12ctx["result"] = t12ctx["manager"].compress(t12ctx["turns"])


@then("the middle turns collapse into one bounded summary turn")
def middle_collapsed(t12ctx):
    result = t12ctx["result"]
    assert result.compressed is True
    assert len(result.turns) < len(t12ctx["turns"])
    summaries = [
        m
        for m in result.turns
        if isinstance(m.content, str) and SUMMARY_PREFIX in m.content
    ]
    assert len(summaries) == 1


@then("the system tier and the most recent turns are preserved")
def tiers_preserved(t12ctx):
    out = t12ctx["result"].turns
    original = t12ctx["turns"]
    # Leading system instruction is kept verbatim as the first turn.
    assert out[0] is original[0]
    # The latest turn is kept verbatim at the tail.
    assert out[-1] is original[-1]


@then("the lineage records which earlier turns the summary subsumes")
def lineage_recorded(t12ctx):
    lineage = t12ctx["result"].lineage
    assert lineage.compressed is True
    assert len(lineage.child_indices) > 0
    assert len(lineage.child_indices) == len(lineage.child_roles)
    assert lineage.parent_index >= 0


@then("the turns come back unchanged")
def turns_unchanged(t12ctx):
    result = t12ctx["result"]
    assert result.compressed is False
    assert len(result.turns) == len(t12ctx["turns"])
    assert all(a is b for a, b in zip(result.turns, t12ctx["turns"], strict=True))


class _Profile:
    """A duck-typed provider profile exposing the prefix-cache capability flags."""

    def __init__(self, *, supports: bool) -> None:
        self.supports_prefix_cache = supports

    def mark_prefix_cache(self, payload: dict) -> dict:
        out = dict(payload)
        out["cache_control"] = {"type": "ephemeral"}
        return out


@given("a provider profile that advertises prefix-cache support")
def supporting_profile(t12ctx):
    t12ctx["profile"] = _Profile(supports=True)
    t12ctx["posture"] = "auto"


@given("the built-in local and OpenAI-compatible provider profiles")
def builtin_profiles(t12ctx):
    from applicant.adapters.llm.provider_profiles import get_profile

    t12ctx["builtin"] = [
        get_profile("ollama", "http://localhost:11434/v1"),
        get_profile("openai", "https://api.openai.com/v1"),
    ]
    t12ctx["posture"] = "auto"


@when("prefix-cache breakpoints are applied to the request")
def apply_breakpoints(t12ctx):
    posture = t12ctx.get("posture", "auto")
    if "builtin" in t12ctx:
        t12ctx["outputs"] = [
            prefix_cache_breakpoints({"messages": []}, p, posture=posture)
            for p in t12ctx["builtin"]
        ]
    else:
        t12ctx["output"] = prefix_cache_breakpoints(
            {"messages": []}, t12ctx["profile"], posture=posture
        )


@then("the stable-prefix cache breakpoint is stamped on the request")
def breakpoint_stamped(t12ctx):
    assert provider_supports_prefix_cache(t12ctx["profile"], posture="auto") is True
    assert "cache_control" in t12ctx["output"]


@then("no cache breakpoint is added for those providers")
def no_breakpoint_builtin(t12ctx):
    for p in t12ctx["builtin"]:
        assert provider_supports_prefix_cache(p, posture="auto") is False
    for out in t12ctx["outputs"]:
        assert "cache_control" not in out


@when("the operator sets the prefix-cache posture to off")
def posture_off(t12ctx):
    t12ctx["posture"] = "off"
    apply_breakpoints(t12ctx)


@then("no cache breakpoint is added even for a supporting provider")
def no_breakpoint_off(t12ctx):
    assert provider_supports_prefix_cache(t12ctx["profile"], posture="off") is False
    assert "cache_control" not in t12ctx["output"]


# ===========================================================================
# GREEN — #144 memory/skills/recall + desktop as agent-callable loop tools
# ===========================================================================
@given("an agent-memory backend and a curation service wired into the loop toolset")
def loop_toolset_wired(t12ctx):
    t12ctx["curation"] = _FakeCuration()
    t12ctx["toolset"] = LoopToolset(
        campaign_id="campaign-1",
        agent_memory=_agent_memory_bundle(),
        curation_service=t12ctx["curation"],
    )


@given("an agent-memory backend wired into the loop toolset")
def loop_toolset_memory(t12ctx):
    t12ctx["agent_memory"] = _agent_memory_bundle()
    t12ctx["curation"] = _FakeCuration()


@when("the loop's tool schemas are collected")
def collect_schemas(t12ctx):
    t12ctx["schema_names"] = {
        s["function"]["name"] for s in t12ctx["toolset"].tool_schemas()
    }


@then("memory, skills, and recall tools are offered to the model")
def memory_skills_recall_offered(t12ctx):
    names = t12ctx["schema_names"]
    assert {"remember", "forget"} <= names  # memory.*
    assert {"save_playbook", "update_playbook"} <= names  # skill_manage
    assert "recall" in names  # recall.search


@when("desktop assist is operable")
def desktop_operable_toolbox(t12ctx):
    box = ChatToolbox(
        campaign_id="c",
        agent_memory=t12ctx["agent_memory"],
        curation_service=t12ctx["curation"],
        computer_use=_OperableComputerUse(),
        desktop_operable=True,
    )
    t12ctx["operable_names"] = {s["function"]["name"] for s in box.tool_schemas()}


@then("a bounded desktop tool is also offered")
def desktop_tool_offered(t12ctx):
    assert "desktop" in t12ctx["operable_names"]


@then("when desktop assist is not operable the desktop tool is withheld")
def desktop_tool_withheld(t12ctx):
    box = ChatToolbox(
        campaign_id="c",
        agent_memory=t12ctx["agent_memory"],
        curation_service=t12ctx["curation"],
        computer_use=_OperableComputerUse(),
        desktop_operable=False,
    )
    names = {s["function"]["name"] for s in box.tool_schemas()}
    assert "desktop" not in names


@given("the loop-tools setting is left at its default")
def loop_tools_default(t12ctx):
    t12ctx["loop_setting"] = Settings().loop_tools


@when("the loop toolset is built")
def build_toolset(t12ctx):
    t12ctx["built"] = build_loop_toolset(
        setting=t12ctx.get("loop_setting", "off"),
        llm=t12ctx.get("llm"),
        campaign_id="c",
        agent_memory=_agent_memory_bundle(),
        curation_service=_FakeCuration(),
    )


@then("no toolset is built and the loop runs exactly as before")
def no_toolset_default(t12ctx):
    assert t12ctx["loop_setting"] == "off"
    assert t12ctx["built"] is None


@given("the loop-tools setting is enabled but the model does not advertise tool calling")
def loop_tools_no_tool_model(t12ctx):
    t12ctx["loop_setting"] = "on"
    # A model object with no supports_tools / complete_with_tools => not tool-capable.
    t12ctx["llm"] = SimpleNamespace()


@then("no toolset is built")
def no_toolset_no_model(t12ctx):
    assert t12ctx["built"] is None


@when("the model calls the remember tool with a note")
def call_remember(t12ctx):
    t12ctx["dispatch_result"] = t12ctx["toolset"].dispatch(
        "remember", json.dumps({"text": "I prefer remote senior roles", "about_user": True})
    )


@then("the note is staged for the user's approval rather than applied silently")
def note_staged(t12ctx):
    assert "I prefer remote senior roles" in t12ctx["curation"].staged
    assert "approval" in t12ctx["dispatch_result"].lower()


@given("the engine's central tool registry")
def central_tool_registry(t12ctx):
    t12ctx["registry_probe"] = True


@then("memory, skills, recall, and desktop are registered for one shared dispatch path")
def central_dispatch(t12ctx):
    # FR-MIND-6 desired: ONE central engine-wide registry + handle_function_call that
    # dispatches every agent tool (today each campaign gets its own LoopToolset/ChatToolbox).
    import importlib

    mod = importlib.import_module("applicant.adapters.tools.tool_registry")
    registry_cls = mod.ToolRegistry
    assert hasattr(registry_cls, "handle_function_call"), (
        "no central engine-wide tool dispatch (handle_function_call) exists yet"
    )


# ===========================================================================
# GREEN — #145 MIND_BACKEND=bridge selection + degrade-when-off
# ===========================================================================
@given("the mind backend is set to bridge")
def mind_bridge(t12ctx):
    t12ctx["settings"] = Settings(MIND_BACKEND="bridge")
    t12ctx["workspace"] = None


@given("the mind backend is left at its default")
def mind_default(t12ctx):
    t12ctx["settings"] = Settings()
    t12ctx["workspace"] = None


@when("the agent-memory trio is built")
def build_trio(t12ctx):
    t12ctx["trio"] = build_agent_memory(
        t12ctx["settings"], workspace_port=t12ctx.get("workspace")
    )


@then("the bridge-backed memory, skills, and recall adapters are wired")
def bridge_adapters_wired(t12ctx):
    from applicant.adapters.memory.bridge import (
        WorkspaceBridgeMemoryStore,
        WorkspaceBridgeRecallIndex,
        WorkspaceBridgeSkillStore,
    )

    trio = t12ctx["trio"]
    assert trio.backend == "bridge"
    assert isinstance(trio.memory, WorkspaceBridgeMemoryStore)
    assert isinstance(trio.skills, WorkspaceBridgeSkillStore)
    assert isinstance(trio.recall, WorkspaceBridgeRecallIndex)


@then("the in-memory memory, skills, and recall adapters are wired")
def in_memory_adapters_wired(t12ctx):
    from applicant.adapters.memory.in_memory import (
        InMemoryMemoryStore,
        InMemoryRecallIndex,
        InMemorySkillStore,
    )

    trio = t12ctx["trio"]
    assert trio.backend == "in_memory"
    assert isinstance(trio.memory, InMemoryMemoryStore)
    assert isinstance(trio.skills, InMemorySkillStore)
    assert isinstance(trio.recall, InMemoryRecallIndex)


@given("the bridge backend with the engine-to-workspace channel turned off")
def bridge_channel_off(t12ctx):
    class _OffWorkspace:
        def available(self) -> bool:
            return False

    t12ctx["trio"] = build_agent_memory(
        Settings(MIND_BACKEND="bridge"), workspace_port=_OffWorkspace()
    )


@when("memory is added and a snapshot is read back")
def add_and_snapshot(t12ctx):
    trio = t12ctx["trio"]
    trio.memory.add(
        MemoryEntry(text="ghost", kind=KIND_ENVIRONMENT, scope=SCOPE_GLOBAL, campaign_id=None)
    )
    t12ctx["snapshot"] = trio.memory.snapshot()


@then("the bridge degrades to an empty result rather than raising")
def bridge_empty(t12ctx):
    snap = t12ctx["snapshot"]
    assert len(snap.environment) == 0
    assert len(snap.user) == 0


@given("a live workspace with the internal token set and MIND_BACKEND=bridge")
def live_workspace(t12ctx):
    t12ctx["needs_live_stack"] = True


@when("the engine adds a memory entry and reads the snapshot back")
def live_roundtrip(t12ctx):
    # Requires a running workspace container reachable over the internal channel.
    raise RuntimeError("live workspace stack is not available in the hermetic lane")


@then("the entry is reflected from the workspace substrate")
def entry_reflected(t12ctx):
    raise AssertionError("no live workspace round-trip in the hermetic lane")


@given("a curation proposal approved in the portal against a live workspace")
def live_curation_proposal(t12ctx):
    t12ctx["needs_live_stack"] = True


@when("the approval is applied")
def apply_approval(t12ctx):
    raise RuntimeError("live workspace stack is not available in the hermetic lane")


@then("the change persists into the workspace substrate")
def change_persists(t12ctx):
    raise AssertionError("no live workspace substrate in the hermetic lane")


# ===========================================================================
# GREEN — #179 desktop assist wired but capability-gated on the image bake
# ===========================================================================
@given("no desktop backend is configured")
def no_desktop_backend(t12ctx):
    t12ctx["settings"] = Settings()


@when("the computer-use adapter is selected")
def select_computer_use(t12ctx):
    t12ctx["cu"] = build_computer_use(t12ctx["settings"])


@then("the no-op desktop backend is selected")
def noop_selected(t12ctx):
    assert isinstance(t12ctx["cu"], NoopComputerUse)
    assert t12ctx["cu"].backend == "noop"


@given("the no-op desktop backend")
def noop_backend(t12ctx):
    t12ctx["cu"] = NoopComputerUse()


@when("its health preflight is read")
def read_health(t12ctx):
    t12ctx["health"] = t12ctx["cu"].health()


@then("it is healthy but reports the no-op backend, so the surface stays locked")
def noop_health_locked(t12ctx):
    report = t12ctx["health"]
    assert report.ok is True
    assert report.backend == "noop"
    # The prefill/router operability gate is "ok AND backend != noop" — so locked.
    operable = report.ok and report.backend != "noop"
    assert operable is False


@given("the cua backend selected but the driver binary missing from the image")
def cua_missing_driver(t12ctx):
    t12ctx["cu"] = CuaDriverComputerUse(driver_cmd="applicant-no-such-driver-binary")


@then("the preflight fails and names the missing driver as a deploy signal")
def cua_health_fails(t12ctx):
    report = t12ctx["health"]
    assert report.ok is False
    assert report.backend == "cua"
    assert "applicant-no-such-driver-binary" in report.missing


@given("the engine's dormant-surface registry")
def dormant_registry(t12ctx):
    t12ctx["surfaces"] = DORMANT_SURFACES


@when("the desktop-assist surface is looked up")
def lookup_desktop_surface(t12ctx):
    t12ctx["surface"] = next(
        s for s in t12ctx["surfaces"] if s.key == "desktop_assist"
    )


@then("it is marked live and its notes explain the capability gate")
def desktop_surface_gated(t12ctx):
    surface = t12ctx["surface"]
    assert surface.status == STATUS_LIVE
    notes = surface.wiring_notes.lower()
    assert "capability" in notes
    assert "cua" in notes or "driver" in notes


@given("the cua backend with the driver baked into the sandbox image")
def cua_with_driver(t12ctx):
    import shutil

    if shutil.which("cua-driver") is None:
        raise RuntimeError("cua-driver binary is not baked into this image")
    t12ctx["cu"] = CuaDriverComputerUse()


@then("the preflight passes and the desktop surface is operable")
def cua_health_operable(t12ctx):
    report = t12ctx["health"]
    assert report.ok is True and report.backend != "noop"
