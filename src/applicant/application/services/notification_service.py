"""NotificationService (FR-NOTIF-1/2/3/5).

Orchestrates the multi-channel escalation ladder for decisions awaiting the user:

- a **decision is created server-side** and a notification is queued through the
  ``NotificationPort`` (FR-NOTIF-2): the Discord push is held ~30s for a web-portal
  pre-empt; the in-app surface is preferred when the user is verifiably present;
  email follows after the configurable timeout;
- **idempotency** (FR-NOTIF-3): ``acted`` expires every pending channel for the same
  decision so acting on one no-ops the others;
- **errors** are sent IMMEDIATE so they fan out any hour, bypassing quiet hours
  (FR-NOTIF-5).

Time is driven by the adapter's injected clock; ``advance`` steps the ladder
deterministically (no real sleeps), so the durable layer (Phase 2) can call it from
a scheduled tick and tests can step it directly.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime

from applicant.observability.logging import get_logger
from applicant.ports.driven.notification import Notification, NotificationUrgency

log = get_logger(__name__)


class NotificationService:
    def __init__(self, notification) -> None:
        self._notification = notification
        # (campaign_id, UTC date) the digest-ready ping already fired for (#15). This
        # service instance is SHARED across the scheduler's fresh-per-tick AgentLoops,
        # so this per-day marker survives the loop's empty ``_digest_sent`` and makes
        # the ready ping fire exactly once per campaign per UTC day even in prod.
        self._digest_ready_sent: dict[tuple[str, date], str] = {}
        # CONC: this service is shared across the scheduler's fresh-per-tick loops, and
        # the scheduler tick now runs OFF the event loop (worker thread), so the
        # read-modify-write of ``_digest_ready_sent`` must be guarded against two
        # overlapping ticks racing the same per-day marker.
        self._digest_ready_lock = threading.Lock()
        # outcome-event id -> notification handle already sent for it (design-audit
        # Top-25 #5). Same shared-across-ticks/requests instance as above, so this
        # is the single source of truth that makes a retry/replay of the SAME
        # OutcomeEvent id a no-op rather than a second celebratory ping.
        self._positive_outcome_sent: dict[str, str] = {}
        self._positive_outcome_lock = threading.Lock()

    def dedup_key(self, decision_ref: str) -> str:
        """Stable cross-channel idempotency key for a decision (FR-NOTIF-3)."""
        return f"decision:{decision_ref}"

    # --- decision/approval ladder (FR-NOTIF-2) ----------------------------
    def notify_decision(
        self,
        decision_ref: str,
        *,
        title: str,
        body: str,
        deep_link: str | None = None,
    ) -> str:
        """Queue an approval notification that the web portal can pre-empt.

        Discord is held for the configured hold; in-app surfaces immediately;
        email escalates after the timeout (FR-NOTIF-2). Idempotent per decision.
        """
        return self._notification.notify(
            Notification(
                title=title,
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=self.dedup_key(decision_ref),
                web_preemptable=True,
            )
        )

    def acted(self, decision_ref: str) -> None:
        """The user acted on one channel — expire the others (FR-NOTIF-3)."""
        self._notification.expire(self.dedup_key(decision_ref))
        log.info("notification_acted", decision_ref=decision_ref)

    def digest_dedup_key(self, campaign_id: str) -> str:
        """Dedup key the digest-ready ping uses (FR-NOTIF-3/FR-DIG-2).

        Must match :meth:`notify_digest_ready` so acting on a digest item expires
        the very ping that announced it.
        """
        return f"digest:{campaign_id}"

    def acted_digest(self, campaign_id: str) -> None:
        """Acting on any digest item expires the campaign's digest-ready ping.

        FR-NOTIF-3: the ready ping is keyed per campaign (``digest:<campaign_id>``),
        so once the user acts on any row in that campaign's digest the announcement
        is no longer pending and is expired.
        """
        self._notification.expire(self.digest_dedup_key(campaign_id))
        log.info("digest_notification_acted", campaign_id=campaign_id)

    # --- errors (FR-NOTIF-5) ----------------------------------------------
    def notify_error(self, *, title: str, body: str, dedup_key: str | None = None) -> str:
        """Errors surface immediately, any hour, across every channel (FR-NOTIF-5)."""
        return self._notification.notify(
            Notification(
                title=title,
                body=body,
                urgency=NotificationUrgency.IMMEDIATE,
                dedup_key=dedup_key,
            )
        )

    # --- digest-ready ping (FR-DIG-2) -------------------------------------
    def notify_digest_ready(
        self,
        campaign_id: str,
        *,
        count: int,
        deep_link: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """Discord/in-app 'your digest is ready' ping (FR-DIG-2), once per UTC day.

        #15: per-(campaign, UTC-day) idempotency. In prod ``tick_services_factory``
        builds a fresh ``AgentLoop`` each tick (its ``_digest_sent`` is empty), so
        without a per-day guard HERE the ready ping re-fired every ~60s tick. This
        service is shared across ticks, so the marker holds and 3 same-day ticks send
        exactly 1 ready ping (a new UTC day pings again).
        """
        day = (now or datetime.now(UTC)).date()
        key = (str(campaign_id), day)
        # CONC: guard the per-day marker read against concurrent ticks. The external
        # ``notify`` call stays OUTSIDE the lock (no IO under a lock); a re-check under
        # the lock after notifying keeps the once-per-(campaign, day) guarantee even if
        # two ticks raced past the first check.
        with self._digest_ready_lock:
            prior = self._digest_ready_sent.get(key)
        if prior is not None:
            return prior
        body = (
            f"{count} viable role(s) await your review."
            if count
            else "No new viable roles today; tap to see what was searched and why."
        )
        handle = self._notification.notify(
            Notification(
                title="Daily digest ready",
                body=body,
                deep_link=deep_link or f"/digest?campaign={campaign_id}",
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"digest:{campaign_id}",
            )
        )
        with self._digest_ready_lock:
            existing = self._digest_ready_sent.get(key)
            if existing is not None:
                return existing
            self._digest_ready_sent[key] = handle
            # Prune stale days so the marker map does not grow unbounded over 24/7 ops.
            self._digest_ready_sent = {
                k: v for k, v in self._digest_ready_sent.items() if k[1] == day
            }
        return handle

    # --- digest email (FR-DIG-2) ------------------------------------------
    def send_digest_email(
        self,
        *,
        subject: str,
        html: str,
        deep_link: str | None = None,
        dedup_key: str | None = None,
    ) -> bool:
        """Send the rendered digest email body through the email channel (FR-DIG-2).

        The digest email is no longer pull-only: this pushes the rendered body to the
        notifier's email channel. Offline-safe — the notifier captures it in memory
        and only sends over SMTP when NOTIFICATIONS_LIVE is on. Returns True when the
        notifier accepted it (email channel configured).

        IDEM-1: ``dedup_key`` (per campaign + UTC day) makes the send idempotent so a
        re-driven delivery never dispatches a second digest email for the same day.
        """
        send = getattr(self._notification, "send_email", None)
        if send is None:
            return False
        sent = send(subject=subject, html=html, deep_link=deep_link, dedup_key=dedup_key)
        if sent:
            log.info("digest_email_sent", subject=subject)
        return bool(sent)

    # --- proactive agent status update (FR-AGENT-7 / FR-OBS-2) ------------
    def notify_status_update(
        self,
        *,
        campaign_id: str,
        body: str,
        day: date,
        deep_link: str | None = None,
    ) -> str:
        """Push the periodic plain-language agent status update (FR-AGENT-7).

        Informational (NORMAL urgency): it lands in the in-app inbox and fans out to
        whatever channels the user has opted into — exactly the existing digest/decision
        path, NOT a parallel channel. ``dedup_key`` is keyed per (campaign, UTC day) so a
        re-driven same-day push is a no-op at the notifier (the scheduler already guards
        the cadence; this is defense in depth, FR-NOTIF-3).
        """
        return self._notification.notify(
            Notification(
                title="Update from your job-search agent",
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"status_update:{campaign_id}:{day.isoformat()}",
            )
        )

    # --- proactive "still blocked on essentials" nudge (FR-NOTIF / FR-ONBOARD) ---
    def notify_essentials_nudge(
        self,
        *,
        campaign_id: str,
        body: str,
        day: date,
        deep_link: str | None = None,
    ) -> str:
        """Push the friendly "I'm still blocked — I need X to start" nudge (FR-ONBOARD).

        Informational (NORMAL urgency): it lands in the in-app inbox and fans out to
        whatever channels the user has opted into — exactly the existing digest/status
        path, NOT a parallel channel. ``dedup_key`` is keyed per (campaign, UTC day) so a
        re-driven same-day push is a no-op at the notifier (the scheduler already guards
        the cadence; this is defense in depth, FR-NOTIF-3).
        """
        return self._notification.notify(
            Notification(
                title="One more step to start your job search",
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"essentials_nudge:{campaign_id}:{day.isoformat()}",
            )
        )

    # --- daily cap reached (P1-6 cost & pace guardrails) -------------------
    def notify_budget_reached(
        self,
        campaign_id: str,
        *,
        applications_today: int,
        hard_cap: bool,
        day: date,
        deep_link: str | None = None,
    ) -> str:
        """Tell the owner their daily application cap paused new work today.

        "Silence never means stopped" (P1-6 DoD): without this, hitting the
        throughput cap (``core.entities.campaign.clamp_throughput``/
        ``THROUGHPUT_HARD_CAP``, enforced server-side in ``AgentLoop``) was
        invisible — the owner would only notice a quiet day by checking Today
        themselves. Fires through the EXACT SAME fan-out as the daily digest /
        status update (in-app inbox always, Discord/email for whatever channels
        the owner has opted into) — not a parallel delivery path. ``hard_cap``
        distinguishes "reached today's configured target" from "hit the
        engine's absolute safety ceiling" in the copy. ``dedup_key`` is keyed
        per (campaign, UTC day) and is the PRIMARY de-duplication: once the
        budget is exhausted, ``AgentLoop`` re-enters the exhausted branch and
        calls this again on every subsequent tick that day — there is no
        loop-side cadence guard, so do not drop the dedup key (FR-NOTIF-3,
        mirroring ``notify_status_update``).
        """
        cap_word = "safety limit" if hard_cap else "daily target"
        body = (
            f"I've sent {applications_today} application(s) today and reached your "
            f"{cap_word}. I'll pick back up automatically tomorrow — nothing is stuck."
        )
        return self._notification.notify(
            Notification(
                title="Today's application cap reached",
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"budget_reached:{campaign_id}:{day.isoformat()}",
            )
        )

    # --- weekly recap (Top-25 #18 / FR-DIG-2 sibling) ----------------------
    def notify_weekly_recap(
        self,
        campaign_id: str,
        *,
        body: str,
        week_start: date,
        deep_link: str | None = None,
    ) -> str:
        """Push the weekly recap through the EXISTING fan-out (Top-25 #18).

        Reuses the SAME path as the daily digest ready-ping and the periodic status
        update: in-app inbox always, Discord/email fan-out for whatever the user has
        opted into — NOT a parallel channel. ``dedup_key`` is keyed per (campaign,
        ISO-week-start) so a re-driven same-week push is a no-op at the notifier
        (the scheduler already guards the weekly cadence; this is defense in depth,
        FR-NOTIF-3, mirroring ``notify_status_update``'s per-day key).
        """
        return self._notification.notify(
            Notification(
                title="Your weekly recap",
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"weekly_recap:{campaign_id}:{week_start.isoformat()}",
            )
        )

    # --- positive-outcome celebration (design-audit Top-25 #5) ------------
    def notify_positive_outcome(
        self,
        outcome_event_id: str,
        *,
        outcome_type: str,
        company: str | None = None,
        deep_link: str | None = None,
    ) -> str | None:
        """The product's emotional peak: "you got an interview" / "you got an offer".

        Fires through the EXACT SAME ``NotificationPort.notify()`` fan-out as the
        daily digest / weekly recap (in-app inbox always, Discord/email for
        whatever the user has opted into) -- NOT a parallel delivery pipeline.
        Reachable from either recording path (the owner's manual tracker tap OR
        the automated email-scan detector), since both funnel through
        ``PostSubmissionService._record_outcome_event``.

        Deduped on ``outcome_event_id``: a retry/replay that calls this again for
        the SAME already-notified event is a no-op (returns ``None``), so a crash-
        and-retry around the recording step can't double-fire the celebration.
        Unrecognized ``outcome_type``s are silently ignored (defensive -- callers
        should only ever pass ``interview_invited``/``offer``, but this method
        must never be the thing that breaks outcome recording).
        """
        key = str(outcome_event_id)
        with self._positive_outcome_lock:
            if key in self._positive_outcome_sent:
                return None
        if outcome_type == "interview_invited":
            company_name = company or "the company"
            title = "🎉 Interview invitation!"
            body = f"You got an interview at {company_name}!"
        elif outcome_type == "offer":
            company_name = company or "the company"
            title = "🎉 Offer!"
            body = f"{company_name} made you an offer!"
        else:
            return None
        handle = self._notification.notify(
            Notification(
                title=title,
                body=body,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
                dedup_key=f"positive_outcome:{key}",
            )
        )
        with self._positive_outcome_lock:
            existing = self._positive_outcome_sent.get(key)
            if existing is not None:
                return existing
            self._positive_outcome_sent[key] = handle
        return handle

    # --- in-app notification center (FR-UI-3 feed) ------------------------
    def list_inbox(self, *, include_seen: bool = False, owner: str | None = None) -> list:
        """Current in-app notifications backing the notification center.

        Delegates to the notifier's in-app sink. Returns an empty list if the
        configured notifier has no in-app inbox (degrade gracefully).

        ``owner`` (dark-engine audit lens 10 #28): an optional caller-identity
        tag, threaded straight to the notifier so an owner-aware notifier can
        scope the returned entries to it. Every notifier in this tree is
        single-tenant per deployment (every entry belongs to the one engine
        owner), so passing ``owner`` today is a safe no-op — omitted entirely
        when ``None`` (the default), and gracefully dropped via the
        ``TypeError`` fallback if a notifier's ``list_inbox`` doesn't accept it,
        so existing callers/notifiers are completely unaffected. The actual
        multi-user authorization boundary for the front-door lives in the
        workspace's own proxy (``applicant_portal_routes.py``), which must
        resolve the caller to the engine-owner account BEFORE ever reaching
        this service — this parameter is defense in depth, not the boundary.
        """
        lister = getattr(self._notification, "list_inbox", None)
        if lister is None:
            return []
        if owner is None:
            return lister(include_seen=include_seen)
        try:
            return lister(include_seen=include_seen, owner=owner)
        except TypeError:
            return lister(include_seen=include_seen)

    def dismiss_notification(self, inbox_id: str, *, owner: str | None = None) -> bool:
        """Dismiss one informational in-app notification by id (FR-UI-3).

        Returns True if the id matched a current entry. Action-required entries
        are cleared via :meth:`acted` when their pending action resolves.

        ``owner``: see :meth:`list_inbox` — same defense-in-depth thread-through,
        same no-op-when-unsupported degrade, same ``None``-means-unchanged
        default.
        """
        marker = getattr(self._notification, "mark_seen", None)
        if marker is None:
            return False
        if owner is None:
            return bool(marker(inbox_id))
        try:
            return bool(marker(inbox_id, owner=owner))
        except TypeError:
            return bool(marker(inbox_id))

    # --- ladder introspection (dark-engine audit #77) ----------------------
    def ladder_status(self, decision_ref: str) -> dict | None:
        """Current escalation-ladder rung for a decision (#77).

        Keyed the SAME way ``notify_decision``/``acted`` derive the dedup key
        (``decision:<ref>``), so a caller holding the RAW ref (e.g. a pending
        action's own ``material_review:{doc_id}``) doesn't need to know the
        internal prefix. Returns ``None`` when the notifier doesn't support ladder
        introspection or there is nothing currently held/pending for it (already
        acted on, or never sent through the ladder in the first place).
        """
        getter = getattr(self._notification, "ladder_status", None)
        if getter is None:
            return None
        return getter(self.dedup_key(decision_ref))

    # --- ladder advance (deterministic, FR-NOTIF-2) -----------------------
    def advance(self, now: datetime | None = None) -> list[str]:
        """Fire any escalation rungs now due. Returns channels fired this tick."""
        advance = getattr(self._notification, "advance", None)
        return advance(now) if advance else []

    def deliver_now(self, now: datetime | None = None) -> list[str]:
        """Force-flush notifications held back by quiet hours (#302).

        Backs the front-door "Deliver now" control: releases every pending rung on
        every active delivery at once, bypassing the quiet-hours hold. Returns the
        channels flushed (empty if the notifier does not support a force flush).
        """
        flush = getattr(self._notification, "deliver_now", None)
        return flush(now) if flush else []
