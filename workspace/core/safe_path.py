"""Shared safe-path helper — defends file reads/writes against path traversal
and file-inclusion (`../../etc/passwd`, absolute-path escape, symlink escape).

Many call sites build a filesystem path from a user- or agent-supplied value (a
session id, a filename, a document key) and `open()` it. Without containment a
poisoned value can traverse outside the intended directory and read or clobber
arbitrary files. This module centralizes the fix so every such site reuses one
audited implementation instead of ad-hoc per-call patches:

* :func:`safe_join` — join an UNTRUSTED relative component to an allowed base dir
  and return the realpath, raising :class:`UnsafePathError` if the result escapes
  the base (after resolving ``..`` and symlinks).
* :func:`is_within_base` — boolean containment check (the existing
  ``app_helpers.inside_base_dir`` predicate, lifted here so engine + workspace
  share one definition).
* :func:`safe_filename` — reduce a value to a bare, traversal-free basename for
  the cases where only a single filename (no sub-dirs) is ever legitimate.

Pure + IO-light (only ``os.path.realpath`` on the supplied strings — no network),
so it is hermetically unit-testable.
"""

from __future__ import annotations

import os


class UnsafePathError(ValueError):
    """Raised when a resolved path escapes its allowed base directory."""


def is_within_base(base_dir: str, path: str) -> bool:
    """Return True iff ``path`` resolves to a location inside ``base_dir``.

    Both sides are passed through :func:`os.path.realpath` first so ``..`` segments
    and symlinks are resolved before the containment comparison. Returns ``False``
    (fail closed) on any error rather than raising.
    """
    try:
        base = os.path.realpath(base_dir)
        target = os.path.realpath(path)
    except Exception:
        return False
    try:
        return os.path.commonpath([base, target]) == base
    except Exception:
        # commonpath raises when the paths are on different drives (Windows) or one
        # is relative and the other absolute — treat as "not contained".
        return False


def safe_join(base_dir: str, *parts: str) -> str:
    """Join UNTRUSTED ``parts`` onto ``base_dir`` and return a contained realpath.

    Resolves the joined path with :func:`os.path.realpath` (collapsing ``..`` and
    symlinks) and asserts it still lives inside ``base_dir``. Raises
    :class:`UnsafePathError` otherwise — so a traversal value like
    ``"../../etc/passwd"`` or an absolute ``"/etc/passwd"`` is rejected before any
    file is opened.

    Use this at the boundary where a caller-supplied value first becomes a path;
    do the owner-scoping check BEFORE calling this, never instead of it.
    """
    if not parts:
        raise UnsafePathError("safe_join requires at least one path component")
    base = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(base, *parts))
    if not is_within_base(base, candidate):
        raise UnsafePathError(
            f"refusing path outside allowed base: {os.path.join(*parts)!r} "
            f"escapes {base_dir!r}"
        )
    return candidate


def safe_filename(name: str) -> str:
    """Reduce ``name`` to a bare, traversal-free basename.

    Strips any directory components (``os.path.basename``) and rejects empty,
    ``.`` / ``..`` results — for the cases where only a single flat filename is
    ever legitimate (no sub-directories). Raises :class:`UnsafePathError` when the
    value cannot be reduced to a usable filename.
    """
    cleaned = os.path.basename((name or "").strip().replace("\\", "/").rstrip("/"))
    cleaned = os.path.basename(cleaned)
    if not cleaned or cleaned in (".", ".."):
        raise UnsafePathError(f"invalid filename: {name!r}")
    return cleaned
