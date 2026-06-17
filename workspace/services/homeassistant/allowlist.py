"""Pure entity-allowlist matching for Home Assistant (Phase 4).

No blanket control: an entity is touchable only if it matches the user's
allowlist. Entries may be an exact entity id (``light.kitchen``), a domain
wildcard (``light`` or ``light.*``), or ``*`` for everything (discouraged).
Standard-library only, so it's exhaustively unit-testable.
"""

from __future__ import annotations

from typing import List, Optional


def entity_domain(entity_id: str) -> str:
    """Return the HA domain of an entity id (``light.kitchen`` -> ``light``)."""
    if not entity_id or "." not in entity_id:
        return ""
    return entity_id.split(".", 1)[0]


def is_allowed(entity_id: str, allowlist: Optional[List[str]]) -> bool:
    """True iff ``entity_id`` is permitted by ``allowlist``.

    Empty/None allowlist => nothing allowed (safe default).
    """
    if not allowlist or not entity_id:
        return False
    dom = entity_domain(entity_id)
    for raw in allowlist:
        a = (raw or "").strip()
        if not a:
            continue
        if a == "*":
            return True
        if a == entity_id:
            return True
        if dom and a in (dom, f"{dom}.*"):
            return True
    return False
