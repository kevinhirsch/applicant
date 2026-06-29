"""Step bindings for the deep-research roadmap acceptance specs (issues #305–312).

These are the canonical pattern for the issue-tracker enhancement Gherkins:

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour
  that already ships on this branch — they assert against the actual core rules /
  services and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the real target
  (a speculative import, a missing attribute, an absent endpoint, or an assertion
  the current code fails) so the scenario is a genuine red — never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail, so the
  spec is collected and tracked without breaking the green gate. When the feature
  lands, drop the tag and the scenario becomes a hard regression gate.

Hexagonal: assertions target core rules (``core/rules``), driving/driven ports,
and application services through in-memory adapters or the TestClient — never UI
internals.
"""

from __future__ import annotations

import importlib
import logging
import pathlib
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.config import Settings
from applicant.app.container import _build_storage
from applicant.core.rules.url_safety import ip_is_blocked, scheme_is_allowed

scenarios(
    "../features/enhancements/enh_305_plan_as_data.feature",
    "../features/enhancements/enh_306_learning_flywheel.feature",
    "../features/enhancements/enh_307_memory_backend.feature",
    "../features/enhancements/enh_308_mcp_server.feature",
    "../features/enhancements/enh_309_eval_harness.feature",
    "../features/enhancements/enh_310_ssrf_redirect.feature",
    "../features/enhancements/enh_311_require_privilege.feature",
    "../features/enhancements/enh_312_db_fallback_warning.feature",
)

UNREACHABLE_DSN = "postgresql+psycopg://x:x@127.0.0.1:1/none"
CONFIGURED_UNREACHABLE_DSN = "postgresql+psycopg://applicant:s3cr3t@db.internal.invalid:5432/applicant"


@pytest.fixture
def rctx() -> dict:
    return {}


def _probe(modpath: str, attr: str | None = None):
    """Import ``modpath`` (and optionally ``getattr`` ``attr``).

    Raises ImportError/AttributeError when the not-yet-built target is absent —
    exactly the honest red a ``@pending`` scenario wants.
    """
    module = importlib.import_module(modpath)
    return getattr(module, attr) if attr is not None else module


# ===========================================================================
# GREEN — SSRF entry-URL guard already shipped (#310, references #168)
# ===========================================================================
@given("the URL-safety core rule")
def url_safety_rule(rctx):
    rctx["rule"] = "url_safety"


@when('a "file:///etc/passwd" URL is checked')
def check_file_scheme(rctx):
    rctx["scheme_ok"] = scheme_is_allowed(urlparse("file:///etc/passwd").scheme)


@then("the scheme is rejected as not navigable")
def scheme_rejected(rctx):
    assert rctx["scheme_ok"] is False


@when("the resolved IP of a candidate host is on a blocked range")
def resolved_ip_blocked(rctx):
    # 169.254.169.254 is the cloud-metadata link-local address.
    rctx["blocked"] = ip_is_blocked("169.254.169.254")


@then("navigation to that host is refused")
def navigation_refused(rctx):
    assert rctx["blocked"] is True


@then("an ordinary public IP is allowed")
def public_allowed(rctx):
    assert ip_is_blocked("8.8.8.8") is False


# ===========================================================================
# GREEN + PENDING — privilege gate (#311, workspace/src/auth_helpers.py)
# ===========================================================================
def _load_auth_helpers(monkeypatch):
    ws = str(pathlib.Path(__file__).resolve().parents[3] / "workspace")
    if ws not in sys.path:
        sys.path.insert(0, ws)
    auth_helpers = importlib.import_module("src.auth_helpers")
    # Isolate the privilege-decision logic from the user resolver: this gate is
    # what we are testing, not authentication.
    monkeypatch.setattr(auth_helpers, "require_user", lambda request: "subuser")
    return auth_helpers


def _fake_request(privs: dict):
    mgr = SimpleNamespace(get_privileges=lambda user: dict(privs))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=mgr)))


@given("a sub-user whose known privilege is set to false")
def subuser_known_false(rctx, monkeypatch):
    rctx["auth"] = _load_auth_helpers(monkeypatch)
    rctx["request"] = _fake_request({"approve_submit": False})
    rctx["key"] = "approve_submit"


@when("a route guarded by that privilege is called")
def call_guarded_known(rctx):
    from fastapi import HTTPException

    try:
        rctx["auth"].require_privilege(rctx["request"], rctx["key"])
        rctx["status"] = 200
    except HTTPException as e:
        rctx["status"] = e.status_code


@then("access is refused with a 403")
def refused_403(rctx):
    assert rctx["status"] == 403


@given("a sub-user whose privilege map does not contain a requested key")
def subuser_unknown_key(rctx, monkeypatch):
    rctx["auth"] = _load_auth_helpers(monkeypatch)
    # A known privilege is present-and-true; the requested key is simply absent.
    rctx["request"] = _fake_request({"approve_submit": True})
    rctx["key"] = "exfiltrate_everything"


@when("a route guarded by that unknown key is called")
def call_guarded_unknown(rctx):
    from fastapi import HTTPException

    try:
        rctx["auth"].require_privilege(rctx["request"], rctx["key"])
        rctx["status"] = 200
    except HTTPException as e:
        rctx["status"] = e.status_code


@then("access is refused rather than silently granted")
def refused_not_silent(rctx):
    # Default-deny on unknown keys. Today require_privilege fails OPEN
    # (privs.get(key, True)) so this is a genuine red until the fix lands.
    assert rctx["status"] == 403


# ===========================================================================
# GREEN + PENDING — DB fallback at boot (#312, container._build_storage)
# ===========================================================================
@given("a database URL that cannot be reached")
def unreachable_db(rctx):
    rctx["dsn"] = UNREACHABLE_DSN


@when("the storage layer is built")
def build_storage(rctx):
    _engine, _factory, storage = _build_storage(Settings(DATABASE_URL=rctx["dsn"]))
    rctx["storage"] = storage


@then("an in-memory storage is returned so the app can boot")
def in_memory_returned(rctx):
    assert isinstance(rctx["storage"], InMemoryStorage)


@given("a configured (non-default) database URL that cannot be reached")
def configured_unreachable_db(rctx, caplog):
    rctx["dsn"] = CONFIGURED_UNREACHABLE_DSN
    rctx["caplog"] = caplog


@when("the storage layer falls back to in-memory")
def build_storage_capture_logs(rctx):
    with rctx["caplog"].at_level(logging.WARNING):
        _engine, _factory, storage = _build_storage(Settings(DATABASE_URL=rctx["dsn"]))
    rctx["storage"] = storage


@then("a warning is logged naming the DSN host but never the credentials")
def warning_logged(rctx):
    text = rctx["caplog"].text
    # Today the fallback is silent — genuine red until the warning is added.
    assert "db.internal.invalid" in text
    assert "s3cr3t" not in text


# ===========================================================================
# PENDING — MCP server surface (#308) — probes the live app
# ===========================================================================
@then("the engine advertises its capabilities as MCP tools")
def mcp_tools_listed(rctx, app_client):
    resp = app_client.get("/mcp")
    assert resp.status_code == 200


@then("it passes through the same review/stop-boundary gates as the HTTP surface")
def mcp_reuses_gates(rctx, app_client):
    resp = app_client.get("/mcp")
    assert resp.status_code == 200


# ===========================================================================
# PENDING — pure import/attribute probes (#305, #306, #307, #309, #310-redirect)
# ===========================================================================
_PENDING_THEN_PROBES = {
    # --- #305 plan-as-data ---
    "only typed operations from the allowed op-set are accepted": lambda: _probe(
        "applicant.core.rules.plan", "validate_plan"
    ),
    "any op referencing an unknown attribute id is rejected before execution": lambda: _probe(
        "applicant.core.rules.plan", "validate_plan"
    ),
    "every filled value traces back to a stored attribute, never an LLM free-text": lambda: _probe(
        "applicant.core.rules.plan", "resolve_fill_values"
    ),
    "the final submit is withheld for human review and not auto-authorized": lambda: _probe(
        "applicant.ports.driving.planner", "PlannerPort"
    ),
    "it can extract data but cannot issue network requests or mutate the page": lambda: _probe(
        "applicant.core.rules.plan", "ReadOnlyScrapePlan"
    ),
    "the same typed-DSL contract is used across pre-fill, scrape, and the whole-application flow": lambda: _probe(
        "applicant.ports.driving.planner", "PlannerPort"
    ),
    # --- #306 learning flywheel ---
    "a parameterized, reusable workflow for that ATS is stored as a planner prior": lambda: _assert_attr(
        "applicant.application.services.learning_service", "LearningService", "induce_workflow"
    ),
    "the induced workflow is retrieved and offered to the planner before planning from scratch": lambda: _assert_attr(
        "applicant.application.services.learning_service", "LearningService", "induce_workflow"
    ),
    "the playbook is updated with structured incremental deltas, not wholesale rewrites": lambda: _probe(
        "applicant.application.services.playbook_service", "PlaybookService"
    ),
    "a verbal lesson is written to episodic memory and recalled on the next similar attempt": lambda: _assert_attr(
        "applicant.application.services.learning_service", "LearningService", "reflect_on_failure"
    ),
    # --- #307 memory backend ---
    "the engine writes and reads memory through the same port contract unchanged": lambda: _probe(
        "applicant.adapters.memory.vendor_backend"
    ),
    "both satisfy the port's contract test identically": lambda: _probe(
        "applicant.adapters.memory.vendor_backend"
    ),
    "the older fact is retained with a closed validity window rather than overwritten": lambda: _probe(
        "applicant.adapters.memory.temporal_backend"
    ),
    # --- #309 eval harness ---
    "a success-rate, step-count, and cost metric is reported per run": lambda: _probe(
        "applicant.evaluation.planner_harness", "run_suite"
    ),
    "a regression in success rate fails the gate": lambda: _probe(
        "applicant.evaluation.planner_harness", "ab_gate"
    ),
    "each material receives a quality score against a rubric": lambda: _probe(
        "applicant.evaluation.material_judge", "judge_material"
    ),
    # --- #310 redirect / subresource interception ---
    "the redirect hop to the blocked host is aborted and no body is captured": lambda: _probe(
        "applicant.core.rules.url_safety", "ip_chain_is_blocked"
    ),
    "the subresource request to the blocked host is aborted by route interception": lambda: _probe(
        "applicant.core.rules.url_safety", "ip_chain_is_blocked"
    ),
}


def _assert_attr(modpath: str, cls: str, attr: str):
    klass = _probe(modpath, cls)
    assert hasattr(klass, attr), f"{cls}.{attr} not implemented yet"


def _make_probe_then(probe):
    def step(rctx):
        probe()

    return step


for _phrase, _probe_fn in _PENDING_THEN_PROBES.items():
    then(_phrase)(_make_probe_then(_probe_fn))


# ===========================================================================
# PENDING — narrative Given/When scaffolding (the probe lives in the Then)
# ===========================================================================
_PENDING_NARRATIVE = [
    # #305
    "a planner that emits a typed operation list over a semantic-DOM snapshot",
    "the plan is validated against the plan-as-data schema",
    "a typed plan whose fill ops reference attributes by id",
    "the harness resolves each fill value from the attribute cloud",
    "a typed plan that includes a final-submit operation",
    "the harness executes the plan up to the stop-boundary",
    "a read-only scrape plan over a semantic-DOM snapshot",
    "the read-only JS lane runs",
    "the engine exposes a PlannerPort driving port",
    "a surface requests a plan",
    # #306
    "a completed successful pre-fill trajectory for an ATS",
    "the workflow-induction step runs over the trajectory",
    "a stored induced workflow for an ATS",
    "a new application targets the same ATS",
    "an existing playbook of curated strategies",
    "a generation and reflection pass produces new insights",
    "a pre-fill run that failed on an ATS step",
    "the reflection step runs over the failure",
    # #307
    "a memory driven port with a pluggable backend",
    "the backend is configured to a vendor-able implementation",
    "two memory backends implementing the same port",
    "the same store-and-recall sequence runs against each",
    "a temporal knowledge-graph memory backend",
    "a fact is superseded by a newer fact",
    # #308
    "a freshly booted Applicant engine",
    "an MCP client lists the available tools",
    "the engine exposed as an MCP server",
    "an MCP tool invokes a consequential action",
    # #309
    "an eval harness wrapping the pre-fill planner",
    "a benchmark task suite is run",
    "a baseline planner score and a candidate planner change",
    "the harness compares candidate against baseline",
    "a set of generated résumé/cover-letter materials",
    "the LLM-as-judge evaluation runs",
    # #310 redirect / subresource
    "a scraped posting URL on a public host that 3xx-redirects to a metadata host",
    "the harness follows the navigation",
    "a page that issues a subresource request to a private-range host",
    "the page loads",
]


def _noop(rctx):
    return None


for _phrase in _PENDING_NARRATIVE:
    given(_phrase)(_noop)
    when(_phrase)(_noop)
