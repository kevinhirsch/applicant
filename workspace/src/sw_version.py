"""Service-worker cache-busting (P0-6, DoD item 5).

The PWA service worker (``static/sw.js``) names its cache with a hand-bumped
``CACHE_NAME`` constant ("bump whenever the precache list or SW logic
changes"). A forgotten bump leaves the previous release's precached shell and
assets alive in the named cache — the classic stale-service-worker failure.
The static-serving policy (network-first JS/CSS + ``max-age=60``) already
bounds ONLINE staleness, so the smallest honest fix is to make the cache name
itself track the release: this module stamps a fingerprint of the shipped
front-end assets into ``CACHE_NAME`` when ``/static/sw.js`` is served.

Any changed asset ⇒ different fingerprint ⇒ byte-different service worker ⇒
the browser's SW update cycle installs it, precaches fresh copies, and the
``activate`` handler deletes every older cache. No manual bump needed (the
hand-maintained suffix stays as a belt-and-braces override for logic-only
changes... which the fingerprint also catches, since ``sw.js`` fingerprints
itself).

The fingerprint is computed once per process (deploys restart the server) and
covers the shell + every ``.js``/``.css`` under ``static/`` — a superset of
the precache list, so a drifted precache list cannot dodge the bust.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache

_CACHE_NAME_RE = re.compile(r"(const CACHE_NAME = ')([^']+)(';)")


@lru_cache(maxsize=1)
def static_asset_fingerprint(static_dir: str) -> str:
    """A stable content hash of the shipped front-end assets.

    Hashes the bytes of every ``.js``/``.css``/``.html`` file under
    ``static_dir`` (sorted by relative path, path names included so a rename
    with identical bytes still busts). 12 hex chars — collision-safe for a
    per-release cache label.
    """
    digest = hashlib.sha256()
    # Determinism comes from the outer sorted() over the walk tuples plus
    # sorted(files) — a dirs.sort() here would be dead code (the generator is
    # already fully consumed by sorted()).
    for root, _dirs, files in sorted(os.walk(static_dir)):
        for name in sorted(files):
            if not name.endswith((".js", ".css", ".html")):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, static_dir)
            try:
                with open(path, "rb") as fh:
                    digest.update(rel.encode("utf-8", "replace"))
                    digest.update(b"\0")
                    digest.update(fh.read())
            except OSError:
                # A file racing a deploy: skip rather than 500 the SW fetch —
                # the post-restart process recomputes over the settled tree.
                continue
    return digest.hexdigest()[:12]


def stamp_sw_cache_name(sw_source: str, fingerprint: str) -> str:
    """Rewrite ``const CACHE_NAME = 'applicant-vNNN';`` to carry the release
    fingerprint (``applicant-vNNN-<fingerprint>``). Returns the source
    unchanged if the constant is missing (never break the worker over the
    stamp)."""
    return _CACHE_NAME_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}-{fingerprint}{m.group(3)}",
        sw_source,
        count=1,
    )
