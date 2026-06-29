"""Step bindings for the deploy / CI / ops acceptance specs (T10).

Theme: the deploy scripts (`scripts/install.sh`, `scripts/update.sh`), the CI
workflows (`.github/workflows/ci*.yml`), the startup readiness probe, and a pair
of test-hygiene bugs (`pytest.xfail` in a test body, a tautological BDD step).

Pattern (mirrors ``test_enh_research_steps`` / ``test_p1b_steps``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour
  that already ships on this branch — they assert against the actual files /
  the live ``/healthz`` probe and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for a residual gap that
  is NOT yet fixed on this branch. Their steps make an honest probe — they read
  the real script / workflow / source file and assert the *desired* property, an
  assertion the current text genuinely fails — so the scenario is a true red.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

These are script/CI/config facts, so the honest probe is to read the actual file
content from the repo tree (resolved relative to this file: ``parents[3]`` is the
repo root) and assert the property. No deploy script is ever executed; no real
socket/DB/browser is opened.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_181_integration_lane.feature",
    "../features/enhancements/enh_183_frozen_container_enforcement.feature",
    "../features/enhancements/enh_188_startup_capability_report.feature",
    "../features/enhancements/enh_275_dryrun_xfail_in_body.feature",
    "../features/enhancements/enh_276_tautological_bdd_step.feature",
    "../features/enhancements/enh_277_compileall_uses_uv.feature",
    "../features/enhancements/enh_278_ci_hosted_fallback.feature",
    "../features/enhancements/enh_279_rollback_reverts_code.feature",
    "../features/enhancements/enh_281_install_pull_failure.feature",
    "../features/enhancements/enh_282_backup_rotation.feature",
    "../features/enhancements/enh_283_cred_regen_guard.feature",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _read(relpath: str) -> str:
    """Read a repo file as text, relative to the repo root."""
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


@pytest.fixture
def t10ctx() -> dict:
    return {}


# ===========================================================================
# GREEN — #181: a dedicated integration CI lane exercises the real-adapter tests
# ===========================================================================
@given("the continuous-integration workflow set")
def ci_workflow_set(t10ctx):
    t10ctx["integration_ci"] = _read(".github/workflows/ci-integration.yml")


@when("the integration lane is inspected")
def inspect_integration_lane(t10ctx):
    t10ctx["text"] = t10ctx["integration_ci"]


@then("it runs the integration-marked tests against real dependencies on a schedule")
def lane_runs_integration_on_schedule(t10ctx):
    text = t10ctx["text"]
    # Invokes the integration-marked suite explicitly.
    assert re.search(r"pytest\b.*-m\s+integration", text), "lane must run `pytest -m integration`"
    # Runs against a real database (a postgres service container) and on a schedule.
    assert "postgres" in text
    assert "schedule:" in text and "cron:" in text


@given("the integration continuous-integration workflow")
def integration_ci_only(t10ctx):
    t10ctx["integration_ci"] = _read(".github/workflows/ci-integration.yml")


@when("its dependency preflight is inspected")
def inspect_preflight(t10ctx):
    t10ctx["text"] = t10ctx["integration_ci"]


@then("a missing renderer or browser binary aborts the lane instead of silently skipping")
def preflight_fails_fast(t10ctx):
    text = t10ctx["text"]
    # The TeX preflight aborts (exit 1) when neither engine is present, and the
    # Xvfb preflight aborts when xvfb-run is absent — fail fast, do not skip.
    assert "lualatex" in text and "xelatex" in text
    assert "xvfb-run" in text
    # Each guard emits a workflow error and exits non-zero rather than skipping.
    assert text.count("::error::") >= 2
    assert "exit 1" in text


# ===========================================================================
# GREEN — #183: the freeze intent is documented on the ports + container
# ===========================================================================
@given("the port packages and the composition root")
def ports_and_container(t10ctx):
    t10ctx["container"] = _read("src/applicant/app/container.py")
    t10ctx["ports_init"] = _read("src/applicant/ports/__init__.py")


@when("their freeze markers are inspected")
def inspect_freeze_markers(t10ctx):
    pass


@then("each declares that its definitions are frozen for downstream agents")
def freeze_documented(t10ctx):
    assert "FROZEN" in t10ctx["container"], "container must declare the freeze"
    # The ports package documents that the Protocols are frozen once Foundation completes.
    assert "FROZEN" in t10ctx["ports_init"]


# ===========================================================================
# GREEN — #188: the readiness probe reports health / degrades on a dead DB
# ===========================================================================
@given("a freshly booted Applicant instance")
def booted_instance(t10ctx, app_client):
    t10ctx["client"] = app_client


@when("the readiness probe is called")
def call_readiness(t10ctx):
    t10ctx["resp"] = t10ctx["client"].get("/healthz")


@then("it returns a green status with its dependency checks named")
def readiness_green(t10ctx):
    resp = t10ctx["resp"]
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body.get("checks"), dict) and body["checks"]


@given("a storage layer whose database cannot be reached")
def storage_db_unreachable(t10ctx, app_client):
    # Wire a real (but broken) engine onto the live container so the probe runs the
    # SELECT-1 path instead of the in-memory sentinel — a faithful degraded boundary.
    class _BoomConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *_a, **_k):
            raise RuntimeError("db down")

    class _BoomEngine:
        def connect(self):
            return _BoomConn()

        def dispose(self):
            pass

    app_client.app.state.container.engine = _BoomEngine()
    t10ctx["client"] = app_client


@when("the readiness probe evaluates the database check")
def evaluate_db_check(t10ctx):
    t10ctx["resp"] = t10ctx["client"].get("/healthz")


@then("a degraded result is reported instead of a false green")
def readiness_degraded(t10ctx):
    resp = t10ctx["resp"]
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"].startswith("error")


# ===========================================================================
# PENDING — #188: a startup capability report naming real-vs-stub binaries
# ===========================================================================
@given("the engine's capability self-report")
def capability_self_report(t10ctx):
    t10ctx["probe"] = "capability_report"


@when("the report is generated at boot")
def generate_capability_report(t10ctx):
    # Speculative import INSIDE the step: there is no capability-report module yet,
    # so this raises ImportError → honest red until the report lands.
    import importlib

    module = importlib.import_module("applicant.app.capability_report")
    t10ctx["report"] = module.build_capability_report()


@then("it lists the resume renderer, the browser, and the orchestrator as real or stub")
def capability_report_lists_binaries(t10ctx):
    report = t10ctx["report"]
    keys = {str(k).lower() for k in report}
    assert {"resume_renderer", "browser", "orchestrator"} <= keys


# ===========================================================================
# PENDING — #183: a contract test that catches a frozen-port signature drift
# ===========================================================================
@given("a recorded baseline of the driven and driving port signatures")
def port_signature_baseline(t10ctx):
    t10ctx["probe"] = "port_signature_baseline"


@when("a port Protocol method signature drifts from that baseline")
def port_signature_drifts(t10ctx):
    pass


@then("a contract test fails rather than letting the change land silently")
def port_drift_caught(t10ctx):
    # The enforcement module does not exist yet: there is no recorded baseline and
    # no diffing contract test for the frozen ports. Speculative import → red.
    import importlib

    module = importlib.import_module("applicant.ports.signature_baseline")
    assert hasattr(module, "assert_ports_unchanged")


# ===========================================================================
# PENDING — #275: the live ATS dry-run must not xfail inside the test body
# ===========================================================================
@given("the live ATS dry-run test source")
def dryrun_source(t10ctx):
    t10ctx["text"] = _read("tests/integration/test_ats_prefill_dryrun.py")


@when("the zero-fields-detected branch is inspected")
def inspect_zero_fields_branch(t10ctx):
    pass


@then("it does not call pytest.xfail inside the test body to mask the failure")
def no_inbody_xfail(t10ctx):
    text = t10ctx["text"]
    # A runtime `pytest.xfail(...)` call turns a real failure into an expected pass.
    # Today the zero-fields branch still calls it → genuine red until the fix lands.
    assert "pytest.xfail(" not in text, (
        "an in-body pytest.xfail() masks a browser/detection failure as XFAIL"
    )


# ===========================================================================
# PENDING — #276: the zero-command-line BDD step must not assert a bare truth
# ===========================================================================
@given("the P0 acceptance step source")
def p0_step_source(t10ctx):
    t10ctx["text"] = _read("tests/bdd/steps/test_p0_steps.py")


@when("the zero-command-line step body is inspected")
def inspect_no_cli_step(t10ctx):
    text = t10ctx["text"]
    # Isolate the `no_cli` step body so we judge that step, not the whole file.
    marker = "def no_cli(ctx):"
    start = text.index(marker)
    t10ctx["step_body"] = text[start : start + 400]


@then("it verifies setup happened over HTTP rather than asserting a bare truth")
def no_cli_is_concrete(t10ctx):
    body = t10ctx["step_body"]
    # Today the step is `assert True` — a tautology that passes even if never reached.
    # Genuine red until it is replaced with a concrete HTTP-surface check.
    assert "assert True" not in body, (
        "the zero-command-line step still asserts a bare truth (tautological no-op)"
    )


# ===========================================================================
# PENDING — #277: compileall must run under the project interpreter (`uv run`)
# ===========================================================================
@given("the continuous-integration workflow")
def ci_workflow(t10ctx):
    t10ctx["ci"] = _read(".github/workflows/ci.yml")


@when("the workspace compileall step is inspected")
def inspect_compileall(t10ctx):
    pass


@then("it invokes compileall through the project interpreter rather than bare python")
def compileall_uses_uv(t10ctx):
    text = t10ctx["ci"]
    # Find the compileall invocation and require it to run via `uv run python`.
    m = re.search(r"^\s*([^\n]*python -m compileall[^\n]*)$", text, re.MULTILINE)
    assert m is not None, "expected a compileall step in ci.yml"
    line = m.group(1)
    # Today it is bare `python -m compileall ...` → red until it is `uv run python ...`.
    assert "uv run python -m compileall" in line, (
        "compileall must run under `uv run python` so workspace deps are importable"
    )


# ===========================================================================
# PENDING — #278: CI needs an active hosted fallback, not a commented one
# ===========================================================================
@when("its runner selection is inspected")
def inspect_runner(t10ctx):
    pass


@then("a hosted fallback is wired in rather than left commented out")
def hosted_fallback_active(t10ctx):
    text = t10ctx["ci"]
    # An ACTIVE (non-commented) ubuntu-latest fallback: a runner group, a labels
    # array, or a matrix that resolves to a hosted runner when self-hosted is down.
    active_hosted = bool(
        re.search(r"^\s*runs-on:\s*\[[^\]]*ubuntu-latest", text, re.MULTILINE)
        or re.search(r"^\s*group:\s*\S+\s*$", text, re.MULTILINE)
        or re.search(r"^\s*-\s*ubuntu-latest\s*$", text, re.MULTILINE)
    )
    # Today ubuntu-latest only appears as a commented `# runs-on:` swap → red.
    assert active_hosted, "the hosted fallback is still commented out, not wired in"


# ===========================================================================
# PENDING — #279: --rollback must revert code + images, not only the DB
# ===========================================================================
@given("the updater script")
def updater_script(t10ctx):
    t10ctx["update"] = _read("scripts/update.sh")


@when("its rollback path is inspected")
def inspect_rollback(t10ctx):
    text = t10ctx["update"]
    # Isolate the `--rollback` branch so we judge that path's actions.
    start = text.index('if [[ "${ROLLBACK}" -eq 1 ]]; then')
    t10ctx["rollback_body"] = text[start : start + 800]


@then("it reverts the git checkout and the container images alongside the database")
def rollback_reverts_code(t10ctx):
    body = t10ctx["rollback_body"]
    # Today rollback only restores the DB dump. A real rollback must also revert the
    # source checkout and the images → red until git/image revert is added.
    reverts_git = "git reset" in body or "git checkout" in body or "HEAD@{" in body
    reverts_images = "image tag" in body or "docker image" in body or "image:previous" in body
    assert reverts_git and reverts_images, (
        "rollback restores only the DB; it must also revert the git checkout and images"
    )


# ===========================================================================
# PENDING — #281: install.sh must not swallow a failed `git pull`
# ===========================================================================
@given("the installer script")
def installer_script(t10ctx):
    t10ctx["install"] = _read("scripts/install.sh")


@when("its checkout-reuse pull step is inspected")
def inspect_install_pull(t10ctx):
    pass


@then("a pull failure is detected and surfaced rather than swallowed with an unconditional true")
def install_pull_not_swallowed(t10ctx):
    text = t10ctx["install"]
    # Today: `git -C ... pull --ff-only --quiet || true` discards every failure.
    swallows = bool(re.search(r"git -C[^\n]*pull[^\n]*\|\|\s*true", text))
    assert not swallows, (
        "install.sh swallows all pull failures with `|| true`; it must detect and surface them"
    )


# ===========================================================================
# PENDING — #282: update.sh must prune old backups (retention policy)
# ===========================================================================
@when("its backup handling is inspected")
def inspect_backup_handling(t10ctx):
    pass


@then("it prunes old backups by a configurable count or age rather than keeping them forever")
def backups_pruned(t10ctx):
    text = t10ctx["update"]
    # A retention knob (count/age/days) plus an actual prune action over the backups.
    has_retention_knob = bool(
        re.search(r"BACKUP_KEEP_(DAYS|COUNT)|BACKUP_RETENTION|MAX_BACKUPS", text)
    )
    prunes = bool(re.search(r"(rm\b[^\n]*applicant-|find[^\n]*applicant-[^\n]*-delete)", text))
    # Today there is no rotation at all → red until retention + prune land.
    assert has_retention_knob and prunes, (
        "update.sh never prunes backups; add a configurable retention policy"
    )


# ===========================================================================
# PENDING — #283: install.sh must not regenerate creds over an existing volume
# ===========================================================================
@when("its credential generation guard is inspected")
def inspect_cred_guard(t10ctx):
    pass


@then("it refuses to mint new credentials when the Postgres data volume already exists")
def cred_guard_checks_volume(t10ctx):
    text = t10ctx["install"]
    # The guard must consult the actual DB volume state, not just `! -f .env`.
    checks_volume = bool(
        re.search(r"docker volume (ls|inspect)", text)
        or "already initialized" in text
        or re.search(r"refuse[^\n]*credential", text, re.IGNORECASE)
    )
    # Today regeneration is guarded only by the absence of .env → red.
    assert checks_volume, (
        "install.sh regenerates credentials guarded only by `! -f .env`; it must detect "
        "an initialized Postgres volume and refuse"
    )


# ===========================================================================
# PENDING — #181 residual: per-skip un-exercised-boundary ledger
# ===========================================================================
@given("the integration coverage ledger")
def integration_coverage_ledger(t10ctx):
    t10ctx["probe"] = "integration_coverage_ledger"


@when("the suite skips a real-adapter test for a missing dependency")
def suite_skips_real_adapter(t10ctx):
    pass


@then("the un-exercised boundary is surfaced as a tracked gap rather than vanishing")
def skip_recorded_as_gap(t10ctx):
    # No coverage-ledger / skip-accounting module exists yet. Speculative import → red.
    import importlib

    module = importlib.import_module("applicant.observability.integration_coverage")
    assert hasattr(module, "record_unexercised_boundary")
