"""UI surface quality checks: every screen is styled, and no internal jargon ships.

This is the test that would have caught two shipped regressions:

1. The wizard (and every other screen) loaded unstyled because the HTML referenced
   assets with RELATIVE paths (``../style.css``, ``applicant.css``, ``js/wizard.js``)
   while the ui router serves them at clean routes (``/``, ``/wizard``, …), so the
   relative asset URLs 404'd. We assert every ``<link href>`` / ``<script src>`` an
   surface references resolves with a 200.

2. The user-facing copy (and the HTML/JS source comments that ship with it) was full
   of internal requirement IDs (``FR-…`` / ``NFR-…``). We assert no such token appears
   in any served surface HTML or in any referenced JS.

Hermetic: ``create_app()`` boots without network or external services.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app

# Every clean UI route the ui router exposes.
UI_ROUTES = ["/", "/wizard", "/digest", "/review", "/criteria", "/attributes", "/debug", "/chat"]

# Forbidden internal tokens — requirement IDs must never reach the product.
REQ_ID_RE = re.compile(r"\b(?:FR|NFR)-")

# Pull asset URLs out of <link href="..."> and <script src="..."> tags.
_LINK_HREF_RE = re.compile(r"<link\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _asset_urls(html: str) -> list[str]:
    return _LINK_HREF_RE.findall(html) + _SCRIPT_SRC_RE.findall(html)


@pytest.mark.parametrize("route", UI_ROUTES)
def test_surface_loads(client, route):
    """Each UI route returns a 200 HTML page."""
    r = client.get(route)
    assert r.status_code == 200, f"{route} -> {r.status_code}"


@pytest.mark.parametrize("route", UI_ROUTES)
def test_surface_assets_resolve(client, route):
    """Every asset a surface references resolves with a 200 (no 404s)."""
    html = client.get(route).text
    assets = _asset_urls(html)
    assert assets, f"{route} referenced no assets — parser/markup regression?"
    for url in assets:
        # Only check same-origin assets we serve (skip any absolute http(s) URLs).
        if url.startswith("http://") or url.startswith("https://") or url.startswith("//"):
            continue
        res = client.get(url)
        assert res.status_code == 200, f"{route} references {url!r} -> {res.status_code} (404 = unstyled)"


@pytest.mark.parametrize("route", UI_ROUTES)
def test_surface_html_has_no_requirement_ids(client, route):
    """No FR-/NFR- token appears in any served surface HTML."""
    html = client.get(route).text
    matches = REQ_ID_RE.findall(html)
    assert not matches, f"{route} HTML contains requirement IDs: {matches}"


@pytest.mark.parametrize("route", UI_ROUTES)
def test_surface_js_has_no_requirement_ids(client, route):
    """No FR-/NFR- token appears in any JS a surface loads."""
    html = client.get(route).text
    for url in _asset_urls(html):
        if not url.endswith(".js"):
            continue
        js = client.get(url).text
        matches = REQ_ID_RE.findall(js)
        assert not matches, f"{url} (loaded by {route}) contains requirement IDs: {matches}"


def test_vendored_and_applicant_stylesheets_resolve(client):
    """The vendored Applicant stylesheet and our own stylesheet both resolve."""
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/applicant/applicant.css").status_code == 200


def test_shared_ui_module_has_no_requirement_ids(client):
    """The shared UI module (imported by every screen's JS) is jargon-free too."""
    js = client.get("/static/applicant/js/applicant-ui.js").text
    assert js  # sanity: the module is served
    assert not REQ_ID_RE.findall(js)
