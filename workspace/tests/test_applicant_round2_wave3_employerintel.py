"""Regression coverage for round 2 / wave 3, Top-25 #22 ("company/employer
intelligence brief per digest row (reuse deep-research)"), confined to
``static/js/emailLibrary/applicantDigest.js`` and (read-only reference)
``static/js/applicantPortal.js``.

**Investigation finding (this is a confirmation, not a new build).** The audit's
anchor — "``material_service.py`` research, never surfaced" — was accurate when
written, but the gap was already closed by two prior commits before this task was
picked up:

  * ``dcc99a5`` (#299) wired the engine's capped/deduped/cached ``ResearchService``
    into ``MaterialService`` so on-demand cover-letter generation folds a
    company-research block into the letter (the anchor the audit pointed at).
  * ``443cca0`` / an earlier commit shipped the FRONT-DOOR affordance itself: a
    "Research" button on every digest row (``buildDigestRow`` in this module) that
    calls the SAME engine ``ResearchService`` through its manual-trigger endpoint
    (``/api/research/{campaign_id}/run`` -> proxied at
    ``/api/applicant/research/{campaign_id}/run`` by
    ``routes/applicant_research_routes.py``) and renders a readable
    summary/key-findings/sources brief in ``_showReport``.

Proof that it is the SAME research capability, not a second pipeline: the engine
container (``src/applicant/app/container.py``) builds exactly ONE
``ResearchService`` instance and wires it BOTH into ``material_service._research``
(the cover-letter feed) AND as ``container.research_service`` (what
``get_research_service`` — the manual-trigger router's dependency — returns), so
the two paths share one process-lived budget ledger + dedupe cache. See
``tests/unit/test_cov_round2_employerintel.py`` for the engine-side proof (object
identity across all three ``MaterialService`` builds).

This file exists because no test previously PINNED the front-door half of that
reachability chain (the manual research trigger + button existed and had route-
level proxy coverage in ``test_applicant_research_routes.py``, but nothing
asserted that a digest ROW actually renders the action, that the report is a
readable brief rather than a raw dump, that the SAME row renderer — and so the
SAME brief — is reachable from both the Email panel and the Portal home base
(``applicantPortal.js`` reuses ``buildDigestRow`` "wholesale"), or that the
research fetch is LAZY (only on click, never eagerly for every row on digest
load) — the safer design given research is capped/budgeted per campaign.

Each assertion below was verified, by hand, to actually go red when the
corresponding piece of the chain is reverted (temporarily renaming the action
class / stripping the report renderer / making Portal build its own row markup
instead of reusing ``buildDigestRow``), then confirmed green again after
restoring — per this series' standing DoD.

Follows the ``test_applicant_round1_observability.py`` / ``..._round2_wave1_polling.py``
convention: source-text regex assertions for the browser-only module (it has no
DOM-independent entry point cheap enough to shim here), plus one real
node-executed behavioral test of ``_researchQuery`` — a small, dependency-free,
extractable pure function — mirroring the ``pollVisible`` extraction precedent.
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
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"
PORTAL_JS = JS_DIR / "applicantPortal.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the digest row renders the research action, wired to the manual trigger ──


def test_digest_row_renders_a_research_action():
    """``buildDigestRow`` (the single row-card builder) attaches a Research
    button distinct from Open/Approve/Pass, wired to the on-demand handler."""
    src = _read(DIGEST_JS)
    build_fn = re.search(
        r"export function buildDigestRow\(.*?\n\}\n", src, re.S
    )
    assert build_fn, "expected an exported buildDigestRow(row, ctx) builder"
    body = build_fn.group(0)
    assert "applicant-digest-research" in body, (
        "digest row card must render a dedicated research action"
    )
    assert re.search(r"research\.addEventListener\('click',\s*\(\)\s*=>\s*_onResearch\(", body), (
        "the research button must be wired to _onResearch, not a stub"
    )


def test_research_action_hits_the_manual_trigger_proxy_not_a_new_pipeline():
    """The research button calls the workspace's manual deep-research proxy —
    the SAME channel the engine's manual-trigger router exposes — not a
    freshly invented endpoint. Principle #1: no second research pipeline."""
    src = _read(DIGEST_JS)
    # A distinct fetch helper for the research proxy, kept separate from the
    # digest/email proxy so its base path is easy to audit here.
    api_research = re.search(r"async function _apiResearch\(.*?\n\}\n", src, re.S)
    assert api_research, "expected a dedicated _apiResearch proxy helper"
    assert "/api/applicant/research" in api_research.group(0), (
        "must call the workspace's manual-research proxy "
        "(-> engine /api/research/{campaign_id}/run, the SAME ResearchService "
        "MaterialService escalates to for cover letters)"
    )
    on_research = re.search(r"async function _onResearch\(.*?\n\}\n", src, re.S)
    assert on_research, "expected an _onResearch handler"
    assert re.search(r"_apiResearch\(`/\$\{encodeURIComponent\(campaignId\)\}/run`", on_research.group(0)), (
        "_onResearch must POST to the manual-trigger run endpoint"
    )


def test_report_is_rendered_as_a_readable_brief_not_a_raw_dump():
    """``_showReport`` renders the engine's ResearchReport as a plain-language
    brief (heading, summary paragraph, a labelled key-findings list, sources) —
    not a JSON blob — and gracefully explains the degraded/unavailable states."""
    src = _read(DIGEST_JS)
    show_report = re.search(r"function _showReport\(.*?\n\}\n", src, re.S)
    assert show_report, "expected a _showReport renderer"
    body = show_report.group(0)
    # Readable structure: a heading, the free-text summary, a findings list.
    assert "data.summary" in body, "brief must surface the researched summary"
    assert "Key findings" in body and "data.key_findings" in body, (
        "brief must surface the researched key findings, labelled for the reader"
    )
    assert "Sources" in body and "data.sources" in body, (
        "brief must surface sources so the user can verify the research"
    )
    # Graceful degradation: channel-off / budget-exhausted read as plain
    # language, not an error dump (the engine returns 200 + unavailable+reason).
    assert "data.unavailable" in body
    assert "budget_exhausted" in body and "workspace_unavailable" in body


def test_researched_query_reflects_the_actual_posting():
    """``_researchQuery`` builds a query scoped to the row's own role/company
    (not a generic placeholder), so the brief is genuinely about the posting
    the user is looking at."""
    src = _read(DIGEST_JS)
    fn = re.search(r"function _researchQuery\(row\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _researchQuery(row) helper"
    body = fn.group(0)
    assert "row.company" in body and ("row.title" in body or "row.role" in body)


def test_researched_query_behaviour(node_available):
    """Real execution (mirrors the pollVisible precedent): a role+company row
    produces a '<role> at <company>' query; a partial row degrades to
    whichever field is present rather than crashing."""
    src = _read(DIGEST_JS)
    m = re.search(r"function _researchQuery\(row\) \{.*?\n\}\n", src, re.S)
    assert m, "expected a _researchQuery(row) helper to extract"
    fn_src = m.group(0)
    script = textwrap.dedent(f"""
        {fn_src}
        const out = {{
          both: _researchQuery({{ title: 'Backend Engineer', company: 'Acme' }}),
          companyOnly: _researchQuery({{ company: 'Acme' }}),
          neither: _researchQuery({{}}),
        }};
        console.log(JSON.stringify(out));
    """)
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT / "workspace",
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node failed:\n{res.stderr}"
    out = json.loads([ln for ln in res.stdout.splitlines() if ln.strip()][-1])
    assert out["both"] == "Backend Engineer at Acme"
    assert out["companyOnly"] == "Acme"
    assert out["neither"] == "this role"


# ── lazy / on-demand, never eager for every row on digest load ──────────────


def test_research_is_never_fetched_eagerly_on_digest_load():
    """The research budget is capped per campaign, so fetching a brief for
    EVERY row on every digest load/refresh would burn the cap on rows the
    user never looks at. Assert the fetch only happens inside the click
    handler (_onResearch), never inside the render/load path."""
    src = _read(DIGEST_JS)
    for fn_name in ("_renderDigest", "_buildRow", "_loadDigest", "buildDigestRow"):
        fn = re.search(rf"function {fn_name}\(.*?\n\}}\n", src, re.S) or re.search(
            rf"export function {fn_name}\(.*?\n\}}\n", src, re.S
        )
        assert fn, f"expected to find {fn_name} to audit"
        assert "_apiResearch(" not in fn.group(0), (
            f"{fn_name} must not eagerly call the research proxy — "
            "research is lazy, triggered only by the user clicking Research "
            "on one row (_onResearch)"
        )


# ── the SAME row (and so the SAME brief) is reachable from the Portal, too ──


def test_portal_reuses_the_same_digest_row_renderer_not_a_duplicate():
    """The Portal home base (the post-login landing surface, CLAUDE.md) must
    render digest rows through the SAME buildDigestRow the Email panel uses —
    not a hand-rolled duplicate — so the employer-intelligence brief is
    reachable from the Portal too, with no second implementation to drift out
    of sync (C1, this file's neighbouring precedent)."""
    src = _read(PORTAL_JS)
    assert "digestModule.buildDigestRow" in src, (
        "Portal must reuse the digest module's row renderer wholesale so the "
        "Research action (and so the employer-intelligence brief) is reachable "
        "from the Portal home base, not just the Email panel"
    )
    # Guard against a hand-rolled competing action row for research in Portal.
    assert "_onResearch" not in src and "_apiResearch" not in src, (
        "Portal must not re-implement the research trigger — it should come "
        "for free via the shared buildDigestRow"
    )


def test_node_check_applicant_digest_js(node_available):
    """Syntax smoke: the module the above assertions read from must still parse."""
    res = subprocess.run(
        ["node", "--check", str(DIGEST_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
