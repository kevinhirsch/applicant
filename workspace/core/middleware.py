# src/middleware.py
# Shared middleware, decorators, and request helpers

import os
import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


# Per-process token that lets the in-app tool layer hit admin-gated
# routes via HTTP loopback (the agent's tool calls don't carry the
# admin user's session cookie). Read from APPLICANT_INTERNAL_TOKEN only;
# never auto-generated. An empty/unset value disables the bypass so the
# channel is not silently active in unconfigured deployments.
# Mirror: routes/applicant_internal_routes.py requires explicit config.
INTERNAL_TOOL_TOKEN: str = (os.environ.get("APPLICANT_INTERNAL_TOKEN") or "").strip()
INTERNAL_TOOL_HEADER = "X-Applicant-Internal-Token"

# Explicit kill switch for the internal-tool loopback bypass (#266). Operators
# can hard-disable the path even when a token is configured by setting
# APPLICANT_INTERNAL_TOOL=off (or false/0/disabled). Otherwise the bypass is
# active only when a token is actually configured — it never auto-generates, so
# an unconfigured deployment has it OFF by default. ``require_admin`` /
# ``verify_internal_tool`` consult this flag, so flipping it off closes the path
# regardless of whether a token happens to be present.
INTERNAL_TOOL_ENABLED: bool = bool(INTERNAL_TOOL_TOKEN) and (
    (os.environ.get("APPLICANT_INTERNAL_TOOL") or "on").strip().lower()
    not in ("off", "false", "0", "no", "disabled")
)


def internal_tool_active(token_header: str | None) -> bool:
    """True only when the internal-tool bypass is enabled AND the header matches.

    Single chokepoint for the loopback bypass: it short-circuits to ``False`` when
    the path is disabled (no token configured, or the explicit kill switch is set),
    so a single flag flip closes the bypass everywhere it is consulted.
    """
    if not INTERNAL_TOOL_ENABLED or not token_header:
        return False
    return secrets.compare_digest(token_header, INTERNAL_TOOL_TOKEN)


def verify_origin(request: Request) -> bool:
    """Return True when the request Origin/Referer matches the app's own origin.

    CSRF guard for cookie-authenticated non-GET ``/api/*`` mutations: an
    attacker page on a different origin cannot forge a request because the
    browser sets ``Origin`` (and, as a fallback, ``Referer``) to the attacker's
    origin.  This function extracts that header, parses its scheme+host+port,
    and compares it against the request's own ``base_url``.

    Callers should skip this check for ``/api/applicant/internal/*`` (token-
    gated, not cookie-authed) and for safe methods (GET/HEAD/OPTIONS).
    """
    raw = (
        request.headers.get("origin")
        or request.headers.get("referer")
    )
    if not raw:
        return False

    parsed = urlparse(raw)
    origin_netloc = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        origin_netloc += f":{parsed.port}"

    base = request.base_url
    app_origin = f"{base.scheme}://{base.hostname}"
    if base.port:
        app_origin += f":{base.port}"

    return origin_netloc == app_origin


def require_admin(request: Request):
    """Raise 403 if the current user isn't an admin.
    Allows access when auth is explicitly disabled, or when the request carries
    the in-process internal-tool token used by loopback agent tools.
    """
    # In-process bypass for tool-layer loopback calls. Two paths:
    # (a) header-direct (caller set X-Applicant-Internal-Token), or
    # (b) the auth middleware already validated the token and stamped
    #     request.state.current_user = "internal-tool".
    try:
        hdr = request.headers.get(INTERNAL_TOOL_HEADER)
        if internal_tool_active(hdr):
            return
        if getattr(request.state, "current_user", None) == "internal-tool":
            return
    except Exception:
        pass

    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if os.getenv("AUTH_ENABLED", "true").lower() == "false":
        return
    if not auth_mgr or not auth_mgr.is_configured:
        raise HTTPException(403, "Admin only")
    user = getattr(request.state, "current_user", None)
    if not user or not auth_mgr.is_admin(user):
        raise HTTPException(403, "Admin only")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        # Generate a per-request nonce for inline scripts. Only the handful of
        # HTML-serving routes (`/`, `/login`, and their deep-link siblings via
        # `_serve_html_with_nonce` in app.py) ever read `request.state.csp_nonce`
        # to stamp it into a shipped page's `{{CSP_NONCE}}` placeholder. Every
        # `/static/*` asset (~162 JS/CSS modules per page load, per the perf
        # audit) is served straight from disk and never consults it, and the
        # CSP header a non-HTML asset response carries is inert anyway (CSP is
        # enforced against the navigated document, not each sub-resource
        # fetch) — so skip the `secrets.token_hex` call for that whole path
        # prefix instead of paying it on every single asset request.
        if path.startswith("/static/"):
            nonce = ""
        else:
            nonce = secrets.token_hex(16)
        request.state.csp_nonce = nonce

        # --- CSRF: refuse cross-origin state-changing /api/* requests ---
        # Safe methods (GET/HEAD/OPTIONS) and the token-gated internal channel
        # are exempt; everything else under /api/ that relies on the session
        # cookie must pass a same-origin check.
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and path.startswith("/api/")
            and not path.startswith("/api/applicant/internal/")
            and not verify_origin(request)
        ):
            return Response(
                content='{"detail":"CSRF check failed"}',
                status_code=403,
                media_type="application/json",
            )

        response = await call_next(request)
        path = request.url.path

        # Tool render endpoints are served inside iframes — allow framing by self
        is_tool_render = path.startswith("/api/tools/") and path.endswith("/render")
        # Visual report pages are self-contained HTML — need inline scripts + external images
        is_report = path.startswith("/api/research/report/")

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"

        if is_report:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                "img-src 'self' data: blob: https:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        elif is_tool_render:
            # Tool iframe content: skip all framing headers — the iframe's
            # sandbox="allow-scripts" attribute provides isolation.
            # Don't overwrite the route's own restrictive CSP either.
            pass
        else:
            response.headers["X-Frame-Options"] = "DENY"
            # NOTE: `style-src 'unsafe-inline'` is intentionally retained.
            # `static/index.html` and `static/login.html` ship inline <style>
            # blocks, and several JS modules build runtime `style=""` attrs.
            # Migrating to nonce-only requires templating the HTML files +
            # auditing every JS-set style attribute. Since inline styles
            # don't execute script, the residual risk is visual-only.
            # CDN scripts (KaTeX, Mermaid) are SRI-pinned via integrity
            # hashes on the <script> tags and CSP hash sources below, so
            # cdn.jsdelivr.net is removed from script-src.
            # NOTE: cdn.jsdelivr.net IS still required in style-src and
            # font-src — index.html loads katex.min.css (and KaTeX's
            # @font-face math fonts) from the CDN. SRI/integrity does not
            # exempt a resource from CSP, so dropping the origin here blocks
            # the stylesheet and fonts and breaks math rendering.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}' "
                "'sha256-6NiFUFlJ86X0q91d0NU2lr0Tca0m/79PMQ3Nd8jNrok=' "
                "'sha256-dNfEbavKMowilHM5EKiqHtDDdFF3bo1Sldo4ordY+5s='; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "font-src 'self' https://cdn.jsdelivr.net; "
                "img-src 'self' data: blob:; "
                "media-src 'self' blob:; "
                "connect-src 'self'; "
                "frame-src 'self'; "
                "frame-ancestors 'none'"
            )
        return response
