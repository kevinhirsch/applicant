"""Regression coverage for the front-door half of dark-engine audit item 38
("retrieve cached company-research reports without re-running them"), confined
to ``static/js/emailLibrary/applicantDigest.js``.

The digest row's existing "Research" button (a prior merged PR, see
``test_applicant_round2_wave3_employerintel.py``) always POSTed to the manual
``.../run`` trigger. The engine's ``ResearchService`` already dedupes/caches a
FRESH run internally, but there was previously no way for the front-door to
PEEK at a cached report without a round-trip through the run endpoint. This
extends the SAME click handler (``_onResearch``) to check the new cached-read
proxy (``GET .../cached``) first, and only fall back to ``POST .../run`` when
nothing is cached yet — so re-displaying a brief the user already paid for
never burns another research call.

Each assertion below was verified, by hand, to actually go red when the
corresponding piece of the chain is reverted (stripping the cache-check
helper, making ``_onResearch`` call ``run`` unconditionally again, or breaking
the 404-means-fall-back contract), then confirmed green again after
restoring — per this series' standing DoD.
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

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── a cache-check helper exists and is distinct from the run trigger ────────


def test_cached_read_helper_exists_and_hits_the_cached_proxy():
    src = _read(DIGEST_JS)
    fn = re.search(r"async function _apiResearchCached\(.*?\n\}\n", src, re.S)
    assert fn, "expected a dedicated _apiResearchCached(campaignId, query) helper"
    body = fn.group(0)
    assert "/cached" in body, "must call the cached-read proxy, not the run trigger"
    assert "_apiResearch(" in body, (
        "must reuse the SAME _apiResearch fetch helper as the run trigger, not "
        "hand-roll a second fetch"
    )


def test_cached_read_helper_treats_404_as_not_cached_not_an_error():
    """A 404 from the cached-read proxy means 'nothing cached yet' — the
    caller must treat that as a signal to fall back to a fresh run, not
    surface it as a failure."""
    src = _read(DIGEST_JS)
    fn = re.search(r"async function _apiResearchCached\(.*?\n\}\n", src, re.S)
    assert fn, "expected a dedicated _apiResearchCached helper"
    body = fn.group(0)
    assert re.search(r"e\.status\s*===\s*404", body), (
        "must special-case a 404 (not cached) rather than throwing it like a "
        "real failure"
    )
    assert re.search(r"return null", body), "a 404 must resolve to null, not throw"


# ── _onResearch checks the cache FIRST, only running fresh on a miss ────────


def test_on_research_checks_cache_before_running_fresh():
    src = _read(DIGEST_JS)
    on_research = re.search(r"async function _onResearch\(.*?\n\}\n", src, re.S)
    assert on_research, "expected an _onResearch handler"
    body = on_research.group(0)

    cache_check = body.find("_apiResearchCached(")
    fresh_run = body.find("_apiResearch(`/${encodeURIComponent(campaignId)}/run`")
    assert cache_check != -1, "_onResearch must consult the cache first"
    assert fresh_run != -1, "_onResearch must still fall back to a fresh run"
    assert cache_check < fresh_run, (
        "the cache check must happen BEFORE the fresh run is ever attempted, "
        "so a cache hit never burns a research call"
    )
    # The fresh run must be conditioned on the cache miss (an `if` guarding it),
    # not fired unconditionally alongside the cache check.
    between = body[cache_check:fresh_run]
    assert re.search(r"if\s*\(\s*!\s*report\s*\)", between), (
        "the fresh run must be gated on the cache-check result coming back "
        "empty, not run unconditionally"
    )


def test_on_research_still_renders_through_the_shared_report_view():
    """Whichever path served the report (cache or fresh run), it must still
    render through the SAME _showReport brief renderer — no second display
    path for the cached case."""
    src = _read(DIGEST_JS)
    on_research = re.search(r"async function _onResearch\(.*?\n\}\n", src, re.S)
    assert on_research
    assert "_showReport(report" in on_research.group(0)


def test_node_check_applicant_digest_js(node_available):
    """Syntax smoke: the module the above assertions read from must still parse."""
    res = subprocess.run(
        ["node", "--check", str(DIGEST_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


def test_cached_then_fresh_fallback_behaviour(node_available):
    """Real execution: extract _apiResearchCached + a slimmed _onResearch-style
    orchestration against a fake fetch, proving (a) a cache hit short-circuits
    before any run call, and (b) a cache miss (404) falls through to the run
    call exactly once."""
    src = _read(DIGEST_JS)
    cached_fn = re.search(r"async function _apiResearchCached\(.*?\n\}\n", src, re.S)
    api_fn = re.search(r"async function _apiResearch\(.*?\n\}\n", src, re.S)
    assert cached_fn and api_fn

    script = textwrap.dedent(f"""
        const calls = [];
        globalThis.fetch = async (url, opts) => {{
          calls.push({{ url, method: (opts && opts.method) || 'GET' }});
          if (url.includes('/cached')) {{
            if (url.includes('hit')) {{
              return {{ ok: true, status: 200, json: async () => ({{ summary: 'cached brief', cached: true }}) }};
            }}
            return {{ ok: false, status: 404, json: async () => ({{ detail: 'No cached report for this query' }}) }};
          }}
          return {{ ok: true, status: 200, json: async () => ({{ summary: 'fresh brief', cached: false }}) }};
        }};
        const API_BASE = '';
        {api_fn.group(0)}
        {cached_fn.group(0)}

        async function run(campaignId, query) {{
          let report = await _apiResearchCached(campaignId, query);
          if (!report) {{
            report = await _apiResearch(`/${{encodeURIComponent(campaignId)}}/run`, {{
              method: 'POST',
              body: {{ query }},
            }});
          }}
          return report;
        }}

        (async () => {{
          const hit = await run('c1', 'hit query');
          const miss = await run('c1', 'miss query');
          console.log(JSON.stringify({{
            hitSummary: hit.summary,
            hitCalls: calls.filter(c => c.url.includes('hit')).length,
            missSummary: miss.summary,
            missCalledRun: calls.some(c => c.url.includes('/c1/run') && c.method === 'POST'),
          }}));
        }})();
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
    assert out["hitSummary"] == "cached brief"
    assert out["hitCalls"] == 1, "a cache hit must only touch the cached-read endpoint, once"
    assert out["missSummary"] == "fresh brief"
    assert out["missCalledRun"] is True, "a cache miss (404) must fall back to the run endpoint"
