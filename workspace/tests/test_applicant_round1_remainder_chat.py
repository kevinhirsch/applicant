"""Chat-unification regression coverage for ``static/js/applicantChat.js``.

This file originally guarded the two §C Chat design-audit follow-ups
(APPLE_GENIUS_IMPROVEMENTS.md items 46 and 64) on the Job Assistant's own
modal panel: docking that panel to the real composer band + dimming the real
composer underneath it (#46), and adopting the .ow-window titlebar kit (#64).

The chat-unification pass RETIRES that modal entirely: the Job Assistant now
resolves a dedicated engine-backed workspace session (GET
/api/applicant/chat/session) and opens it in the NATIVE chat surface via
selectSession() — the same pattern assistant.js uses for the personal
assistant. Both audit items are thereby superseded, not regressed: there is
no second panel to dock/dim (the conversation lives in the one real chat
plane, with the one real composer), and no bespoke window chrome to align
with the kit. What this file now guards is that the retirement is total —
no half-modal resurrects — and that the unified plumbing stays wired.

(Note for the theme owner: the now-dormant ``#applicant-chat-modal`` blocks
in static/style.css were deliberately left untouched by this pass — style.css
is owned by the theme lane; they are dead selectors safe to sweep later.)

Follows the established convention: every fact is read from the actual
static file content via ``pathlib`` + regex — no browser, no DOM, no real
socket (``applicantChat.js`` does top-level ``document`` work on import, so
it is not importable under a bare ``node --input-type=module``).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CHAT_JS = JS_DIR / "applicantChat.js"
CHAT_CORE_JS = JS_DIR / "chat.js"
RENDERER_JS = JS_DIR / "chatRenderer.js"
SESSIONS_JS = JS_DIR / "sessions.js"
MODEL_PICKER_JS = JS_DIR / "modelPicker.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# The modal really is retired — no scaffold, no dimming, no window chrome.
# ===========================================================================


def test_chat_modal_scaffold_is_fully_retired():
    src = _read(CHAT_JS)
    assert "applicant-chat-modal" not in src, "the retired modal's element id resurfaced"
    assert "_ensureModalEl" not in src
    assert "modal-content" not in src
    assert "--window-w" not in src, "no bespoke window sizing — the native plane owns layout"


def test_chat_composer_dimming_is_gone_with_the_overlay():
    """Item #46's composer-dimming existed only because the modal covered the
    real composer's band. With the conversation living IN the native plane
    there is nothing to dim — the helper must not linger as dead code."""
    src = _read(CHAT_JS)
    assert "_setComposerDimmed" not in src
    assert "#chat-container > .chat-input-bar" not in src


def test_chat_window_kit_chrome_is_gone_with_the_modal():
    """Item #64's .ow-window titlebar adoption is superseded — no second
    window means no titlebar to align with the kit."""
    src = _read(CHAT_JS)
    assert "ow-window" not in src
    assert "ow-titlebar" not in src
    assert "ow-close" not in src


# ===========================================================================
# The unified plumbing: launcher → session bootstrap → native surface.
# ===========================================================================


def test_launcher_resolves_the_engine_session_and_opens_it_natively():
    src = _read(CHAT_JS)
    m = re.search(r"export async function openApplicantChat\(opts\)\s*\{(.*?)\n\}\n", src, re.S)
    assert m, "expected openApplicantChat(opts)"
    body = m.group(1)
    assert "${API}/session" in body or "`${API}/session`" in src, (
        "openApplicantChat must resolve the per-user session via GET /api/applicant/chat/session"
    )
    assert "selectSession(_sessionId)" in body, (
        "the resolved session must open through the NATIVE selectSession path"
    )


def test_engine_session_identified_by_endpoint_sentinel():
    src = _read(CHAT_JS)
    assert "const ENGINE_SESSION_URL = 'applicant://engine';" in src
    m = re.search(r"export function isEngineSession\(meta\)\s*\{(.*?)\n\}\n", src, re.S)
    assert m and "ENGINE_SESSION_URL" in m.group(1), (
        "isEngineSession must key off the endpoint sentinel (survives renames)"
    )
    assert "export function isEngineSessionActive()" in src


def test_chat_send_path_dispatches_engine_sessions_to_the_proxy():
    """chat.js's handleChatSubmit must hand Job Assistant sends to
    sendEngineMessage() BEFORE the LLM streaming path — the engine owns this
    conversation's replies."""
    src = _read(CHAT_CORE_JS)
    seam = re.search(
        r"window\.applicantChatModule\.isEngineSessionActive\(\)(.*?)"
        r"window\.applicantChatModule\.sendEngineMessage\(msg\);",
        src,
        re.S,
    )
    assert seam, "expected the Job Assistant dispatch seam in handleChatSubmit"
    # The seam must run before the pending-session materialization /
    # streaming machinery, i.e. appear before the fetch of /api/default-chat.
    assert src.index("window.applicantChatModule.sendEngineMessage(msg);") < src.index(
        "'/api/default-chat'"
    ), "the dispatch seam must precede the native auto-create/streaming path"


def test_renderer_has_the_per_message_decoration_seam():
    """chatRenderer.addMessage must hand engine turns (metadata.applicant) to
    decorateEngineMessage so the job-action chips render identically on the
    live send and on a history reload."""
    src = _read(RENDERER_JS)
    assert "metadata.applicant" in src
    assert "import('./applicantChat.js')" in src
    assert "decorateEngineMessage" in src


def test_sessions_module_announces_session_switches():
    """The session-type dispatch seam: selectSession must fire the
    'applicant:session-selected' event so the Job Assistant can mount/unmount
    its per-session extras (job-search bar + composer hint)."""
    src = _read(SESSIONS_JS)
    assert "applicant:session-selected" in src
    chat = _read(CHAT_JS)
    assert "document.addEventListener('applicant:session-selected'" in chat


def test_model_picker_hides_for_the_engine_session():
    """The engine session has no swappable LLM endpoint — the model picker
    must hide for it exactly like it does for group chat, via the same
    isEngineSessionActive seam."""
    src = _read(MODEL_PICKER_JS)
    assert "window.applicantChatModule" in src
    assert "isEngineSessionActive" in src


def test_hash_route_still_registered_and_redirects_into_the_native_surface():
    """The old '#chat' deep link must keep working: the route stays
    registered, and its open() path lands on selectSession (which swaps the
    hash to the canonical '#<sessionId>' form), so nothing 404s."""
    src = _read(CHAT_JS)
    assert re.search(
        r"registerRoute\(\s*'chat'\s*,\s*\{\s*open:\s*openApplicantChat\s*,\s*close:\s*_close\s*\}\s*\)",
        src,
    )
    assert "clearHash('chat')" in src


def test_public_module_surface_keeps_external_callers_working():
    """applicantDebug.js / commandPalette.js / applicantGallery.js all reach
    the Job Assistant through window.applicantChatModule.openApplicantChat —
    the unified module must keep that public seam (plus the new dispatch
    hooks) intact."""
    src = _read(CHAT_JS)
    m = re.search(r"const applicantChatModule = \{([^}]*)\}", src, re.S)
    assert m, "expected the module object literal"
    body = m.group(1)
    for name in (
        "openApplicantChat",
        "closeApplicantChat",
        "isEngineSession",
        "isEngineSessionActive",
        "sendEngineMessage",
        "decorateEngineMessage",
    ):
        assert name in body, f"missing {name} on the public module object"
    assert "window.applicantChatModule = applicantChatModule;" in src
