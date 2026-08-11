"""AZ2 (#833-#838) — the activity/daily-loop panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/activity.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_drives_the_engine_through_agent_runs_proxy(html):
    assert 'callJsonApi("agent_runs", { action: "status" })' in html


def test_run_button_wired(html):
    assert 'callJsonApi("agent_runs", { action: "run" })' in html


def test_pause_button_wired(html):
    assert 'callJsonApi("agent_runs", { action: "pause" })' in html


def test_resume_button_wired(html):
    assert 'callJsonApi("agent_runs", { action: "resume" })' in html


def test_list_wired(html):
    assert 'callJsonApi("agent_runs", { action: "list" })' in html


def test_error_line_present(html):
    assert 'fatalError' in html or 'r.ok' in html or 'r.error' in html
