# src/app_helpers.py
import os
import base64
import logging

log = logging.getLogger(__name__)

def read_if_exists(path: str) -> str:
    """Read file if it exists, return empty string otherwise."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        log.warning("read_if_exists failed for %s", path)
        return ""

def file_to_data_url(path: str, mime: str) -> str:
    """Convert file to data URL."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def abs_join(base_dir: str, rel: str) -> str:
    """Join paths and return absolute path."""
    return os.path.abspath(os.path.join(base_dir, rel))

def inside_base_dir(base_dir: str, path: str) -> bool:
    """Check if path is inside base directory."""
    base = os.path.realpath(base_dir)
    p = os.path.realpath(path)
    try:
        return os.path.commonpath([base, p]) == base
    except Exception:
        log.warning("inside_base_dir failed for base=%s path=%s", base_dir, path)
        return False


#: Sentinel owner principal the engine->workspace callback channel falls back to
#: when no ``X-Applicant-Owner`` header is supplied. Owner-scoping treats this as
#: "all owners' data", so an unattributed callback must never be honored as this
#: principal (see ``require_owner_attribution``).
ALL_OWNER_PRINCIPAL = "internal-engine"


def require_owner_attribution(owner, known_users) -> str:
    """Resolve the owner an internal engine callback is scoped to, or refuse it.

    The engine->workspace callback channel is token-gated, but the token only
    proves the *caller* is the engine — it does not say *whose* data the call is
    for. Attributing an unattributed (or unknown-user) callback to the
    ``internal-engine`` all-owner principal means a single leaked token grants
    access to EVERY owner's data. This guard refuses that: a callback must name a
    real, known owner via ``X-Applicant-Owner`` or it is rejected.

    ``owner`` is the trimmed header value (may be empty/None). ``known_users`` is
    the auth manager's user map (or any container supporting ``in``). Returns the
    validated owner string on success; raises ``ValueError`` otherwise so the
    caller can translate it to a 401/403 rather than silently widening scope.
    """
    owner = (owner or "").strip()
    if not owner:
        raise ValueError("internal callback refused: no owner attribution supplied")
    if owner == ALL_OWNER_PRINCIPAL:
        raise ValueError("internal callback refused: cannot impersonate the all-owner principal")
    try:
        is_known = owner in (known_users or {})
    except TypeError:
        is_known = False
    if not is_known:
        raise ValueError(f"internal callback refused: unknown owner {owner!r}")
    return owner


def serve_html_contained(base_dir: str, file_path: str) -> str:
    """Read an HTML file ONLY if it resolves inside ``base_dir``; refuse otherwise.

    Centralised containment-enforcing read for any HTML-serving route: the path is
    resolved (collapsing ``..`` and symlinks) and asserted to live inside
    ``base_dir`` BEFORE the file is opened, so a caller threading user input here
    cannot read outside the served-app root. Raises ``ValueError`` on an
    out-of-base path (callers translate to a 404), and lets a genuine missing-file
    ``FileNotFoundError`` propagate.
    """
    if not inside_base_dir(base_dir, file_path):
        raise ValueError(
            f"refusing to serve path outside base: {file_path!r} escapes {base_dir!r}"
        )
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


#: Module-level cache for ``read_cached_html_parts``: absolute file path ->
#: (mtime, split-parts-list). Each served HTML file (index.html,
#: backgrounds.html, login.html, ...) gets its own independent entry.
_html_parts_cache: dict = {}


def read_cached_html_parts(
    base_dir: str,
    file_path: str,
    cache=None,
    nonce_token: str = "{{CSP_NONCE}}",
) -> list:
    """Containment-checked HTML read, split around ``nonce_token``, cached by mtime.

    Perf audit (round-3 lens #11): ``index.html`` is 232 KB and was re-read from
    disk PLUS re-scanned with a full-string ``.replace()`` on every single
    navigation (nine deep-link routes share ``serve_index``), with no ETag/304
    support anywhere in the chain. Only the nonce substitution itself is
    genuinely per-request — CSP requires a fresh, unique nonce on EVERY response
    (see ``core/middleware.py``, ``secrets.token_hex(16)`` generated per request
    before this function ever runs) — the disk read and the 232 KB scan are not.

    This splits the file's contents on ``nonce_token`` once and caches the
    resulting list of static segments keyed by the file's
    ``os.stat().st_mtime``. As long as mtime is unchanged, repeat calls for the
    same ``file_path`` skip the disk read AND the string-scan entirely; a
    redeploy/edit that touches the file's mtime naturally busts the cache with
    no manual invalidation needed. Callers reassemble the live response with
    ``nonce.join(parts)`` — cheap regardless of file size — which is exactly
    equivalent to ``content.replace(nonce_token, nonce)`` (same set of
    occurrences, same replacement value); only the expensive scan is amortized
    across every request that shares a file version.

    Containment (``inside_base_dir``) is re-checked on every call — the cache
    only stores already-validated paths' *contents*, never a decision that
    would let a differently-shaped ``file_path`` skip the check. Raises
    ``ValueError`` on an out-of-base path (callers translate to a 404) and lets
    a genuine missing-file ``FileNotFoundError`` propagate, matching
    ``serve_html_contained``.
    """
    if cache is None:
        cache = _html_parts_cache
    if not inside_base_dir(base_dir, file_path):
        raise ValueError(
            f"refusing to serve path outside base: {file_path!r} escapes {base_dir!r}"
        )
    mtime = os.stat(file_path).st_mtime  # raises FileNotFoundError if missing
    cached = cache.get(file_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    parts = content.split(nonce_token)
    cache[file_path] = (mtime, parts)
    return parts


def safe_join(base_dir: str, *parts: str) -> str:
    """Join UNTRUSTED ``parts`` onto ``base_dir`` and return a contained realpath.

    Resolves the joined path with os.path.realpath (collapsing .. and
    symlinks) and asserts it still lives inside ``base_dir``. Raises
    ValueError otherwise — so a traversal value like
    ``"../../etc/passwd"`` or an absolute ``"/etc/passwd"`` is rejected before any
    file is opened.

    Use this at the boundary where a caller-supplied value first becomes a path;
    do the owner-scoping check BEFORE calling this, never instead of it.

    NOTE: delegates to core.safe_path.safe_join when available; inlines the same
    logic otherwise so this module stays importable without the full workspace deps.
    """
    try:
        from core.safe_path import safe_join as _core_safe_join
        return _core_safe_join(base_dir, *parts)
    except ImportError:
        # Fallback: inline the containment logic (identical behaviour, no extra deps).
        if not parts:
            raise ValueError("safe_join requires at least one path component")
        base = os.path.realpath(base_dir)
        candidate = os.path.realpath(os.path.join(base, *parts))
        if not inside_base_dir(base, candidate):
            raise ValueError(
                f"refusing path outside allowed base: {os.path.join(*parts)!r} "
                f"escapes {base_dir!r}"
            )
        return candidate
