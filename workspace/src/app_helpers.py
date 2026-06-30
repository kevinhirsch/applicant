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
