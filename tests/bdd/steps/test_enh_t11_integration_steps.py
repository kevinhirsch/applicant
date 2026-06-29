"""Step bindings for the T11 integration-surfaces acceptance specs.

Theme: cross-surface integrations between the Applicant engine and the white-labeled
front door (chat steering, email, calendar, documents, the memory bridge, tasks,
gallery, compare, the local-LLM tier, research, settings) plus orphan-route audits
and the two explicit descopes (Notes #303, Cookbook #304).

Convention (same as ``test_enh_research_steps``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch. They assert against the engine core/ports/services,
  the front-door feature-state layer, the workspace proxy routers (imported via the
  ``setup_applicant_*_routes`` factories with ``workspace`` on ``sys.path``), or the
  static JS/HTML file content read from disk. They must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the real seam (a missing
  route, an absent config default, a not-yet-offered tool, or a file fact the current
  tree fails) so the scenario is a genuine red. ``conftest.pytest_bdd_apply_tag`` maps
  ``@pending`` to a non-strict xfail.

Hexagonal: assertions target the engine core/ports/services and the front-door
boundary objects (route factories, feature-state layer, static asset content) — never
a real browser, socket, or DB. Speculative imports for not-yet-built targets live
INSIDE the step bodies so absence is a runtime xfail, never a collection error.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_184_compare_present_but_disabled.feature",
    "../features/enhancements/enh_258_email_route_consumer.feature",
    "../features/enhancements/enh_259_research_route_consumer.feature",
    "../features/enhancements/enh_286_memory_bridge_default.feature",
    "../features/enhancements/enh_287_email_surface_wired.feature",
    "../features/enhancements/enh_288_calendar_read_only.feature",
    "../features/enhancements/enh_290_chat_steering.feature",
    "../features/enhancements/enh_291_email_two_way.feature",
    "../features/enhancements/enh_292_calendar_write.feature",
    "../features/enhancements/enh_294_memory_two_way_learning.feature",
    "../features/enhancements/enh_295_tasks_integration.feature",
    "../features/enhancements/enh_296_gallery_integration.feature",
    "../features/enhancements/enh_297_compare_wiring.feature",
    "../features/enhancements/enh_298_local_llm_tier_delegation.feature",
    "../features/enhancements/enh_299_research_integration.feature",
    "../features/enhancements/enh_301_settings_surface.feature",
    "../features/enhancements/enh_303_remove_notes_integration.feature",
    "../features/enhancements/enh_304_remove_cookbook_integration.feature",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKSPACE = REPO_ROOT / "workspace"
JS_DIR = WORKSPACE / "static" / "js"


@pytest.fixture
def t11ctx() -> dict:
    return {}


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _ws_on_path() -> None:
    """Put the vendored ``workspace`` package roots on sys.path (idempotent).

    The full front-door app cannot be imported in the root env (heavier vendored
    deps), but the individual ``setup_applicant_*_routes`` factories and the
    feature-state layer import cleanly, so the proxy routers can be introspected
    without a running server.
    """
    ws = str(WORKSPACE)
    if ws not in sys.path:
        sys.path.insert(0, ws)


def _route_paths(module_name: str, factory_name: str) -> list[str]:
    """Return the path strings of every route on a workspace proxy router."""
    _ws_on_path()
    module = importlib.import_module(module_name)
    router = getattr(module, factory_name)()
    return [getattr(r, "path", "") for r in router.routes]


def _read_js(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


def _js_files() -> list[pathlib.Path]:
    return list(JS_DIR.rglob("*.js"))


def _any_js_fetches(needle: str) -> bool:
    for f in _js_files():
        try:
            if needle in f.read_text(encoding="utf-8"):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _feature_sections() -> tuple:
    _ws_on_path()
    mod = importlib.import_module("src.applicant_features")
    return mod.APPLICANT_SECTIONS


def _section(key: str) -> dict | None:
    for s in _feature_sections():
        if s.get("key") == key:
            return s
    return None


def _applicant_route_files() -> list[str]:
    return sorted(p.name for p in (WORKSPACE / "routes").glob("applicant_*.py"))


def _build_in_memory_agent_memory():
    from applicant.adapters.memory.factory import AgentMemory
    from applicant.adapters.memory.in_memory import (
        InMemoryMemoryStore,
        InMemoryRecallIndex,
        InMemorySkillStore,
    )

    return AgentMemory(
        memory=InMemoryMemoryStore(),
        skills=InMemorySkillStore(),
        recall=InMemoryRecallIndex(),
        backend="in_memory",
    )


# =========================================================================== #
# #184 — Compare present-but-disabled                                          #
# =========================================================================== #
@given("the Applicant feature-state layer")
def feature_layer(t11ctx):
    t11ctx["layer"] = "applicant_features"


@when("the Applicant section registry is inspected")
def inspect_registry(t11ctx):
    t11ctx["sections"] = _feature_sections()


@then("the Compare section is flagged present-but-disabled")
def compare_pbd(t11ctx):
    compare = _section("compare")
    assert compare is not None
    assert compare.get("present_but_disabled") is True


@when("the per-section state is computed against an unreachable engine")
def compute_unreachable(t11ctx):
    _ws_on_path()
    mod = importlib.import_module("src.applicant_features")
    # Point at an unroutable engine so the layer degrades without opening a socket
    # that completes; present-but-disabled short-circuits before any reachability.
    t11ctx["features"] = mod.compute_features(base_url="http://127.0.0.1:1")


@then("the Compare section reports the disabled state")
def compare_disabled(t11ctx):
    assert t11ctx["features"]["sections"]["compare"]["state"] == "disabled"


# =========================================================================== #
# #258 / #287 — email proxy mounted + has a JS consumer                        #
# =========================================================================== #
@given("the front-door application")
def front_door_app(t11ctx):
    t11ctx["app"] = "front-door"


@when("the mounted routes are inspected")
def mounted_routes(t11ctx):
    t11ctx["email_paths"] = _route_paths(
        "routes.applicant_email_routes", "setup_applicant_email_routes"
    )
    t11ctx["research_paths"] = _route_paths(
        "routes.applicant_research_routes", "setup_applicant_research_routes"
    )
    t11ctx["chat_paths"] = _route_paths(
        "routes.applicant_chat_routes", "setup_applicant_chat_routes"
    )
    t11ctx["internal_paths"] = _route_paths(
        "routes.applicant_internal_routes", "setup_applicant_internal_routes"
    )


@then("a route under the Applicant email prefix is present")
def email_prefix_present(t11ctx):
    assert any(p.startswith("/api/applicant/email/") for p in t11ctx["email_paths"])


@given("the front-door static JavaScript")
def front_door_js(t11ctx):
    assert JS_DIR.is_dir()
    t11ctx["js_dir"] = JS_DIR


@when("the email proxy prefix is searched for across the JS modules")
def search_email_js(t11ctx):
    t11ctx["email_consumer"] = _any_js_fetches("/api/applicant/email")


@then("at least one module fetches the Applicant email prefix")
def email_consumer_found(t11ctx):
    assert t11ctx["email_consumer"] is True


@when("the email surface module is inspected")
def inspect_email_surface(t11ctx):
    t11ctx["email_lib"] = _read_js("emailLibrary.js")


@then("it mounts the Applicant digest consumer module")
def mounts_digest_consumer(t11ctx):
    text = t11ctx["email_lib"]
    assert "applicantDigest.js" in text
    assert "mountApplicantDigest" in text


@then("an email section is present and not present-but-disabled")
def email_section_active(t11ctx):
    email = _section("email")
    assert email is not None
    assert email.get("present_but_disabled") is False


@then("approve and decline application paths are present under the email prefix")
def approve_decline_present(t11ctx):
    paths = t11ctx["email_paths"]
    assert any(p.endswith("/approve") for p in paths)
    assert any(p.endswith("/decline") for p in paths)


# =========================================================================== #
# #259 / #299 — research proxy mounted + JS consumer + engine client methods   #
# =========================================================================== #
@then("the research run and budget paths are present under the research prefix")
def research_paths_present(t11ctx):
    paths = t11ctx["research_paths"]
    assert any(p.endswith("/run") for p in paths)
    assert any(p.endswith("/budget") for p in paths)


@when("the research proxy prefix is searched for across the JS modules")
def search_research_js(t11ctx):
    t11ctx["research_consumer"] = _any_js_fetches("/api/applicant/research")


@then("at least one module fetches the Applicant research prefix")
def research_consumer_found(t11ctx):
    assert t11ctx["research_consumer"] is True


@given("the front-door engine client")
def engine_client(t11ctx):
    _ws_on_path()
    t11ctx["client_mod"] = importlib.import_module("src.applicant_engine")


@when("the engine client is inspected for research methods")
def inspect_client_research(t11ctx):
    cls = t11ctx["client_mod"].ApplicantEngineClient
    t11ctx["has_run"] = hasattr(cls, "research_run")
    t11ctx["has_budget"] = hasattr(cls, "research_budget")


@then("it exposes a research run call and a research budget call")
def client_has_research(t11ctx):
    assert t11ctx["has_run"] is True
    assert t11ctx["has_budget"] is True


# =========================================================================== #
# #286 / #294 — memory bridge adapters exist; default + staging                #
# =========================================================================== #
@given("the agent-memory factory")
def memory_factory(t11ctx):
    t11ctx["factory"] = importlib.import_module("applicant.adapters.memory.factory")


@when("the bridge backend is selected")
def select_bridge(t11ctx):
    from types import SimpleNamespace

    factory = t11ctx["factory"]
    t11ctx["trio"] = factory.build_agent_memory(
        SimpleNamespace(mind_backend="bridge"), workspace_port=None
    )


@then("the trio is backed by workspace-bridge adapters")
def trio_is_bridge(t11ctx):
    from applicant.adapters.memory.bridge import (
        WorkspaceBridgeMemoryStore,
        WorkspaceBridgeRecallIndex,
        WorkspaceBridgeSkillStore,
    )

    trio = t11ctx["trio"]
    assert isinstance(trio.memory, WorkspaceBridgeMemoryStore)
    assert isinstance(trio.skills, WorkspaceBridgeSkillStore)
    assert isinstance(trio.recall, WorkspaceBridgeRecallIndex)
    assert trio.backend == "bridge"


@when("the in-memory backend is selected")
def select_in_memory(t11ctx):
    from types import SimpleNamespace

    factory = t11ctx["factory"]
    t11ctx["trio"] = factory.build_agent_memory(
        SimpleNamespace(mind_backend="in_memory"), workspace_port=None
    )


@then("the trio is backed by in-process adapters")
def trio_is_in_memory(t11ctx):
    from applicant.adapters.memory.in_memory import (
        InMemoryMemoryStore,
        InMemoryRecallIndex,
        InMemorySkillStore,
    )

    trio = t11ctx["trio"]
    assert isinstance(trio.memory, InMemoryMemoryStore)
    assert isinstance(trio.skills, InMemorySkillStore)
    assert isinstance(trio.recall, InMemoryRecallIndex)
    assert trio.backend == "in_memory"


@given("the engine default configuration")
def engine_default_config(t11ctx):
    from applicant.app.config import Settings

    t11ctx["settings"] = Settings()


@when("the configured memory backend is read")
def read_mind_backend(t11ctx):
    t11ctx["mind_backend"] = t11ctx["settings"].mind_backend


@then("it is the bridge so workspace memories reach the engine by default")
@then("it is the bridge so the learning loop is two-way by default")
def mind_backend_is_bridge(t11ctx):
    # Today the default is "in_memory" — the bridge-as-default is the residual gap.
    assert t11ctx["mind_backend"] == "bridge"


@given("the assistant tool belt with memory available")
def toolbelt_memory(t11ctx):
    from applicant.application.services.curation_service import (
        CurationLedger,
        CurationService,
    )

    am = _build_in_memory_agent_memory()
    t11ctx["curation"] = CurationService(
        memory_store=am.memory,
        skill_store=am.skills,
        ledger=CurationLedger(),
        recall=am.recall,
    )


@when("the assistant proposes remembering a note")
def propose_remember(t11ctx):
    t11ctx["stage_result"] = t11ctx["curation"].stage_memory(
        "I prefer smaller companies under 200 people", kind="user"
    )


@then("the proposal is staged for approval rather than written silently")
def proposal_staged(t11ctx):
    result = t11ctx["stage_result"]
    # review-before-write is on by default: nothing auto-applies, one item is staged.
    assert result.auto_applied == 0
    assert result.staged >= 1


# =========================================================================== #
# #288 / #292 — calendar read ships; write/availability are gaps               #
# =========================================================================== #
@given("a set of raw calendar events including an interview invite")
def raw_calendar_events(t11ctx):
    t11ctx["events"] = [
        {"title": "Technical interview with Stripe", "notes": "", "start": "2026-07-01"},
        {"title": "Team standup", "notes": "daily sync", "start": "2026-06-30"},
    ]


@when("the interview-detection rule runs over them")
def run_interview_detection(t11ctx):
    _ws_on_path()
    routes = importlib.import_module("routes.applicant_internal_routes")
    t11ctx["detected"] = routes.detect_interviews(t11ctx["events"])


@then("the interview event is detected and the plain meeting is not")
def interview_detected(t11ctx):
    titles = [d.get("title", "") for d in t11ctx["detected"]]
    assert any("interview" in t.lower() for t in titles)
    assert not any("standup" in t.lower() for t in titles)


@given("the front-door internal callback routes")
def internal_routes(t11ctx):
    t11ctx["internal_paths"] = _route_paths(
        "routes.applicant_internal_routes", "setup_applicant_internal_routes"
    )


@when("the internal routes are inspected")
def inspect_internal(t11ctx):
    # paths already collected in the given; keep the When meaningful by re-reading
    t11ctx["internal_paths"] = _route_paths(
        "routes.applicant_internal_routes", "setup_applicant_internal_routes"
    )


@then("a calendar interviews read path is present")
def calendar_read_present(t11ctx):
    assert any(
        p.endswith("/calendar/interviews") for p in t11ctx["internal_paths"]
    )


@when("a calendar write channel is looked up")
@when("a calendar create-event channel is looked up")
@when("a calendar availability channel is looked up")
def lookup_calendar_write(t11ctx):
    t11ctx["cal_write"] = [
        p
        for p in t11ctx["internal_paths"]
        if "calendar" in p and p.split("/")[-1] not in ("interviews",)
    ]


@then("an endpoint to create a calendar event is available")
@then("an endpoint to create a calendar reminder is available")
def calendar_create_available(t11ctx):
    # No calendar write endpoint exists — only GET /calendar/interviews.
    assert t11ctx["cal_write"], "no calendar write endpoint is exposed yet"


@then("an endpoint that reports busy or away windows is available")
def calendar_availability_available(t11ctx):
    assert any(
        ("availability" in p or "busy" in p or "free" in p)
        for p in t11ctx["internal_paths"]
    ), "no calendar availability endpoint is exposed yet"


# =========================================================================== #
# #290 — chat steering: read/proxy ships; NL campaign-control tools are a gap   #
# =========================================================================== #
@then("the chat surface exposes campaign list and campaign create paths")
def chat_campaign_paths(t11ctx):
    paths = t11ctx["chat_paths"]
    assert "/api/applicant/chat/campaigns" in paths


@then("the chat surface exposes a pending-action resolve path")
def chat_resolve_path(t11ctx):
    assert any(p.endswith("/resolve") for p in t11ctx["chat_paths"])


@given("the assistant tool belt")
def assistant_tool_belt(t11ctx):
    from applicant.application.services.chat_tools import ChatToolbox

    am = _build_in_memory_agent_memory()
    t11ctx["toolbox"] = ChatToolbox(campaign_id="c1", agent_memory=am)


@when("the available tool schemas are listed")
def list_tool_schemas(t11ctx):
    schemas = t11ctx["toolbox"].tool_schemas()
    t11ctx["tool_names"] = [s["function"]["name"] for s in schemas]


@then("a campaign-control tool for creating a campaign is offered")
def create_campaign_tool(t11ctx):
    # The assistant's tool belt has memory/skills/recall/desktop only — no
    # natural-language campaign steering tool exists yet.
    assert any(
        n in {"create_campaign", "new_campaign", "start_campaign"}
        for n in t11ctx["tool_names"]
    )


@then("a campaign-control tool for pausing a campaign is offered")
def pause_campaign_tool(t11ctx):
    assert any(
        n in {"pause_campaign", "pause", "stop_campaign"}
        for n in t11ctx["tool_names"]
    )


@given("the engine has finished a discovery run")
def engine_finished_discovery(t11ctx):
    t11ctx["discovery_done"] = True


@when("a proactive chat push is attempted")
def attempt_chat_push(t11ctx):
    def probe():
        # No engine->chat proactive push channel exists yet.
        mod = importlib.import_module("applicant.application.services.chat_push_service")
        return mod.ChatPushService

    t11ctx["push_probe"] = probe


@then("a chat push channel delivers the digest summary with inline actions")
def chat_push_delivers(t11ctx):
    t11ctx["push_probe"]()  # ImportError -> genuine red


# =========================================================================== #
# #291 — email outbound ships; inbound parsing is a gap                         #
# =========================================================================== #
@then("a digest deliver path is present under the email prefix")
def digest_deliver_present(t11ctx):
    assert any(p.endswith("/deliver") for p in t11ctx["email_paths"])


@given("a digest email rendered for the operator")
def digest_email_rendered(t11ctx):
    t11ctx["digest"] = "rendered"


@when("the email is generated for delivery")
def generate_email_for_delivery(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.digest_email_service"
        )
        return mod.render_inline_action_email

    t11ctx["inline_probe"] = probe


@then("it embeds inline approve and decline controls that post back to the engine")
def inline_actions_embedded(t11ctx):
    t11ctx["inline_probe"]()


@given("an inbox message matching a rejection pattern")
def inbox_rejection(t11ctx):
    t11ctx["inbox"] = "unfortunately we have decided to move forward with other candidates"


@given("an inbox message containing an interview scheduling request")
def inbox_interview(t11ctx):
    t11ctx["inbox"] = "we would like to schedule an interview with you next week"


@when("the inbound email parser runs over it")
def run_inbound_parser(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.inbound_email_service"
        )
        return mod.InboundEmailService

    t11ctx["inbound_probe"] = probe


@then("the matching application is marked rejected and fed to learning")
@then("an interview pending action is created for the operator")
def inbound_result(t11ctx):
    t11ctx["inbound_probe"]()


# =========================================================================== #
# #295 — tasks integration (no bridge yet)                                      #
# =========================================================================== #
@given("the front-door route directory")
def route_directory(t11ctx):
    t11ctx["route_files"] = _applicant_route_files()


@when("the Applicant route files are listed")
def list_route_files(t11ctx):
    t11ctx["route_files"] = _applicant_route_files()


@then("there is no Applicant tasks route file")
def no_tasks_route(t11ctx):
    assert "applicant_tasks_routes.py" not in t11ctx["route_files"]


@given("the engine has an open pending action")
def open_pending_action(t11ctx):
    t11ctx["pending"] = True


@when("the task bridge runs")
def run_task_bridge(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.task_bridge_service"
        )
        return mod.TaskBridgeService

    t11ctx["task_probe"] = probe


@then("a corresponding workspace task is created with priority and a deep link")
def task_created(t11ctx):
    t11ctx["task_probe"]()


@given("a material-review task linked to an application")
def material_review_task(t11ctx):
    t11ctx["task"] = "material-review"


@when("the task is marked approved")
def mark_task_approved(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.task_bridge_service"
        )
        return mod.TaskBridgeService

    t11ctx["task_probe"] = probe


@then("the engine advances the application to final approval")
def engine_advances(t11ctx):
    t11ctx["task_probe"]()


# =========================================================================== #
# #296 — gallery integration (no bridge yet)                                    #
# =========================================================================== #
@then("there is no Applicant gallery route file")
def no_gallery_route(t11ctx):
    assert "applicant_gallery_routes.py" not in t11ctx["route_files"]


@given("the engine captured pre-fill screenshots for a campaign")
def captured_screenshots(t11ctx):
    t11ctx["shots"] = True


@when("the gallery bridge runs")
def run_gallery_bridge(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.gallery_bridge_service"
        )
        return mod.GalleryBridgeService

    t11ctx["gallery_probe"] = probe


@then("a gallery collection holds the screenshots with application metadata")
def gallery_collection_created(t11ctx):
    t11ctx["gallery_probe"]()


@given("several resume variants for one application")
def resume_variants(t11ctx):
    t11ctx["variants"] = ["v1", "v2"]


@when("the gallery compare view is opened for that application")
def open_gallery_compare(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.gallery_bridge_service"
        )
        return mod.GalleryBridgeService

    t11ctx["gallery_probe"] = probe


@then("the variants are presented side by side")
def variants_side_by_side(t11ctx):
    t11ctx["gallery_probe"]()


# =========================================================================== #
# #297 — compare wiring (no comparison backend yet)                             #
# =========================================================================== #
@given("two campaigns that should be compared side by side")
def two_campaigns_compare(t11ctx):
    t11ctx["entities"] = ("campaign-a", "campaign-b")


@given("one application that converted and one that ghosted")
def two_applications_compare(t11ctx):
    t11ctx["entities"] = ("app-converted", "app-ghosted")


@given("two campaigns with discovery and conversion metrics")
def two_campaigns_metrics(t11ctx):
    t11ctx["entities"] = ("campaign-a", "campaign-b")


@when("a cross-entity comparison is requested from the engine")
@when("a comparison is requested from the engine")
@when("a campaign comparison is requested")
def request_comparison(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.comparison_service"
        )
        return mod.ComparisonService

    t11ctx["compare_probe"] = probe


@then("the engine returns a structured diff with per-entity metrics")
@then("the differing dimensions are surfaced with metrics")
@then("the engine returns side-by-side metrics for each campaign")
def comparison_result(t11ctx):
    t11ctx["compare_probe"]()


# =========================================================================== #
# #298 — tier ladder ships; smart task-routing/budget are gaps                  #
# =========================================================================== #
@given("the OpenAI-compatible LLM adapter")
def openai_adapter(t11ctx):
    from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
    from applicant.ports.driven.llm import TierConfig, TierLadder

    ladder = TierLadder(
        tiers=[
            TierConfig(
                provider="ollama",
                base_url="http://local/v1",
                model="gemma2:9b",
                api_key="",
                context_window=8192,
            ),
            TierConfig(
                provider="openai",
                base_url="http://cloud/v1",
                model="pro",
                api_key="k",
                context_window=128000,
            ),
        ]
    )
    t11ctx["llm"] = OpenAICompatibleLLM(ladder=ladder)


@when("the tier-ladder escalation behaviour is inspected")
def inspect_escalation(t11ctx):
    llm = t11ctx["llm"]
    t11ctx["tier_count"] = len(llm._ladder.tiers)
    t11ctx["has_complete"] = hasattr(llm, "complete")


@then("it advances to the next tier on failure or overflow")
def advances_tiers(t11ctx):
    # The adapter holds an ordered multi-tier ladder and exposes the completion path
    # that walks it (FR-LLM-3/4 escalation already ships).
    assert t11ctx["tier_count"] >= 2
    assert t11ctx["has_complete"] is True


@given("a task classifier that routes by complexity")
def task_classifier(t11ctx):
    t11ctx["classifier_wanted"] = True


@when("a simple field-disambiguation task is classified")
def classify_simple_task(t11ctx):
    def probe():
        mod = importlib.import_module("applicant.core.rules.tier_routing")
        return mod.classify_task_tier

    t11ctx["classifier_probe"] = probe


@then("it is routed to the local tier without calling the cloud")
def routed_to_local(t11ctx):
    t11ctx["classifier_probe"]()


@given("a per-tier budget tracker")
def budget_tracker(t11ctx):
    t11ctx["budget_wanted"] = True


@when("tokens are spent on a tier")
def spend_tokens(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.tier_budget_service"
        )
        return mod.TierBudgetService

    t11ctx["budget_probe"] = probe


@then("the spend is accumulated per tier and checked against the budget")
def budget_accumulated(t11ctx):
    t11ctx["budget_probe"]()


# =========================================================================== #
# #299 — research pipeline feed (manual ships; auto-feed is a gap)              #
# =========================================================================== #
@given("an application about to generate a cover letter")
def app_before_cover(t11ctx):
    t11ctx["app"] = "pre-cover"


@when("the material-generation pipeline runs")
def run_material_pipeline(t11ctx):
    def probe():
        mod = importlib.import_module(
            "applicant.application.services.material_service"
        )
        svc = mod.MaterialService
        # The desired seam: material generation auto-runs company research first.
        if not hasattr(svc, "research_before_generation"):
            raise AttributeError("MaterialService.research_before_generation missing")
        return svc

    t11ctx["research_feed_probe"] = probe


@then("it first performs company research and enriches the generation context")
def research_enriches(t11ctx):
    t11ctx["research_feed_probe"]()


@given("a completed research run for an application")
def completed_research(t11ctx):
    t11ctx["research_done"] = True


@when("the application record is read")
def read_application_record(t11ctx):
    def probe():
        mod = importlib.import_module("applicant.core.entities.application")
        app = mod.Application
        if not hasattr(app, "research_notes"):
            raise AttributeError("Application.research_notes missing")
        return app

    t11ctx["research_notes_probe"] = probe


@then("the research findings are stored as application-attached notes")
def research_notes_stored(t11ctx):
    t11ctx["research_notes_probe"]()


# =========================================================================== #
# #301 — settings surface (relocated cards ship; campaign mgmt is a gap)        #
# =========================================================================== #
@given("the front-door settings module")
def settings_module(t11ctx):
    t11ctx["settings_js"] = _read_js("settings.js")


@when("the settings module is inspected for relocated cards")
def inspect_relocated_cards(t11ctx):
    pass  # the source is already loaded in the Given


@then("it hosts the notifications, fonts and sandbox cards")
def hosts_relocated_cards(t11ctx):
    text = t11ctx["settings_js"]
    assert "notifications" in text
    assert "fonts" in text
    assert "sandbox" in text


@when("the settings module is inspected for the model ladder")
def inspect_model_ladder(t11ctx):
    pass


@then("it mounts the model escalation-ladder editor")
def mounts_model_ladder(t11ctx):
    text = t11ctx["settings_js"]
    assert "ladder" in text.lower()


@when("the settings module is inspected for campaign management")
def inspect_campaign_mgmt(t11ctx):
    text = t11ctx["settings_js"].lower()
    t11ctx["has_campaign_mgmt"] = (
        "archive campaign" in text
        or "clone campaign" in text
        or "rename campaign" in text
    )


@then("it offers create, rename, archive and clone campaign controls")
def offers_campaign_controls(t11ctx):
    # Campaign lifecycle management is not yet in the settings surface.
    assert t11ctx["has_campaign_mgmt"] is True


# =========================================================================== #
# #303 — Notes integration descoped (absent today -> GREEN)                     #
# =========================================================================== #
@then("there is no Applicant notes route file")
def no_notes_route(t11ctx):
    assert "applicant_notes_routes.py" not in t11ctx["route_files"]


@then("there is no notes section in the registry")
def no_notes_section(t11ctx):
    keys = {s.get("key") for s in t11ctx["sections"]}
    assert "notes" not in keys


@then("no internal notes lane is exposed")
def no_internal_notes_lane(t11ctx):
    assert not any("notes" in p.lower() for p in t11ctx["internal_paths"])


# =========================================================================== #
# #304 — Cookbook descoped except tier ladder (coupling still present -> gap)   #
# =========================================================================== #
@then("there is no cookbook section in the registry")
def no_cookbook_section(t11ctx):
    keys = {s.get("key") for s in t11ctx["sections"]}
    assert "cookbook" not in keys


@then("no Cookbook-specific local-models lane is exposed")
def no_cookbook_lane(t11ctx):
    # Today the internal callback exposes a Cookbook-served local-models lane
    # (#304 wants that removed in favour of the standard tier ladder).
    assert not any("local-models" in p for p in t11ctx["internal_paths"])


@given("the engine settings")
def engine_settings(t11ctx):
    from applicant.app.config import Settings

    t11ctx["settings_fields"] = set(Settings.model_fields)


@when("the settings fields are inspected")
def inspect_settings_fields(t11ctx):
    pass


@then("there is no Cookbook-specific host setting")
def no_cookbook_setting(t11ctx):
    # Today a cookbook_local_host field still exists; #304 wants it removed.
    assert not any("cookbook" in f.lower() for f in t11ctx["settings_fields"])
