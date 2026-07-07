"""ONE chat — the default chat experience is the engine-backed Applicant
assistant (chat unification, requirement 1).

The first unification pass made the Job Assistant open inside the NATIVE chat
surface (its sentinel-flagged workspace session + the send dispatch seam in
``chat.js``). This pass finishes the job: a user who clicks **New Chat**, the
rail chat entry, or just types into the bare empty-state composer must land in
the SAME engine-backed assistant — never in a second, parallel "native LLM"
brain. The raw workspace-LLM chat stays reachable only through a deliberate
model pick (model picker / models list), which document chat, Compare and
agent runs still rely on.

Source contracts (same convention as ``test_applicant_backlog_dupguard.py``:
facts read from the shipped static files — no browser, no socket):

* ``chat.js`` — a send with NO active session opens the assistant's unified
  session and dispatches through ``sendEngineMessage`` BEFORE the historical
  ``/api/default-chat`` auto-create (which survives only as the non-owner /
  engine-down fallback); an engine session is recognized by its sentinel even
  if the surface module hasn't loaded yet; the ``content_replace`` settle
  event from the server's reasoning hygiene is handled.
* ``sessions.js`` — the first-load and zero-sessions landings resolve the
  engine chat session before falling back to the default-model auto-create.
* ``applicantChat.js`` — the generic new-chat affordances (sidebar brand, New
  Chat item, rail new-session, mobile new-chat) are claimed for the assistant
  via a document-capture interceptor, gated on the boot probe that confirms
  the account owns the engine chat (the engine is single-tenant).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC_JS = REPO_ROOT / "workspace" / "static" / "js"
CHAT_JS = STATIC_JS / "chat.js"
SESSIONS_JS = STATIC_JS / "sessions.js"
APPLICANT_CHAT_JS = STATIC_JS / "applicantChat.js"
MODEL_PICKER_JS = STATIC_JS / "modelPicker.js"
SESSION_ROUTES_PY = REPO_ROOT / "workspace" / "routes" / "session_routes.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── chat.js: the bare-composer send goes to the engine path ─────────────────


def test_no_session_send_opens_the_assistant_before_the_default_model_autocreate():
    src = _read(CHAT_JS)
    m = re.search(
        r"if \(!sessionModule\.getCurrentSessionId\(\)\) \{(.*?)'/api/default-chat'",
        src,
        re.S,
    )
    assert m, "expected the no-session branch to precede the /api/default-chat fetch"
    engine_first = m.group(1)
    assert "openApplicantChat" in engine_first, (
        "a bare-composer send must resolve/open the engine-backed assistant first"
    )
    assert "sendEngineMessage(msg)" in engine_first, (
        "the send itself must dispatch through the engine path when the "
        "assistant session opened"
    )
    assert "isEngineSessionActive" in engine_first, (
        "the engine dispatch must be predicated on the assistant session "
        "actually being the active chat (non-owner accounts fall through)"
    )


def test_engine_sessions_are_recognized_by_sentinel_even_before_the_module_loads():
    """The surface module loads lazily; an engine session send must never fall
    through to the LLM streaming path just because of load order."""
    src = _read(CHAT_JS)
    assert "endpoint_url === 'applicant://engine'" in src
    guard = re.search(
        r"endpoint_url === 'applicant://engine'\) \{(.*?)\n\s*\}\n",
        src,
        re.S,
    )
    assert guard and "import('./applicantChat.js')" in guard.group(1), (
        "the sentinel guard must pull the surface module in on demand"
    )


def test_content_replace_event_rebases_the_streamed_text():
    """Server-side reasoning hygiene can settle on cleaner text than what
    streamed live; the client must honor the replace event before the final
    render."""
    src = _read(CHAT_JS)
    m = re.search(r"json\.type === 'content_replace'\) \{(.*?)\n\s*\} else if", src, re.S)
    assert m, "expected a content_replace handler in the SSE type chain"
    body = m.group(1)
    assert "accumulated = json.content" in body
    assert "roundText = accumulated" in body
    assert "_renderStream()" in body


# ── sessions.js: fresh landings resolve the engine chat first ───────────────


def test_first_load_lands_in_the_engine_chat_before_default_model_autocreate():
    src = _read(SESSIONS_JS)
    assert "async function _resolveEngineChatSession()" in src
    assert "/api/applicant/chat/session" in src
    first_load = re.search(r"if \(_isFirstLoad\) \{(.*?)\n    \}", src, re.S)
    assert first_load, "expected the first-load landing block"
    body = first_load.group(1)
    assert "_resolveEngineChatSession()" in body
    assert body.index("_resolveEngineChatSession()") < body.index("/api/default-chat"), (
        "the engine chat must be tried before the default-model auto-create"
    )


def test_zero_sessions_landing_prefers_the_engine_chat():
    src = _read(SESSIONS_JS)
    zero = re.search(
        r"if \(activeSessions\.length === 0 && !_autoCreateInProgress\) \{(.*?)_autoCreateInProgress = false;",
        src,
        re.S,
    )
    assert zero, "expected the zero-sessions auto-create block"
    body = zero.group(1)
    assert "_resolveEngineChatSession()" in body
    assert "selectSession(engineSid" in body
    assert body.index("_resolveEngineChatSession()") < body.index("/api/default-chat")


def test_selecting_a_real_session_clears_a_stale_pending_direct_chat():
    src = _read(SESSIONS_JS)
    m = re.search(r"export async function selectSession\(id.*?\{(.*?)const navToken", src, re.S)
    assert m and "_pendingChat = null;" in m.group(0), (
        "selectSession must invalidate a not-yet-materialized pending direct "
        "chat so it can't shadow the conversation the user is actually in"
    )


# ── applicantChat.js: New Chat / rail entries open the assistant ────────────


def test_new_chat_affordances_are_claimed_for_the_assistant():
    src = _read(APPLICANT_CHAT_JS)
    m = re.search(r"const NEW_CHAT_LAUNCHER_IDS = \[(.*?)\];", src, re.S)
    assert m, "expected the launcher-id list"
    ids = m.group(1)
    for launcher in (
        "sidebar-new-chat-btn",
        "rail-new-session",
        "mobile-new-chat-btn",
    ):
        assert launcher in ids, f"expected {launcher} to open the assistant"
    # The wordmark is HOME now, not a chat affordance — it must NOT open a chat;
    # it is declared separately as the Home launcher.
    assert "sidebar-brand-btn" not in ids, (
        "the wordmark is the Home launcher, not a new-chat affordance"
    )
    assert re.search(r"HOME_LAUNCHER_ID = 'sidebar-brand-btn'", src), (
        "the wordmark must be declared the Home launcher"
    )
    # Document-capture interception (wins regardless of module load order).
    assert re.search(
        r"document\.addEventListener\('click', _interceptNewChatClick, true\)", src
    ), "the interceptor must be document-capture"
    intercept = re.search(r"function _interceptNewChatClick\(e\) \{(.*?)\n\}", src, re.S)
    assert intercept, "expected the interceptor body"
    body = intercept.group(1)
    assert "if (!_unifiedPrimary) return;" in body, (
        "interception must engage only for the engine-owner account"
    )
    assert "openApplicantChat()" in body
    assert "stopPropagation()" in body
    # The wordmark routes to Today (the Portal home base), not the chat.
    assert "HOME_LAUNCHER_ID" in body and "tool-portal-btn" in body, (
        "the wordmark interception must open Today (the Portal home base)"
    )


def test_unification_probe_is_owner_gated_via_the_session_endpoint():
    """`GET /api/applicant/chat/session` is require_engine_owner-gated; the
    probe flips the unification switch only when it succeeds, so a second
    (non-owner) workspace account keeps the native chat affordances."""
    src = _read(APPLICANT_CHAT_JS)
    probe = re.search(r"async function _probeUnifiedPrimary\(\) \{(.*?)\n\}", src, re.S)
    assert probe, "expected the boot probe"
    body = probe.group(1)
    assert "${API}/session" in body
    assert "_unifiedPrimary = true;" in body
    boot = re.search(r"function _boot\(\) \{(.*?)\n\}", src, re.S)
    assert boot and "_probeUnifiedPrimary()" in boot.group(1), (
        "the probe must run at boot"
    )


def test_open_applicant_chat_reports_success_for_the_send_fallback():
    """chat.js's bare-composer dispatch needs a truthy/falsy signal to decide
    between the engine path and the non-owner fallback."""
    src = _read(APPLICANT_CHAT_JS)
    m = re.search(r"export async function openApplicantChat\(opts\)\s*\{(.*?)\n\}\n", src, re.S)
    assert m, "expected openApplicantChat(opts)"
    body = m.group(1)
    assert "return true;" in body
    assert "return false;" in body


# ── the engine sentinel can never be rewritten to a raw LLM endpoint ────────


def test_model_picker_never_auto_heals_the_engine_session():
    """updateModelPicker's 'model no longer available → PATCH first available
    model onto the session' auto-heal must recognize the engine session by its
    SENTINEL (not via the lazily-loaded surface module, which loses the boot
    race) — otherwise a reload silently reconnects the assistant's chat to a
    raw LLM endpoint (live-caught regression during this pass's verification)."""
    src = _read(MODEL_PICKER_JS)
    fn = re.search(r"export function updateModelPicker\(\) \{(.*?)\n\}\n", src, re.S)
    assert fn, "expected updateModelPicker"
    body = fn.group(1)
    sentinel_at = body.find("=== 'applicant://engine'")
    heal_at = body.find("method: 'PATCH'")
    assert sentinel_at != -1, "expected a direct sentinel check in updateModelPicker"
    assert heal_at != -1, "expected the auto-heal PATCH (contract anchor)"
    assert sentinel_at < heal_at, (
        "the sentinel check must run BEFORE the auto-heal PATCH so the engine "
        "session can never be rewritten"
    )


def test_session_update_route_refuses_model_switch_on_the_engine_session():
    """Server-side enforcement (guards never rely on the client alone): the
    session-update route must reject a model/endpoint rewrite on the
    sentinel-flagged Job Assistant session."""
    src = SESSION_ROUTES_PY.read_text(encoding="utf-8")
    guard_at = src.find('== "applicant://engine"')
    assert guard_at != -1, "expected the engine-sentinel guard in session_routes.py"
    mutate_at = src.find("session.endpoint_url = endpoint_url")
    assert mutate_at != -1, "expected the model-switch mutation (contract anchor)"
    assert guard_at < mutate_at, (
        "the sentinel guard must run before the endpoint mutation"
    )
    # And it must be a hard HTTP error, not a silent no-op.
    window = src[guard_at : guard_at + 700]
    assert "HTTPException" in window and "400" in window
