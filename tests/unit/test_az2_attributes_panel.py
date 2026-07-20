"""AZ2 — the attributes panel contract (source assertions).

The panel is browser-rendered HTML/JS (full E2E belongs in the P0-6 Playwright harness),
so here we pin the load-bearing contract at the source level, like the repo's other JS gates.
"""
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/attributes.html"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_drives_the_engine_through_attributes_proxy(html):
    assert 'callJsonApi("attributes", {' in html and 'action: "list"' in html


def test_add_form_wired(html):
    assert 'action: "add"' in html and 'name:' in html and 'value:' in html


def test_sensitive_checkbox_wired(html):
    assert 'is_sensitive' in html or 'isSensitive' in html


def test_delete_button_wired(html):
    assert 'action: "delete"' in html and 'attribute_id:' in html


def test_empty_state_present(html):
    assert 'empty' in html.lower() or 'no attributes' in html.lower() or 'no profile' in html.lower()


def test_error_line_present(html):
    assert 'fatalError' in html or 'r.ok' in html or 'r.error' in html
