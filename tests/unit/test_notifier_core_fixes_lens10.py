"""Regression tests for design-audit exhaustive2 lens 10 (notifications), findings
#9, #19, #20, #35, #36 — see ``docs/design/audits/exhaustive2/10_notifications.md``.

#9 (CONFIRMED LIVE BUG) — ``notify()`` with an ALREADY-ACTIVE ``dedup_key`` used to
unconditionally overwrite ``_sent[key]`` and immediately fire fresh rungs, even
though the scheduler-stall alert and the daily nudge services both commented that a
repeat key is "a no-op at the notifier". A repeat ``notify()`` while the key is
still live (not yet ``expire()``-d, not yet aged out) is now an idempotent no-op:
it returns the SAME handle and does not re-dispatch. The re-arm-after-expire (and
re-arm-after-timeout) path keeps working.

#19 — ntfy used to only get a rung when ``notification.web_preemptable`` was True,
so a phone-push-only user (no Discord/email configured) never received the digest
ready ping, the daily status update, or the essentials nudge — only decisions and
IMMEDIATE errors. ntfy now fans out to every NORMAL notification.

#20 — ntfy was scheduled with the same 30s hold as Discord for web-preemptable
decisions, but had no presence pre-empt (unlike Discord), so it always fired 30s
later even when the user was verifiably in the web UI — the worst of both (delayed,
but not actually preemptable). Decision made here: ntfy now matches Discord exactly
for web-preemptable decisions (held + presence-preemptable); informational NORMAL
notifications (nothing to pre-empt) fire immediately, matching in-app.

#35 — the "email" field (``apprise_urls``) accepts ANY Apprise service URL, so a
pasted Slack/Telegram/etc. URL silently inherits the email ladder's 15-minute
backstop timing and the "email" quiet-hours label. The adapter now recognizes
non-mail-shaped schemes (``non_mail_apprise_urls()``) and logs a warning at
configure time instead of staying silent.

#36 — ``NotificationChannel.PUSH`` aliases ``"ntfy"`` (same runtime value), which
pins the logical push-channel concept to its current ntfy transport. Existing
pinned tests (``test_notification_ladder.py``) lock ``NotificationChannel.NTFY.value
== "ntfy"`` and ``"ntfy" in configured_channels()``, so the wire-visible values are
intentionally left alone; the forward-compat fix lives entirely in the adapter's
per-channel quiet-hours preference lookup, which now also accepts the logical
"push" key as a synonym for the transport "ntfy" key (``_preference_for_channel``),
so a config layer that migrates to storing "push" does not orphan existing
"ntfy"-keyed preferences (and vice versa).

Deterministic: an injected clock steps time so the ladder fires without real sleeps
(mirrors the fixture pattern in test_notification_ladder.py / test_notifier_quiet_hours_lens10.py).

Hand-verified RED-on-revert / GREEN-on-restore: every test in this file failed
against a backup of ``apprise_notifier.py`` taken before the lens-10 #9/#19/#20/#35/
#36 fixes, and passed again once the fix was restored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.adapters.notification.apprise_notifier import (
    AppriseNotifier,
    _non_mail_apprise_urls,
)
from applicant.observability.logging import recent_logs
from applicant.ports.driven.notification import (
    Notification,
    NotificationChannel,
    NotificationUrgency,
)


class _Clock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _notifier(clock, **kw):
    return AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
        **kw,
    )


# === #9: notify() with an active dedup_key is idempotent ====================


def test_repeat_immediate_notify_same_active_key_does_not_redispatch():
    """The scheduler-stall alert's own comment: a second notify() with the same key
    must collapse to a single operator alert, not fire every channel twice."""
    clock = _Clock()
    n = _notifier(clock)

    h1 = n.notify(
        Notification(
            title="Your job-search agent is stuck",
            body="boom",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="scheduler_stall",
        )
    )
    first_count = len(n.captured())
    assert first_count > 0

    h2 = n.notify(
        Notification(
            title="Your job-search agent is stuck",
            body="boom again",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="scheduler_stall",
        )
    )

    assert h2 == h1  # same delivery, not a new one
    assert len(n.captured()) == first_count  # no re-dispatch


def test_repeat_normal_decision_notify_same_active_key_does_not_readd_rungs():
    """A web-preemptable decision re-queued with the same dedup_key (e.g. a retried
    ``notify_decision`` call) must not duplicate the in-app row or reset the ladder."""
    clock = _Clock()
    n = _notifier(clock)

    n.notify(
        Notification(
            title="Approve?",
            body="Acme role",
            dedup_key="decision:doc-1",
            web_preemptable=True,
        )
    )
    assert len(n.list_inbox()) == 1
    pending_before = sorted(n.pending_escalations("decision:doc-1"))

    n.notify(
        Notification(
            title="Approve?",
            body="Acme role (retry)",
            dedup_key="decision:doc-1",
            web_preemptable=True,
        )
    )

    assert len(n.list_inbox()) == 1  # no duplicate in-app row
    assert sorted(n.pending_escalations("decision:doc-1")) == pending_before


def test_repeat_notify_rearms_after_expire():
    """Acting on the decision (expire) must still let a FRESH event with the same
    dedup_key start a brand-new ladder — the idempotency fix must not break re-arm."""
    clock = _Clock()
    n = _notifier(clock)

    h1 = n.notify(Notification(title="Approve?", body="first", dedup_key="d1"))
    n.expire("d1")

    h2 = n.notify(Notification(title="Approve?", body="second", dedup_key="d1"))

    assert h2 != h1
    assert n.is_active("d1") is True


def test_repeat_notify_rearms_once_the_prior_delivery_ages_out():
    """Even without an explicit expire(), a delivery that has fully escalated and
    aged past the email-timeout cutoff no longer blocks a fresh notify() for the
    same key (the "no scheduler / no expire call" recovery path)."""
    clock = _Clock()
    n = _notifier(clock, email_timeout_seconds=60)

    h1 = n.notify(
        Notification(title="Run failed", body="boom", urgency=NotificationUrgency.IMMEDIATE, dedup_key="e1")
    )
    assert n.is_active("e1") is True

    clock.tick(120)  # past the (shortened) email-timeout cutoff
    h2 = n.notify(
        Notification(title="Run failed again", body="boom", urgency=NotificationUrgency.IMMEDIATE, dedup_key="e1")
    )

    assert h2 != h1


# === #19: ntfy reaches NORMAL informational kinds, not just decisions ========


def test_ntfy_only_configured_still_receives_the_digest_ready_ping():
    """A phone-push-only user (no Discord/email) must still get informational NORMAL
    pings — before the fix, ntfy only fired for web_preemptable decisions."""
    clock = _Clock()
    n = AppriseNotifier(ntfy_url="https://ntfy.test/topic", clock=clock)

    n.notify(
        Notification(
            title="Daily digest ready",
            body="3 viable roles await your review.",
            dedup_key="digest:c1",
            urgency=NotificationUrgency.NORMAL,
            web_preemptable=False,
        )
    )

    assert "ntfy" in n.sent_channels("digest:c1")


def test_ntfy_informational_normal_fires_immediately_no_hold():
    """Informational NORMAL notifications have nothing to pre-empt, so ntfy fires in
    the same tick as in-app — no 30s hold."""
    clock = _Clock()
    n = AppriseNotifier(ntfy_url="https://ntfy.test/topic", clock=clock)

    n.notify(
        Notification(
            title="Update from your job-search agent",
            body="status",
            dedup_key="status_update:c1",
            urgency=NotificationUrgency.NORMAL,
            web_preemptable=False,
        )
    )

    assert "ntfy" in n.sent_channels("status_update:c1")
    assert n.pending_escalations("status_update:c1") == []


# === #20: ntfy's hold is now presence-preemptable, matching Discord ==========


def test_ntfy_decision_is_held_like_discord():
    clock = _Clock()
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
    )
    n.notify(
        Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True)
    )

    # Neither push channel has fired yet — both are held for the escalation window.
    assert "discord" not in n.sent_channels("k1")
    assert "ntfy" not in n.sent_channels("k1")
    assert set(n.pending_escalations("k1")) >= {"discord", "ntfy"}


def test_ntfy_decision_is_presence_preempted_like_discord():
    """#20: presence pre-emption now applies to ntfy too, not just Discord — a user
    verifiably in the web UI should not get buzzed on their phone either."""
    clock = _Clock()
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
    )
    n.notify(
        Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True)
    )
    n.set_presence(True)
    clock.tick(30)  # past the hold
    n.advance()

    assert "discord" not in n.sent_channels("k1")
    assert "ntfy" not in n.sent_channels("k1")  # suppressed, not just delayed
    assert n.pending_escalations("k1") == []  # both rungs resolved (fired=True, no dispatch)


def test_ntfy_decision_fires_after_hold_when_absent():
    clock = _Clock()
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
    )
    n.notify(
        Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True)
    )
    clock.tick(30)
    n.advance()

    assert "ntfy" in n.sent_channels("k1")
    assert "discord" in n.sent_channels("k1")


# === #35: apprise_urls scheme validation ======================================


def test_non_mail_apprise_urls_flags_a_pasted_slack_url():
    assert _non_mail_apprise_urls("mailto://user:pw@smtp.test,slack://token/channel") == [
        "slack://token/channel"
    ]


def test_non_mail_apprise_urls_empty_for_mail_only_config():
    assert _non_mail_apprise_urls("mailto://user:pw@smtp.test,mailgun://api-key/domain") == []


def test_non_mail_apprise_urls_empty_string_is_fine():
    assert _non_mail_apprise_urls("") == []


def test_notifier_exposes_non_mail_apprise_urls_and_warns_on_configure():
    from applicant.observability.logging import configure_logging

    configure_logging(log_format="json", log_level="INFO")

    n = AppriseNotifier(apprise_urls="mailto://user:pw@smtp.test")
    assert n.non_mail_apprise_urls() == []

    n.configure(apprise_urls="mailto://user:pw@smtp.test,tgram://token/chatid")

    assert n.non_mail_apprise_urls() == ["tgram://token/chatid"]
    events = recent_logs(limit=50)
    assert any(e.get("event") == "apprise_url_non_mail_scheme" for e in events)


# === #36: logical "push" name is a back-compat synonym for the ntfy transport ==


def test_ntfy_and_push_are_both_present_on_the_enum():
    """The wire-visible NTFY value is pinned elsewhere (test_notification_ladder.py);
    this only re-asserts the two names both resolve (no accidental removal)."""
    assert NotificationChannel.NTFY.value == "ntfy"
    assert hasattr(NotificationChannel, "PUSH")


def test_quiet_hours_preference_honors_the_legacy_ntfy_key():
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # inside 22:00-07:00
    n = AppriseNotifier(
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
        quiet_hours=(22, 7),
        quiet_hours_channels={"ntfy": False},  # "let ntfy through overnight"
    )
    notif = Notification(title="Update", body="b", urgency=NotificationUrgency.NORMAL)
    assert n._channel_quiet_deferred("ntfy", notif, clock.now) is False


def test_quiet_hours_preference_honors_the_logical_push_key():
    """#36: a preference map keyed by the LOGICAL "push" name (rather than the
    transport "ntfy") must resolve identically — a future config migration to the
    logical name must not silently stop honoring the user's saved preference."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # inside 22:00-07:00
    n = AppriseNotifier(
        ntfy_url="https://ntfy.test/topic",
        clock=clock,
        quiet_hours=(22, 7),
        quiet_hours_channels={"push": False},  # same preference, logical key
    )
    notif = Notification(title="Update", body="b", urgency=NotificationUrgency.NORMAL)
    assert n._channel_quiet_deferred("ntfy", notif, clock.now) is False


def test_quiet_hours_preference_still_holds_ntfy_by_default_inside_the_window():
    """Sanity: without an explicit exemption (either key), ntfy still respects the
    quiet window like any other push channel — the alias only adds a lookup path,
    it does not change the default posture."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    n = AppriseNotifier(ntfy_url="https://ntfy.test/topic", clock=clock, quiet_hours=(22, 7))
    notif = Notification(title="Update", body="b", urgency=NotificationUrgency.NORMAL)
    assert n._channel_quiet_deferred("ntfy", notif, clock.now) is True
