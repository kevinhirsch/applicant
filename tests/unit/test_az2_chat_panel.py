"""AZ2 (#837) — the chat panel contract (source assertions + real JS execution).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS
gates. ``TestChatPanelBehavior`` additionally drives the extracted ``chatPanel()`` Alpine
factory through real ``node`` execution (skips gracefully when ``node`` isn't on PATH),
mirroring ``test_review_deep_link.py``'s ``TestDeepLinkParserBehavior`` for this same
class of panel.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/chat.html"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


class TestChatPanel:
    """Source-level assertions for the chat panel."""

    def test_list_campaigns_via_callJsonApi(self, html):
        assert 'callJsonApi("campaigns", { action: "list" }' in html

    def test_chat_history_via_callJsonApi(self, html):
        assert 'callJsonApi("chat", { action: "history"' in html

    def test_chat_send_via_callJsonApi(self, html):
        assert 'callJsonApi("chat"' in html
        assert 'action: "send"' in html

    def test_has_error_line(self, html):
        assert "fatalError" in html

    def test_empty_state(self, html):
        assert "Start a conversation" in html

    def test_has_conversation_div(self, html):
        assert "conversation" in html

    def test_has_msg_user_class(self, html):
        assert "msg.user" in html

    def test_has_msg_assistant_class(self, html):
        assert "msg.assistant" in html

    def test_has_input_row(self, html):
        assert "input-row" in html

    def test_has_send_button(self, html):
        assert "Send" in html

    def test_has_pending_confirm_banner(self, html):
        assert "confirm-banner" in html

    def test_chip_css_classes(self, html):
        """D1: chip rendering CSS classes exist in the panel HTML."""
        assert '.achat .chips' in html
        assert '.achat .chip' in html

    def test_chip_markup_structure(self, html):
        """D1: chips are rendered for assistant messages with actions."""
        assert 'item.actions' in html
        assert 'act.label' in html
        assert 'act.action' in html
        assert 'callJsonApi' in html

    def test_chip_actions_data_field(self, html):
        """D1: the actions field from data is attached to conversation items."""
        assert 'data.actions' in html
        assert 'pendingIdx].actions' in html

    def test_chip_assistant_only(self, html):
        """D1: chips only render for assistant role messages."""
        assert "item.role === 'assistant'" in html


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


class TestChatPanelBehavior:
    """Real JS execution of the ``chatPanel()`` Alpine factory (skips without node).

    Regression coverage for the three audited P0/P1 bugs:

    * init()/loadConversation() must land in a ready, non-fatal state even when
      the "history" action fails (P0: chat panel dead on load) — fatalError must
      never be set purely because history-load failed, since that hides the
      WHOLE panel (input row included) behind the "!fatalError" template guard.
    * sendMessage() must POST the "message" field, not "text" (P0: the proxy's
      "send" dispatch reads ``input.get("message")``).
    * confirmChange() must actually call the confirm / confirm_criteria API
      (P1: it previously only cleared the banner client-side).
    """

    @staticmethod
    def _extract_factory(src: str) -> str:
        marker = 'window.Alpine.data("chatPanel", () => ({'
        start = src.index(marker)
        brace_start = start + len(marker) - 1  # index of the object's opening "{"
        depth = 0
        for i in range(brace_start, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    return src[brace_start : i + 1]
        raise AssertionError("unbalanced braces while extracting chatPanel factory")

    def _run(self, html: str, *, routes: list[dict], driver: str) -> dict:
        """Execute ``driver`` JS against a live ``chatPanel()`` instance.

        ``routes`` is a list of ``{"ep": ..., "action": ..., "response": {...}}``
        entries; a fake ``callJsonApi`` walks them in order and returns the first
        whose ``ep`` (and ``action``, if given) matches the call, recording every
        call it saw so assertions can inspect exactly what the panel sent —
        including a field it wrongly omitted (e.g. "message" vs "text").
        """
        obj_src = self._extract_factory(html)
        script = textwrap.dedent(
            f"""
            const _routes = {json.dumps(routes)};
            const _calls = [];
            async function callJsonApi(ep, body) {{
              _calls.push({{ep, body}});
              for (const r of _routes) {{
                if (r.ep === ep && (!r.action || (body && body.action === r.action))) {{
                  return r.response;
                }}
              }}
              return null;
            }}
            const chatPanel = () => ({obj_src});

            async function main() {{
              const panel = chatPanel();
              {driver}
              console.log(JSON.stringify({{panel, calls: _calls}}));
            }}
            main().catch((e) => {{ console.error(e.stack || String(e)); process.exit(1); }});
            """
        )
        res = subprocess.run(
            ["node", "-e", script], capture_output=True, timeout=15, text=True
        )
        if res.returncode != 0:
            raise AssertionError(f"node failed:\n{res.stderr}")
        lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
        if not lines:
            raise AssertionError("node produced no stdout")
        return json.loads(lines[-1])

    # --- P0: panel dead on load ------------------------------------------
    def test_init_lands_ready_when_history_action_is_unimplemented(
        self, html, node_available
    ):
        # Mirrors production reality today: the proxy has no "history" action, so
        # it 400s with "unknown chat action 'history'".
        routes = [
            {
                "ep": "campaigns",
                "action": "list",
                "response": {"ok": True, "data": {"campaigns": [{"id": "c1", "name": "Camp"}]}},
            },
            {
                "ep": "chat",
                "action": "history",
                "response": {"ok": False, "status": 400, "error": "unknown chat action 'history'"},
            },
        ]
        out = self._run(html, routes=routes, driver="await panel.init();")
        panel = out["panel"]
        assert panel["loading"] is False
        assert panel["fatalError"] == ""
        assert panel["conversation"] == []
        assert panel["selectedCampaignId"] == "c1"

    def test_init_still_reports_a_truly_unreachable_engine(self, html, node_available):
        # A genuinely broken campaigns fetch (the engine unreachable) must still
        # surface fatalError — only the history-load failure is safe to swallow.
        routes = [
            {"ep": "campaigns", "action": "list", "response": {"ok": False, "error": "engine down"}},
            {"ep": "chat", "action": "history", "response": {"ok": False, "status": 400, "error": "x"}},
        ]
        out = self._run(html, routes=routes, driver="await panel.init();")
        assert out["panel"]["fatalError"] == "engine down"

    # --- P0: sendMessage wrong field --------------------------------------
    def test_send_message_posts_message_field_not_text(self, html, node_available):
        routes = [
            {
                "ep": "chat",
                "action": "send",
                "response": {"ok": True, "data": {"message": "Hi! How can I help?"}},
            },
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.inputText = "Hello there";
            await panel.sendMessage();
        """
        out = self._run(html, routes=routes, driver=driver)
        send_calls = [c for c in out["calls"] if c["ep"] == "chat" and c["body"].get("action") == "send"]
        assert len(send_calls) == 1
        body = send_calls[0]["body"]
        assert body["message"] == "Hello there"
        assert "text" not in body  # the historical wrong field must be gone
        convo = out["panel"]["conversation"]
        assert convo[-1]["role"] == "assistant"
        assert convo[-1]["text"] == "Hi! How can I help?"
        assert out["panel"]["fatalError"] == ""

    def test_send_message_reports_a_real_send_failure(self, html, node_available):
        routes = [
            {"ep": "chat", "action": "send", "response": {"ok": False, "status": 400, "error": "message required"}},
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.inputText = "hi";
            await panel.sendMessage();
        """
        out = self._run(html, routes=routes, driver=driver)
        assert out["panel"]["fatalError"] == "message required"
        # The optimistic pending placeholder must be rolled back, not left dangling.
        assert all(not m.get("pending") for m in out["panel"]["conversation"])

    # --- P1: pending-confirm derived from the real engine response shape --
    def test_send_message_derives_pending_confirm_from_proposed_changes(
        self, html, node_available
    ):
        routes = [
            {
                "ep": "chat",
                "action": "send",
                "response": {
                    "ok": True,
                    "data": {
                        "message": "Got it, want me to save that?",
                        "proposed_changes": [
                            {
                                "kind": "attribute",
                                "name": "first name",
                                "value": "Kevin",
                                "is_integral": True,
                                "requires_confirmation": True,
                                "applied": False,
                            }
                        ],
                    },
                },
            },
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.inputText = "my first name is Kevin";
            await panel.sendMessage();
        """
        out = self._run(html, routes=routes, driver=driver)
        pending = out["panel"]["pendingConfirm"]
        assert pending is not None
        assert pending["kind"] == "attribute"
        assert pending["name"] == "first name"
        assert pending["value"] == "Kevin"

    def test_send_message_derives_pending_confirm_from_control_actions(
        self, html, node_available
    ):
        routes = [
            {
                "ep": "chat",
                "action": "send",
                "response": {
                    "ok": True,
                    "data": {
                        "message": "That changes scope, confirm?",
                        "control_actions": [
                            {
                                "kind": "criteria",
                                "applied": False,
                                "requires_confirmation": True,
                                "detail": {"salary_floor": 150000},
                            }
                        ],
                    },
                },
            },
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.inputText = "set my salary floor to 150k";
            await panel.sendMessage();
        """
        out = self._run(html, routes=routes, driver=driver)
        pending = out["panel"]["pendingConfirm"]
        assert pending is not None
        assert pending["kind"] == "criteria"
        assert pending["changes"]["salary_floor"] == 150000

    def test_send_message_leaves_pending_confirm_null_when_nothing_gated(
        self, html, node_available
    ):
        routes = [
            {"ep": "chat", "action": "send", "response": {"ok": True, "data": {"message": "Sure thing."}}},
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.inputText = "hello";
            await panel.sendMessage();
        """
        out = self._run(html, routes=routes, driver=driver)
        assert out["panel"]["pendingConfirm"] is None

    # --- P1: confirm is a no-op --------------------------------------------
    def test_confirm_change_commits_an_attribute_via_confirm_action(
        self, html, node_available
    ):
        routes = [
            {
                "ep": "chat",
                "action": "confirm",
                "response": {"ok": True, "data": {"committed": True, "name": "first name", "value": "Kevin"}},
            },
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.pendingConfirm = { kind: "attribute", name: "first name", value: "Kevin", message: "Set?" };
            await panel.confirmChange();
        """
        out = self._run(html, routes=routes, driver=driver)
        confirm_calls = [c for c in out["calls"] if c["ep"] == "chat" and c["body"].get("action") == "confirm"]
        assert len(confirm_calls) == 1
        body = confirm_calls[0]["body"]
        assert body["campaign_id"] == "c1"
        assert body["name"] == "first name"
        assert body["value"] == "Kevin"
        assert out["panel"]["pendingConfirm"] is None
        assert out["panel"]["conversation"][-1]["role"] == "assistant"
        assert "Done" in out["panel"]["conversation"][-1]["text"]

    def test_confirm_change_commits_criteria_via_confirm_criteria_action(
        self, html, node_available
    ):
        routes = [
            {
                "ep": "chat",
                "action": "confirm_criteria",
                "response": {"ok": True, "data": {"committed": True, "salary_floor": 150000}},
            },
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.pendingConfirm = { kind: "criteria", changes: { salary_floor: 150000 }, message: "Apply?" };
            await panel.confirmChange();
        """
        out = self._run(html, routes=routes, driver=driver)
        calls = [c for c in out["calls"] if c["ep"] == "chat" and c["body"].get("action") == "confirm_criteria"]
        assert len(calls) == 1
        assert calls[0]["body"]["changes"] == {"salary_floor": 150000}
        assert out["panel"]["pendingConfirm"] is None

    def test_confirm_change_surfaces_a_real_commit_failure(self, html, node_available):
        routes = [
            {"ep": "chat", "action": "confirm", "response": {"ok": False, "status": 409, "error": "conflict"}},
        ]
        driver = """
            panel.selectedCampaignId = "c1";
            panel.pendingConfirm = { kind: "attribute", name: "first name", value: "Kevin", message: "Set?" };
            await panel.confirmChange();
        """
        out = self._run(html, routes=routes, driver=driver)
        assert out["panel"]["fatalError"] == "conflict"
        assert out["panel"]["pendingConfirm"] is None

    def test_confirm_change_is_a_noop_without_a_pending_change(self, html, node_available):
        out = self._run(html, routes=[], driver="await panel.confirmChange();")
        assert out["calls"] == []
        assert out["panel"]["pendingConfirm"] is None
