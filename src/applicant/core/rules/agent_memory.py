"""Agent-memory policy (FR-MIND-1 / FR-MIND-11) — PURE, no IO.

Two responsibilities, both kept in the core so adapters and services cannot drift
from them:

1. **Curated-memory hygiene (FR-MIND-1).** ``is_save_worthy`` is the upstream save
   policy: skip trivia, easily re-derivable facts, large dumps, and one-off session
   details; ``enforce_bounds`` clips a list of entries to a character budget so the
   per-tick snapshot never grows the prompt unboundedly (FR-MIND-13).

2. **Advisory-not-authorization invariant (FR-MIND-11) — the load-bearing rule.**
   Curated memory, skills, and recalled content are **context only**. They can NEVER
   opt the agent past a safety boundary. The boundary (``prefill_boundary``) derives
   its own ground truth from server-side config; this module proves that a skill/
   memory body which *claims* submit/account/CAPTCHA authority changes nothing —
   ``ensure_advisory_only`` strips any such claim to a no-op and the boundary still
   raises. This is what keeps a self-improving loop from improving its way around the
   stop-boundary ("never rely on a caller-supplied input to opt a safety check in").

No external dependencies; no IO; safe to unit-test in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from applicant.core.errors import MemoryPolicyViolation

#: Hard character budget defaults (FR-MIND-1). The store/snapshot enforce these; the
#: container threads the configured values in. A single entry longer than the
#: per-entry cap is a "large dump" and is not save-worthy.
DEFAULT_MEMORY_MAX_CHARS = 8000
DEFAULT_USER_MAX_CHARS = 4000
#: A single curated line longer than this is a paste/dump, not a curated lesson.
_MAX_ENTRY_CHARS = 600
#: A curated line shorter than this carries no real signal (trivia / fragment).
_MIN_ENTRY_CHARS = 8

#: Phrases that, if a skill/memory body uses them, would (if naively trusted) try to
#: claim authority the agent does not have. They are advisory text ONLY — matching
#: one NEVER grants the action; the boundary still derives its own ground truth
#: (FR-MIND-11). Used by ``claims_authority`` to flag content for the audit trail.
_AUTHORITY_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bauto[- ]?submit\b",
        r"\bfinal[- ]?submit\b",
        r"\bsubmit\s+automatically\b",
        r"\bcreate\s+the\s+account\b",
        r"\bcreate\s+an?\s+account\b",
        r"\bsolve\s+the\s+captcha\b",
        r"\bbypass\s+the\s+captcha\b",
        r"\bskip\s+(?:the\s+)?review\b",
        r"\bno\s+approval\s+needed\b",
        r"\byou\s+are\s+authorized\s+to\b",
    )
)

#: One-off / session-detail markers (FR-MIND-1 "skips one-off session details").
_ONE_OFF_MARKERS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bjust\s+now\b",
        r"\bthis\s+session\b",
        r"\bfor\s+now\b",
        r"\btemporar(?:y|ily)\b",
        r"\bignore\s+this\b",
    )
)

#: Trivia / easily re-derivable markers (FR-MIND-1 "skips trivia").
_TRIVIA_MARKERS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^\s*(?:ok|okay|hi|hello|thanks?|thank you|yes|no|sure)\b",
        r"^\s*the\s+(?:current\s+)?(?:date|time)\s+is\b",
        r"^\s*\d+\s*[+\-*/]\s*\d+\s*=",  # arithmetic the model can redo
    )
)


def is_save_worthy(text: str) -> bool:
    """Apply the upstream save policy (FR-MIND-1).

    Returns False for trivia, easily re-derivable facts, large dumps, and one-off
    session details; True for a durable, curated lesson/preference worth keeping.
    """
    s = (text or "").strip()
    if len(s) < _MIN_ENTRY_CHARS:
        return False
    if len(s) > _MAX_ENTRY_CHARS:
        # A large paste/dump is not a curated lesson — consolidate before saving.
        return False
    for pat in _TRIVIA_MARKERS:
        if pat.search(s):
            return False
    for pat in _ONE_OFF_MARKERS:
        if pat.search(s):
            return False
    return True


def claims_authority(text: str) -> bool:
    """True if ``text`` *claims* a safety-gated authority (FR-MIND-11).

    Note: this is purely informational (audit/UI). Matching does NOT block the
    content from being stored as advisory context, and crucially it NEVER grants the
    action — the boundary derives its own ground truth regardless. Use it to flag a
    skill/memory body so a human reviewer sees the claim during write-approval.
    """
    s = text or ""
    return any(pat.search(s) for pat in _AUTHORITY_CLAIM_PATTERNS)


@dataclass(frozen=True)
class AdvisoryContext:
    """Recalled/skill/memory content reduced to its only legitimate role: advice.

    There is intentionally **no** authorization field. Whatever a skill body claimed,
    the agent gets only ``text`` (advice) and a ``claims_authority`` flag for the
    audit trail. The boundary cannot read an "allow" flag from here because none
    exists (FR-MIND-11).
    """

    text: str
    claimed_authority: bool = False


def ensure_advisory_only(text: str) -> AdvisoryContext:
    """Coerce any recalled/skill/memory content into advisory-only context.

    This is the choke point for FR-MIND-11: the returned :class:`AdvisoryContext`
    carries the text as *advice* and a flag noting whether it *claimed* authority,
    but it can never confer authority. Safety guards keep deriving their own ground
    truth; nothing here can flip a boundary decision.
    """
    return AdvisoryContext(text=text or "", claimed_authority=claims_authority(text or ""))


def reject_if_used_as_authorization(*, derived_authorized: bool, claimed: bool) -> None:
    """Guard that a memory/skill claim was NOT mistaken for authorization (FR-MIND-11).

    ``derived_authorized`` is the boundary's OWN server-derived decision. ``claimed``
    is whether the advisory content asserted authority. If content claimed authority
    while the server did NOT grant it, that is fine (advisory text is allowed to say
    anything) — but a caller must never pass the *claim* in as the authorization. This
    helper raises only when a caller tries to source authorization from the claim (the
    two diverge in the dangerous direction), making the misuse loud in tests.
    """
    if claimed and not derived_authorized:
        # The content wants the action; the server did not grant it. The action stays
        # forbidden. Surfacing this as a violation makes any code path that tried to
        # treat the claim as a grant fail loudly rather than silently succeed.
        # NOTE: keep the message white-labeled (no FR-/NFR- jargon, principle #3).
        raise MemoryPolicyViolation(
            "A learned skill or remembered note claimed authority the system did not "
            "grant; it is advisory context only and confers no permission."
        )


def enforce_bounds(entries: tuple[str, ...], max_chars: int) -> tuple[tuple[str, ...], bool]:
    """Clip ``entries`` to a total character budget (FR-MIND-1 / FR-MIND-13).

    Keeps entries in order until the running total would exceed ``max_chars``.
    Returns ``(kept, truncated)`` where ``truncated`` is True if anything was dropped.
    """
    kept: list[str] = []
    total = 0
    truncated = False
    for e in entries:
        n = len(e)
        if total + n > max_chars:
            truncated = True
            continue
        kept.append(e)
        total += n
    return tuple(kept), truncated
