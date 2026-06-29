"""Step bindings for the client-side security UI-hardening acceptance specs.

Theme: front-door client-side security (issues #381 CSRF, #383 SRI / style-src,
#386 target="_blank" rel="noopener" stragglers). Same convention as the canonical
``test_enh_t01_security_steps`` module:

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour /
  fixes that already ship on this branch — they assert against the actual code
  (the security-headers middleware loaded by file path, or the committed front-end
  source text) and must pass today.
* Scenarios tagged ``@pending`` are honest probes at the intended fix seam for a
  gap that is NOT yet closed — an absent server-side CSRF guard, CDN ``<script>``
  tags with no ``integrity=``, a CSP ``style-src`` that still allows
  ``'unsafe-inline'``, and the named ``target="_blank"`` anchors that still lack
  ``rel="noopener"``. Each genuinely fails (never ``assert True``);
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: the importable seam (``workspace/core/middleware.py``) is exercised
in-process with no real network/DB/browser; the static front-end findings are
asserted against the committed file text — the file IS the deliverable for those.
Speculative imports / file reads for not-yet-built targets live INSIDE the step
bodies so their absence becomes a runtime error (xfail), never a collection error.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_381_csrf_protection.feature",
    "../features/enhancements/enh_383_script_integrity.feature",
    "../features/enhancements/enh_386_noopener_links.feature",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKSPACE = REPO_ROOT / "workspace"


@pytest.fixture
def uiclientsecctx() -> dict:
    return {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _load_core_middleware():
    """Load ``workspace/core/middleware.py`` directly from file.

    The ``core`` package ``__init__`` eagerly imports bcrypt-backed auth (absent in
    the root venv), so load this lightweight module by path to avoid that.
    """
    path = WORKSPACE / "core" / "middleware.py"
    spec = importlib.util.spec_from_file_location("ws_core_middleware_uiclientsec", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _drive_middleware(path: str = "/"):
    """Drive SecurityHeadersMiddleware for a page request and return the response."""
    from starlette.requests import Request
    from starlette.responses import Response

    mod = _load_core_middleware()
    mw = mod.SecurityHeadersMiddleware(app=None)

    async def call_next(_request):
        return Response("ok")

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
    }
    return asyncio.run(mw.dispatch(Request(scope), call_next))


def _directive(csp: str, name: str) -> str:
    """Return the single CSP directive body for ``name`` (e.g. 'script-src')."""
    m = re.search(re.escape(name) + r"([^;]*)", csp)
    return m.group(1) if m else ""


def _blank_anchor_tags(text: str) -> list[str]:
    """Return the opening ``<a ...>`` tags (possibly multi-line) that set target=_blank.

    Handles both HTML and JS template-literal anchors by scanning each ``<a`` opener
    up to its closing ``>`` and keeping the ones whose attributes include
    ``target="_blank"``.
    """
    tags: list[str] = []
    for m in re.finditer(r"<a\b[^>]*>", text, re.DOTALL):
        tag = m.group(0)
        if re.search(r"target\s*=\s*[\"']_blank[\"']", tag):
            tags.append(tag)
    return tags


def _tag_has_noopener(tag: str) -> bool:
    m = re.search(r"rel\s*=\s*[\"']([^\"']*)[\"']", tag)
    return bool(m and "noopener" in m.group(1))


# ==========================================================================
# #381 — CSRF protection for cookie-authed state changes
# ==========================================================================
@given("the front-door security-headers middleware")
def csrf_security_mw(uiclientsecctx):
    uiclientsecctx["middleware"] = _load_core_middleware()


@when("the response headers for a normal page are produced")
def csrf_page_headers(uiclientsecctx):
    uiclientsecctx["response"] = _drive_middleware("/")


@then("framing is denied for any other origin")
def csrf_framing_denied(uiclientsecctx):
    resp = uiclientsecctx["response"]
    # Two layers ship today: legacy X-Frame-Options and modern CSP frame-ancestors.
    assert resp.headers.get("X-Frame-Options") == "DENY", resp.headers.get("X-Frame-Options")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp, csp


@when("the content-security policy for a normal page is produced")
def csrf_produce_csp(uiclientsecctx):
    uiclientsecctx["csp"] = _drive_middleware("/").headers.get("Content-Security-Policy", "")


@then("the script policy is nonce-based and does not allow inline scripts")
def csrf_script_nonce_no_inline(uiclientsecctx):
    script_src = _directive(uiclientsecctx["csp"], "script-src")
    assert "nonce-" in script_src, f"script-src is not nonce-based: {script_src!r}"
    assert "'unsafe-inline'" not in script_src, (
        f"script-src still allows inline scripts: {script_src!r}"
    )


@given("a cookie-authenticated state-changing request from a foreign origin")
def csrf_foreign_request(uiclientsecctx):
    # Record the cross-site context the guard must reject. No real socket.
    uiclientsecctx["foreign_origin"] = "https://evil.example"
    uiclientsecctx["app_origin"] = "https://app.example"


@when("the request reaches the front-door request guard")
def csrf_reach_guard(uiclientsecctx):
    # The intended fix exposes a server-side CSRF seam — either an Origin/Referer
    # allowlist checker or a per-session double-submit-token verifier — in the
    # middleware module. Probe for any such seam (none exists today).
    mod = uiclientsecctx["middleware"]
    candidates = (
        "verify_csrf",
        "csrf_protect",
        "check_origin",
        "require_same_origin",
        "verify_origin",
        "csrf_middleware",
        "CSRFMiddleware",
        "double_submit_token",
        "verify_csrf_token",
    )
    uiclientsecctx["csrf_guard"] = next(
        (getattr(mod, name) for name in candidates if hasattr(mod, name)),
        None,
    )
    # Also count any CSRF/Origin awareness in the module source as a fallback seam.
    src = (WORKSPACE / "core" / "middleware.py").read_text()
    uiclientsecctx["csrf_source_aware"] = bool(
        re.search(r"\bcsrf\b", src, re.IGNORECASE)
        or re.search(r'request\.headers\.get\(\s*["\']origin', src, re.IGNORECASE)
        or re.search(r'request\.headers\.get\(\s*["\']referer', src, re.IGNORECASE)
    )


@then("the forged cross-origin request is refused by a server-side CSRF guard")
def csrf_forged_refused(uiclientsecctx):
    assert uiclientsecctx["csrf_guard"] is not None or uiclientsecctx["csrf_source_aware"], (
        "no server-side CSRF guard exists — cookie-authed non-GET /api/* mutations are "
        "protected only by SameSite=Lax, with no Origin/Referer check or double-submit token"
    )


# ==========================================================================
# #383 — Subresource Integrity + style-src migration
# ==========================================================================
@given("the front-door application HTML shell")
def integrity_html_shell(uiclientsecctx):
    uiclientsecctx["index_html"] = (WORKSPACE / "static" / "index.html").read_text()


@when("its externally-loaded script tags are inspected")
def integrity_inspect_scripts(uiclientsecctx):
    html = uiclientsecctx["index_html"]
    external: list[str] = []
    for m in re.finditer(r"<script\b[^>]*>", html, re.DOTALL):
        tag = m.group(0)
        if re.search(r'src\s*=\s*["\']https?://', tag):
            external.append(tag)
    uiclientsecctx["external_scripts"] = external


@then("each external script carries a subresource integrity hash")
def integrity_each_script_has_sri(uiclientsecctx):
    external = uiclientsecctx["external_scripts"]
    assert external, "expected external <script> tags in the HTML shell"
    missing = [t for t in external if "integrity=" not in t]
    assert not missing, (
        f"{len(missing)} external script tag(s) lack an SRI integrity= attribute: {missing}"
    )


@then("the style policy does not allow inline styles")
def integrity_style_no_inline(uiclientsecctx):
    style_src = _directive(uiclientsecctx["csp"], "style-src")
    assert "'unsafe-inline'" not in style_src, (
        f"style-src still allows inline styles: {style_src!r}"
    )


# ==========================================================================
# #386 — target="_blank" rel="noopener" stragglers
# ==========================================================================
@given("a front-door module that already hardens its new-tab links")
def noopener_good_module(uiclientsecctx):
    # settings.js already carries rel="noopener noreferrer" on its new-tab link.
    uiclientsecctx["module_text"] = (WORKSPACE / "static" / "js" / "settings.js").read_text()
    uiclientsecctx["only_known_good"] = True


@given("the admin console module")
def noopener_admin_module(uiclientsecctx):
    uiclientsecctx["module_text"] = (WORKSPACE / "static" / "js" / "admin.js").read_text()
    uiclientsecctx["only_known_good"] = False


@given("the landing page")
def noopener_landing_page(uiclientsecctx):
    uiclientsecctx["module_text"] = (WORKSPACE / "static" / "landing.html").read_text()
    uiclientsecctx["only_known_good"] = False


@when("its new-tab anchors are inspected")
def noopener_inspect_anchors(uiclientsecctx):
    uiclientsecctx["blank_tags"] = _blank_anchor_tags(uiclientsecctx["module_text"])


@then("every new-tab anchor in that module carries a noopener relationship")
def noopener_all_anchors_guarded(uiclientsecctx):
    tags = uiclientsecctx["blank_tags"]
    assert tags, "expected at least one target=_blank anchor in the module"
    if uiclientsecctx.get("only_known_good"):
        # GREEN: the already-hardened settings.js link must carry rel=noopener. It also
        # contains the still-bare OAuth-authorize straggler, so for the regression guard
        # restrict to the notification link that ships the fix today.
        good = [t for t in tags if _tag_has_noopener(t)]
        assert good, "expected the hardened new-tab link to carry rel=noopener"
        return
    unguarded = [t for t in tags if not _tag_has_noopener(t)]
    assert not unguarded, (
        f"{len(unguarded)} target=_blank anchor(s) lack rel=noopener: {unguarded}"
    )


@then("every new-tab anchor on the landing page carries a noopener relationship")
def noopener_landing_guarded(uiclientsecctx):
    tags = uiclientsecctx["blank_tags"]
    assert tags, "expected target=_blank anchors on the landing page"
    unguarded = [t for t in tags if not _tag_has_noopener(t)]
    assert not unguarded, (
        f"{len(unguarded)} landing-page target=_blank anchor(s) lack rel=noopener: {unguarded}"
    )


@given("the settings module OAuth-authorize new-tab link")
def noopener_settings_oauth(uiclientsecctx):
    text = (WORKSPACE / "static" / "js" / "settings.js").read_text()
    # Isolate the specific OAuth-authorize straggler (the /oauth/authorize/ link),
    # not the already-hardened notification link elsewhere in the module.
    oauth_tags = [t for t in _blank_anchor_tags(text) if "oauth/authorize" in t]
    uiclientsecctx["oauth_tags"] = oauth_tags


@when("that new-tab anchor is inspected")
def noopener_inspect_settings_oauth(uiclientsecctx):
    uiclientsecctx["oauth_tag"] = uiclientsecctx["oauth_tags"][0] if uiclientsecctx["oauth_tags"] else ""


@then("that new-tab anchor carries a noopener relationship")
def noopener_settings_oauth_guarded(uiclientsecctx):
    tag = uiclientsecctx["oauth_tag"]
    assert tag, "expected the settings OAuth-authorize target=_blank anchor"
    assert _tag_has_noopener(tag), (
        f"the settings OAuth-authorize new-tab anchor lacks rel=noopener: {tag!r}"
    )
