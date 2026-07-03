"""Regression coverage for dark-engine audit item #55: the engine's per-posting
viability score + plain-language rationale (`JobPosting.viability_score` /
`.rationale`, `src/applicant/core/entities/job_posting.py`, populated by
`ScoringService.score_viability`) rendered ONLY inside the digest lane
(workspace/static/js/emailLibrary/applicantDigest.js), with every other
posting-showing surface reachable from the front-door (Gallery, Results,
Tracker) either not showing individual postings at all or showing them with
no score/why.

The Pending-Actions Portal (workspace/static/js/applicantPortal.js) is a
genuinely distinct surface from the digest (it is the post-login home base and
in-app notification center, not the Email tab) that already carries one
`digest_approval` pending-action row per SPECIFIC scored posting (see
`DigestService.deliver` / `PendingActionsService.digest_approval` on the
engine side: `payload = {posting_id, link, score}`), but its card
(`_renderDigest`) used to render nothing but a generic "Review applications"
button — no title, no score, no why. This confines the fix to `_renderDigest`
(now shows the persisted `payload.score` synchronously) plus the new
`_wireDigestWhy`/`_digestRowsForCampaign` lazy loader (fills in the
plain-language "why" by reusing the EXACT SAME `digestModule.fetchDigest`
read + `why_suggested` field the digest panel itself already uses — no
second scoring/formatting implementation, no engine change).

Every fact below is read from the ACTUAL current source of
workspace/static/js/applicantPortal.js (no duplicated re-implementation of the
logic under test), following the same two precedents already established for
this file by workspace/tests/test_applicant_round1_portal.py and
workspace/tests/test_applicant_round2_wave1_portal.py:

  * plain Python regex-over-source-text for markup/wiring facts (this file is
    not a pure leaf module — it touches `document`/`window`/`fetch` at import
    time, so a full module import under Node is impractical), and
  * extracting REAL private functions' source text out of the live file at
    test time and running them under `node --input-type=module` against
    minimal fake DOM/fetch stand-ins, so the pure logic under test is
    genuinely executed, not just pattern-matched.

Every assertion here was verified against a temporary revert of the
corresponding change (edit -> rerun -> confirm a real AssertionError ->
restore) before being left in its final, passing form.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
PORTAL_JS = _REPO / "static" / "js" / "applicantPortal.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _portal_src() -> str:
    return PORTAL_JS.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


# ===========================================================================
# _digestScoreLine / _renderDigest — the score renders synchronously from the
# pending action's own persisted payload, real data, no fetch required.
# ===========================================================================

def _render_digest_block() -> str:
    src = _portal_src()
    return _slice_between(src, "function _digestScoreLine(item) {", "function _renderConfirmChange(item) {")


def test_render_digest_shows_the_matched_role_score_from_the_payload(node_available):
    block = _render_digest_block()
    script = textwrap.dedent(f"""
        function esc(s) {{ return String(s == null ? '' : s); }}

        {block}

        const out = {{}};
        out.withScore = _renderDigest({{
          id: 'pa-1', campaign_id: 'camp-1',
          payload: {{ posting_id: 'post-1', score: 87, link: 'https://example.com/job' }},
        }});
        out.withoutScore = _renderDigest({{ id: 'pa-2', campaign_id: 'camp-1', payload: {{}} }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert "87% match" in out["withScore"], (
        "the pending action's own persisted viability score should render "
        "immediately, without any extra fetch"
    )
    assert "% match" not in out["withoutScore"], (
        "a row with no score in its payload must not fabricate one"
    )


def test_render_digest_emits_a_why_placeholder_keyed_to_the_posting_and_campaign(node_available):
    block = _render_digest_block()
    script = textwrap.dedent(f"""
        function esc(s) {{ return String(s == null ? '' : s); }}

        {block}

        const out = {{}};
        out.withPosting = _renderDigest({{
          id: 'pa-1', campaign_id: 'camp-1',
          payload: {{ posting_id: 'post-1', score: 87 }},
        }});
        out.withoutPosting = _renderDigest({{ id: 'pa-2', campaign_id: 'camp-1', payload: {{}} }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert 'data-digest-why="pa-1"' in out["withPosting"]
    assert 'data-digest-posting="post-1"' in out["withPosting"]
    assert 'data-digest-campaign="camp-1"' in out["withPosting"]
    assert "data-digest-why" not in out["withoutPosting"], (
        "a row with no posting id to look up must not render a dangling why placeholder"
    )


# ===========================================================================
# _wireDigestWhy / _digestRowsForCampaign — the plain-language "why" is filled
# in lazily from the SAME digest read (`digestModule.fetchDigest`) the digest
# panel itself uses, one fetch per campaign even when several rows share it.
# ===========================================================================

def _why_wiring_block() -> str:
    src = _portal_src()
    return _slice_between(
        src, "function _digestRowsForCampaign(campaignId) {", "function _openRedline(appId) {"
    )


def _fake_dom_prelude() -> str:
    return textwrap.dedent("""
        class FakeEl {
          constructor(attrs) { this._attrs = attrs; this.textContent = ''; this.title = ''; }
          getAttribute(name) { return this._attrs[name] != null ? this._attrs[name] : ''; }
        }
        class FakeHost {
          constructor(els) { this._els = els; }
          querySelectorAll(sel) {
            if (sel === '[data-digest-why]') return this._els;
            return [];
          }
        }
    """)


def test_wire_digest_why_fills_the_placeholder_from_the_matching_digest_row(node_available):
    block = _why_wiring_block()
    script = textwrap.dedent(f"""
        {_fake_dom_prelude()}
        let fetchCalls = [];
        const digestModule = {{
          fetchDigest: async (campaignId) => {{
            fetchCalls.push(campaignId);
            return {{ rows: [
              {{ posting_id: 'post-1', why_suggested: 'Strong match on Python and remote work.' }},
              {{ posting_id: 'post-2', why_suggested: 'Good title match, salary not listed.' }},
            ] }};
          }},
        }};

        {block}

        const out = {{}};
        const el1 = new FakeEl({{ 'data-digest-posting': 'post-1', 'data-digest-campaign': 'camp-1' }});
        const el2 = new FakeEl({{ 'data-digest-posting': 'post-2', 'data-digest-campaign': 'camp-1' }});
        const host = new FakeHost([el1, el2]);

        (async () => {{
          await _wireDigestWhy(host);
          out.el1Text = el1.textContent;
          out.el2Text = el2.textContent;
          out.el1Title = el1.title;
          out.fetchCallCount = fetchCalls.length;
          console.log(JSON.stringify(out));
        }})();
    """)
    out = _run_node(script)
    assert out["el1Text"] == "Strong match on Python and remote work."
    assert out["el2Text"] == "Good title match, salary not listed."
    assert out["el1Title"] == "Why the assistant suggested this"
    assert out["fetchCallCount"] == 1, (
        "two rows from the SAME campaign should share one digest fetch, not "
        "one request per row"
    )


def test_wire_digest_why_leaves_the_line_blank_when_the_posting_has_dropped_out_of_the_digest(node_available):
    block = _why_wiring_block()
    script = textwrap.dedent(f"""
        {_fake_dom_prelude()}
        const digestModule = {{
          fetchDigest: async () => ({{ rows: [] }}),
        }};

        {block}

        const out = {{}};
        const el = new FakeEl({{ 'data-digest-posting': 'post-gone', 'data-digest-campaign': 'camp-1' }});
        const host = new FakeHost([el]);

        (async () => {{
          await _wireDigestWhy(host);
          out.text = el.textContent;
          console.log(JSON.stringify(out));
        }})();
    """)
    out = _run_node(script)
    assert out["text"] == "", (
        "a posting no longer present in the digest (already acted on, expired, "
        "or the engine offline) must degrade to a blank line, never throw or "
        "fabricate a rationale"
    )


def test_wire_digest_why_never_throws_when_the_digest_fetch_fails(node_available):
    block = _why_wiring_block()
    script = textwrap.dedent(f"""
        {_fake_dom_prelude()}
        const digestModule = {{
          fetchDigest: async () => {{ throw new Error('engine offline'); }},
        }};

        {block}

        const out = {{}};
        const el = new FakeEl({{ 'data-digest-posting': 'post-1', 'data-digest-campaign': 'camp-1' }});
        const host = new FakeHost([el]);

        (async () => {{
          let threw = false;
          try {{ await _wireDigestWhy(host); }} catch (e) {{ threw = true; }}
          out.threw = threw;
          out.text = el.textContent;
          console.log(JSON.stringify(out));
        }})();
    """)
    out = _run_node(script)
    assert out["threw"] is False
    assert out["text"] == ""


def test_wire_digest_why_re_fetches_on_a_later_call_never_holding_a_stale_cache(node_available):
    # Deliberately NO cross-call cache (`_renderList` calls `_wireDigestWhy` fresh
    # on every render): a later call for the same campaign must hit the digest
    # again rather than replaying a stale/expired posting's rationale.
    block = _why_wiring_block()
    script = textwrap.dedent(f"""
        {_fake_dom_prelude()}
        let fetchCalls = 0;
        const digestModule = {{
          fetchDigest: async () => {{
            fetchCalls += 1;
            return {{ rows: [{{ posting_id: 'post-1', why_suggested: 'why ' + fetchCalls }}] }};
          }},
        }};

        {block}

        (async () => {{
          const el1 = new FakeEl({{ 'data-digest-posting': 'post-1', 'data-digest-campaign': 'camp-1' }});
          await _wireDigestWhy(new FakeHost([el1]));

          const el2 = new FakeEl({{ 'data-digest-posting': 'post-1', 'data-digest-campaign': 'camp-1' }});
          await _wireDigestWhy(new FakeHost([el2]));

          console.log(JSON.stringify({{ fetchCalls, el1Text: el1.textContent, el2Text: el2.textContent }}));
        }})();
    """)
    out = _run_node(script)
    assert out["fetchCalls"] == 2, (
        "a later call must re-fetch rather than replay a previous call's rows"
    )
    assert out["el1Text"] == "why 1"
    assert out["el2Text"] == "why 2"


# ===========================================================================
# Wiring facts: the new pieces are actually reached from the render/load path.
# ===========================================================================

def test_render_list_wires_the_digest_why_lookup():
    src = _portal_src()
    block = _slice_between(src, "function _renderList(body) {", "// ── Matched-role")
    assert "_wireDigestWhy(body)" in block, (
        "_renderList must trigger the lazy why-fetch on every render, the same "
        "fire-and-forget shape as the rest of the file's lazy loaders"
    )
