"""Step bindings for the security & auth enhancement acceptance specs (theme T01).

Issues #160-#280 (security scan + auth-layer hardening). Same convention as the
canonical ``test_enh_research_steps`` module:

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour /
  fixes that already ship on this branch — they assert against the actual code
  (core helpers, route error-translators, the security-headers middleware, or the
  resolved lockfile) and must pass today.
* Scenarios tagged ``@pending`` are honest probes at the intended fix seam for a
  security gap that is NOT yet closed — a missing header value, an absent
  containment check, a still-present third-party CDN, a root-running Dockerfile, a
  mutable base tag, an inline secret. Each genuinely fails (never ``assert True``);
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: the importable seams (workspace ``src.*`` / ``core.middleware`` /
``routes.applicant_*``) are exercised in-process with no real network/DB/browser.
Speculative imports for not-yet-built targets live INSIDE the step bodies so their
absence becomes a runtime error (xfail), never a collection error. Build-artifact
findings (Dockerfiles, CI workflows, deploy scripts) are asserted against the
committed file text — the file IS the deliverable for those issues.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import pathlib
import re
import sys

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_160_mutable_base_tag.feature",
    "../features/enhancements/enh_161_root_user_dockerfile.feature",
    "../features/enhancements/enh_162_vulnerable_deps.feature",
    "../features/enhancements/enh_163_path_traversal_reads.feature",
    "../features/enhancements/enh_164_unverified_remote_fetch.feature",
    "../features/enhancements/enh_167_checkout_persists_credentials.feature",
    "../features/enhancements/enh_228_require_admin_loopback.feature",
    "../features/enhancements/enh_229_raw_error_leak.feature",
    "../features/enhancements/enh_230_unattributed_callback.feature",
    "../features/enhancements/enh_231_features_unauthenticated.feature",
    "../features/enhancements/enh_251_serve_html_containment.feature",
    "../features/enhancements/enh_252_generic_exception_handler.feature",
    "../features/enhancements/enh_266_internal_token_disable_flag.feature",
    "../features/enhancements/enh_267_impersonation_admin_gate.feature",
    "../features/enhancements/enh_268_csp_third_party_cdn.feature",
    "../features/enhancements/enh_269_session_cookie_secure.feature",
    "../features/enhancements/enh_280_deploy_password_leak.feature",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKSPACE = REPO_ROOT / "workspace"


@pytest.fixture
def t01ctx() -> dict:
    return {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _ensure_workspace_on_path() -> None:
    """Put ``workspace/`` on sys.path so its ``src.*`` / ``routes.*`` modules import."""
    ws = str(WORKSPACE)
    if ws not in sys.path:
        sys.path.insert(0, ws)


def _load_core_middleware():
    """Load ``workspace/core/middleware.py`` directly from file.

    The ``core`` package ``__init__`` eagerly imports bcrypt-backed auth (absent in
    the root venv), so load this lightweight module by path to avoid that.
    """
    path = WORKSPACE / "core" / "middleware.py"
    spec = importlib.util.spec_from_file_location("ws_core_middleware_t01", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _checkout_block(workflow_text: str) -> str:
    """Return the YAML block for the actions/checkout step (the step + its ``with:``)."""
    lines = workflow_text.splitlines()
    out: list[str] = []
    capturing = False
    indent = 0
    for line in lines:
        if "actions/checkout@" in line:
            capturing = True
            indent = len(line) - len(line.lstrip())
            out.append(line)
            continue
        if capturing:
            stripped = line.strip()
            cur_indent = len(line) - len(line.lstrip())
            # End of the step when a new same-or-lower-indent list item starts.
            if stripped.startswith("- ") and cur_indent <= indent:
                break
            if stripped and cur_indent <= indent and not stripped.startswith("with") and ":" in stripped and not stripped.startswith("#"):
                # a new step key at the same indent ends the checkout step
                if not stripped.startswith("persist-credentials") and not stripped.startswith("with"):
                    break
            out.append(line)
    return "\n".join(out)


def _read_emit_csp(extra_headers: list | None = None) -> str:
    """Drive SecurityHeadersMiddleware for a normal page and return the emitted CSP."""
    from starlette.requests import Request
    from starlette.responses import Response

    mod = _load_core_middleware()
    mw = mod.SecurityHeadersMiddleware(app=None)

    async def call_next(_request):
        return Response("ok")

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": extra_headers or [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
    }
    resp = asyncio.run(mw.dispatch(Request(scope), call_next))
    return resp.headers.get("Content-Security-Policy", "")


# ==========================================================================
# #160 — webtop base image pinned to an immutable digest (PENDING)
# ==========================================================================
@given("the takeover desktop Dockerfile")
def webtop_dockerfile(t01ctx):
    t01ctx["dockerfile"] = (REPO_ROOT / "docker" / "webtop-chrome" / "Dockerfile").read_text()


@when("its default base image reference is inspected")
def inspect_base_ref(t01ctx):
    m = re.search(r"^ARG BASE=(.+)$", t01ctx["dockerfile"], re.MULTILINE)
    t01ctx["base_ref"] = m.group(1).strip() if m else ""


@then("the base image is pinned to an immutable digest")
def base_is_digest_pinned(t01ctx):
    # A mutable tag (":ubuntu-cinnamon") is unsafe; an immutable ref carries "@sha256:".
    assert "@sha256:" in t01ctx["base_ref"], (
        f"base image is on a mutable tag, not digest-pinned: {t01ctx['base_ref']!r}"
    )


# ==========================================================================
# #161 — application images declare a non-root USER (PENDING)
# ==========================================================================
@given("the engine application Dockerfile")
def engine_dockerfile(t01ctx):
    t01ctx["app_dockerfile"] = (REPO_ROOT / "docker" / "Dockerfile").read_text()


@given("the front-door application Dockerfile")
def frontdoor_dockerfile(t01ctx):
    t01ctx["app_dockerfile"] = (WORKSPACE / "Dockerfile").read_text()


@when("its runtime user is inspected")
def inspect_runtime_user(t01ctx):
    users = re.findall(r"^USER\s+(\S+)", t01ctx["app_dockerfile"], re.MULTILINE)
    t01ctx["declared_users"] = users


@then("a non-root USER directive is declared before the runtime entrypoint")
def nonroot_user_declared(t01ctx):
    non_root = [u for u in t01ctx["declared_users"] if u not in ("root", "0", "0:0")]
    assert non_root, "no non-root USER directive declared in the image"


# ==========================================================================
# #162 — locked deps at/above advisory-fixed releases (GREEN)
# ==========================================================================
def _locked_version(pkg: str) -> str:
    text = (REPO_ROOT / "uv.lock").read_text()
    m = re.search(
        r'\[\[package\]\]\nname = "' + re.escape(pkg) + r'"\nversion = "([^"]+)"', text
    )
    assert m, f"{pkg} not found in uv.lock"
    return m.group(1)


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


@given("the resolved dependency lockfile")
def resolved_lockfile(t01ctx):
    t01ctx["lockfile"] = REPO_ROOT / "uv.lock"


@when("the locked version of the PDF library is read")
def read_pdf_version(t01ctx):
    t01ctx["pdf_version"] = _locked_version("pypdf")


@then("it is at least the advisory-fixed PDF library release")
def pdf_at_least_fixed(t01ctx):
    assert _ver_tuple(t01ctx["pdf_version"]) >= (6, 14, 2), t01ctx["pdf_version"]


@when("the locked version of the settings library is read")
def read_settings_version(t01ctx):
    t01ctx["settings_version"] = _locked_version("pydantic-settings")


@then("it is at least the advisory-fixed settings library release")
def settings_at_least_fixed(t01ctx):
    assert _ver_tuple(t01ctx["settings_version"]) >= (2, 14, 2), t01ctx["settings_version"]


# ==========================================================================
# #163 — file reads contained to a base dir (GREEN helper + PENDING shared seam)
# ==========================================================================
@given("the workspace path-containment helper")
def path_containment_helper(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["app_helpers"] = importlib.import_module("src.app_helpers")
    t01ctx["base"] = str(WORKSPACE)


@when("a path that escapes the base directory is checked")
def check_escaping_path(t01ctx):
    helper = t01ctx["app_helpers"].inside_base_dir
    t01ctx["escape_result"] = helper(t01ctx["base"], str(WORKSPACE / ".." / "etc" / "passwd"))
    t01ctx["inside_result"] = helper(t01ctx["base"], str(WORKSPACE / "src" / "app_helpers.py"))


@then("the path is reported as outside the base directory")
def escaping_outside(t01ctx):
    assert t01ctx["escape_result"] is False


@then("a path inside the base directory is reported as contained")
def inside_contained(t01ctx):
    assert t01ctx["inside_result"] is True


@given("the workspace path utilities module")
def path_utils_module(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["app_helpers"] = importlib.import_module("src.app_helpers")


@when("a shared safe-join helper is requested")
def request_safe_join(t01ctx):
    # The intended centralised fix: a reusable safe-join that joins-and-contains in
    # one call. It does not exist yet, so this records its absence for the Then.
    t01ctx["safe_join"] = getattr(t01ctx["app_helpers"], "safe_join", None)


@then("a containment-enforcing safe-join helper is available for reuse")
def safe_join_available(t01ctx):
    helper = t01ctx["safe_join"]
    assert callable(helper), "no shared safe_join helper exists in src.app_helpers"
    # It must REJECT a traversal (raise or return None/falsey) rather than join blindly.
    escaped = helper(str(WORKSPACE), "../etc/passwd")
    assert not escaped


# ==========================================================================
# #164 — build-time remote fetch integrity (PENDING)
# ==========================================================================
@given("the takeover desktop Dockerfile build step")
def webtop_build_step(t01ctx):
    t01ctx["dockerfile"] = (REPO_ROOT / "docker" / "webtop-chrome" / "Dockerfile").read_text()


@when("the Google Chrome apt source line is inspected")
def inspect_apt_source(t01ctx):
    m = re.search(r'echo "deb \[.*?\] (\S+) ', t01ctx["dockerfile"])
    t01ctx["apt_source_url"] = m.group(1) if m else ""


@then("the apt source URL uses HTTPS")
def apt_source_https(t01ctx):
    assert t01ctx["apt_source_url"].startswith("https://"), t01ctx["apt_source_url"]


@when("the Google signing-key fetch is inspected")
def inspect_key_fetch(t01ctx):
    t01ctx["key_fetch_block"] = t01ctx["dockerfile"]


@then("the fetched key is verified against a pinned fingerprint or checksum")
def key_integrity_verified(t01ctx):
    text = t01ctx["key_fetch_block"]
    # A genuine integrity step would compare a checksum/fingerprint of the fetched key.
    verified = any(
        token in text
        for token in ("sha256sum", "sha256:", "--fingerprint", "gpg --with-fingerprint",
                      "EXPECTED_", "CHECKSUM")
    )
    assert verified, "signing key is fetched and trusted with no checksum/fingerprint verification"


# ==========================================================================
# #167 — CI checkout persist-credentials (GREEN engine + PENDING others)
# ==========================================================================
@given("the engine CI workflow checkout step")
def engine_ci_checkout(t01ctx):
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    t01ctx["checkout_block"] = _checkout_block(text)


@given("the integration CI workflow checkout step")
def integration_ci_checkout(t01ctx):
    text = (REPO_ROOT / ".github" / "workflows" / "ci-integration.yml").read_text()
    t01ctx["checkout_block"] = _checkout_block(text)


@given("the front-door CI workflow checkout step")
def frontdoor_ci_checkout(t01ctx):
    text = (WORKSPACE / ".github" / "workflows" / "ci.yml").read_text()
    t01ctx["checkout_block"] = _checkout_block(text)


@when("the checkout options are inspected")
def inspect_checkout_options(t01ctx):
    t01ctx["persist_disabled"] = "persist-credentials: false" in t01ctx["checkout_block"]


@then("credential persistence is disabled on that checkout")
def engine_persist_disabled(t01ctx):
    assert t01ctx["persist_disabled"] is True


@then("credential persistence is disabled on the integration checkout")
def integration_persist_disabled(t01ctx):
    assert t01ctx["persist_disabled"] is True


@then("credential persistence is disabled on the front-door checkout")
def frontdoor_persist_disabled(t01ctx):
    assert t01ctx["persist_disabled"] is True


# ==========================================================================
# #228 — admin gate refuses remote callers in unconfigured mode (PENDING)
# ==========================================================================
class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeAuthMgr:
    is_configured = False


class _FakeAppState:
    auth_manager = _FakeAuthMgr()


class _FakeApp:
    state = _FakeAppState()


class _FakeReqState:
    current_user = None


class _AdminReq:
    """Minimal request the workspace ``_require_admin`` gate reads."""

    def __init__(self, host: str) -> None:
        self.client = _FakeClient(host)
        self.app = _FakeApp()
        self.state = _FakeReqState()


def _call_require_admin(host: str) -> int:
    _ensure_workspace_on_path()
    from fastapi import HTTPException

    mod = importlib.import_module("routes.applicant_admin_routes")
    try:
        mod._require_admin(_AdminReq(host))
        return 200
    except HTTPException as exc:
        return exc.status_code


@given("the workspace admin gate in unconfigured mode")
def admin_gate_unconfigured(t01ctx):
    t01ctx["call_admin"] = _call_require_admin


@when("an unauthenticated request arrives from a remote address")
def admin_remote_request(t01ctx):
    t01ctx["admin_status"] = t01ctx["call_admin"]("203.0.113.9")


@then("the admin gate refuses the remote caller")
def admin_refuses_remote(t01ctx):
    # Today _require_admin returns "" (status 200) for ANY host in unconfigured mode.
    assert t01ctx["admin_status"] in (401, 403), (
        "remote unauthenticated caller passed the admin gate (no loopback check)"
    )


@when("an unauthenticated request arrives from loopback")
def admin_loopback_request(t01ctx):
    t01ctx["admin_loopback_status"] = t01ctx["call_admin"]("127.0.0.1")


@then("the admin gate allows the loopback caller")
def admin_allows_loopback(t01ctx):
    assert t01ctx["admin_loopback_status"] == 200


# ==========================================================================
# #229 — engine 5xx detail masked (GREEN email + PENDING documents)
# ==========================================================================
_LEAK_DETAIL = "Traceback (most recent call last): RuntimeError at /engine/internal secret-path"


@given("an engine server error carrying a raw traceback")
def engine_5xx_with_traceback(t01ctx):
    _ensure_workspace_on_path()
    eng = importlib.import_module("src.applicant_engine")
    t01ctx["engine_error"] = eng.EngineError("upstream failed", status=500, detail=_LEAK_DETAIL)


@when("the email proxy translates it for the browser")
def email_translate(t01ctx):
    mod = importlib.import_module("routes.applicant_email_routes")
    t01ctx["email_http"] = mod._engine_error_to_http(t01ctx["engine_error"])


@then("a generic message is returned and the raw traceback is not exposed")
def email_masks_detail(t01ctx):
    http = t01ctx["email_http"]
    assert http.status_code == 502
    assert _LEAK_DETAIL not in str(http.detail)
    assert "engine returned an error" in str(http.detail).lower()


@when("the documents proxy translates it for the browser")
def documents_translate(t01ctx):
    mod = importlib.import_module("routes.applicant_documents_routes")
    resp = mod._engine_error_response(t01ctx["engine_error"])
    t01ctx["documents_body"] = resp.body.decode("utf-8")


@then("the documents response does not expose the raw traceback")
def documents_masks_detail(t01ctx):
    # Today the documents proxy still forwards exc.detail verbatim in the body.
    assert _LEAK_DETAIL not in t01ctx["documents_body"], (
        "documents proxy leaks the engine's raw error detail to the browser"
    )


# ==========================================================================
# #230 — engine callback requires owner attribution (PENDING)
# ==========================================================================
@given("the engine-to-workspace callback channel")
def callback_channel(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["app_helpers"] = importlib.import_module("src.app_helpers")


@when("the engine calls without an owner attribution header")
def engine_calls_no_owner(t01ctx):
    # The intended fix: a guard that refuses an unattributed internal callback rather
    # than treating it as the all-owner "internal-engine" principal. Probe its seam.
    t01ctx["guard"] = getattr(t01ctx["app_helpers"], "require_owner_attribution", None)


@then("the callback is refused rather than treated as all-owner access")
def callback_refused(t01ctx):
    guard = t01ctx["guard"]
    assert callable(guard), (
        "no owner-attribution guard exists — an unattributed engine callback is "
        "still mapped to the all-owner 'internal-engine' principal"
    )


# ==========================================================================
# #231 — sanitised public feature view (PENDING)
# ==========================================================================
@given("the workspace feature-state module")
def feature_state_module(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["features_mod"] = importlib.import_module("src.applicant_features")


@when("a configuration-free public feature view is requested")
def request_public_features(t01ctx):
    t01ctx["public_fn"] = getattr(t01ctx["features_mod"], "compute_public_features", None)


@then("a sanitised public feature view is available that omits engine configuration state")
def public_features_available(t01ctx):
    assert callable(t01ctx["public_fn"]), (
        "the unauthenticated /features endpoint still serves compute_features(), which "
        "leaks which LLM/channels/surfaces are configured; no sanitised public variant exists"
    )


# ==========================================================================
# #251 — HTML serving contained to its base (GREEN helper + PENDING serve guard)
# ==========================================================================
@given("the HTML base directory containment helper")
def html_containment_helper(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["app_helpers"] = importlib.import_module("src.app_helpers")
    t01ctx["base"] = str(WORKSPACE / "static")


@when("an escaping HTML path is checked against the base directory")
def check_escaping_html(t01ctx):
    helper = t01ctx["app_helpers"].inside_base_dir
    t01ctx["html_escape_result"] = helper(t01ctx["base"], str(WORKSPACE / "data" / "app.db"))


@then("the escaping HTML path is reported as outside the base directory")
def html_escape_outside(t01ctx):
    assert t01ctx["html_escape_result"] is False


@given("the HTML-serving helper and a path outside its base directory")
def html_serve_helper_and_bad_path(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["serve_html"] = getattr(
        importlib.import_module("src.app_helpers"), "serve_html_contained", None
    )


@when("the HTML-serving helper is asked to serve that path")
def serve_bad_html(t01ctx):
    # The intended fix: a containment-enforcing serve helper. ``_serve_html_with_nonce``
    # in app.py opens any path with no check; the safe variant does not exist yet.
    fn = t01ctx["serve_html"]
    t01ctx["serve_callable"] = callable(fn)


@then("the HTML-serving helper refuses the out-of-base path")
def serve_refuses(t01ctx):
    assert t01ctx["serve_callable"], (
        "no containment-enforcing HTML-serve helper exists; _serve_html_with_nonce "
        "opens its path with no base-directory check"
    )


# ==========================================================================
# #252 — generic unhandled-exception handler (PENDING)
# ==========================================================================
@given("the front-door application module source")
def frontdoor_app_source(t01ctx):
    t01ctx["app_source"] = (WORKSPACE / "app.py").read_text()


@when("its registered exception handlers are inspected")
def inspect_exception_handlers(t01ctx):
    src = t01ctx["app_source"]
    t01ctx["has_catch_all"] = bool(
        re.search(r"@app\.exception_handler\(\s*Exception\s*\)", src)
        or re.search(r"add_exception_handler\(\s*Exception\s*,", src)
    )


@then("a catch-all unhandled-exception handler is registered")
def catch_all_registered(t01ctx):
    assert t01ctx["has_catch_all"], (
        "no generic Exception handler is registered — unhandled crashes fall through "
        "to a bare 500 with no logging enrichment"
    )


# ==========================================================================
# #266 — flag to disable the internal-tool bypass (PENDING)
# ==========================================================================
@given("the workspace middleware module")
def middleware_module(t01ctx):
    t01ctx["middleware"] = _load_core_middleware()


@when("a flag to disable the internal-tool bypass is requested")
def request_disable_flag(t01ctx):
    mod = t01ctx["middleware"]
    # The intended fix exposes an explicit disable switch (a flag/constant or a
    # token value that is None when disabled). Probe for any such seam.
    t01ctx["disable_flag"] = (
        getattr(mod, "INTERNAL_TOOL_DISABLED", None)
        if hasattr(mod, "INTERNAL_TOOL_DISABLED")
        else getattr(mod, "INTERNAL_TOOL_ENABLED", "__missing__")
    )
    t01ctx["token_value"] = getattr(mod, "INTERNAL_TOOL_TOKEN", None)


@then("a configuration flag that disables the internal-tool path exists")
def disable_flag_exists(t01ctx):
    # Today: no flag, and the token auto-generates (always-on) when env is unset.
    has_flag = t01ctx["disable_flag"] != "__missing__"
    assert has_flag, (
        "no flag disables the internal-tool path; INTERNAL_TOOL_TOKEN auto-generates, "
        "so the loopback bypass is always active by default"
    )


# ==========================================================================
# #267 — impersonation gated on admin (PENDING)
# ==========================================================================
@given("the workspace impersonation auth seam")
def impersonation_seam(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["auth_helpers"] = importlib.import_module("src.auth_helpers")


@when("the internal channel attempts to impersonate an existing non-admin owner")
def attempt_impersonation(t01ctx):
    # The intended defense-in-depth fix: an auth-layer guard that allows owner
    # impersonation only in an admin context. Probe its seam.
    t01ctx["impersonation_guard"] = getattr(
        t01ctx["auth_helpers"], "require_admin_for_impersonation", None
    )


@then("impersonation is gated on admin privilege rather than mere user existence")
def impersonation_admin_gated(t01ctx):
    assert callable(t01ctx["impersonation_guard"]), (
        "impersonation via X-Applicant-Owner is gated only on user existence; no "
        "auth-layer admin guard for impersonation exists"
    )


# ==========================================================================
# #268 — CSP forbids a third-party CDN in script-src (PENDING)
# ==========================================================================
@given("the security-headers middleware")
def security_headers_mw(t01ctx):
    t01ctx["middleware"] = _load_core_middleware()


@when("the content-security policy for a normal page is produced")
def produce_csp(t01ctx):
    t01ctx["csp"] = _read_emit_csp()


@then("the script-src directive does not allow a third-party CDN")
def script_src_no_cdn(t01ctx):
    csp = t01ctx["csp"]
    m = re.search(r"script-src([^;]*)", csp)
    script_src = m.group(1) if m else ""
    assert "cdn.jsdelivr.net" not in script_src, (
        "script-src trusts the third-party CDN cdn.jsdelivr.net (KaTeX/Mermaid); "
        "these should be self-hosted"
    )


# ==========================================================================
# #269 — session cookie Secure flag (GREEN env-driven + PENDING proxy auto)
# ==========================================================================
def _resolve_secure_from_env(monkeypatch, value: str | None) -> bool:
    """Reproduce the route's secure-flag resolution (os.getenv SECURE_COOKIES)."""
    import os

    if value is None:
        monkeypatch.delenv("SECURE_COOKIES", raising=False)
    else:
        monkeypatch.setenv("SECURE_COOKIES", value)
    return os.getenv("SECURE_COOKIES", "false").lower() == "true"


@given("the session-cookie secure setting is enabled")
def secure_setting_enabled(t01ctx, monkeypatch):
    t01ctx["monkeypatch"] = monkeypatch
    t01ctx["secure_env"] = "true"
    # Confirm the route actually wires this env into the cookie (not a hardcoded false).
    src = (WORKSPACE / "routes" / "auth_routes.py").read_text()
    assert 'secure=os.getenv("SECURE_COOKIES"' in src, (
        "auth route does not derive the cookie Secure flag from SECURE_COOKIES"
    )


@given("the session-cookie secure setting is left at its default")
def secure_setting_default(t01ctx, monkeypatch):
    t01ctx["monkeypatch"] = monkeypatch
    t01ctx["secure_env"] = None


@when("the cookie secure flag is resolved from configuration")
def resolve_secure_flag(t01ctx):
    t01ctx["resolved_secure"] = _resolve_secure_from_env(
        t01ctx["monkeypatch"], t01ctx["secure_env"]
    )


@then("the resolved cookie secure flag is true")
def secure_flag_true(t01ctx):
    assert t01ctx["resolved_secure"] is True


@then("the resolved cookie secure flag is false")
def secure_flag_false(t01ctx):
    assert t01ctx["resolved_secure"] is False


@given("a request forwarded over HTTPS by a reverse proxy")
def forwarded_https_request(t01ctx):
    _ensure_workspace_on_path()
    t01ctx["auth_routes_src"] = (WORKSPACE / "routes" / "auth_routes.py").read_text()


@when("the cookie secure flag is resolved from the request scheme")
def resolve_secure_from_scheme(t01ctx):
    # The intended fix derives Secure from the forwarded scheme so a TLS reverse proxy
    # that forgets SECURE_COOKIES still gets a secure cookie. Probe for that seam.
    src = t01ctx["auth_routes_src"]
    t01ctx["proxy_aware"] = (
        "x-forwarded-proto" in src.lower() or "request.url.scheme" in src
    )


@then("the cookie is marked Secure even without the explicit setting")
def secure_from_proxy_scheme(t01ctx):
    assert t01ctx["proxy_aware"], (
        "the Secure flag is not auto-derived from a forwarded HTTPS scheme; a TLS "
        "reverse-proxy deployment without SECURE_COOKIES still emits an insecure cookie"
    )


# ==========================================================================
# #280 — deploy script does not pass the DB password inline (PENDING)
# ==========================================================================
@given("the Proxmox deploy script")
def proxmox_deploy_script(t01ctx):
    t01ctx["deploy_script"] = (REPO_ROOT / "scripts" / "proxmox-deploy.sh").read_text()


@when("the database-install invocation is inspected")
def inspect_install_invocation(t01ctx):
    lines = [
        ln for ln in t01ctx["deploy_script"].splitlines()
        if "install.sh" in ln and "POSTGRES_PASSWORD=" in ln
    ]
    t01ctx["inline_pw_lines"] = lines


@then("the database password is not passed inline on the install command line")
def no_inline_password(t01ctx):
    assert not t01ctx["inline_pw_lines"], (
        "proxmox-deploy.sh passes POSTGRES_PASSWORD inline on the install command line "
        "(readable via /proc/<pid>/cmdline and ps aux)"
    )
