"""Shared auth helpers used by all route files."""

from typing import Optional
from fastapi import Request, HTTPException


def get_current_user(request: Request) -> Optional[str]:
    """Get current username from request state (set by auth middleware)."""
    return getattr(request.state, 'current_user', None)


def require_user(request: Request) -> str:
    """FastAPI dependency: reject unauthenticated callers, even if upstream
    middleware was bypassed (LOCALHOST_BYPASS, AUTH_ENABLED=false, SSRF from
    a sibling service). Returns the resolved username, or "" in unconfigured
    first-run mode when the caller is on loopback.

    Use this on routes that touch user data so middleware misconfig can't
    open them up.
    """
    u = get_current_user(request)
    if u:
        return u
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    if auth_mgr is not None and getattr(auth_mgr, "is_configured", False):
        raise HTTPException(401, "Not authenticated")
    # Unconfigured / first-run mode: only allow loopback callers.
    client = getattr(request, "client", None)
    host = (client.host if client else "") or ""
    if host in ("127.0.0.1", "::1", "localhost"):
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
        # If we can't read privileges, fail closed.
        raise HTTPException(403, "Unable to verify permissions.")
    # Fail closed: missing key = denied. Only an explicit truthy value permits.
    if not privs.get(key, False):
        raise HTTPException(403, f"Your account is not allowed to {key.replace('_', ' ')}.")
    return user


def owner_filter(query, model_cls, user: str, *, include_shared: bool = True):
    """Filter `query` so only rows owned by `user` (and optionally null-owner
    'shared' rows) come through. No-op when `user` is empty (single-user
    mode). Returns the modified query."""
    if not user:
        return query
    if include_shared:
        return query.filter((model_cls.owner == user) | (model_cls.owner == None))  # noqa: E711
    return query.filter(model_cls.owner == user)
