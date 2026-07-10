"""RT — retire the remaining GENERAL-WORKSPACE data polls (investigation outcome).

Sibling of ``test_applicant_ws_retire_polls.py`` (which retired the APPLICANT
surfaces' polls over the engine realtime push). This one pins the traced,
honest decision for the three general-workspace surfaces the sweep looked at —
``emailInbox.js`` (new-mail poll), ``calendar.js`` (events), and
``appkitStatusPanel.js`` (status timer):

* ``emailInbox.js`` — the 60s unread-count poll is now a WS-DOWN FALLBACK. A real
  owner-scoped IMAP-IDLE relay exists (``src/email_events.py`` +
  ``src/email_idle_watcher.py``, over ``/api/email/events/ws``): a background
  watcher holds an IMAP IDLE on each owner's IDLE-capable mailbox and pushes
  ``email:unread-changed`` + a ``live`` heartbeat. The poll is SUPPRESSED only while
  that push is genuinely live for the owner, and RESTORED on every non-live state
  (no socket, ``down``, stale heartbeats). So the poll is retained (not deleted) and
  runs whenever the push isn't live — no silent dead inbox. The honesty guard still
  holds: it must NOT be gated on the applicant realtime channel (``applicant:realtime``
  carries the ENGINE's job notifications, not workspace email); the relay is a SEPARATE
  workspace-native channel.

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


# ── emailInbox.js: the poll is retained as the WS-down fallback ───────────────


def test_email_unread_poll_is_preserved(email_src: str) -> None:
    # The 60s unread-count poll must NOT be deleted — it is the honest fallback that
    # runs whenever the IMAP-IDLE push isn't live. It now lives in _startUnreadPoll.
    assert "setInterval(_refreshUnreadCount, 60000)" in email_src
    assert "_refreshUnreadCount();" in email_src


def test_email_poll_is_gated_on_the_real_imap_idle_relay(email_src: str) -> None:
    # The poll retirement is honest ONLY because a real server-side push now exists.
    # It is documented + wired at the poll site so a future sweep doesn't re-investigate.
    assert "imap-idle relay" in email_src.lower()
    assert "/api/email/events/ws" in email_src
    # The relay is connected and can suppress/restore the poll.
    assert "_connectEmailRelay()" in email_src
    assert "_stopUnreadPoll" in email_src and "_startUnreadPoll" in email_src


def test_email_fallback_restores_the_poll_on_every_non_live_state(email_src: str) -> None:
    # The absolute honesty invariant: the poll is only suppressed by a genuine `live`
    # push; a `down` frame and a socket close BOTH restart the poll (no dead inbox).
    assert "onclose" in email_src and "_startUnreadPoll()" in email_src
    # `down` maps to resume-poll, `live` to suppress-poll (the gate).
    assert "'suppress-poll'" in email_src and "'resume-poll'" in email_src


def test_email_poll_is_not_wired_to_the_applicant_realtime_channel(email_src: str) -> None:
    # Honesty guard (still load-bearing): the email poll must never be gated on the
    # ENGINE's realtime push channel (`applicant:realtime` carries job-search
    # notifications, not workspace email). The new relay is a SEPARATE workspace-native
    # channel; assert the email poll never subscribes to the engine channel/flag.
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
