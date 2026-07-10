"""Source-composition pins for the chat-WS transport migration.

The three remaining front-end `/api/chat_stream` SSE consumers — model
comparison (`compare/stream.js`, two fetches), background note-solving
(`notes.js`), and group chat (`group.js`) — were migrated to reuse the shared
`chatWsTransport.openChatStreamReader()` transport (added in #808 and already
used by `chat.js`). The transport prefers the `/api/chat/ws` WebSocket and keeps
each request's SSE body (`res.body`) as the AUTOMATIC fallback lane.

Like `test_chat_stream_scope.py`, these tests read the shipped source and assert
its composition, so reverting a call site back to a raw `res.body.getReader()`
(which would drop the WS path) flips them red.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"


def _src(rel: str) -> str:
    return (JS_DIR / rel).read_text(encoding="utf-8")


def test_compare_stream_uses_ws_transport_for_both_fetches():
    src = _src("compare/stream.js")
    # Imports the shared transport (relative from the compare/ subdir).
    assert "import chatWsTransport from '../chatWsTransport.js';" in src
    # Both fetches now go through the transport (synthesis pane + main pane).
    assert src.count("chatWsTransport.openChatStreamReader(") == 2
    # Each passes the session id it already knows — the synthesis temp session
    # id and the per-pane session id — so the WS can subscribe/resume.
    assert "sessionId: createData.id," in src
    assert "\n      sessionId,\n" in src
    # SSE fallback preserved: the raw getReader() lives ONLY inside the
    # transport now, never in this consumer.
    assert ".getReader();" not in src


def test_notes_agent_solve_uses_ws_transport():
    src = _src("notes.js")
    assert "import chatWsTransport from './chatWsTransport.js';" in src
    assert "chatWsTransport.openChatStreamReader(" in src
    # The background agent-solve drain subscribes with the session it just
    # created for the note.
    assert "sessionId: sid," in src
    assert ".getReader();" not in src


def test_group_chat_uses_ws_transport():
    src = _src("group.js")
    assert "import chatWsTransport from './chatWsTransport.js';" in src
    assert "chatWsTransport.openChatStreamReader(" in src
    # Streams a participant's turn on its own session id (the fn param).
    assert "\n      sessionId,\n" in src
    assert ".getReader();" not in src


def test_transport_still_keeps_sse_fallback():
    """The migrated consumers rely on the transport for the SSE fallback, so
    the transport must still return res.body.getReader() when the WS can't
    connect (never a silent dead UI)."""
    src = _src("chatWsTransport.js")
    assert "return res.body.getReader();" in src
