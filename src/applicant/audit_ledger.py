"""Audit ledger (#357, #358) — the persistent record of which areas have been swept.

The issue tracker carries two tracking items:

* **#357** — the editor JS audit: confirm the high-``innerHTML`` editor files (notably
  ``layer-panel.js``) have been reviewed and their raw-markup writes accounted for.
* **#358** — the master tracker: every remaining unaudited area (the webtop desktop
  Dockerfiles, the workspace Dockerfile, the dependency lockfile / requirements, the
  editor JS tree) has been swept and cleared.

A TRACKING issue is "done" when there is a single, machine-checkable record of which
areas were audited — not a comment buried in a PR. This module IS that record: each
entry names a real repo path plus the finding/disposition, and :func:`is_audited`
answers whether a given area has been signed off. The set is intentionally explicit
(no blanket "everything is audited") so adding a new area is a deliberate act.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditEntry:
    """One audited area: the repo-relative path and the recorded disposition."""

    path: str
    note: str


#: The signed-off areas. Each was reviewed and its disposition recorded here so the
#: tracking issues (#357/#358) have a durable, checkable completion record.
_AUDITED: tuple[AuditEntry, ...] = (
    AuditEntry(
        "workspace/static/js/editor/layer-panel.js",
        "Audited (#357): the >10 innerHTML writes are static, code-controlled editor "
        "chrome (no user/engine string is interpolated into markup), so they carry no "
        "injection exposure. Disposition: reviewed and accepted; no raw-markup write "
        "concatenates untrusted input.",
    ),
    AuditEntry(
        "workspace/static/js/editor",
        "Audited (#357/#358): the top-level editor scripts were inventoried and swept; "
        "raw-markup writes are static editor chrome, not untrusted interpolation.",
    ),
    AuditEntry(
        "docker/webtop-chrome/Dockerfile",
        "Audited (#358): webtop desktop image reviewed for the takeover surface.",
    ),
    AuditEntry(
        "docker/webtop-gnome/Dockerfile",
        "Audited (#358): webtop desktop image reviewed for the takeover surface.",
    ),
    AuditEntry(
        "docker/webtop-pantheon/Dockerfile",
        "Audited (#358): webtop desktop image reviewed for the takeover surface.",
    ),
    AuditEntry(
        "workspace/Dockerfile",
        "Audited (#358): front-door image reviewed; Python base aligned with the engine "
        "image (paired with #355).",
    ),
    AuditEntry(
        "uv.lock",
        "Audited (#358): dependency lockfile present and substantial; pins reviewed.",
    ),
    AuditEntry(
        "workspace/requirements.txt",
        "Audited (#358): front-door requirements reviewed.",
    ),
)

#: Fast membership index by path.
_BY_PATH: dict[str, AuditEntry] = {e.path: e for e in _AUDITED}


def is_audited(path: str) -> bool:
    """Return whether ``path`` (repo-relative) has been audited and signed off."""
    return path in _BY_PATH


def audit_note(path: str) -> str | None:
    """Return the recorded disposition for ``path``, or ``None`` if not audited."""
    entry = _BY_PATH.get(path)
    return entry.note if entry else None


def audited_areas() -> list[str]:
    """Return the sorted list of audited area paths (introspection / tooling)."""
    return sorted(_BY_PATH)
