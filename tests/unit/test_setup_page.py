"""Setup-page (settings) checks: forced-open OOBE, gating, and field tooltips.

The setup page is the real settings page; on first run it opens itself to the setup
sections and keeps the chat surface locked until the model is connected. These tests
assert the served markup/JS carry the gate behavior and the tooltips the design
system uses (``title="…"``), without booting a browser.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_root_serves_settings_shell(client):
    html = client.get("/").text
    # The real settings modal markup (sidebar tabs, panels) is present.
    assert 'id="settings-modal"' in html
    assert 'class="settings-sidebar"' in html
    assert 'data-settings-panel="services"' in html  # Add Models
    assert 'data-settings-panel="ai"' in html  # AI Defaults


def test_setup_has_local_and_remote_endpoint_forms(client):
    html = client.get("/").text
    # Local (Ollama-style) form.
    assert 'id="adm-epLocalUrl"' in html
    assert 'id="adm-epLocalAddBtn"' in html
    # Cloud (OpenRouter-style) form: provider picker + base URL + key.
    assert 'id="adm-epUrl"' in html
    assert 'id="adm-epApiKey"' in html
    assert 'id="adm-epAddBtn"' in html
    assert "OpenRouter" in html


def test_ai_defaults_dropdowns_present(client):
    html = client.get("/").text
    assert 'id="set-defaultEpSelect"' in html
    assert 'id="set-defaultModelSelect"' in html


def test_setup_js_forces_settings_open_and_gates_chat(client):
    js = client.get("/static/applicant/js/setup.js").text
    # Chat surface is hidden until the gate is open; setup opens on first run.
    assert "chat-surface" in js
    assert "openSettings" in js
    assert "_gateOpen" in js
    # The model-endpoint flow is ported (live model listing on add).
    assert "/api/model-endpoints" in js
    assert "fillModelSelect" in js
    assert "fillEndpointSelect" in js


def test_setup_fields_have_tooltips(client):
    """Every non-obvious setup field carries a design-system title="" tooltip."""
    html = client.get("/").text
    field_ids = [
        "adm-epLocalUrl",
        "adm-epLocalApiKey",
        "adm-epUrl",
        "adm-epApiKey",
        "adm-epProvider",
        "set-defaultEpSelect",
        "set-defaultModelSelect",
        "notif-discord",
        "notif-email",
    ]
    for fid in field_ids:
        # Find the element with this id and assert it (or its row) has a title.
        m = re.search(r'<[^>]*\bid="' + re.escape(fid) + r'"[^>]*>', html)
        assert m, f"field {fid!r} not found in setup page"
        assert "title=" in m.group(0), f"field {fid!r} is missing a tooltip"


def test_setup_page_has_no_requirement_ids(client):
    html = client.get("/").text
    js = client.get("/static/applicant/js/setup.js").text
    req = re.compile(r"\b(?:FR|NFR)-")
    assert not req.findall(html)
    assert not req.findall(js)
