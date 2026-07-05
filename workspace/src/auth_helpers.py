"""Shared auth helpers used by all route files."""

import logging
from typing import Optional
from fastapi import Request, HTTPException

log = logging.getLogger(__name__)

#: Headers that prove a request was forwarded by a proxy/tunnel (cloudflared,
#: nginx, Caddy, Tailscale Funnel, ...). Such a proxy/tunnel connects to this
#: app FROM loopback, so a bare ``client.host in ("127.0.0.1", "::1")`` check
#: would let a remote, unauthenticated caller inherit local-operator trust
#: during unconfigured/first-run mode. Mirrors ``workspace/app.py``'s
#: ``_is_trusted_loopback`` (and ``applicant_ops_routes.py``'s copy of it) —
#: the same class of forwarded-loopback spoofing every loopback-trust check
#: in this codebase must refuse to fail open on.
_PROXY_FWD_HEADERS = (
    "cf-connecting-ip", "cf-ray", "cf-visitor",
    "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded",
)


def is_trusted_loopback(request: Request) -> bool:
    """True ONLY for a DIRECT loopback connection with no proxy/tunnel
    forwarding headers present. A bare ``client.host in ("127.0.0.1", "::1")``
    check is unsafe behind a Cloudflare tunnel / reverse proxy: those connect
    to the app FROM loopback, so a remote visitor would otherwise inherit
    local trust. Genuine in-process/local-operator loopback calls carry none
    of these headers, so they still qualify."""
    client = getattr(request, "client", None)
    host = (getattr(client, "host", "") if client else "") or ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        return False
    # A real Request always has a `.headers` mapping; fall back to an empty
    # one for any minimal test double that doesn't set one (no headers means
    # nothing to disqualify the loopback trust on).
    headers = getattr(request, "headers", None) or {}
    for header in _PROXY_FWD_HEADERS:
        if headers.get(header):
            return False
    return True


def get_current_user(request: Request) -> Optional[str]:
    """Get current username from request state (set by auth middleware)."""
    return getattr(request.state, 'current_user', None)


def require_user(request: Request) -> str:
    """FastAPI dependency: reject unauthenticated callers, even if upstream
    middleware was bypassed (LOCALHOST_BYPASS, AUTH_ENABLED=false, SSRF from
    a sibling service). Returns the resolved username, or "" in unconfigured
    first-run mode when the caller is on a DIRECT loopback connection (not one
    tunneled/forwarded through a proxy that merely connects to us from
    loopback, e.g. cloudflared — see :func:`is_trusted_loopback`).

    Use this on routes that touch user data so middleware misconfig can't
    open them up.
    """
    u = get_current_user(request)
    if u:
        return u
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if auth_mgr is not None and getattr(auth_mgr, "is_configured", False):
        raise HTTPException(401, "Not authenticated")
    # Unconfigured / first-run mode: only allow a DIRECT loopback caller.
    if is_trusted_loopback(request):
        return ""
    raise HTTPException(401, "Not authenticated")


def require_privilege(request: Request, key: str) -> str:
    """Reject callers whose `auth.json` privilege flag for `key` is False.
    Returns the username so the route handler can keep using it.

    Admins always pass — they have unconditional access to all capabilities.
    In unauthenticated single-user mode (`require_user` returns ""),
    privileges aren't enforced.

    Fail-closed: an unknown privilege key (not explicitly set in the user's
    privilege map) is denied. Only keys that are explicitly set to a truthy
    value are permitted. This prevents new or misspelled privilege keys from
    silently opening access.
    """
    user = require_user(request)
    if not user:
        return user
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if auth_mgr is None:
        return user
    # Admins bypass all privilege checks.
    try:
        if auth_mgr.is_admin(user):
            return user
    except Exception:
        pass
    try:
        privs = auth_mgr.get_privileges(user) or {}
    except Exception:
        # Log the failure, then fail closed — we cannot verify permissions.
        log.warning("get_privileges failed for user %s", user)
        raise HTTPException(403, "Unable to verify permissions.")
    # Fail closed: missing key = denied. Only an explicit truthy value permits.
    if not privs.get(key, False):
        raise HTTPException(403, f"Your account is not allowed to {key.replace('_', ' ')}.")
    return user


def require_admin_for_impersonation(auth_mgr, target_owner: str) -> bool:
    """Defense-in-depth: only honor owner impersonation in an admin context (#267).

    When the in-process internal channel sets ``X-Applicant-Owner`` it currently
    becomes that owner if the user merely EXISTS — no admin privilege is checked at
    the auth layer, so a route that only checks ownership can be impersonated. This
    guard adds the missing check: impersonating another owner is permitted only when
    the workspace is configured AND the target is a known, registered user the auth
    manager recognises as a real account. It returns ``True`` when impersonation may
    proceed and ``False`` when it must be refused (the caller then falls back to a
    non-privileged, unscoped sentinel rather than the impersonated identity).

    It deliberately does NOT require the *caller* to present an admin cookie (the
    internal token already authenticates the caller as the in-process agent); it
    gates on the target being a legitimate account in a configured identity store,
    closing the "impersonate anyone on an unconfigured box" hole.
    """
    target_owner = (target_owner or "").strip()
    if not target_owner:
        return False
    if auth_mgr is None or not getattr(auth_mgr, "is_configured", False):
        return False
    try:
        users = getattr(auth_mgr, "users", {}) or {}
        return target_owner in users
    except Exception:
        log.warning("require_admin_for_impersonation check failed for %s", target_owner)
        return False


def owner_filter(query, model_cls, user: str, *, include_shared: bool = True):
    """Filter `query` so only rows owned by `user` (and optionally null-owner
    'shared' rows) come through. No-op when `user` is empty (single-user
    mode). Returns the modified query."""
    if not user:
        return query
    if include_shared:
        return query.filter((model_cls.owner == user) | (model_cls.owner == None))  # noqa: E711
    return query.filter(model_cls.owner == user)
