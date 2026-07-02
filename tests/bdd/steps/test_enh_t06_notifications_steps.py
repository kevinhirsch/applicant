"""Step bindings for the notifications & digest-delivery enhancement specs (theme T06).

Issues #172, #233, #234, #235, #236, #300, #302.

Convention (mirrors ``test_enh_research_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships — they assert against the actual ``AppriseNotifier`` adapter through its
  injected deterministic clock (no real sleeps, no real SMTP/Discord/ntfy sockets) and
  must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built. Their steps make an honest probe at the real seam — a missing
  channel enum value, an absent lock, an un-floored constructor field, or a delivery that
  the current code loses — so the scenario is a genuine red, never ``assert True``.
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail.

Hexagonal: assertions target the driven notification adapter and its port contract via the
in-memory (offline) lane. Speculative imports for not-yet-built targets live INSIDE the
step bodies so absence is a runtime error (xfail), never a collection error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.ports.driven.notification import (
    Notification,
    NotificationChannel,
    NotificationUrgency,
)

scenarios(
    "../features/enhancements/enh_172_quiet_hours.feature",
    "../features/enhancements/enh_233_send_email_dedup_before_dispatch.feature",
    "../features/enhancements/enh_234_one_failure_crashes_tick.feature",
    "../features/enhancements/enh_235_sent_dict_lock.feature",
    "../features/enhancements/enh_236_email_timeout_floor.feature",
    "../features/enhancements/enh_300_ntfy_push.feature",
    "../features/enhancements/enh_302_quiet_hours_suppression.feature",
)

_EMAIL = NotificationChannel.EMAIL.value
_DISCORD = NotificationChannel.DISCORD.value
_IN_APP = NotificationChannel.IN_APP.value


class _Clock:
    """Deterministic, steppable clock — never sleeps."""

    def __init__(self, *, hour: int = 12) -> None:
        self.now = datetime(2026, 1, 1, hour, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture
def t06ctx() -> dict:
    return {}


# ===========================================================================
# #172 — GREEN: quiet hours suppress NORMAL Discord/email; errors still fan out;
#               24/7 mode disables the window. PENDING: a critical override.
# ===========================================================================
@given("a notifier configured with a quiet-hours window covering the current time")
def quiet_window_now(t06ctx):
    clock = _Clock(hour=3)  # 03:00 UTC, inside a 22:00->07:00 window
    t06ctx["clock"] = clock
    t06ctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
    )


@given("a notifier configured for round-the-clock delivery with a quiet window")
def quiet_window_always_on(t06ctx):
    clock = _Clock(hour=3)
    t06ctx["clock"] = clock
    t06ctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
        always_on=True,
    )


@when("a normal approval is queued and the ladder is advanced past the email timeout")
def queue_approval_advance_full(t06ctx):
    n = t06ctx["notifier"]
    n.notify(
        Notification(
            title="Approve?",
            body="role",
            urgency=NotificationUrgency.NORMAL,
            dedup_key="quiet",
            web_preemptable=True,
        )
    )
    # Step past the Discord hold AND the email timeout so both later rungs are due.
    t06ctx["clock"].tick(30 * 60)
    n.advance()


@then("neither Discord nor email has fired while inside the quiet window")
def quiet_suppressed(t06ctx):
    sent = t06ctx["notifier"].sent_channels("quiet")
    assert _DISCORD not in sent
    assert _EMAIL not in sent


@then("the in-app surface still received the approval immediately")
def quiet_in_app_fired(t06ctx):
    assert _IN_APP in t06ctx["notifier"].sent_channels("quiet")


@when("an immediate error notification is queued")
def queue_immediate_error(t06ctx):
    t06ctx["notifier"].notify(
        Notification(
            title="boom",
            body="failure",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="err",
        )
    )


@then("every configured channel fired at once despite the quiet window")
def error_fans_out_in_quiet(t06ctx):
    sent = set(t06ctx["notifier"].sent_channels("err"))
    assert {_DISCORD, _IN_APP, _EMAIL} <= sent


@then("Discord and email both fired even though a quiet window was configured")
def always_on_fires(t06ctx):
    sent = set(t06ctx["notifier"].sent_channels("quiet"))
    assert _DISCORD in sent and _EMAIL in sent


@when("a critical action is queued that must reach the user during quiet hours")
def queue_critical_action(t06ctx):
    # PROBE: there is no urgency level today that BOTH overrides quiet hours AND is a
    # targeted action (not the generic IMMEDIATE error fan-out). A "CRITICAL" urgency is
    # the intended seam; absence -> AttributeError -> honest red.
    critical = NotificationUrgency.CRITICAL
    t06ctx["notifier"].notify(
        Notification(
            title="Live takeover needed",
            body="captcha",
            urgency=critical,
            dedup_key="crit",
            web_preemptable=True,
        )
    )


@then("the critical action fires on Discord even inside the quiet window")
def critical_overrides_quiet(t06ctx):
    assert _DISCORD in t06ctx["notifier"].sent_channels("crit")


# ===========================================================================
# #233 — GREEN: same-key digest email is idempotent. PENDING: a failed first
#               dispatch must not permanently consume the dedup key.
# ===========================================================================
@given("a notifier with an email channel and a deterministic clock")
def notifier_email_channel(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    t06ctx["notifier"] = AppriseNotifier(apprise_urls="mailto://u:p@smtp.test", clock=clock)


@when("the same digest email is sent twice with one dedup key")
def send_same_email_twice(t06ctx):
    n = t06ctx["notifier"]
    key = "digest_email:c1:2026-01-01"
    n.send_email(subject="Digest", html="<p>hi</p>", dedup_key=key)
    n.send_email(subject="Digest", html="<p>hi</p>", dedup_key=key)


@then("the email channel dispatched exactly once")
def email_dispatched_once(t06ctx):
    emails = [c for c in t06ctx["notifier"].captured() if c.channel == _EMAIL]
    assert len(emails) == 1


@given("a notifier with an email channel whose first dispatch fails")
def notifier_email_first_dispatch_fails(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    notifier = AppriseNotifier(apprise_urls="mailto://u:p@smtp.test", clock=clock)
    real_dispatch = notifier._dispatch
    state = {"calls": 0, "delivered": 0}

    def flaky_dispatch(channel, notification):
        state["calls"] += 1
        if state["calls"] == 1:
            # Simulate an SMTP failure on the first attempt WITHOUT opening a socket.
            raise RuntimeError("SMTP unreachable")
        real_dispatch(channel, notification)
        state["delivered"] += 1

    notifier._dispatch = flaky_dispatch  # type: ignore[method-assign]
    t06ctx["notifier"] = notifier
    t06ctx["state"] = state


@when("the digest email is sent, fails, and is then retried")
def send_email_fail_then_retry(t06ctx):
    n = t06ctx["notifier"]
    key = "digest_email:c1:2026-01-01"
    try:
        n.send_email(subject="Digest", html="<p>hi</p>", dedup_key=key)
    except RuntimeError:
        pass  # first SMTP attempt failed
    # The user/scheduler re-drives the same campaign+day digest.
    t06ctx["retry_returned"] = n.send_email(
        subject="Digest", html="<p>hi</p>", dedup_key=key
    )


@then("the retry re-dispatches the email rather than silently returning sent")
def retry_redispatches(t06ctx):
    # Today the dedup key is committed BEFORE dispatch, so the failed first send still
    # consumed it and the retry returns True without re-dispatching -> email is lost.
    assert t06ctx["state"]["delivered"] >= 1, (
        "retry returned 'sent' but never actually delivered the email"
    )


# ===========================================================================
# #234 — PENDING: a raising delivery on one notification must not drop another
#                 notification's due rung in the same advance.
# ===========================================================================
@given("a notifier whose dispatch raises for one notification but succeeds for another")
def notifier_dispatch_raises_for_one(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        clock=clock,
    )
    real_dispatch = notifier._dispatch

    def selective_dispatch(channel, notification):
        if notification.dedup_key == "bad":
            raise RuntimeError("Discord unreachable")
        real_dispatch(channel, notification)

    notifier._dispatch = selective_dispatch  # type: ignore[method-assign]
    t06ctx["notifier"] = notifier


@when("the ladder is advanced with both rungs due on the same tick")
def advance_with_both_rungs_due(t06ctx):
    n = t06ctx["notifier"]
    # Both NORMAL, non-preemptable -> Discord rung is due immediately. The "bad" one is
    # queued first so its raising dispatch happens before the healthy one in advance().
    n.notify(
        Notification(title="bad", body="x", urgency=NotificationUrgency.NORMAL, dedup_key="bad")
    )
    n.notify(
        Notification(title="good", body="y", urgency=NotificationUrgency.NORMAL, dedup_key="good")
    )
    # notify() fires already-due rungs; the bad one raised during its own notify, so the
    # good one was queued and we advance to fire its due Discord rung. Today that advance
    # re-scans the bad delivery, re-raises, and never reaches the good rung.
    try:
        n.advance()
    except RuntimeError:
        t06ctx["advance_raised"] = True


@then("the healthy notification's rung still fired despite the other one failing")
def healthy_rung_fired(t06ctx):
    assert _DISCORD in t06ctx["notifier"].sent_channels("good"), (
        "a single failing channel aborted the whole advance and lost the healthy rung"
    )


# ===========================================================================
# #235 — PENDING: the shared _sent delivery state needs a lock.
# ===========================================================================
@given("the shipped notifier adapter")
def shipped_notifier(t06ctx):
    t06ctx["notifier"] = AppriseNotifier(discord_webhook_url="https://discord.test/wh")


@when("the delivery state machine is inspected for a concurrency guard")
def inspect_for_lock(t06ctx):
    t06ctx["lock"] = getattr(t06ctx["notifier"], "_sent_lock", None)


@then("a lock protects the shared sent-delivery dictionary")
def sent_dict_has_lock(t06ctx):
    import threading

    lock = t06ctx["lock"]
    # acquire/release is the duck-typed lock contract; today _sent_lock is absent (None).
    assert lock is not None and hasattr(lock, "acquire") and hasattr(lock, "release")
    assert isinstance(lock, type(threading.Lock()))


# ===========================================================================
# #236 — GREEN: configure() floors the email timeout. PENDING: the constructor
#               must floor it too (no 0s instant-email).
# ===========================================================================
@given("a notifier reconfigured through configure with a zero-second email timeout")
def notifier_configured_zero_timeout(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    notifier = AppriseNotifier(apprise_urls="mailto://u:p@smtp.test", clock=clock)
    notifier.configure(email_timeout_seconds=0)
    t06ctx["notifier"] = notifier


@given("a notifier constructed directly with a zero-second email timeout")
def notifier_constructed_zero_timeout(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    t06ctx["notifier"] = AppriseNotifier(
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        email_timeout_seconds=0,
    )


@when("a normal approval is queued")
def queue_normal_approval(t06ctx):
    t06ctx["notifier"].notify(
        Notification(
            title="Approve?",
            body="role",
            urgency=NotificationUrgency.NORMAL,
            dedup_key="floor",
            web_preemptable=True,
        )
    )


@then("the email rung is not due immediately")
def email_rung_not_due_now(t06ctx):
    # The email rung must escalate AFTER the floor, so it has not fired on the queue tick.
    assert _EMAIL not in t06ctx["notifier"].sent_channels("floor")


@then("the email rung is not due on the same tick as the in-app surface")
def email_not_same_tick_as_in_app(t06ctx):
    # Read the dispatched channels off ``captured`` (the delivery is pruned from ``_sent``
    # once every rung has fired, so ``sent_channels`` would be empty here). in-app surfaces
    # immediately; with a 0s constructor timeout the email rung fires on the SAME tick
    # (instant blast) until the constructor floors it the way ``configure()`` already does.
    fired = [c.channel for c in t06ctx["notifier"].captured()]
    assert _IN_APP in fired
    assert _EMAIL not in fired


# ===========================================================================
# #300 — PENDING: a device-push (ntfy) channel wired into the notifier.
# ===========================================================================
@given("the shipped notification channel set")
def shipped_channel_set(t06ctx):
    t06ctx["channels"] = NotificationChannel


@when("the available channels are inspected for a device-push option")
def inspect_for_push_channel(t06ctx):
    # PROBE: NotificationChannel has DISCORD/IN_APP/EMAIL today; a PUSH member is the
    # intended seam. Absence -> AttributeError -> honest red.
    t06ctx["push"] = t06ctx["channels"].PUSH


@then("a push channel is available alongside Discord, in-app, and email")
def push_channel_available(t06ctx):
    values = {c.value for c in t06ctx["channels"]}
    assert t06ctx["push"].value in values
    assert {_DISCORD, _IN_APP, _EMAIL} <= values


@given("a notifier configured with an ntfy push endpoint")
def notifier_with_ntfy(t06ctx):
    # PROBE: the constructor has no push/ntfy parameter today, so a notifier that knows a
    # push endpoint cannot be built. Pass the not-yet-supported kwarg -> TypeError red.
    t06ctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="https://ntfy.test/applicant",
    )


@when("a critical takeover alert with a deep link is queued")
def queue_takeover_alert(t06ctx):
    t06ctx["notifier"].notify(
        Notification(
            title="Live takeover needed",
            body="captcha on Stripe",
            deep_link="/takeover/session-1",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="takeover",
        )
    )


@then("the push channel received the alert carrying the takeover deep link")
def push_received_alert(t06ctx):
    push_value = NotificationChannel.PUSH.value
    pushes = [c for c in t06ctx["notifier"].captured() if c.channel == push_value]
    assert pushes and pushes[0].deep_link == "/takeover/session-1"


# ===========================================================================
# #302 — GREEN: HH:MM + midnight-wrap window and timezone localization ship.
#               PENDING: per-channel quiet behaviour and a deliver-now flush.
# ===========================================================================
@given("a quiet-hours window from 22:30 to 07:15")
def hhmm_window(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    t06ctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        clock=clock,
        quiet_hours=("22:30", "07:15"),
    )


@when("the current minute is checked against the window across the night")
def check_window_minutes(t06ctx):
    n = t06ctx["notifier"]
    # 23:00 and 03:00 are inside the wrapping window; 12:00 and 07:30 are outside.
    t06ctx["inside_late"] = n._in_quiet_hours(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    t06ctx["inside_early"] = n._in_quiet_hours(datetime(2026, 1, 2, 3, 0, tzinfo=UTC))
    t06ctx["outside_noon"] = n._in_quiet_hours(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    t06ctx["outside_edge"] = n._in_quiet_hours(datetime(2026, 1, 2, 7, 30, tzinfo=UTC))


@then("a time inside the window is quiet and a time outside it is not")
def window_minute_precision(t06ctx):
    assert t06ctx["inside_late"] is True
    assert t06ctx["inside_early"] is True
    assert t06ctx["outside_noon"] is False
    assert t06ctx["outside_edge"] is False


@given("a quiet-hours window configured in a non-UTC timezone")
def tz_window(t06ctx):
    clock = _Clock()
    t06ctx["clock"] = clock
    # 22:00->07:00 New York local. 03:00 UTC == 22:00 EST (winter) -> inside the window.
    t06ctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        clock=clock,
        quiet_hours=(22, 7),
        quiet_tz="America/New_York",
    )


@when("a UTC instant that falls inside the local night is checked")
def check_tz_instant(t06ctx):
    # 03:00 UTC on 2026-01-01 is 22:00 EST the prior evening -> inside 22:00->07:00 local.
    t06ctx["tz_inside"] = t06ctx["notifier"]._in_quiet_hours(
        datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    )


@then("the instant is treated as inside the quiet window")
def tz_inside_window(t06ctx):
    assert t06ctx["tz_inside"] is True


@given("a notifier with per-channel quiet-hours preferences")
def notifier_per_channel_quiet(t06ctx):
    # Per-channel quiet-hours preference: Discord (True) respects the window and is
    # held only while the clock is actually inside it; email (False) is exempt and
    # always delivers. Use a fixed clock inside the configured window (22:00->07:00)
    # so "during quiet hours" is deterministic, not dependent on wall-clock time.
    clock = _Clock(hour=23)  # 23:00 UTC, inside a 22:00->07:00 window
    t06ctx["clock"] = clock
    t06ctx["notifier"] = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
        quiet_hours_channels={_DISCORD: True, _EMAIL: False},
    )


@when("a normal notification fires during quiet hours")
def per_channel_fire(t06ctx):
    n = t06ctx["notifier"]
    n.notify(
        Notification(
            title="Approve?", body="role", urgency=NotificationUrgency.NORMAL, dedup_key="pc"
        )
    )
    n.advance()


@then("Discord is held but the email channel still delivers overnight")
def per_channel_behaviour(t06ctx):
    sent = t06ctx["notifier"].sent_channels("pc")
    assert _DISCORD not in sent and _EMAIL in sent


@given("notifications that were deferred because of an active quiet window")
def deferred_during_quiet(t06ctx):
    clock = _Clock(hour=3)
    t06ctx["clock"] = clock
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:p@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
    )
    notifier.notify(
        Notification(
            title="Approve?", body="role", urgency=NotificationUrgency.NORMAL, dedup_key="dn"
        )
    )
    notifier.advance()
    t06ctx["notifier"] = notifier


@when("the user taps deliver now to force-send the queued notifications")
def deliver_now(t06ctx):
    # PROBE: there is no "deliver now" / flush-queued entrypoint on the adapter today.
    t06ctx["notifier"].deliver_now()


@then("the deferred notifications are flushed to their channels immediately")
def deferred_flushed(t06ctx):
    sent = t06ctx["notifier"].sent_channels("dn")
    assert _DISCORD in sent and _EMAIL in sent
