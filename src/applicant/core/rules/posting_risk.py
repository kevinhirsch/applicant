"""Scam / ghost-job risk scoring for a posting before apply (Issue #367).

A pure, side-effect-free core rule that scores a job posting for scam and
ghost-job signals **before** the engine pre-fills or applies, so the user's PII
is never blasted at a fake listing. High-risk postings are held for explicit
human confirmation rather than auto-applied.

Signals (heuristic, conservative — when in doubt, hold for a human):

* **Unrealistic compensation** — "$9,500/week", "earn $5000 daily", far above
  market for an entry/no-experience role.
* **PII harvesting** — asks for SSN, bank account, full ID scan, or a payment
  up-front before any interview.
* **Off-platform contact** — pushes the conversation to Telegram / WhatsApp /
  personal email only, away from the ATS.
* **No-experience + high-pay** — the classic mule / data-entry scam framing.

Kept in the pure core (no I/O) so every path — service, router, BDD — shares one
definition and the auto-apply gate can never be bypassed by an adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# === risk signal lexicons ==================================================

#: Phrases that solicit sensitive PII / money up-front — a strong scam signal.
_PII_HARVEST_CUES: tuple[str, ...] = (
    "ssn",
    "social security number",
    "bank account",
    "routing number",
    "scan of your id",
    "scan of your driver",
    "photo of your id",
    "credit card",
    "pay a fee",
    "registration fee",
    "send money",
    "wire transfer",
    "gift card",
)

#: Off-platform / unverifiable contact channels the scam pushes you toward.
_OFF_PLATFORM_CUES: tuple[str, ...] = (
    "telegram",
    "whatsapp",
    "signal app",
    "contact us on telegram",
    "text only",
    "message me on",
)

#: Framing that, combined with high pay, marks the classic mule / data-entry scam.
_NO_EXPERIENCE_CUES: tuple[str, ...] = (
    "no experience",
    "no experience needed",
    "no skills required",
    "anyone can apply",
    "work from home easy",
)

#: A pay figure that is implausibly high for the stated effort (weekly/daily).
_UNREALISTIC_PAY_RE = re.compile(
    r"\$\s?([\d,]{3,})\s*(?:/|per\s+)?\s*(week|day|wk|daily|weekly)",
    re.IGNORECASE,
)
#: Weekly pay above this (USD) for a no-experience role is treated as unrealistic.
_WEEKLY_PAY_CEILING = 4000
#: Daily pay above this (USD) is treated as unrealistic.
_DAILY_PAY_CEILING = 800

#: Score at or above which a posting is held for human confirmation.
HIGH_RISK_THRESHOLD = 2


@dataclass(frozen=True)
class PostingRisk:
    """The outcome of scoring a posting for scam / ghost-job risk.

    Immutable so a downstream caller cannot quietly flip ``auto_apply_allowed``
    back to ``True`` after the rule has held a posting.
    """

    score: int
    signals: tuple[str, ...] = ()

    @property
    def is_high_risk(self) -> bool:
        return self.score >= HIGH_RISK_THRESHOLD

    @property
    def auto_apply_allowed(self) -> bool:
        """Auto-apply is permitted only for low-risk postings."""
        return not self.is_high_risk

    @property
    def requires_human_confirmation(self) -> bool:
        """High-risk postings must be confirmed by a human before applying."""
        return self.is_high_risk

    @property
    def reason(self) -> str:
        """A plain-language summary of why the posting was flagged (or cleared)."""
        if not self.signals:
            return "No scam or ghost-job signals detected."
        labels = {
            "unrealistic_compensation": "pay is implausibly high for the role",
            "pii_harvesting": "asks for sensitive personal/financial details up front",
            "off_platform_contact": "pushes contact to an off-platform channel",
            "no_experience_high_pay": "no-experience framing paired with high pay",
        }
        return "; ".join(labels.get(s, s) for s in self.signals)


def _has_unrealistic_pay(text: str) -> bool:
    for amount_str, unit in _UNREALISTIC_PAY_RE.findall(text):
        try:
            amount = int(amount_str.replace(",", ""))
        except ValueError:
            continue
        unit = unit.lower()
        if unit in ("week", "wk", "weekly") and amount >= _WEEKLY_PAY_CEILING:
            return True
        if unit in ("day", "daily") and amount >= _DAILY_PAY_CEILING:
            return True
    return False


def assess_posting_risk(posting: dict) -> PostingRisk:
    """Score a posting for scam / ghost-job risk before apply (#367).

    ``posting`` is a mapping with (any of) ``title``, ``company``,
    ``description`` keys. Returns a :class:`PostingRisk`; a high-risk posting
    has ``auto_apply_allowed is False`` and ``requires_human_confirmation``.
    """
    blob = " ".join(
        str(posting.get(k, ""))
        for k in ("title", "company", "description", "url", "source_url")
    ).lower()

    signals: list[str] = []
    if _has_unrealistic_pay(blob):
        signals.append("unrealistic_compensation")
    if any(cue in blob for cue in _PII_HARVEST_CUES):
        signals.append("pii_harvesting")
    if any(cue in blob for cue in _OFF_PLATFORM_CUES):
        signals.append("off_platform_contact")
    if any(cue in blob for cue in _NO_EXPERIENCE_CUES) and _has_unrealistic_pay(blob):
        signals.append("no_experience_high_pay")

    return PostingRisk(score=len(signals), signals=tuple(signals))
