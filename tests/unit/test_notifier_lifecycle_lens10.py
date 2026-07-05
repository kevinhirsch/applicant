"""Regression tests for design-audit lens 10 (notifications), findings #10, #27, #4.

#10 — "Deliver now" over-delivers. ``deliver_now`` called ``_fire_due(force=True)``,
and the buggy ``_fire_due`` fired EVERY not-yet-fired rung regardless of its
scheduled ``due_at`` when ``force`` was set — so a user tapping "Deliver now" to
release an overnight digest also instantly triggered the 15-minute email backstop
for every open decision (an email they would never otherwise get so soon), because
that rung's ``due_at`` simply hadn't arrived yet, quiet hours or not. The fix scopes
``force`` to bypassing the quiet-hours gate (and presence pre-emption) only — a rung
whose ``due_at`` is still in the future is never force-fired.

#27 — the in-app inbox aged out UNSEEN informational notifications after a fixed
24-hour window, so a weekend away silently deleted Friday's unread error. The fix
(a) raises the age cap to a much longer window (14 days, `_INBOX_MAX_AGE`) and
(b) exempts unseen entries from the age prune entirely — an entry only ages out
once the user has actually seen/dismissed it. The 1000-entry count cap still bounds
memory on its own.

#4 — the digest email was dispatched via ``client.notify(title, body)`` with no
``body_format`` hint, so Apprise's default TEXT handling delivered literal
``<table>...</table>`` markup to most SMTP recipients instead of rendering it. The
fix sniffs the body for HTML markup (``_looks_like_html``) and, only when detected,
passes ``body_format=apprise.NotifyFormat.HTML`` to ``client.notify`` — plain-text
bodies (decision pings, status updates) are untouched.

Deterministic: an injected clock steps time so the escalation ladder is exercised
without real sleeps (mirrors the fixture pattern used across the other lens-10
notifier regression tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import apprise

from applicant.adapters.notification.apprise_notifier import (
    _INBOX_MAX_AGE,
    AppriseNotifier,
    _looks_like_html,
)
from applicant.ports.driven.notification import Notification, NotificationUrgency


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class _SpyClient:
    """Stands in for ``apprise.Apprise()``; records every ``notify()`` call's kwargs."""

    def __init__(self) -> None:
        self.added: list[str] = []
        self.calls: list[dict] = []

    def add(self, url):
        self.added.append(url)
        return True

    def notify(self, **kwargs):
        self.calls.append(kwargs)
        return True


def _install_spy(monkeypatch, spy):
    # Patch the class attribute on the real, already-imported ``apprise`` module
    # (rather than swapping the whole module into sys.modules) so ``apprise.
    # NotifyFormat`` stays the genuine enum the adapter references at call time.
    monkeypatch.setattr(apprise, "Apprise", lambda: spy)


# === #10: deliver_now must not force-fire a not-yet-due rung ==================


def test_deliver_now_flushes_quiet_held_discord_but_not_the_future_email_backstop():
    """Inside quiet hours: Discord's hold has elapsed (due, but quiet-held); the
    15-minute email backstop has NOT elapsed (due_at still in the future).
    "Deliver now" must flush the former and leave the latter alone."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # 23:00, inside 22-07
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
    )
    notifier.notify(
        Notification(
            title="Approve?",
            body="Acme role",
            dedup_key="d1",
            web_preemptable=True,
        )
    )
    clock.tick(30)  # past the Discord hold; email (15 min) is nowhere near due
    notifier.advance()
    # Normal advance while still inside the quiet window: Discord is due but held.
    assert "discord" not in notifier.sent_channels("d1")
    assert "email" not in notifier.sent_channels("d1")

    notifier.deliver_now()

    # Discord was quiet-held and its due_at had passed -> flushed by force.
    assert "discord" in notifier.sent_channels("d1")
    # Email's due_at (now + 15min) had NOT passed -> must NOT be force-fired.
    assert "email" not in notifier.sent_channels("d1")
    assert "email" in notifier.pending_escalations("d1")


def test_deliver_now_does_not_fire_a_future_rung_even_with_no_quiet_hours():
    """Same shape without quiet hours configured at all: deliver_now still must not
    yank in a rung scheduled for later (the over-delivery bug was independent of
    quiet hours actually being active at the moment of the call)."""
    clock = _Clock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
    )
    notifier.notify(
        Notification(
            title="Approve?",
            body="Acme role",
            dedup_key="d2",
            web_preemptable=True,
        )
    )
    # Nothing ticks: Discord's 30s hold and the 15-min email timeout are both
    # still in the future relative to "now".
    flushed = notifier.deliver_now()
    assert flushed == []
    assert notifier.sent_channels("d2") == ["in_app"]


def test_deliver_now_preserves_critical_immediate_fan_out():
    """CRITICAL notifications fan out to every channel at notify()-time already
    (due_at == now); deliver_now must remain a no-op for them, not double-send."""
    clock = _Clock(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))  # inside quiet hours
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
        quiet_hours=(22, 7),
    )
    notifier.notify(
        Notification(
            title="Action needed",
            body="CAPTCHA",
            dedup_key="d3",
            urgency=NotificationUrgency.CRITICAL,
        )
    )
    # CRITICAL bypasses quiet hours entirely and fires immediately.
    assert sorted(notifier.sent_channels("d3")) == sorted(["discord", "email", "in_app"])

    flushed = notifier.deliver_now()
    assert flushed == []  # nothing left pending to force-flush


# === #27: unseen informational notifications must not silently age out =======


def test_default_inbox_age_window_is_raised_well_past_a_day():
    """Sanity: the age cap itself was raised (belt-and-suspenders alongside the
    unseen exemption) so a fixed 24h window can no longer be the sole guard."""
    assert _INBOX_MAX_AGE >= timedelta(days=7)


def test_unseen_notification_survives_past_the_old_24h_window():
    clock = _Clock(datetime(2026, 6, 17, 12, 0, tzinfo=UTC))
    notifier = AppriseNotifier(in_app=True, clock=clock)
    # Force a short age window so the test doesn't have to wait out the (now much
    # longer) real default to prove the EXEMPTION mechanism itself.
    notifier._max_age = timedelta(hours=1)
    notifier.notify(Notification(title="Heads up: scheduler stalled", body="b", dedup_key="old"))

    clock.tick(25 * 3600)  # 25 hours later — well past the old 24h prune window
    inbox = notifier.list_inbox()

    assert [e.title for e in inbox] == ["Heads up: scheduler stalled"]


def test_unseen_notification_survives_indefinitely_until_dismissed():
    clock = _Clock(datetime(2026, 6, 17, 12, 0, tzinfo=UTC))
    notifier = AppriseNotifier(in_app=True, clock=clock)
    notifier._max_age = timedelta(hours=1)
    notifier.notify(Notification(title="Old error", body="b", dedup_key="old"))

    clock.tick(30 * 24 * 3600)  # a month away
    assert [e.title for e in notifier.list_inbox()] == ["Old error"]


def test_dismissed_notification_still_ages_out_normally():
    """The fix scopes the exemption to UNSEEN entries only — once acknowledged, the
    age prune (and the count cap) still apply, so dismissed history doesn't pin the
    inbox open forever either."""
    clock = _Clock(datetime(2026, 6, 17, 12, 0, tzinfo=UTC))
    notifier = AppriseNotifier(in_app=True, clock=clock)
    notifier._max_age = timedelta(hours=1)
    notifier.notify(Notification(title="Old error", body="b", dedup_key="old"))
    [entry] = notifier.list_inbox()
    assert notifier.mark_seen(entry.id) is True

    clock.tick(2 * 3600)  # past the (shortened) age window, now that it's seen
    assert notifier.list_inbox(include_seen=True) == []


def test_count_cap_is_unaffected_by_the_unseen_exemption():
    """#27's fix must not defeat the existing count cap — it only changes the AGE
    axis. A flood of unseen notifications still rotates out the oldest."""
    clock = _Clock(datetime(2026, 6, 17, 12, 0, tzinfo=UTC))
    notifier = AppriseNotifier(in_app=True, clock=clock)
    notifier._max_inbox = 5
    for i in range(20):
        notifier.notify(Notification(title=f"t{i}", body="b", dedup_key=f"k{i}"))
    assert len(notifier.inbox()) <= 5


# === #4: HTML digest body gets a body_format hint; plain text does not =======


def test_looks_like_html_detects_the_digest_markup():
    assert _looks_like_html("<h1>Your daily digest</h1><table><tr><td>x</td></tr></table>")
    assert _looks_like_html("<table border='1' cellpadding='6'>...</table>")


def test_looks_like_html_is_false_for_plain_text_bodies():
    assert not _looks_like_html("Tap to open the redline review.")
    assert not _looks_like_html("Application 42 is ready for final approval.")


def test_send_real_dispatch_html_digest_body_passes_html_format(monkeypatch):
    spy = _SpyClient()
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(apprise_urls="mailto://user:pw@smtp.test", send_real=True)
    html_body = "<h1>Your daily digest</h1><table><tr><td>Acme SRE</td></tr></table>"
    note = Notification(
        title="Your daily digest",
        body=html_body,
        urgency=NotificationUrgency.NORMAL,
    )

    notifier._send_real_dispatch("email", note)

    assert spy.calls[0]["body_format"] == apprise.NotifyFormat.HTML


def test_send_real_dispatch_plain_text_decision_has_no_body_format(monkeypatch):
    spy = _SpyClient()
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(apprise_urls="mailto://user:pw@smtp.test", send_real=True)
    note = Notification(
        title="Approve?",
        body="Tap to open the redline review.",
        dedup_key="decision:abc",
    )

    notifier._send_real_dispatch("email", note)

    assert "body_format" not in spy.calls[0]


def test_send_email_end_to_end_dispatches_with_html_format(monkeypatch):
    """The real caller path (``NotificationService.send_digest_email`` ->
    ``AppriseNotifier.send_email``) must carry the same fix through ``_dispatch``."""
    spy = _SpyClient()
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(apprise_urls="mailto://user:pw@smtp.test", send_real=True)

    ok = notifier.send_email(
        subject="Your daily digest",
        html="<h1>Your daily digest</h1><table><tr><td>Acme SRE</td></tr></table>",
    )

    assert ok is True
    assert spy.calls[-1]["body_format"] == apprise.NotifyFormat.HTML


def test_send_real_dispatch_discord_ping_unaffected_by_html_check(monkeypatch):
    """A routine Discord notify (never HTML) must not pick up a body_format kwarg
    Discord's Apprise plugin doesn't expect."""
    spy = _SpyClient()
    _install_spy(monkeypatch, spy)
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh", send_real=True)
    note = Notification(title="Daily digest ready", body="Your matches are ready to review.")

    notifier._send_real_dispatch("discord", note)

    assert "body_format" not in spy.calls[0]
