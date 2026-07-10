"""RT — retire the remaining GENERAL-WORKSPACE data polls (investigation outcome).

Sibling of ``test_applicant_ws_retire_polls.py`` (which retired the APPLICANT
surfaces' polls over the engine realtime push). This one pins the traced,
honest decision for the three general-workspace surfaces the sweep looked at —
``emailInbox.js`` (new-mail poll), ``calendar.js`` (events), and
``appkitStatusPanel.js`` (status timer):

* ``emailInbox.js`` — the ONE real general-workspace data poll (a 60s unread-count
  check). It is deliberately LEFT ON — the workspace has no server-side new-mail
  change signal to relay (stdlib ``imaplib``, no IDLE watcher; the legacy inbound
  scanner is disabled and browser-silent), so there is nothing to push. Retiring it
  would need a real IMAP-IDLE relay that does not exist yet. The honesty guard: it
  must NOT be gated on the applicant realtime channel (``applicant:realtime`` carries
  the ENGINE's job notifications, not workspace email — gating there retires the poll
  while no email events arrive = a silent dead UI).

* ``calendar.js`` — has NO periodic events data poll to retire. Calendar DATA is
  refreshed on-demand (open / navigation) and event-driven via the ``calendar-refresh``
  window event. Its only ``setInterval`` is a client-side wall-clock tick.

* ``appkitStatusPanel.js`` — a purely cosmetic timer that re-renders the relative
  "updated Xs ago" text from an already-known timestamp; it makes ZERO network calls,
  so there is no backend change event and nothing to push.

Each assertion was hand-verified to go RED when the piece it protects is reverted
(delete the poll, wire it to the applicant channel, or add a fetch to the status kit).
"""

from __future__ import annotations

import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_EMAIL_JS = _JS_DIR / "emailInbox.js"
_CALENDAR_JS = _JS_DIR / "calendar.js"
_APPKIT_JS = _JS_DIR / "appkitStatusPanel.js"


@pytest.fixture(scope="module")
def email_src() -> str:
    return _EMAIL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calendar_src() -> str:
    return _CALENDAR_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def appkit_src() -> str:
    return _APPKIT_JS.read_text(encoding="utf-8")


# ── emailInbox.js: the real poll stays as the honest fallback ─────────────────


def test_email_unread_poll_is_preserved(email_src: str) -> None:
    # The 60s unread-count poll is the inbox's only new-mail signal; it must NOT be
    # deleted (there is no server push to replace it).
    assert "setInterval(_refreshUnreadCount, 60000)" in email_src
    assert "_refreshUnreadCount();" in email_src


def test_email_poll_retention_is_documented(email_src: str) -> None:
    # The reason it stays (no server-side new-mail change signal) is written at the
    # poll site so the next engineer in the poll-retirement sweep doesn't re-investigate.
    assert "no server-side new-mail change signal" in email_src.lower() \
        or "no server-side" in email_src.lower()
    assert "imap-idle relay" in email_src.lower()


def test_email_poll_is_not_wired_to_the_applicant_realtime_channel(email_src: str) -> None:
    # Honesty guard (the whole point of pinning this): the email poll must never be
    # gated on the engine's realtime push channel. That channel carries job-search
    # notifications, not workspace email, so retiring the poll behind it would leave
    # the inbox silently stale — a dead UI. The literal string may appear in the
    # rationale COMMENT, so assert against the actual subscription/wiring instead.
    assert "addEventListener('applicant:realtime'" not in email_src
    assert "addEventListener('applicant:data-changed'" not in email_src
    assert "__applicantRealtimeLive" not in email_src


# ── calendar.js: already event-driven, no data poll to retire ─────────────────


def test_calendar_data_refresh_is_event_driven_not_polled(calendar_src: str) -> None:
    # Calendar changes surface via a document event (dispatched after a manage_calendar
    # tool call), not a periodic fetch loop — the refresh path is already push-shaped.
    assert "addEventListener('calendar-refresh'" in calendar_src
    # The ONLY setInterval in calendar.js is a client-side wall-clock tick, not a data
    # poll — so there is no events poll to retire.
    assert calendar_src.count("setInterval(") == 1
    assert "setInterval(_tick, 30000)" in calendar_src
    # And it does not ride the applicant realtime channel (calendar is workspace-native).
    assert "addEventListener('applicant:realtime'" not in calendar_src


# ── appkitStatusPanel.js: cosmetic timer, no backend change event ─────────────


def test_appkit_status_timer_is_cosmetic_only(appkit_src: str) -> None:
    # The kit's autoRefresh timer only re-renders the relative "updated Xs ago" line
    # from an already-known timestamp — no data is fetched, so there is nothing to push.
    assert "setInterval(" in appkit_src
    assert "relativeTime(self.o.lastUpdated)" in appkit_src
    # It makes zero network calls of any kind — a fetch/socket appearing here would mean
    # it grew a real backend signal that a push could then replace.
    assert "fetch(" not in appkit_src
    assert "XMLHttpRequest" not in appkit_src
    assert "WebSocket" not in appkit_src
    assert "EventSource" not in appkit_src
