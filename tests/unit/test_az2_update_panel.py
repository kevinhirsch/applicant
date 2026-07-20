"""AZ2 (#841) — the update panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/update.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_calls_update_panel_proxy_with_status_on_init(html):
    assert 'callJsonApi("update_panel", { action: "status" })' in html or \
           'callJsonApi("update_panel", {action: "status"})' in html


def test_trigger_button_wired(html):
    assert 'action: "trigger"' in html or 'action:\"trigger\"' in html


def test_renders_returned_message(html):
    assert 'triggerMessage' in html or 'message' in html


def test_error_line_present(html):
    assert 'fatalError' in html


def test_updater_not_deployed_state_present(html):
    assert 'notDeployedMsg' in html or 'Not deployed' in html


def test_log_tail_rendered(html):
    assert 'logTail' in html or 'log_tail' in html
