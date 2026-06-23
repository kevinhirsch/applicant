"""EssentialsNudgeService — the proactive "I'm still blocked" nudge (FR-NOTIF / FR-ONBOARD / FR-AGENT-7).

This closes the onboarding loop: the minimal intake form gates almost nothing, the
agent asks for the required-to-apply essentials in chat, and — if the user wanders
off before supplying them — THIS service pushes a friendly, first-person nudge that
names exactly what is still missing, so the user comes back and unblocks the gate.

It is the PUSH sibling of the apply-readiness "what's still missing" surface
(``OnboardingService.apply_readiness``): once per UTC day, for each active campaign
whose automated work is BLOCKED specifically because apply-essentials are absent, it
pushes ONE short, plain-language, white-labeled notification through the EXISTING
notification system (in-app inbox + the user's opt-in channel fan-out) — NOT a
parallel channel (binding principle #1).

Truthful (FR-AGENT-5): the missing list is read back from ``apply_readiness().missing``
— never fabricated. When the gate is already open (nothing missing), the service emits
nothing at all. Scheduling/idempotency live in the scheduler (mirroring the daily
digest + curation + status-update cadence); this service only decides + emits one
nudge on demand.
"""

from __future__ import annotations

from datetime import date, datetime

from applicant.observability.logging import get_logger

log = get_logger(__name__)


class EssentialsNudgeService:
    """Assembles + pushes the once-daily "still blocked on essentials" nudge."""

    def __init__(
        self,
        *,
        notification_service=None,
        onboarding_service=None,
    ) -> None:
        # The EXISTING notification path (in-app inbox + opt-in fan-out). Reused, not
        # rebuilt (principle #1). When None the service is a no-op (degrades gracefully).
        self._notifications = notification_service
        # The single source of truth for "what's still missing": apply_readiness reads
        # REAL campaign state (criteria + résumé presence). Optional: when absent the
        # service has nothing truthful to say and emits nothing.
        self._onboarding = onboarding_service

    def dedup_key(self, campaign_id, day: date) -> str:
        """Stable per-(campaign, UTC day) idempotency key (FR-NOTIF-3).

        The scheduler already guards the once-per-day cadence; this key makes a
        re-driven same-day emit a no-op at the notifier too (defense in depth).
        """
        return f"essentials_nudge:{campaign_id}:{day.isoformat()}"

    def emit(self, campaign_id, now: datetime) -> str | None:
        """Assemble + push ONE essentials nudge for ``campaign_id``.

        Returns the notification handle when a nudge was pushed, or ``None`` when there
        is nothing to nudge about — the gate is already open / nothing's missing, no
        readiness reader is wired, or no notifier is wired. Bounded + truthful: the
        missing list comes straight from ``apply_readiness`` (FR-AGENT-5).
        """
        if self._notifications is None or self._onboarding is None:
            return None
        missing = self._missing(campaign_id)
        if not missing:
            # Gate is open (or nothing's known to be missing) — emit nothing.
            return None
        body = self.build_message(missing)
        if not body:
            return None
        notify = getattr(self._notifications, "notify_essentials_nudge", None)
        if notify is None:  # pragma: no cover - defensive (older notifier)
            return None
        return notify(
            campaign_id=str(campaign_id),
            body=body,
            day=now.date(),
            deep_link="/wizard",
        )

    # --- truthful missing-essentials read (FR-AGENT-5) --------------------
    def _missing(self, campaign_id) -> tuple[str, ...]:
        """The REAL still-missing essentials for the campaign, or ``()``.

        Read back from ``apply_readiness`` — never fabricated. A ready campaign (gate
        open) yields ``()`` so the caller emits nothing. Defensive: a reader hiccup
        yields ``()`` (we never invent a missing list).
        """
        try:
            readiness = self._onboarding.apply_readiness(str(campaign_id))
        except Exception:  # pragma: no cover - defensive: never invent a missing list
            return ()
        if readiness is None or readiness.ready:
            return ()
        return tuple(readiness.missing or ())

    # --- message assembly (first-person, white-label) ---------------------
    def build_message(self, missing) -> str | None:
        """A SHORT, friendly, first-person nudge naming the missing essentials.

        Reads naturally for one item ("I still need a salary floor") or several ("I
        still need your target roles and a salary floor"). Plain language, no
        codenames / FR jargon. Returns ``None`` when nothing is missing.
        """
        items = [str(m).strip() for m in (missing or ()) if str(m).strip()]
        if not items:
            return None
        return (
            "I'm ready to start applying, but I still need "
            + _join(items)
            + ". Add "
            + ("it" if len(items) == 1 else "them")
            + " and I'll begin."
        )


# --- small text helper (pure) --------------------------------------------
def _join(parts: list[str]) -> str:
    """Join clauses with commas + a trailing 'and' (plain language)."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
