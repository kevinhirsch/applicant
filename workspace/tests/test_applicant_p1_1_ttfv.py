"""P1-1 — onboarding time-to-first-value: front-door critical-path hardening.

Engine-side coverage lives in ``tests/unit/test_p1_1_ttfv_walkthrough.py``
(3-action golden path, achievements prefill, single-year education). This file
pins the FRONT-DOOR pieces the story added:

* the model Verify (Test) round-trip reports the failure *reason* — bad key /
  unreachable / no models — each with a specific recovery action, instead of a
  bare "Offline" (``model_routes.py`` classifies; ``admin.js`` renders);
* every known cloud provider gets a one-tap "get a key" pointer next to the
  key field (OpenRouter et al.), so a brand-new user is never stranded;
* Today shows the setup-essentials checklist (model / profile / notifications,
  done-vs-left) while the apply gate is closed — on the gated state AND on the
  onboarding-incomplete card — both keeping the one-tap wizard resume;
* the portal proxy derives that checklist from the SAME engine setup-status
  fields the wizard reads, omitting (never fabricating) unknown fields;
* the wizard finish screen carries the "What happens next" card (first digest
  + approval flow) so the user leaves setup knowing what to expect.

The JS assertions follow the established harness pattern: slice the real
function bodies out of the shipped source and execute them under node.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
ADMIN_JS = _REPO / "static" / "js" / "admin.js"
TODAY_JS = _REPO / "static" / "js" / "applicantToday.js"
ONBOARDING_JS = _REPO / "static" / "js" / "applicantOnboarding.js"
INDEX_HTML = _REPO / "static" / "index.html"
MODEL_ROUTES = _REPO / "routes" / "model_routes.py"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


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


def _esc_stub() -> str:
    return (
        "function esc(s) { return (s == null ? '' : String(s)).replace(/[&<>\"']/g, "
        "(c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])); }"
    )


# ===========================================================================
# Verify round-trip: server-side failure-reason classification
# ===========================================================================


def test_test_endpoint_classifies_bad_key_no_models_unreachable():
    src = _read(MODEL_ROUTES)
    block = _slice_between(
        src, '@router.post("/model-endpoints/test")', "def probe_endpoint_models"
    )
    # The three failure classes + the happy path, and the auth-rejection codes.
    for token in ['"ok"', '"no_models"', '"bad_key"', '"unreachable"']:
        assert token in block, f"expected reason {token} in the test endpoint"
    assert re.search(r"status_code.*in \(401, 403\)", block), (
        "bad_key must be classified from an HTTP 401/403 auth rejection"
    )
    assert '"reason": reason' in block, "the reason must ship in the response"


def test_ping_endpoint_uses_provider_specific_auth_and_path():
    # A rejected Anthropic key must classify as bad_key, not unreachable
    # (Greptile on #738): the fallback ping has to hit the SAME /v1/models +
    # x-api-key surface the probe uses — the generic Bearer + /models pair
    # 404s on Anthropic, which would tell the user to fix the URL instead of
    # replacing the rejected key.
    src = _read(MODEL_ROUTES)
    block = _slice_between(src, "def _ping_endpoint", "\ndef ")
    assert "_provider_headers(api_key, base)" in block, (
        "ping must build provider-specific auth headers (x-api-key for Anthropic)"
    )
    assert "_models_url(base)" in block, (
        "ping must resolve the models URL through the SAME shared helper the "
        "probe uses (Anthropic /v1/models, Ollama /tags) — no hand-rolled copy"
    )


# ===========================================================================
# Verify round-trip: admin.js renders reason-specific recovery copy
# ===========================================================================


def _render_test_result_block() -> str:
    return _slice_between(
        _read(ADMIN_JS),
        "function _renderEndpointTestResult(msg, res, d) {",
        "function _endpointMsg(kind)",
    )


def test_bad_key_and_unreachable_get_distinct_recovery_copy(node_available):
    block = _render_test_result_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        let m;
        m = {{}}; _renderEndpointTestResult(m, {{ ok: false }}, {{ reason: 'bad_key' }});
        out.badKey = m.textContent; out.badKeyClass = m.className;
        m = {{}}; _renderEndpointTestResult(m, {{ ok: false }}, {{ reason: 'unreachable', ping_error: 'HTTP 502' }});
        out.unreachable = m.textContent; out.unreachableClass = m.className;
        m = {{}}; _renderEndpointTestResult(m, {{ ok: true }}, {{ status: 'empty' }});
        out.empty = m.textContent;
        m = {{}}; _renderEndpointTestResult(m, {{ ok: true }}, {{ online: true, models: ['a','b'] }});
        out.online = m.innerHTML; out.onlineClass = m.className;
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    # Bad key: names the key as the problem and the fix (a fresh key).
    assert "key was rejected" in out["badKey"]
    assert "Test again" in out["badKey"]
    assert out["badKeyClass"] == "admin-error"
    # Unreachable: names the URL/server as the problem, echoes the probe error.
    assert "reach this address" in out["unreachable"]
    assert "HTTP 502" in out["unreachable"]
    assert "check the URL" in out["unreachable"].lower() or "check the url" in out["unreachable"].lower()
    assert out["unreachableClass"] == "admin-error"
    # The two failure classes must NOT read the same — different fixes.
    assert out["badKey"] != out["unreachable"]
    # Reachable-but-empty: recovery action (pull/enable a model) inline.
    assert "no models found" in out["empty"]
    assert "Test again" in out["empty"]
    # Happy path unchanged.
    assert "found 2 models" in out["online"]
    assert out["onlineClass"] == "admin-success"


def test_older_server_without_reason_falls_back_to_prior_copy(node_available):
    """A response with no `reason` (older server) keeps the previous behavior —
    detail/ping_error/Offline — rather than crashing or mislabeling."""
    block = _render_test_result_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        let m;
        m = {{}}; _renderEndpointTestResult(m, {{ ok: false }}, {{ ping_error: 'timed out' }});
        out.legacy = m.textContent;
        m = {{}}; _renderEndpointTestResult(m, {{ ok: false }}, {{}});
        out.bare = m.textContent;
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["legacy"] == "Offline — timed out"
    assert out["bare"] == "Offline"


# ===========================================================================
# "Get a key" pointer per provider
# ===========================================================================


def test_provider_key_urls_cover_the_preset_list():
    src = _read(ADMIN_JS)
    block = _slice_between(src, "const PROVIDER_KEY_URLS = {", "};")
    # The DoR-named preset: OpenRouter with a get-a-key link.
    assert "'https://openrouter.ai/api/v1': 'https://openrouter.ai/keys'" in block
    # Every provider preset in the picker has a key URL (no dead pointer).
    html = _read(INDEX_HTML)
    select = _slice_between(html, '<select id="adm-epProvider"', "</select>")
    for base in re.findall(r'option value="(https?://[^"]+)"', select):
        assert f"'{base}':" in block, f"provider preset {base} has no get-a-key URL"


def test_key_help_element_exists_and_link_is_safe():
    html = _read(INDEX_HTML)
    assert 'id="adm-epKeyHelp"' in html
    src = _read(ADMIN_JS)
    block = _slice_between(src, "function _syncKeyHelp()", "provider.addEventListener('change'")
    assert 'target="_blank"' in block and 'rel="noopener"' in block
    assert "No key yet?" in block
    # Hidden for Custom URL / unknown providers — never a wrong link.
    assert "help.style.display = 'none'" in block
    # Wired on provider change AND cleared when the user types a custom URL.
    assert src.count("_syncKeyHelp()") >= 3


# ===========================================================================
# Today: setup-essentials checklist (model / profile / notifications)
# ===========================================================================


def _essentials_block() -> str:
    return _slice_between(
        _read(TODAY_JS),
        "export function _essentialsChecklistHTML(essentials)",
        "function _renderComplete(wrap, item)",
    )


def test_essentials_checklist_renders_done_vs_left(node_available):
    block = _essentials_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.mixed = _essentialsChecklistHTML([
          {{ key: 'model', label: 'Connect a model', done: true }},
          {{ key: 'profile', label: 'Your profile essentials', done: false }},
          {{ key: 'notifications', label: 'Notifications (optional)', done: false }},
        ]);
        out.empty = _essentialsChecklistHTML([]);
        out.missing = _essentialsChecklistHTML(undefined);
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    html = out["mixed"]
    assert "✓" in html and "○" in html, "done and not-done must be visually distinct"
    assert "Connect a model" in html
    assert "Your profile essentials" in html
    assert "Notifications (optional)" in html
    assert html.count("— done") == 1, "only the completed item is marked done"
    # No checklist data -> nothing rendered (older proxy degrades cleanly).
    assert out["empty"] == "" and out["missing"] == ""


def test_gated_state_and_complete_card_both_render_the_checklist():
    src = _read(TODAY_JS)
    gated = _slice_between(src, "function _renderGated(host, data)", "// ── Cost & pace guardrails")
    assert "_essentialsChecklistHTML(data && data.essentials)" in gated
    # One-tap wizard resume stays on the same gated state.
    assert "applicant-today-gated-setup" in gated
    complete = _slice_between(src, "function _renderComplete(wrap, item)", "const _AFFORDANCE_RENDERERS")
    assert "_essentialsChecklistHTML(item.essentials)" in complete
    assert "launchApplicantSetup" in complete, "one-tap wizard resume must remain"


# ===========================================================================
# Portal proxy: essentials derived from engine setup-status (omission-honest)
# ===========================================================================


class _Eng:
    def __init__(self, raw):
        self._raw = raw

    async def setup_status(self):
        return self._raw


def _gate(raw):
    import routes.applicant_portal_routes as portal

    return asyncio.run(portal._gate_state(_Eng(raw)))


def test_gate_state_builds_the_essentials_checklist():
    out = _gate(
        {
            "llm_configured": True,
            "channels_configured": False,
            "apply_ready": False,
            "apply_missing": ["a résumé"],
        }
    )
    ess = {e["key"]: e for e in out["essentials"]}
    assert set(ess) == {"model", "profile", "notifications"}
    assert ess["model"]["done"] is True
    assert ess["profile"]["done"] is False
    assert ess["notifications"]["done"] is False
    for e in ess.values():
        assert e["label"] and "FR-" not in e["label"]


def test_gate_state_profile_done_tracks_apply_readiness():
    out = _gate({"apply_ready": True, "apply_missing": []})
    ess = {e["key"]: e for e in out["essentials"]}
    assert ess["profile"]["done"] is True
    assert "model" not in ess and "notifications" not in ess  # not reported -> omitted


def test_gate_state_omits_essentials_when_engine_reports_nothing():
    """HONESTY: an older engine that reports none of the fields gets NO
    checklist — unknown state is never fabricated as not-done."""
    out = _gate({})
    assert "essentials" not in out


def test_gap_item_carries_essentials_for_the_today_card():
    import routes.applicant_portal_routes as portal

    gate = {
        "apply_ready": False,
        "apply_missing": ["salary floor"],
        "essentials": [{"key": "model", "label": "Connect a model", "done": True}],
    }
    item = portal._apply_gap_item(gate, [("c1", "Campaign 1")])
    assert item["essentials"] == gate["essentials"]
    assert item["kind"] == "onboarding_incomplete"


def test_pending_gated_path_attaches_essentials_best_effort():
    src = _read(_REPO / "routes" / "applicant_portal_routes.py")
    block = _slice_between(src, "except EngineError as exc:", "campaign_list =")
    assert 'degraded.get("gated")' in block
    assert '_gate_state(engine)' in block
    assert 'degraded["essentials"]' in block


# ===========================================================================
# Wizard finish screen: the "What happens next" card
# ===========================================================================


def test_finish_screen_explains_first_digest_and_approval_flow():
    src = _read(ONBOARDING_JS)
    start = src.index("async function _finish()")
    end = src.index("async function _maybeDismiss()")
    body = src[start:end]
    assert "What happens next" in body
    # The three beats: continuous search, first digest, approval-before-send.
    assert "around the clock" in body
    assert "first digest" in body
    assert "nothing is ever sent without your final OK" in body
    # Rendered into the same completion screen (not a new step/surface).
    assert "${whatNextCard}" in body
