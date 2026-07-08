"""P0-4 — De-workspace the surface (docs/backlog/road-to-market.md).

A non-technical user must never see model names, token counters, endpoint
jargon, or AI-workspace furniture on the default surface. These tests pin the
four DoD behaviours against the ACTUAL shipped source (same conventions as
``test_applicant_round1_portal.py``: read the real files, execute real slices
under Node where behaviour matters — never re-implement the logic under test):

1. The engine-backed Applicant chat speaks as "Applicant" — live turns,
   persisted turns, and legacy pre-rename history alike — and renders no
   model-name literals, no token/speed counters, no context-percent chip,
   no per-message edit/delete controls, and no composer model picker.
2. Non-product workspace modules (Notes, Tasks, Cookbook, Deep Research, the
   duplicate image gallery) stay hidden from the default nav/rail.
3. Padlocks → absence: gated sections hide until they become real (the
   detailed gating pins live in ``test_applicant_round1_portal.py``; here we
   pin the CSS contract the gating relies on).
4. The Documents window is titled "Documents" (not "Library") and the Daily
   updates window is titled "Daily updates" (not "Email"), dock chips included.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
CHAT_JS = _REPO / "static" / "js" / "applicantChat.js"
APP_JS = _REPO / "static" / "app.js"
INDEX_HTML = _REPO / "static" / "index.html"
STYLE_CSS = _REPO / "static" / "style.css"
DOCLIB_JS = _REPO / "static" / "js" / "documentLibrary.js"
EMAILLIB_JS = _REPO / "static" / "js" / "emailLibrary.js"
MODALMGR_JS = _REPO / "static" / "js" / "modalManager.js"
CHAT_ROUTES = _REPO / "routes" / "applicant_chat_routes.py"

_HAS_NODE = shutil.which("node") is not None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


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


def _extract_fn(src: str, signature: str) -> str:
    """Brace-balanced extraction of a real function body out of shipped source."""
    start = src.index(signature)
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


# ===========================================================================
# DoD 1 — the Applicant chat speaker reads "Applicant"
# ===========================================================================

def test_live_speaker_label_is_applicant():
    src = _read(CHAT_JS)
    assert re.search(r"const ASSISTANT_LABEL = 'Applicant';", src), (
        "the engine chat's live bubbles must speak as 'Applicant'"
    )
    # Both live call sites (the intro greeting and the thinking/reply bubble)
    # must label through the ONE constant, not a stray literal.
    calls = re.findall(r"addMessage\('assistant',[^)]*\)", src)
    assert calls, "expected assistant addMessage call sites in applicantChat.js"
    for call in calls:
        assert "ASSISTANT_LABEL" in call, f"call site bypasses ASSISTANT_LABEL: {call}"


def test_persisted_speaker_label_is_applicant():
    src = _read(CHAT_ROUTES)
    assert 'ENGINE_SPEAKER_NAME = "Applicant"' in src
    assert re.search(r'"character_name":\s*ENGINE_SPEAKER_NAME', src), (
        "persisted turns must carry character_name='Applicant' so history "
        "reloads label identically to live turns"
    )


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_legacy_history_labels_normalize_to_applicant_without_losing_timestamp():
    """Execute the REAL _normalizeSpeakerLabels against a minimal fake DOM: a
    pre-rename bubble ('Job assistant' + a timestamp child) must relabel to
    'Applicant' keeping the timestamp; an unrelated label must be untouched."""
    src = _read(CHAT_JS)
    # The normalize pass delegates to the shared _rewriteLegacyRoleLabel
    # helper — slice BOTH so the executed harness matches shipped composition.
    fn = (
        _extract_fn(src, "function _rewriteLegacyRoleLabel(roleEl)")
        + "\n"
        + _extract_fn(src, "function _normalizeSpeakerLabels()")
    )
    label = re.search(r"const ASSISTANT_LABEL = '([^']+)';", src).group(1)
    legacy = re.search(r"const LEGACY_ASSISTANT_LABEL = '([^']+)';", src).group(1)
    script = textwrap.dedent(f"""
        const ASSISTANT_LABEL = {json.dumps(label)};
        const LEGACY_ASSISTANT_LABEL = {json.dumps(legacy)};
        function mkRole(text) {{
            const textNode = {{ nodeType: 3, nodeValue: text }};
            const stamp = {{ nodeType: 1, textContent: '12:34' }};
            return {{ firstChild: textNode, _stamp: stamp }};
        }}
        const legacyRole = mkRole(LEGACY_ASSISTANT_LABEL);
        const otherRole = mkRole('You');
        const document = {{
            querySelectorAll: (sel) =>
                sel === '#chat-history .msg-ai .role' ? [legacyRole, otherRole] : [],
        }};
        {fn}
        _normalizeSpeakerLabels();
        console.log(JSON.stringify({{
            legacyNow: legacyRole.firstChild.nodeValue,
            stampKept: legacyRole._stamp.textContent,
            otherUntouched: otherRole.firstChild.nodeValue,
        }}));
    """)
    out = _run_node(script)
    assert out["legacyNow"] == "Applicant"
    assert out["stampKept"] == "12:34"
    assert out["otherUntouched"] == "You"


# ===========================================================================
# DoD 1 — the Applicant chat surface renders NO model-name literals and no
# token/speed/context counters
# ===========================================================================

#: Vocabulary that must never appear in the engine-chat surface module: common
#: model-family names (any one rendering would leak "this is an LLM wrapper")
#: plus the workspace's own counter jargon.
_BANNED_CHAT_SURFACE_LITERALS = (
    "gpt",
    "claude",
    "gemini",
    "llama",
    "mistral",
    "qwen",
    "deepseek",
    "sonnet",
    "haiku",
    "openai",
    "anthropic",
    "tok/s",
    "tokens_per_second",
    "context_percent",
    "ctx-ring",
)


def test_chat_surface_contains_no_model_name_literals():
    src = _read(CHAT_JS).lower()
    hits = [lit for lit in _BANNED_CHAT_SURFACE_LITERALS if lit in src]
    assert not hits, (
        f"applicantChat.js contains model-name/counter literals {hits} — the "
        "Applicant chat surface must never render model names, tok/s, or "
        "context-percent chips"
    )


def test_chat_surface_never_invokes_the_metrics_renderer():
    """displayMetrics (chatRenderer) is the ONLY thing that renders tok/s, token
    counts, cost, and the context ring. The engine send path must never call it,
    and the persisted engine turns must never carry the fields that trigger it
    on a history reload (response_time / output_tokens / tokens_per_second /
    context_percent)."""
    assert "displayMetrics" not in _read(CHAT_JS)
    routes = _read(CHAT_ROUTES)
    # Anchor on the next top-level def, not a named sibling — reordering the
    # module must not silently mis-scope this pin (CodeRabbit on #745).
    _m = re.search(r"\ndef _persist_chat_turn[\s\S]*?(?=\n(?:async )?def )", routes)
    assert _m, "_persist_chat_turn definition not found"
    persist = _m.group(0)
    for metric_field in ("response_time", "output_tokens", "tokens_per_second", "context_percent"):
        assert metric_field not in persist, (
            f"_persist_chat_turn must not persist {metric_field} — it would make "
            "the native renderer draw a token/speed counter on the engine chat"
        )


def test_chat_surface_hides_composer_model_picker_and_prunes_message_actions():
    src = _read(CHAT_JS)
    # Composer model picker hidden while the engine session is active…
    mount = _extract_fn(src, "function _mountExtras()")
    assert "model-picker-wrap" in mount and "display = 'none'" in mount
    # …and restored when the user switches to a raw-LLM session (the raw path
    # stays reachable, unchanged).
    unmount = _extract_fn(src, "function _unmountExtras()")
    assert "model-picker-wrap" in unmount
    # Per-message edit/delete/regenerate controls are pruned from engine turns.
    prune = _extract_fn(src, "function _pruneBubbleActions(wrap)")
    assert ".msg-footer .msg-action-btn" in prune
    assert "_pruneThreadActions" in mount, (
        "mounting the engine chat must sweep history bubbles too"
    )


# ===========================================================================
# DoD 2 — non-product workspace modules stay hidden from default nav/rail
# ===========================================================================

def test_non_product_modules_hidden_from_default_rail_and_sidebar():
    html = _read(INDEX_HTML)
    for launcher_id in (
        "rail-research", "rail-cookbook", "rail-gallery", "rail-notes", "rail-tasks",
        "tool-cookbook-btn", "tool-research-btn", "tool-gallery-btn",
        "tool-notes-btn", "tool-tasks-btn",
    ):
        m = re.search(r'<[^>]*id="%s"[^>]*>' % re.escape(launcher_id), html)
        assert m, f"expected #{launcher_id} to exist (modules stay resolvable)"
        assert "display:none" in m.group(0), (
            f"#{launcher_id} must stay hidden on the default surface — "
            "Notes/Tasks/Cookbook/Research/native-Gallery are not part of Applicant"
        )


def test_command_palette_lists_only_applicant_surfaces():
    palette = _read(_REPO / "static" / "js" / "commandPalette.js")
    for absent in ("Notes", "Tasks", "Cookbook", "Deep Research"):
        assert f"label: '{absent}'" not in palette, (
            f"the command palette must not offer the non-product surface {absent!r}"
        )


# ===========================================================================
# DoD 3 — padlocks → absence (CSS contract; behaviour pinned in
# test_applicant_round1_portal.py)
# ===========================================================================

def test_gated_hidden_css_rule_exists_and_wins_over_inline_display():
    css = _read(STYLE_CSS)
    m = re.search(r"\.applicant-gated-hidden\s*\{([^}]*)\}", css)
    assert m, "expected the .applicant-gated-hidden rule (padlocks → absence)"
    body = m.group(1)
    assert "display: none" in body and "!important" in body, (
        "the hide rule must beat any inline display another renderer sets"
    )


def test_no_lock_glyph_anywhere_in_the_gating_pass():
    src = _read(APP_JS)
    start = src.index("window.refreshApplicantFeatures = function")
    end = src.index("window._applicantFeaturesReady", start)
    assert "🔒" not in src[start:end]


# ===========================================================================
# DoD 4 — window titles: Documents (not "Library"), Daily updates (not "Email")
# ===========================================================================

def test_documents_window_title_and_dock_chip_read_documents():
    doclib = _read(DOCLIB_JS)
    assert "Documents</h4>" in doclib, (
        "the Documents window header must be titled 'Documents'"
    )
    assert "Library</h4>" not in doclib
    mgr = _read(MODALMGR_JS)
    assert re.search(r"'doclib-modal':\s*\{\s*label:\s*'Documents'", mgr)
    assert "label: 'Library'" not in mgr


def test_daily_updates_window_title_and_dock_chip_read_daily_updates():
    email = _read(EMAILLIB_JS)
    header = email[: email.index("email-lib-unread-badge")]
    assert "Daily updates" in header.rsplit("<h4>", 1)[-1], (
        "the Daily updates window header must be titled 'Daily updates'"
    )
    assert re.search(
        r"Modals\.register\('email-lib-modal',\s*\{[^}]*label:\s*'Daily updates'",
        email,
        re.S,
    ), "the Daily updates dock chip must match the window title"
    mgr = _read(MODALMGR_JS)
    assert re.search(r"'email-lib-modal':\s*\{\s*label:\s*'Daily updates'", mgr)


def test_pwa_route_titles_follow_the_product_names():
    html = _read(INDEX_HTML)
    assert "'/library': 'Documents — Applicant'" in html
    assert "'/email': 'Daily updates — Applicant'" in html
    assert "'Library — Applicant'" not in html
    assert "'Email — Applicant'" not in html
