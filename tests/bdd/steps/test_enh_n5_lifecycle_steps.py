"""Step bindings for the N5 lifecycle / config / scoring / tracking specs.

Theme N5 covers eight issue-tracker enhancements:

* #316 — graceful shutdown (lifespan abandons workflows / leaks sandboxes)
* #344 — cold-start viability gate (neutral 0.75 with no criteria)
* #345 — ``_parse_json_loose`` silently drops a score-less reply
* #347 — ``.env.example`` missing several documented config vars
* #348 — ``requires-python`` pinned ``<3.12``  (paired with #355)
* #355 — engine vs workspace Dockerfile Python mismatch (paired with #348)
* #357 — TRACKING: editor JS audit
* #358 — MASTER TRACKING: remaining unaudited areas

Pattern (mirrors ``test_enh_research_steps`` / ``test_enh_t10_deploy_steps``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour /
  facts that already hold on this branch — they assert against the actual scoring
  service, the loose-JSON parser, or the real file/source content, and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for a residual gap that is
  NOT yet closed. Their steps make an honest probe — a speculative import at the
  intended seam, or an assertion the *current* text/code genuinely fails — so the
  scenario is a true red. ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a
  non-strict xfail.

Hexagonal: #344/#345 assert against the application ``ScoringService`` wired with the
in-memory ``LocalEmbedding`` adapter and a tiny in-test fake ``LLMPort`` (no network,
no DB). #316 reads the real lifespan source; #347/#348/#355/#357/#358 read real
repo files / source trees (resolved relative to this file: ``parents[3]`` is the repo
root). No real socket, DB, or browser is ever opened.
"""

from __future__ import annotations

import importlib
import logging
import pathlib

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_316_graceful_shutdown.feature",
    "../features/enhancements/enh_344_cold_start_viability_gate.feature",
    "../features/enhancements/enh_345_loose_json_no_score_log.feature",
    "../features/enhancements/enh_347_env_example_missing_docs.feature",
    "../features/enhancements/enh_348_python_version_pin.feature",
    "../features/enhancements/enh_355_dockerfile_python_mismatch.feature",
    "../features/enhancements/enh_357_editor_js_audit_tracking.feature",
    "../features/enhancements/enh_358_master_audit_tracking.feature",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _read(relpath: str) -> str:
    """Read a repo file as text, relative to the repo root."""
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


@pytest.fixture
def n5ctx() -> dict:
    return {}


# ---------------------------------------------------------------------------
# Tiny in-test fakes for the scoring scenarios (#344, #345). Hexagonal: these
# satisfy the driven ports without any network/DB.
# ---------------------------------------------------------------------------
def _make_scoring_service(*, llm=None):
    """Build a real ``ScoringService`` over the in-memory embedding adapter."""
    from applicant.adapters.embedding.local_embedding import LocalEmbedding
    from applicant.application.services.scoring_service import ScoringService

    return ScoringService(storage=None, llm=llm, embedding=LocalEmbedding())


def _make_posting():
    from applicant.core.entities.job_posting import JobPosting

    return JobPosting(
        id="post-1",
        campaign_id="camp-1",
        title="Backend Engineer",
        company="Acme",
        source_url="https://example.test/jobs/1",
        description="Build and run backend services in Python.",
    )


# ===========================================================================
# #316 — GREEN: the shutdown path stops the loop + disposes the engine
# ===========================================================================
@given("the application lifespan source")
def lifespan_source(n5ctx):
    n5ctx["lifespan"] = _read("src/applicant/app/lifespan.py")


@when("the shutdown branch is inspected")
def inspect_shutdown_branch(n5ctx):
    text = n5ctx["lifespan"]
    # Isolate the post-yield shutdown body so we judge the shutdown path only.
    marker = "\n    yield\n"
    idx = text.index(marker) + len(marker)
    n5ctx["shutdown_body"] = text[idx:]


@then("it cancels the scheduler task and disposes the database engine")
def shutdown_stops_loop_and_engine(n5ctx):
    body = n5ctx["shutdown_body"]
    assert "scheduler_task.cancel()" in body
    assert "container.engine.dispose()" in body


# ===========================================================================
# #316 — PENDING: drain checkpoints + clean up sandboxes/browser/vault
# ===========================================================================
@when("a graceful shutdown is requested with workflows mid-flight")
def shutdown_with_workflows(n5ctx):
    n5ctx["shutdown_body"] = n5ctx["lifespan"][n5ctx["lifespan"].index("\n    yield\n") :]


@then("it flushes the pending workflow checkpoints so no in-progress step is abandoned")
def shutdown_flushes_checkpoints(n5ctx):
    body = n5ctx["shutdown_body"]
    # Today shutdown only cancels the task + disposes the engine; there is no call to
    # drain/flush/checkpoint pending workflow state. Genuine red until that seam lands.
    flushes = any(
        tok in body
        for tok in ("flush_pending", "drain", "checkpoint(", "quiesce", "orchestrator.flush")
    )
    assert flushes, "shutdown abandons in-flight workflows: no checkpoint flush / drain on the loop"


@when("a graceful shutdown is requested with active sandbox sessions")
def shutdown_with_sandboxes(n5ctx):
    n5ctx["shutdown_body"] = n5ctx["lifespan"][n5ctx["lifespan"].index("\n    yield\n") :]


@then("it closes the sandbox sessions, the browser, and the credential vault")
def shutdown_closes_resources(n5ctx):
    body = n5ctx["shutdown_body"].lower()
    # The lifespan has no reference to the sandbox/browser/vault ports on shutdown, so
    # every active session/VM is leaked. Genuine red until cleanup is wired in.
    closes_sandbox = "sandbox" in body
    closes_browser = "browser" in body
    closes_vault = "vault" in body or "credential" in body
    assert closes_sandbox and closes_browser and closes_vault, (
        "shutdown never references the sandbox/browser/credential-vault ports — resources leak"
    )


# ===========================================================================
# #344 — GREEN: no criteria => neutral 0.75 and the posting is viable
# ===========================================================================
@given("a scoring service with no model configured")
def scoring_no_model(n5ctx):
    n5ctx["svc"] = _make_scoring_service(llm=None)


@given("a campaign with no search criteria set")
def campaign_no_criteria(n5ctx):
    # ``None`` criteria => the service synthesises empty criteria => the no-criteria path.
    n5ctx["criteria"] = None


@when("a posting is scored")
def score_posting(n5ctx):
    n5ctx["scoring"] = n5ctx["svc"].score_posting(_make_posting(), n5ctx["criteria"])


@then("it receives the documented neutral score of seventy-five out of one hundred")
def neutral_seventyfive(n5ctx):
    assert n5ctx["scoring"].score == pytest.approx(0.75)


@then("the posting is considered viable")
def posting_is_viable(n5ctx):
    # 0.75 * 100 = 75 >= the default threshold of 70 => the gate is wide open at cold start.
    assert n5ctx["svc"].is_viable(n5ctx["scoring"]) is True


@then("the rationale explains that no criteria are set yet")
def rationale_no_criteria(n5ctx):
    text = n5ctx["scoring"].rationale.lower()
    assert "no search criteria" in text or "no criteria" in text


# ===========================================================================
# #344 — PENDING: discovery must refuse to run with zero criteria
# ===========================================================================
@when("discovery is asked to run for that campaign")
def discovery_run_no_criteria(n5ctx):
    # Probe the intended guard at its seam. Today discovery does NOT require a
    # criterion before running, so this absent rule/attribute is the honest red.
    module = importlib.import_module("applicant.core.rules.discovery_gate")
    n5ctx["gate"] = module


@then("it declines to run until at least one criterion is configured")
def discovery_declines(n5ctx):
    gate = n5ctx["gate"]
    assert hasattr(gate, "require_criteria_before_discovery")


# ===========================================================================
# #345 — GREEN: the loose-JSON parser recovers an embedded object + score key
# ===========================================================================
@given("the loose-JSON parser")
def loose_json_parser(n5ctx):
    from applicant.application.services.scoring_service import ScoringService

    n5ctx["parse"] = ScoringService._parse_json_loose


@when("it is given model output with a JSON object wrapped in prose")
def parse_wrapped_json(n5ctx):
    n5ctx["parsed"] = n5ctx["parse"](
        'Sure! Here is my answer: {"score": 80, "rationale": "Strong fit"} — hope that helps.'
    )


@then("the embedded object is returned as a dictionary")
def embedded_object_returned(n5ctx):
    assert isinstance(n5ctx["parsed"], dict)
    assert n5ctx["parsed"].get("score") == 80


@when("it is given a clean JSON reply with a score and a rationale")
def parse_clean_json(n5ctx):
    n5ctx["parsed"] = n5ctx["parse"]('{"score": 42, "rationale": "Partial match"}')


@then("the parsed dictionary carries the score key")
def parsed_carries_score(n5ctx):
    assert "score" in n5ctx["parsed"]


# ===========================================================================
# #345 — PENDING: a score-less parsed reply must be logged before the fallback
# ===========================================================================
class _ScorelessLLM:
    """Fake LLMPort whose JSON reply parses but carries no ``score`` key."""

    def is_configured(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["fake-model"]

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        from applicant.ports.driven.llm import LLMResult

        # structured is empty so the service falls into the loose-text parse, which
        # yields a dict WITHOUT a ``score`` key -> ValueError -> embedding fallback.
        return LLMResult(
            text='{"rationale": "Great fit"}',
            tier=1,
            model="fake-model",
            structured=None,
        )

    def is_viable(self):  # pragma: no cover - not part of the port surface used here
        return True


@given("a scoring service whose model returns JSON without a score key")
def scoring_scoreless_model(n5ctx, caplog):
    n5ctx["svc"] = _make_scoring_service(llm=_ScorelessLLM())
    n5ctx["caplog"] = caplog


@when("the model-backed base score is attempted")
def attempt_model_base_score(n5ctx):
    from applicant.core.entities.search_criteria import SearchCriteria

    criteria = SearchCriteria(campaign_id="camp-1", titles=("Backend Engineer",))
    with n5ctx["caplog"].at_level(logging.WARNING):
        # Goes through the LLM path, hits the score-less reply, degrades to embeddings.
        n5ctx["scoring"] = n5ctx["svc"].score_posting(_make_posting(), criteria)


@then("a warning is logged that the model returned no score before the embedding fallback")
def warning_no_score(n5ctx):
    # First confirm the fallback actually happened (the embedding path produced a score),
    # so we know the score-less branch was exercised, not skipped.
    assert n5ctx["scoring"].score is not None
    records = [r for r in n5ctx["caplog"].records if r.levelno >= logging.WARNING]
    blob = " ".join(r.getMessage().lower() for r in records)
    # Today the score-less reply is swallowed silently (the ValueError is caught in
    # ``_base_score`` with a bare ``pass`` — no log, no metric). Genuine red until a
    # warning naming the missing score is emitted before degrading to embeddings.
    assert records and ("score" in blob), (
        "model returned score-less JSON but the fallback was silent (no warning logged)"
    )


# ===========================================================================
# #347 — .env.example documents the audited config vars
# ===========================================================================
@given("the environment template")
def env_template(n5ctx):
    n5ctx["env"] = _read(".env.example")


@when("its documented settings are inspected")
def inspect_env_settings(n5ctx):
    pass


@then("the memory-backend selector is present")  # GREEN
def env_has_mind_backend(n5ctx):
    assert "MIND_BACKEND" in n5ctx["env"]


@then("the secure-cookie and upload-size settings are present")  # PENDING
def env_has_secure_cookies(n5ctx):
    env = n5ctx["env"]
    assert "SECURE_COOKIES" in env and "MAX_UPLOAD_SIZE" in env


@then("the sandbox-concurrency and automated-accounts settings are present")  # PENDING
def env_has_sandbox_concurrency(n5ctx):
    env = n5ctx["env"]
    assert "SANDBOX_CONCURRENCY" in env and "ALLOW_AUTOMATED_ACCOUNTS" in env


@then("the in-UI update toggle is present")  # PENDING
def env_has_update_enabled(n5ctx):
    assert "APPLICANT_UPDATE_ENABLED" in n5ctx["env"]


# ===========================================================================
# #348 — pyproject requires-python widened or justified
# ===========================================================================
@given("the project manifest")
def project_manifest(n5ctx):
    n5ctx["pyproject"] = _read("pyproject.toml")


@when("its python requirement is inspected")
def inspect_python_floor(n5ctx):
    pass


@then("it requires at least Python 3.11")  # GREEN
def python_floor_311(n5ctx):
    import re

    m = re.search(r'requires-python\s*=\s*"([^"]+)"', n5ctx["pyproject"])
    assert m is not None, "requires-python not declared"
    assert ">=3.11" in m.group(1)


@when("its python upper bound is inspected")
def inspect_python_ceiling(n5ctx):
    import re

    m = re.search(r'requires-python\s*=\s*"([^"]+)"', n5ctx["pyproject"])
    n5ctx["requires_python"] = m.group(1) if m else ""


@then("either Python 3.12 is admitted or the exclusion is documented")  # PENDING
def python_admits_312_or_documented(n5ctx):
    constraint = n5ctx["requires_python"]
    text = n5ctx["pyproject"]
    # Admit 3.12 either by allowing it (>=3.13 ceiling or no <3.12) ...
    admits_312 = "<3.12" not in constraint
    # ... or by documenting WHY 3.12+ is excluded in a nearby comment.
    documented = bool(__import__("re").search(r"#.*3\.12", text))
    assert admits_312 or documented, (
        "requires-python hard-caps at <3.12 with no recorded justification"
    )


# ===========================================================================
# #355 — engine vs workspace Dockerfile Python versions agree
# ===========================================================================
def _python_minor(dockerfile_text: str) -> str | None:
    import re

    m = re.search(r"FROM\s+python:(\d+\.\d+)", dockerfile_text)
    return m.group(1) if m else None


@given("the engine and workspace Dockerfiles")
def both_dockerfiles(n5ctx):
    n5ctx["engine_df"] = _read("docker/Dockerfile")
    n5ctx["workspace_df"] = _read("workspace/Dockerfile")


@when("their base images are inspected")
def inspect_base_images(n5ctx):
    pass


@then("each pins a slim Python base image")  # GREEN
def both_pin_slim_python(n5ctx):
    assert "FROM python:" in n5ctx["engine_df"] and "-slim" in n5ctx["engine_df"]
    assert "FROM python:" in n5ctx["workspace_df"] and "-slim" in n5ctx["workspace_df"]


@when("their Python minor versions are compared")
def compare_python_minors(n5ctx):
    n5ctx["engine_minor"] = _python_minor(n5ctx["engine_df"])
    n5ctx["workspace_minor"] = _python_minor(n5ctx["workspace_df"])


@then("the engine and workspace pin the same Python minor version")  # PENDING
def python_minors_match(n5ctx):
    # Today engine=3.11, workspace=3.12 -> genuine red until they are aligned.
    assert n5ctx["engine_minor"] is not None and n5ctx["workspace_minor"] is not None
    assert n5ctx["engine_minor"] == n5ctx["workspace_minor"], (
        f"engine pins python:{n5ctx['engine_minor']} but workspace pins "
        f"python:{n5ctx['workspace_minor']}"
    )


# ===========================================================================
# #357 — TRACKING: editor JS audit
# ===========================================================================
@given("the editor JS directory")
def editor_js_dir(n5ctx):
    n5ctx["editor_dir"] = REPO_ROOT / "workspace" / "static" / "js" / "editor"


@when("the top-level scripts are counted")
def count_editor_scripts(n5ctx):
    n5ctx["editor_count"] = len(list(n5ctx["editor_dir"].glob("*.js")))


@then("there are at least thirty top-level editor scripts")  # GREEN (inventory baseline)
def editor_count_ge_30(n5ctx):
    assert n5ctx["editor_count"] >= 30


@when("the dirtiest editor file is scanned")
def scan_dirtiest_editor_file(n5ctx):
    n5ctx["layer_panel"] = (n5ctx["editor_dir"] / "layer-panel.js").read_text(encoding="utf-8")


@then("the layer panel still writes raw markup more than ten times")  # GREEN (inventory baseline)
def layer_panel_raw_markup(n5ctx):
    assert n5ctx["layer_panel"].count("innerHTML") > 10


@when("the layer-panel audit ledger is consulted")
def consult_layer_panel_ledger(n5ctx):
    # Probe the intended audit-ledger seam. No such record exists yet, so the import /
    # lookup raises -> honest red until the per-file audit is recorded.
    module = importlib.import_module("applicant.audit_ledger")
    n5ctx["ledger"] = module


@then("the layer panel is recorded as audited and its raw-markup writes resolved")  # PENDING
def layer_panel_audited(n5ctx):
    ledger = n5ctx["ledger"]
    assert ledger.is_audited("workspace/static/js/editor/layer-panel.js")


# ===========================================================================
# #358 — MASTER TRACKING: remaining unaudited areas
# ===========================================================================
@given("the repository tree")
def repo_tree(n5ctx):
    n5ctx["root"] = REPO_ROOT


@when("the webtop Dockerfiles are enumerated")
def enumerate_webtop_dockerfiles(n5ctx):
    docker_dir = n5ctx["root"] / "docker"
    n5ctx["webtops"] = list(docker_dir.glob("webtop-*/Dockerfile"))


@then("at least three webtop desktop Dockerfiles are present")  # GREEN (inventory baseline)
def webtops_ge_3(n5ctx):
    assert len(n5ctx["webtops"]) >= 3


@when("the dependency lockfile is located")
def locate_lockfile(n5ctx):
    n5ctx["lockfile"] = n5ctx["root"] / "uv.lock"


@then("the uv lockfile is present and substantial")  # GREEN (inventory baseline)
def lockfile_present(n5ctx):
    lock = n5ctx["lockfile"]
    assert lock.exists() and lock.stat().st_size > 50_000


@when("the master audit ledger is consulted")
def consult_master_ledger(n5ctx):
    # Probe the intended master-tracker completion record. No such ledger exists yet ->
    # honest red until every enumerated area is recorded as audited.
    module = importlib.import_module("applicant.audit_ledger")
    n5ctx["ledger"] = module


@then("every enumerated unaudited area is recorded as audited")  # PENDING
def all_areas_audited(n5ctx):
    ledger = n5ctx["ledger"]
    areas = [
        "workspace/static/js/editor",
        "docker/webtop-chrome/Dockerfile",
        "docker/webtop-gnome/Dockerfile",
        "docker/webtop-pantheon/Dockerfile",
        "workspace/Dockerfile",
        "uv.lock",
        "workspace/requirements.txt",
    ]
    assert all(ledger.is_audited(a) for a in areas)
