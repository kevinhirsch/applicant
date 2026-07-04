"""Regression coverage for round 2 / wave 3, design-audit Top-25 #4 ("wire the
post-submission tracker to the front-door — post_submission_service.py had NO
router today"). Confined to the new files this task adds:

  * ``src/applicant/app/routers/post_submission.py`` (new engine router) —
    engine-side reachability + real fields are pinned in
    ``tests/unit/test_post_submission_router.py`` / ``test_post_submission_service.py``
    (per the round-2 convention of keeping engine coverage in the engine test
    tree). This file covers the FRONT-DOOR half of the chain only.
  * ``workspace/routes/applicant_tracker_routes.py`` (new proxy) — route-level
    behavior + the mandatory owner-isolation test live in
    ``workspace/tests/test_applicant_tracker_routes.py``.
  * ``workspace/static/js/applicantTracker.js`` (new surface) — this file.
  * ``workspace/static/index.html`` (nav wiring) — this file.
  * ``workspace/app.py`` (proxy registration) — this file.

``PostSubmissionService`` (G16/#190) already ran the full post-submission state
machine end to end (automated rejection-signal detection, the ghosting-SLA
sweep, follow-up scheduling) with ZERO router/front-door callers — this was a
genuine new-wiring job, not a "surface what's already reachable" fix. Each
assertion below was verified, by hand, to go red when the corresponding piece
of the chain is reverted (temporarily renaming the launcher export, stripping
the nav button, un-registering the proxy router), then confirmed green again
after restoring — per this series' standing DoD.

Follows the ``test_applicant_round2_wave1_corekit.py`` / ``..._wave3_employerintel.py``
convention: source-text regex assertions for the browser-only module (no
DOM-independent entry point cheap enough to shim here), plus one real
node-executed behavioral test of ``_bucketFor`` — a small, dependency-free,
extractable pure function — mirroring the ``_researchQuery`` precedent.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
JS_DIR = WORKSPACE_DIR / "static" / "js"
TRACKER_JS = JS_DIR / "applicantTracker.js"
RESULTS_JS = JS_DIR / "applicantResults.js"
INDEX_HTML = WORKSPACE_DIR / "static" / "index.html"
APP_PY = WORKSPACE_DIR / "app.py"
TRACKER_ROUTES_PY = WORKSPACE_DIR / "routes" / "applicant_tracker_routes.py"
ENGINE_CLIENT_PY = WORKSPACE_DIR / "src" / "applicant_engine.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the surface exists, self-boots, and exposes the established launcher ────


def test_tracker_module_exists_and_talks_to_the_workspace_proxy_only():
    """The module hits the workspace proxy (/api/applicant/tracker) — it never
    reaches the engine directly (CLAUDE.md: the front-door proxies)."""
    assert TRACKER_JS.exists(), "expected workspace/static/js/applicantTracker.js"
    src = _read(TRACKER_JS)
    assert "/api/applicant/tracker" in src
    assert "/api/post-submission" not in src, (
        "the browser module must go through the workspace proxy, never the "
        "engine's own /api/post-submission path directly"
    )


def test_tracker_reuses_the_shared_kit_not_a_hand_rolled_one():
    """Must import the shared loading/empty/error/gated/retry/poll helpers from
    applicantCore.js, exactly like its Results sibling — no duplicated kit."""
    src = _read(TRACKER_JS)
    imports = re.search(r"import \{(.*?)\} from '\./applicantCore\.js';", src, re.S)
    assert imports, "expected a destructured import from applicantCore.js"
    names = {n.strip() for n in imports.group(1).split(",")}
    for required in ("loadingHTML", "emptyHTML", "errorHTML", "gatedHTML", "wireRetry", "_fetchJSON"):
        assert required in names, f"expected {required} imported from the shared kit"


def test_tracker_exports_the_established_launcher_convention():
    """Mirrors applicantResults.js's bottom export block: an
    `openApplicant<Thing>` export, a `window.applicant<Thing>Module` object,
    and a bare `window.openApplicant<Thing>` alias — the deep-link convention
    other modules rely on without import coupling."""
    tracker_src = _read(TRACKER_JS)

    assert "export async function openApplicantTracker()" in tracker_src
    assert "const applicantTrackerModule = { openApplicantTracker };" in tracker_src
    assert "window.applicantTrackerModule = applicantTrackerModule;" in tracker_src
    assert "window.openApplicantTracker = openApplicantTracker;" in tracker_src
    assert "export default applicantTrackerModule;" in tracker_src

    # Same convention family as the Results sibling (module name substituted) —
    # not asserted byte-for-byte against RESULTS_JS since that file is actively
    # evolving in a concurrent wave (hash-routing); the shared *shape* (an
    # `openApplicant*` export + `window.applicant*Module` + bare
    # `window.openApplicant*` alias) is what this proves.
    results_src = _read(RESULTS_JS)
    assert re.search(r"export (async )?function openApplicantResults\(", results_src)
    assert "applicantResultsModule" in results_src


def test_tracker_self_boots_and_wires_its_own_rail_button():
    """Self-boots on DOMContentLoaded/immediately (like every sibling surface)
    and wires #rail-tracker with a retry loop for late DOM (rail
    (re)rendered after boot) — not a one-shot getElementById that silently
    no-ops if the rail isn't there yet."""
    src = _read(TRACKER_JS)
    assert "document.getElementById('rail-tracker')" in src
    assert "_applicantTrackerWired" in src
    assert "document.addEventListener('DOMContentLoaded', _boot)" in src


# ── the board groups by state and offers a manual "record what happened" ────


def test_board_groups_rows_into_lifecycle_buckets():
    """Renders distinct buckets across the post-submission lifecycle — not one
    flat undifferentiated list — so an owner can see WHERE each application
    stands at a glance."""
    src = _read(TRACKER_JS)
    bucket_block = re.search(r"const BUCKETS = \[(.*?)\];", src, re.S)
    assert bucket_block, "expected a BUCKETS bucket-definition table"
    body = bucket_block.group(1)
    for status in (
        "SUBMITTED_BY_USER", "AWAITING_RESPONSE", "REJECTED", "GHOSTED", "ARCHIVED",
    ):
        assert status in body, f"expected the {status} §7 state mapped to a bucket"


def test_positive_signals_render_as_a_tasteful_badge_not_confetti():
    """Interview/offer signals get a small colored badge — no keyframe
    animation, no confetti — reduce-motion-safe by construction (a static
    background/color has nothing to disable under prefers-reduced-motion)."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _signalBadges\(app\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _signalBadges(app) renderer"
    body = fn.group(0)
    assert "SIGNAL_LABEL" in body
    assert "@keyframes" not in src, "no animation for signal badges this pass"
    assert "confetti" not in src.lower()


def test_manual_record_affordance_is_wired_to_the_owner_write_endpoint():
    """Every row offers a 'record what happened' control that POSTs to the
    tracker's outcome endpoint — the owner-triggered write, distinct from the
    read-only board fetch."""
    src = _read(TRACKER_JS)
    assert "data-tracker-record" in src, "expected a per-row record affordance"
    fn = re.search(r"async function _recordOutcome\(select\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _recordOutcome(select) handler"
    body = fn.group(0)
    assert "/applications/" in body and "/outcome" in body
    assert "outcome_type" in body


def test_manual_outcome_options_match_the_engine_catalogue():
    """The offered outcome types are a subset of recognizable engine outcomes
    (interview_invited / offer / rejected / ghosted) — no invented option that
    the engine would 422 on."""
    src = _read(TRACKER_JS)
    options_block = re.search(r"const OUTCOME_OPTIONS = \[(.*?)\];", src, re.S)
    assert options_block, "expected an OUTCOME_OPTIONS table"
    body = options_block.group(1)
    for outcome_type in ("interview_invited", "offer", "rejected", "ghosted"):
        assert outcome_type in body


# ── engine-side: the router exists, and the tracker service methods it uses ──


def test_engine_client_exposes_tracker_methods_reused_by_the_proxy():
    """The workspace's ApplicantEngineClient carries the two tracker methods the
    proxy calls — not an ad hoc inline request — mirroring every other engine
    capability (admin_learning, agent_runs_list, ...)."""
    src = _read(ENGINE_CLIENT_PY)
    assert "async def tracker_board(self, campaign_id: str)" in src
    assert '"/api/post-submission/' in src
    assert "async def tracker_record_outcome(" in src
    assert "application_id: str, outcome_type: str, reason: str | None = None" in src


def test_proxy_router_file_exists_and_is_owner_scoped():
    assert TRACKER_ROUTES_PY.exists(), "expected workspace/routes/applicant_tracker_routes.py"
    src = _read(TRACKER_ROUTES_PY)
    assert "def setup_applicant_tracker_routes()" in src
    assert "require_user(request)" in src
    # The write must validate the caller-supplied application id against this
    # request's own campaign fan-out before forwarding (CLAUDE.md: never trust
    # a caller-supplied input to opt a safety check in).
    assert "_owner_application_ids" in src
    assert "application_id not in owned" in src


# ── wiring: proxy registered, nav entry added ────────────────────────────────


def test_proxy_is_registered_in_workspace_app():
    src = _read(APP_PY)
    assert "from routes.applicant_tracker_routes import setup_applicant_tracker_routes" in src
    assert "app.include_router(setup_applicant_tracker_routes())" in src


def test_index_html_wires_the_rail_button_and_script_include():
    src = _read(INDEX_HTML)
    assert 'id="rail-tracker"' in src
    assert 'src="/static/js/applicantTracker.js"' in src
    # The rail button must come BEFORE the module that wires it, same document
    # order as every other rail entry (script tags load after the rail markup).
    rail_pos = src.index('id="rail-tracker"')
    script_pos = src.index('src="/static/js/applicantTracker.js"')
    assert rail_pos < script_pos


# ── real behavior: the pure bucket-classifier function ──────────────────────


def test_bucket_classifier_behaviour(node_available):
    src = _read(TRACKER_JS)
    buckets_m = re.search(r"const BUCKETS = \[.*?\];\n", src, re.S)
    fn_m = re.search(r"function _bucketFor\(status\) \{.*?\n\}\n", src, re.S)
    assert buckets_m and fn_m
    script = textwrap.dedent(f"""
        {buckets_m.group(0)}
        {fn_m.group(0)}
        const out = {{
          applied: _bucketFor('SUBMITTED_BY_USER'),
          awaiting: _bucketFor('AWAITING_RESPONSE'),
          rejected: _bucketFor('REJECTED'),
          ghosted: _bucketFor('GHOSTED'),
          archived: _bucketFor('ARCHIVED'),
          unknown: _bucketFor('SOME_UNKNOWN_STATE'),
        }};
        console.log(JSON.stringify(out));
    """)
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=WORKSPACE_DIR,
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node failed:\n{res.stderr}"
    out = json.loads([ln for ln in res.stdout.splitlines() if ln.strip()][-1])
    assert out["applied"] == "applied"
    assert out["awaiting"] == "awaiting"
    assert out["rejected"] == "rejected"
    assert out["ghosted"] == "ghosted"
    assert out["archived"] == "archived"
    # An unrecognized status degrades to "awaiting" rather than crashing/dropping
    # the row silently — a fail-open default so a future §7 state addition never
    # makes a real application vanish from the board.
    assert out["unknown"] == "awaiting"


def test_node_check_applicant_tracker_js(node_available):
    """Syntax smoke: the module the above assertions read from must still parse."""
    res = subprocess.run(
        ["node", "--check", str(TRACKER_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
