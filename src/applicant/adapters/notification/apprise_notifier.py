"""Apprise + Discord notification adapter (FR-NOTIF-1/2/3/5).

# STAGE B — owned by Phase 1.

Channels: Discord (primary, one-click), email/SMTP via Apprise, plus an in-app web
sink. The adapter implements the full escalation ladder, idempotency, presence-aware
in-app surfacing, and the quiet-hours posture:

- **Escalation ladder** (FR-NOTIF-2): a web-pre-emptable decision holds the Discord
  push ~30s; if the user is verifiably present in the web UI (focused tab + recent
  input + open socket — modeled via an injected presence signal) the in-app channel
  is surfaced instead of Discord; if still undecided after a UI-configurable timeout
  (default 15 min) email is sent. The hops are driven by an **injected clock**, so
  ``advance(now)`` deterministically fires due rungs with no real sleeps.
- **Cross-channel idempotency** (FR-NOTIF-3): acting on one channel (``expire``)
  cancels every pending rung for that decision; later hops become no-ops.
- **Urgency / quiet hours** (FR-NOTIF-5): IMMEDIATE notifications (errors) fan out to
  every channel at once, any hour, bypassing quiet hours; NORMAL ones (approvals /
  digests) defer to the next allowed hour when quiet hours are configured (unless the
  campaign runs 24/7).

The real Apprise/Discord/SMTP send sits behind a single, clearly-marked boundary
(``_dispatch`` -> ``_send_real``). The DEFAULT lane records deliveries in memory (no
network) so contract/unit/BDD tests assert ladder + idempotency semantics offline;
``send_real=True`` (integration-gated) flips on the real Apprise send.
"""

from __future__ import annotations

import itertools
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from applicant.observability.logging import get_logger
from applicant.ports.driven.notification import (
    Notification,
    NotificationChannel,
    NotificationUrgency,
)

log = get_logger(__name__)

# Escalation ladder defaults (FR-NOTIF-2).
_DISCORD_HOLD_SECONDS = 30
_EMAIL_TIMEOUT_SECONDS = 15 * 60  # 15 min, UI-configurable
#: A web-presence signal is only fresh for this long (FR-NOTIF-2). The client
#: re-signals on a heartbeat while the tab stays focused + active; once the
#: heartbeats stop (tab blurred / closed / asleep) presence decays on its own, so a
#: single stale signal can never suppress the Discord escalation indefinitely.
_PRESENCE_TTL_SECONDS = 90

# CONC-3: rotation caps for the in-app inbox + offline capture lists so 24/7
# operation does not grow them unbounded. The most-recent entries are retained.
_MAX_INBOX = 1000
_MAX_CAPTURED = 1000

# LEAK-NOTIF-2: bound the in-app inbox + capture lists by AGE as well as count.
# Capping by count alone meant a quiet stretch could keep day-old entries pinned
# in the inbox indefinitely; prune anything older than this window on the same
# cadence as the email-dedup prune so the lists stay both small AND fresh.
#
# #27: a 24-hour window emptied the center for anyone who checks in every 2-3
# days (a weekend away deleted Friday's unread error). The count cap (1000)
# already bounds memory on its own, so this window only needs to keep the
# inbox reasonably fresh, not aggressively small — raised to two weeks. Unseen
# in-app entries are additionally exempted from this age prune entirely (see
# ``_prune_old``): an unread notification should never silently vanish just
# because the user was away, it should only age out once acknowledged.
_INBOX_MAX_AGE = timedelta(days=14)

# LEAK-NOTIF-1: bound the digest-email dedup memory to a rolling window of recent
# UTC days. Each digest dedup key embeds its day (``digest_email:<cid>:<YYYY-MM-DD>``),
# so a few days of retention keeps re-driven same-day sends idempotent while never
# growing one key per campaign+day forever over 24/7 operation.
_SENT_EMAIL_RETENTION_DAYS = 3

#: Minutes in a day — the quiet-hours window is expressed as a [start, end) span of
#: minutes-since-midnight so it supports HH:MM precision (FR-NOTIF-5), not just whole
#: hours. A whole-hour ``(start_hour, end_hour)`` tuple is still accepted and scaled up.
_MINUTES_PER_DAY = 24 * 60


def _to_minutes(value: int | str) -> int:
    """Coerce a clock position to minutes-since-midnight (0..1439).

    Accepts an int hour (0-23, the legacy form), an int already in minutes, or an
    ``"HH:MM"`` string (the UI form). Out-of-range values wrap into the day so a
    malformed window can never crash the dispatch path.
    """
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            hh, _, mm = text.partition(":")
            minutes = int(hh) * 60 + int(mm or 0)
        else:
            minutes = int(text) * 60  # bare "22" => 22:00
    elif value <= 24:
        minutes = int(value) * 60  # legacy whole-hour form (0-24)
    else:
        minutes = int(value)
    return minutes % _MINUTES_PER_DAY


def _normalize_quiet_window(
    quiet_hours: tuple[int | str, int | str] | None,
) -> tuple[int, int] | None:
    """Normalize a quiet-hours window to a ``(start_min, end_min)`` minute span.

    Returns ``None`` when quiet hours are not configured. A window with equal start
    and end means "no quiet hours" (an empty span) and is also returned as-is for the
    caller to treat as inactive.
    """
    if not quiet_hours:
        return None
    start, end = quiet_hours
    return (_to_minutes(start), _to_minutes(end))


class NotificationDeliveryError(RuntimeError):
    """Raised when a real Apprise dispatch fails (apprise.notify() == False)."""


@dataclass
class _Rung:
    """One escalation hop: a channel to fire ``due_at`` (epoch-relative seconds)."""

    channel: str
    due_at: float
    fired: bool = False


@dataclass
class _Delivery:
    handle: str
    notification: Notification
    rungs: list[_Rung] = field(default_factory=list)
    sent_channels: list[str] = field(default_factory=list)
    active: bool = True


@dataclass(frozen=True)
class CapturedSend:
    """An offline-captured dispatch (for tests / the in-app sink).

    The in-app sink uses the extra fields (``id``/``created_at``/``dedup_key``/
    ``seen``/``kind``) to back the notification center: the UI lists entries by
    id, toasts the ones newer than its last-seen marker, and dismisses
    informational ones by id. The first five fields keep their original
    positional shape so existing tuple-style equality in tests is unaffected;
    the new fields carry sensible defaults.
    """

    channel: str
    title: str
    body: str
    deep_link: str | None
    urgency: str
    id: str = ""
    created_at: datetime | None = None
    dedup_key: str | None = None
    seen: bool = False
    kind: str = ""


def _default_clock() -> datetime:
    return datetime.now(UTC)


# #4: a coarse "is this body HTML markup" sniff for the digest email path (the
# only notification body that is ever rendered HTML today — ``send_email``
# wraps ``render_email``'s ``<h1>Your daily digest</h1>`` + ``<table ...>``
# string verbatim into ``Notification.body``). Plain-text bodies (decision
# pings, status updates, errors) never contain an opening HTML tag, so this
# only flips on for the digest email and stays off for everything else.
_HTML_BODY_RE = re.compile(r"<(?:html|body|table|h[1-6]|div|p)[\s>]", re.IGNORECASE)


def _looks_like_html(body: str) -> bool:
    """True when ``body`` is HTML markup rather than a plain-text message."""
    return bool(_HTML_BODY_RE.search(body))


# #35: the "email" field (``apprise_urls``) accepts ANY Apprise service URL, but the
# ladder still applies mail-shaped TIMING to whatever is pasted there (the 15-minute
# email-backstop delay) and labels it "email" in the quiet-hours preference map. A
# Slack/Telegram/etc. URL pasted into that field silently inherits both, with no sign
# anything is off. These are the schemes Apprise treats as an actual mail transport
# (direct ``mailto(s)://`` plus its provider-shorthand aliases); anything else is
# flagged by :func:`_non_mail_apprise_urls` rather than silently accepted.
_MAIL_LIKE_APPRISE_SCHEMES = frozenset(
    {
        "mailto",
        "mailtos",
        "mailgun",
        "sendgrid",
        "ses",
        "sparkpost",
        "smtp2go",
        "gmail",
        "outlook365",
        "office365",
        "yahoo",
        "aweber",
        "fastmail",
        "seznam",
        "smtp",
        "smtps",
    }
)


def _non_mail_apprise_urls(apprise_urls: str) -> list[str]:
    """Entries in ``apprise_urls`` whose scheme is not email-shaped (#35).

    Returns the offending entries (original casing) so callers can surface exactly
    what was pasted; an empty list means every configured entry looks like mail (or
    the field is empty). A scheme-less/unparseable entry is left alone here — it is
    someone else's problem (SSRF/URL validation) — this only flags a RECOGNIZABLE,
    non-mail Apprise scheme (e.g. ``slack://``, ``tgram://``, ``discord://``).
    """
    offenders: list[str] = []
    for raw in (apprise_urls or "").split(","):
        entry = raw.strip()
        if not entry or "://" not in entry:
            continue
        scheme = urlsplit(entry).scheme.lower()
        if scheme and scheme not in _MAIL_LIKE_APPRISE_SCHEMES:
            offenders.append(entry)
    return offenders


def _ntfy_url_with_priority(url: str, notification: Notification) -> str:
    """Map urgency to Apprise's ntfy ``priority`` query param (#15).

    Bare ``ntfy://`` URLs carry no priority, so an IMMEDIATE/CRITICAL "agent is
    stuck" push arrives at the same default priority as a routine NORMAL ping —
    no bypass-DND, no distinct sound. NORMAL keeps ntfy's own default; IMMEDIATE
    and CRITICAL request ``urgent`` (Apprise supports ``?priority=`` on ntfy
    URLs). A URL that already names a priority is left alone (explicit
    caller/user override wins).
    """
    if "priority=" in url:
        return url
    priority = (
        "urgent"
        if notification.urgency
        in (NotificationUrgency.IMMEDIATE, NotificationUrgency.CRITICAL)
        else "default"
    )
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}priority={priority}"


# #36: ``NotificationChannel.PUSH`` documents "push" as the LOGICAL name for the
# phone-push channel, with ``NotificationChannel.NTFY`` ("ntfy") as its current
# transport. The two enum members share one runtime value today (existing callers
# and persisted config all key off the literal "ntfy"), so this map is a forward
# seam rather than a live rename: if a per-channel preference (``quiet_hours_channels``
# — see ``configure``) is ever persisted under the logical "push" key instead of the
# transport "ntfy" key (e.g. a future UI/config migration), preference lookups still
# resolve correctly either way. Swapping the underlying transport later (web-push,
# Gotify, ...) only needs an entry added here, not a rename of every persisted key.
_CHANNEL_LOGICAL_ALIASES: dict[str, str] = {
    NotificationChannel.NTFY.value: "push",
}


class AppriseNotifier:
    """NotificationPort adapter: real semantics, offline-safe by default."""

    def __init__(
        self,
        *,
        discord_webhook_url: str = "",
        apprise_urls: str = "",
        ntfy_url: str = "",
        in_app: bool = True,
        escalation_hold_seconds: int = _DISCORD_HOLD_SECONDS,
        email_timeout_seconds: int = _EMAIL_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
        presence: Callable[[], bool] | None = None,
        quiet_hours: tuple[int | str, int | str] | None = None,
        quiet_tz: str = "",
        quiet_hours_channels: dict[str, bool] | None = None,
        always_on: bool = False,
        send_real: bool = False,
    ) -> None:
        self._discord = discord_webhook_url
        self._apprise = apprise_urls  # email/SMTP/other Apprise URLs (comma-separated)
        self._warn_non_mail_apprise_urls()
        # #300: ntfy push channel — a plain ntfy topic URL (e.g. ``ntfy://ntfy.sh/topic``).
        # Opt-in, exactly like Discord/email. IMMEDIATE/CRITICAL notifications fan out
        # here right away, same as every other configured channel.
        # #19/#20: NORMAL notifications also reach ntfy now (not just web-preemptable
        # decisions), so a phone-push-only user still gets the daily digest-ready /
        # status / nudge pings. #20: a web-preemptable DECISION holds ntfy for the same
        # window as Discord and is likewise presence-preemptable (see ``_fire_due``) —
        # a quick web approval, or verified presence, suppresses the phone buzz just
        # like it suppresses Discord. Purely informational NORMAL notifications (no
        # decision to pre-empt) fire immediately, with no hold.
        self._ntfy = ntfy_url
        self._in_app = in_app
        self._hold_seconds = escalation_hold_seconds
        # #236: enforce the same floor in the constructor that configure() enforces,
        # so a 0-second value passed at construction time cannot bypass the guard.
        self._email_timeout = max(60, int(email_timeout_seconds))
        self._clock = clock or _default_clock
        # Presence signal (FR-NOTIF-2): True when the user is verifiably present in
        # the web UI (focused tab + recent input + open socket). Default: absent.
        # An optional injected provider can report presence directly; the front-door
        # instead heartbeats ``set_presence`` which opens a short freshness window.
        self._presence = presence
        self._present_until: datetime | None = None
        # Quiet hours (FR-NOTIF-5): a [start, end) span of minutes-since-midnight in
        # the configured timezone; NORMAL notifications (approvals/digests) defer into
        # this window unless the user is in 24/7 mode (``always_on``). Errors always
        # fire. Accepts HH:MM strings or whole-hour ints (legacy). Empty => disabled.
        self._quiet_hours = _normalize_quiet_window(quiet_hours)
        # The timezone the window is interpreted in. Empty => UTC (the clock's tz).
        self._quiet_tz = quiet_tz or ""
        # #302: per-channel quiet-hours preference — a channel mapped to ``False`` is
        # EXEMPT from quiet hours (it still delivers overnight); a channel mapped to
        # ``True`` (or absent) respects the window. This lets a user say "hold Discord
        # at night but let email through" without disabling quiet hours wholesale.
        # In-app always surfaces regardless (it is silent), and IMMEDIATE/CRITICAL are
        # never deferred by quiet hours at all (those gates are independent of this map).
        self._quiet_hours_channels: dict[str, bool] = dict(quiet_hours_channels or {})
        self._always_on = always_on
        self._send_real = send_real
        # #235: guard _sent (and _sent_emails) against concurrent access from the
        # scheduler-advance path and the API expire path, which run on different threads
        # (the scheduler tick runs in an asyncio worker thread; API handlers are sync
        # threads in FastAPI's threadpool). A single lock covers both dicts so the
        # advance-vs-expire race cannot corrupt the dedup ledger.
        self._sent_lock = threading.Lock()
        # dedup_key -> active delivery (deactivated on expiry, FR-NOTIF-3)
        self._sent: dict[str, _Delivery] = {}
        self._counter = 0
        # In-app sink: notifications surfaced in the portal (FR-UI-3 feed).
        self._inbox: list[CapturedSend] = []
        # Offline capture of every fired dispatch (introspection for tests).
        self._captured: list[CapturedSend] = []
        # IDEM-1: dedup keys of digest emails already sent (per campaign+day) so a
        # re-driven delivery never dispatches the same digest email twice.
        # LEAK-NOTIF-1: bounded to a rolling recent-days window (mirror the
        # today-only prune used elsewhere) so it does not grow one key per
        # campaign+day forever.
        self._sent_emails: set[str] = set()
        # CONC-3: cap the unbounded in-app inbox + capture lists so 24/7 operation
        # does not grow them without bound (oldest entries rotate out).
        self._max_inbox = _MAX_INBOX
        self._max_captured = _MAX_CAPTURED
        # LEAK-NOTIF-2: age cap applied alongside the count cap (overridable in tests).
        self._max_age = _INBOX_MAX_AGE
        # Monotonic id source for in-app inbox entries (stable per-process handle
        # the notification center lists/dismisses by). Independent of ``_counter``
        # so dispatch ids do not collide with notify handles.
        self._inbox_ids = itertools.count(1)
        # Dismissed (seen) in-app inbox ids — an informational notification the
        # user dismissed stops being listed even if it is still in ``_inbox``.
        self._dismissed: set[str] = set()

    # --- channel configuration / gate (FR-OOBE-3) -------------------------
    def configured_channels(self) -> list[str]:
        channels: list[str] = []
        if self._discord:
            channels.append(NotificationChannel.DISCORD.value)
        if self._in_app:
            channels.append(NotificationChannel.IN_APP.value)
        if self._apprise:
            channels.append(NotificationChannel.EMAIL.value)
        if self._ntfy:
            channels.append(NotificationChannel.NTFY.value)
        return channels

    def is_configured(self) -> bool:
        return bool(self._discord or self._apprise or self._in_app or self._ntfy)

    def has_discord(self) -> bool:
        return bool(self._discord)

    def has_email(self) -> bool:
        return bool(self._apprise)

    def has_ntfy(self) -> bool:
        return bool(self._ntfy)

    def non_mail_apprise_urls(self) -> list[str]:
        """Configured ``apprise_urls`` entries that are not an email-shaped scheme (#35).

        The "email" field accepts any Apprise service URL but still applies mail
        timing (the 15-minute backstop) and the "email" quiet-hours label to whatever
        is pasted there. Non-empty means at least one entry (e.g. a Slack/Telegram
        webhook) is silently riding the email ladder's timing — callers (Settings, an
        operator dashboard) can surface this; the adapter itself only warns (see
        ``_warn_non_mail_apprise_urls``) rather than rejecting the value outright.
        """
        return _non_mail_apprise_urls(self._apprise)

    def _warn_non_mail_apprise_urls(self) -> None:
        """Log once per (re)configuration when a non-mail URL is in ``apprise_urls`` (#35)."""
        offenders = _non_mail_apprise_urls(self._apprise)
        if offenders:
            log.warning(
                "apprise_url_non_mail_scheme",
                schemes=sorted({urlsplit(u).scheme.lower() for u in offenders}),
                count=len(offenders),
            )

    def is_live(self) -> bool:
        """True when configured channels actually go over the wire (NOTIFICATIONS_LIVE).

        The default lane captures dispatches in memory (hermetic); only a deployment
        with ``send_real`` on (NOTIFICATIONS_LIVE) delivers for real. Lets the Settings
        "Send a test" report dry-run vs live honestly instead of claiming delivery.
        """
        return bool(self._send_real)

    def configure(
        self,
        *,
        discord_webhook_url: str | None = None,
        apprise_urls: str | None = None,
        ntfy_url: str | None = None,
        quiet_hours: tuple[int | str, int | str] | None = None,
        quiet_tz: str | None = None,
        quiet_hours_channels: dict[str, bool] | None = None,
        always_on: bool | None = None,
        email_timeout_seconds: int | None = None,
    ) -> None:
        """Update channel + quiet-hours config on the live adapter (FR-OOBE-2, FR-NOTIF-5).

        Lets Settings / the OOBE channels step reconfigure the running notifier
        without a restart (zero-CLI). Only the provided fields are updated; passing
        ``quiet_hours=None`` together with ``always_on=True`` is how the UI selects
        24/7 mode (quiet hours off). To CLEAR a configured window, pass
        ``always_on=True`` (the window is then ignored).
        """
        if discord_webhook_url is not None:
            self._discord = discord_webhook_url
        if apprise_urls is not None:
            self._apprise = apprise_urls
            self._warn_non_mail_apprise_urls()
        if ntfy_url is not None:
            self._ntfy = ntfy_url
        if quiet_hours is not None:
            self._quiet_hours = _normalize_quiet_window(quiet_hours)
        if quiet_tz is not None:
            self._quiet_tz = quiet_tz or ""
        if quiet_hours_channels is not None:
            # #302: replace the per-channel quiet preference map wholesale (the UI
            # always sends the full picture). An empty dict means "every push channel
            # respects quiet hours" (the default behaviour).
            self._quiet_hours_channels = dict(quiet_hours_channels)
        if always_on is not None:
            self._always_on = always_on
        if email_timeout_seconds is not None:
            # The email escalation delay is UI-configurable (FR-NOTIF-2); clamp to a
            # sane floor so it can never become a 0s instant-email.
            self._email_timeout = max(60, int(email_timeout_seconds))

    # --- ladder construction (FR-NOTIF-2) ---------------------------------
    def _now_secs(self) -> float:
        return self._clock().timestamp()

    def _build_rungs(self, notification: Notification) -> list[_Rung]:
        """Plan the escalation hops for one notification (FR-NOTIF-2)."""
        now = self._now_secs()
        rungs: list[_Rung] = []

        if notification.urgency is NotificationUrgency.IMMEDIATE:
            # Errors fan out to every configured channel at once, any hour (FR-NOTIF-5).
            for ch in self.configured_channels():
                rungs.append(_Rung(channel=ch, due_at=now))
            if not rungs:
                rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))
            return rungs

        if notification.urgency is NotificationUrgency.CRITICAL:
            # A targeted action the user MUST see now (e.g. live-takeover / captcha):
            # fan out to every configured channel immediately — no Discord hold, no
            # email backstop wait — so the blocked agent gets the human in the loop at
            # once. Unlike IMMEDIATE this is a decision (carries a deep link), and the
            # quiet-hours gate in ``_fire_due`` exempts CRITICAL so it lands overnight.
            for ch in self.configured_channels():
                rungs.append(_Rung(channel=ch, due_at=now))
            if not rungs:
                rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))
            return rungs

        # NORMAL: in-app is always available immediately as the home-base sink.
        if self._in_app:
            rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))

        # Web-pre-emptable decisions hold the Discord push so a quick web approval
        # (or verifiable presence) can pre-empt it; otherwise Discord fires now.
        if self._discord:
            discord_delay = self._hold_seconds if notification.web_preemptable else 0
            rungs.append(
                _Rung(channel=NotificationChannel.DISCORD.value, due_at=now + discord_delay)
            )

        # Email is the final rung after the configurable timeout (FR-NOTIF-2).
        # #302: when the user has marked email as their quiet-hours-exempt "anytime"
        # channel, it is no longer the slow backstop — it is the channel they WANT
        # overnight, so deliver it immediately rather than after the escalation delay.
        if self._apprise:
            email_exempt = (
                self._quiet_hours is not None
                and self._quiet_hours_channels.get(NotificationChannel.EMAIL.value) is False
            )
            email_due = now if email_exempt else now + self._email_timeout
            rungs.append(
                _Rung(channel=NotificationChannel.EMAIL.value, due_at=email_due)
            )

        # #19: ntfy now fans out to every NORMAL notification, not just web-preemptable
        # decisions — a phone-push-only user (no Discord/email configured) previously
        # never received the digest-ready ping, the daily status update, or the
        # essentials nudge. #20: web-preemptable decisions still hold ntfy for the same
        # window as Discord (and are presence-preemptable, see ``_fire_due``); purely
        # informational NORMAL notifications have nothing to pre-empt, so they fire
        # immediately, matching the in-app rung. Deep links are included so the push
        # notification leads directly to the Portal action.
        if self._ntfy:
            ntfy_delay = self._hold_seconds if notification.web_preemptable else 0
            rungs.append(
                _Rung(channel=NotificationChannel.NTFY.value, due_at=now + ntfy_delay)
            )

        if not rungs:
            rungs.append(_Rung(channel=NotificationChannel.IN_APP.value, due_at=now))
        return rungs

    # --- quiet hours (FR-NOTIF-5) -----------------------------------------
    def _in_quiet_hours(self, when: datetime) -> bool:
        """True when ``when`` falls inside the configured quiet window.

        24/7 mode (``always_on``) and an unset/empty window always return False so
        errors-immediate is never affected (that gate lives in the caller, but this
        keeps the window check pure). The window is a [start, end) minute span in the
        configured timezone, evaluated to the minute so HH:MM windows are exact, and
        wraps correctly across midnight (e.g. 22:30 -> 07:15).
        """
        if self._always_on or not self._quiet_hours:
            return False
        start, end = self._quiet_hours
        if start == end:
            return False  # empty span => effectively 24/7
        local = self._localize(when)
        minutes = local.hour * 60 + local.minute
        if start < end:
            return start <= minutes < end
        # Window wraps midnight (e.g. 22:00 -> 07:00).
        return minutes >= start or minutes < end

    def _localize(self, when: datetime) -> datetime:
        """Convert ``when`` into the quiet-hours timezone (UTC when unset/invalid).

        The ladder clock yields UTC instants; the user configures quiet hours in
        their own timezone, so the window must be evaluated in that zone. An unknown
        timezone name degrades to UTC rather than crashing the dispatch path.
        """
        if not self._quiet_tz:
            return when
        try:
            tz = ZoneInfo(self._quiet_tz)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return when
        return when.astimezone(tz)

    def _preference_for_channel(self, channel: str) -> bool | None:
        """Look up a per-channel quiet-hours preference, alias-aware (#36).

        ``_quiet_hours_channels`` is keyed by whatever channel name the caller
        persisted. Today that is always the transport name (``"ntfy"``); this also
        checks the logical alias (``"push"``, see ``_CHANNEL_LOGICAL_ALIASES``) so a
        preference map does not orphan a stored entry if the config layer starts
        writing the logical name instead of (or in addition to) the transport name.
        The transport-keyed entry wins if both happen to be present.
        """
        pref = self._quiet_hours_channels.get(channel)
        if pref is not None:
            return pref
        alias = _CHANNEL_LOGICAL_ALIASES.get(channel)
        if alias is not None:
            return self._quiet_hours_channels.get(alias)
        return None

    def _channel_quiet_deferred(
        self, channel: str, notification: Notification, when: datetime
    ) -> bool:
        """True when this rung should be held back by quiet hours (FR-NOTIF-5).

        Only NORMAL push channels are ever deferred — in-app always surfaces (it is
        silent) and IMMEDIATE/CRITICAL bypass quiet hours entirely (errors and
        live-takeover actions must reach the user any hour).

        #302 per-channel preference: when ``_quiet_hours_channels`` names this channel,
        ``False`` exempts it so it always delivers, even inside the window ("let email
        through") — that bypass IS independent of the instant. ``True`` ("hold Discord
        overnight") does NOT mean "hold this channel 24/7" — it means the channel
        respects the configured window like any other push channel, so it still falls
        through to the actual time-window check and is only held while `when` is
        really inside quiet hours. When the channel is not named, the time-window
        check governs the same way.
        """
        if notification.urgency is not NotificationUrgency.NORMAL:
            return False  # IMMEDIATE / CRITICAL never deferred
        if channel == NotificationChannel.IN_APP.value:
            return False  # the silent home-base sink always surfaces
        pref = self._preference_for_channel(channel)
        if pref is False:
            # Explicit "let it through" preference — never deferred, independent of
            # the instant.
            return False
        return self._in_quiet_hours(when)

    # --- dispatch ---------------------------------------------------------
    @staticmethod
    def _classify(notification: Notification) -> str:
        """Coarse kind for the in-app notification center.

        ``action`` items are decisions the user must act on (they clear when the
        underlying pending action resolves); everything else is ``info`` that the
        center lists as a dismissible entry. Errors are flagged ``error`` so the
        UI can style them, but they are still informational (no inline action).
        """
        key = notification.dedup_key or ""
        if notification.web_preemptable or key.startswith("decision:"):
            return "action"
        if key == "channels-test":
            # #14: the Settings "Send a test" ping (setup.py's ``/channels/test``)
            # uses IMMEDIATE urgency purely so it bypasses quiet hours and fans out
            # to every configured channel at once — it is not a real alert, so it
            # must not fall into the IMMEDIATE->error mapping below (a user's very
            # first in-app notification should not render as a failure). Any other
            # IMMEDIATE notification still classifies as ``error`` unchanged.
            return "info"
        if notification.urgency is NotificationUrgency.IMMEDIATE:
            return "error"
        if key.startswith("digest:"):
            return "digest"
        return "info"

    def _dispatch(self, channel: str, notification: Notification) -> None:
        now = self._clock()
        captured = CapturedSend(
            channel=channel,
            title=notification.title,
            body=notification.body,
            deep_link=notification.deep_link,
            urgency=notification.urgency.value,
            created_at=now,
            dedup_key=notification.dedup_key,
            kind=self._classify(notification),
        )
        self._captured.append(captured)
        self._prune_old(self._captured, now)
        if len(self._captured) > self._max_captured:
            # CONC-3: rotate oldest out so the list is bounded over 24/7.
            del self._captured[: len(self._captured) - self._max_captured]
        if channel == NotificationChannel.IN_APP.value:
            # The in-app sink gets a stable id the notification center addresses.
            captured = replace(captured, id=f"inapp-{next(self._inbox_ids)}")
            self._inbox.append(captured)
            self._prune_old(self._inbox, now, exempt_unseen=True)
            if len(self._inbox) > self._max_inbox:
                del self._inbox[: len(self._inbox) - self._max_inbox]
        if self._send_real:
            self._send_real_dispatch(channel, notification)
        log.info(
            "notification_dispatched",
            channel=channel,
            urgency=notification.urgency.value,
            dedup_key=notification.dedup_key,
        )

    def _prune_old(
        self, entries: list[CapturedSend], now: datetime, *, exempt_unseen: bool = False
    ) -> None:
        """LEAK-NOTIF-2: drop entries older than the age window, in place.

        Mirrors the rolling-window prune used for the email-dedup set so the
        in-app inbox + capture lists are bounded by AGE as well as by count.
        Entries without a ``created_at`` (legacy/test-built) are retained.

        #27: when ``exempt_unseen`` is set (the in-app inbox), an entry the user
        has never dismissed survives the age prune regardless of how old it is —
        only the count cap (``_max_inbox``) bounds it. Only entries the user has
        already acknowledged (dismissed) age out on this window. This is what
        keeps a weekend-away unread error from silently disappearing.
        """
        horizon = now - self._max_age
        entries[:] = [
            e
            for e in entries
            if e.created_at is None
            or e.created_at >= horizon
            or (exempt_unseen and e.id and e.id not in self._dismissed)
        ]

    def _send_real_dispatch(self, channel: str, notification: Notification) -> None:
        """REAL network boundary (FR-NOTIF-1) — integration-gated only.

        Builds an Apprise client for the channel and sends. The in-app channel is
        local (no network); Discord + email + ntfy go over the wire via Apprise URLs.
        """
        if channel == NotificationChannel.IN_APP.value:
            return  # local sink, no network
        import apprise  # imported lazily so the offline lane needs no Apprise import

        client = apprise.Apprise()
        if channel == NotificationChannel.DISCORD.value and self._discord:
            client.add(self._discord)
        elif channel == NotificationChannel.EMAIL.value and self._apprise:
            for url in (u.strip() for u in self._apprise.split(",") if u.strip()):
                client.add(url)
        elif channel == NotificationChannel.NTFY.value and self._ntfy:
            # #300/#15: ntfy push channel. Apprise supports ntfy:// URLs
            # natively; map urgency -> its ``priority`` param so an urgent
            # action alert doesn't arrive identical to a routine ping.
            for url in (u.strip() for u in self._ntfy.split(",") if u.strip()):
                client.add(_ntfy_url_with_priority(url, notification))
        body = notification.body
        if notification.deep_link:
            body = f"{body}\n{notification.deep_link}"
        # #4: the digest email body is rendered HTML (``<h1>``/``<table>``); with no
        # format hint Apprise's default TEXT handling delivered literal markup
        # source to most SMTP recipients. Detect the HTML-bodied case and pass the
        # HTML format hint so those channels render it; plain-text bodies (decision
        # pings, status updates, errors) are untouched and keep the default TEXT
        # format. (Scoped to the format hint only — a plain-text MIME alternative
        # part is a larger change, deferred.)
        notify_kwargs: dict = {"title": notification.title, "body": body}
        if _looks_like_html(notification.body):
            notify_kwargs["body_format"] = apprise.NotifyFormat.HTML
        # Apprise returns False on a failed delivery (it does NOT raise). Ignoring
        # the return recorded failures as "dispatched" — check it and surface the
        # failure so the caller / logs reflect reality (FR-NOTIF-1).
        ok = client.notify(**notify_kwargs)
        if not ok:
            log.error(
                "notification_delivery_failed",
                channel=channel,
                urgency=notification.urgency.value,
                dedup_key=notification.dedup_key,
            )
            raise NotificationDeliveryError(
                f"Apprise delivery failed on the {channel} channel."
            )

    # --- public API -------------------------------------------------------
    def notify(self, notification: Notification) -> str:
        """Dispatch a notification, honoring the ladder + cross-channel dedup.

        #9: a repeat ``notify()`` for a ``dedup_key`` that is STILL ACTIVE (its prior
        delivery has not been ``expire()``-d, and has not yet aged out of ``_sent``)
        is an idempotent no-op — it returns the EXISTING delivery's handle instead of
        replacing it and re-firing fresh rungs. Several call sites already assumed
        this (the scheduler-stall alert's "even if this fired twice the notifier
        collapses it to a single operator alert", the daily nudges' "a no-op at the
        notifier") — before this fix that was false: a second ``notify()`` with the
        same key overwrote ``_sent[key]`` and immediately fired brand-new rungs,
        double-pinging every configured channel for what the caller believed was one
        logical event.

        The re-arm path is preserved: once :meth:`expire` marks the delivery inactive
        (acted-on elsewhere, FR-NOTIF-3) or :meth:`_prune_sent` drops a fully-escalated
        delivery that is past the email-timeout cutoff, the key is no longer "active"
        and the next ``notify()`` for it starts a fresh ladder, exactly as before.
        """
        # Prune BEFORE checking so a delivery that has already fully escalated and
        # aged out is correctly treated as inactive (re-arm), not as still-live.
        # (Uses its own fresh clock read — deliberately NOT reused below, since
        # ``_build_rungs`` takes its own later clock read for ``due_at``; reusing a
        # stale timestamp to fire against would skip rungs due "in the future" by a
        # few microseconds.)
        self._prune_sent(self._now_secs())
        key = notification.dedup_key
        if key:
            with self._sent_lock:
                existing = self._sent.get(key)
                if existing is not None and existing.active:
                    return existing.handle
        with self._sent_lock:
            self._counter += 1
            handle = f"notif-{self._counter}"
        rungs = self._build_rungs(notification)
        delivery = _Delivery(handle=handle, notification=notification, rungs=rungs)
        store_key = key or handle
        with self._sent_lock:
            # Re-check under the lock: another thread may have inserted an active
            # delivery for the same key between the check above and here.
            existing = self._sent.get(store_key)
            if existing is not None and existing.active:
                return existing.handle
            self._sent[store_key] = delivery
        # Fire any rung already due (NORMAL in-app + Discord-now; IMMEDIATE all).
        # _fire_due mutates only the local delivery object (not _sent) so it can run
        # outside the lock; the dispatch itself is deliberately lock-free (no IO under
        # a lock). Fresh clock read (not the one used for the pre-check prune above) —
        # ``_build_rungs`` computed ``due_at`` from its OWN later clock read.
        self._fire_due(delivery, self._now_secs())
        # LEAK-NOTIF-1: opportunistically drop fully-fired, past-timeout deliveries
        # so apps that never call ``expire`` (abandon/complete off-path) do not leak
        # ``_sent`` entries forever.
        self._prune_sent(self._now_secs())
        return handle

    def send_email(
        self,
        *,
        subject: str,
        html: str,
        deep_link: str | None = None,
        dedup_key: str | None = None,
    ) -> bool:
        """Send a rendered email body directly to the EMAIL channel (FR-DIG-2).

        Used by the digest delivery so the daily digest email is actually SENT, not
        merely rendered for pull. Bypasses the escalation ladder (this is a direct,
        already-decided send) but stays behind the same offline-safe boundary: the
        body is captured in memory and only goes over the wire when ``send_real`` is
        on (NOTIFICATIONS_LIVE). Returns True if the email channel is configured.

        IDEM-1: when ``dedup_key`` is supplied, a second send with the same key is a
        no-op (returns True without re-dispatching) so a re-driven daily digest never
        sends two emails for the same campaign+day.

        #233: the dedup key is written to ``_sent_emails`` AFTER a confirmed successful
        dispatch so a failed SMTP send does not permanently lose the digest email (the
        caller can retry and the dedup guard will not block it).
        """
        if not self._apprise:
            return False
        if dedup_key is not None:
            with self._sent_lock:
                if dedup_key in self._sent_emails:
                    return True  # already sent this campaign+day — idempotent no-op
        # Dispatch FIRST (#233); only register the dedup key after a confirmed send so
        # a failed SMTP delivery does not permanently suppress a retry.
        self._dispatch(
            NotificationChannel.EMAIL.value,
            Notification(
                title=subject,
                body=html,
                deep_link=deep_link,
                urgency=NotificationUrgency.NORMAL,
            ),
        )
        if dedup_key is not None:
            with self._sent_lock:
                self._sent_emails.add(dedup_key)
                # LEAK-NOTIF-1: prune to a rolling recent-days window so the dedup set
                # does not grow one key per campaign+day forever.
            self._prune_sent_emails()
        return True

    def _prune_sent_emails(self) -> None:
        """Bound ``_sent_emails`` to recent UTC days (LEAK-NOTIF-1).

        Digest dedup keys embed the UTC day (``...:<YYYY-MM-DD>``). Keep only keys
        whose embedded day is within ``_SENT_EMAIL_RETENTION_DAYS`` of today; keys
        without a parseable trailing date are retained (unknown format, do not drop).
        """
        from datetime import date, timedelta

        today = self._clock().date()
        horizon = today - timedelta(days=_SENT_EMAIL_RETENTION_DAYS)
        for key in list(self._sent_emails):
            tail = key.rsplit(":", 1)[-1]
            try:
                day = date.fromisoformat(tail)
            except ValueError:
                continue  # no parseable date — keep
            if day < horizon:
                self._sent_emails.discard(key)

    def advance(self, now: datetime | None = None) -> list[str]:
        """Fire any escalation rungs now due across active deliveries (FR-NOTIF-2).

        Driven by the injected clock so tests step time deterministically. Returns
        the list of channels fired on this tick.
        """
        ts = (now or self._clock()).timestamp()
        # LEAK-NOTIF-1: prune BEFORE firing so deliveries fully-fired on a PRIOR
        # tick are dropped (``advance`` stops rescanning dead entries) while a
        # delivery whose rungs fire on THIS tick survives for introspection until
        # the next tick.
        self._prune_sent(ts)
        # Take a snapshot of current deliveries under the lock; fire outside the lock
        # so no IO is held under the mutex (#235).
        with self._sent_lock:
            snapshot = list(self._sent.values())
        fired: list[str] = []
        for delivery in snapshot:
            fired.extend(self._fire_due(delivery, ts))
        return fired

    def ladder_status(self, dedup_key: str) -> dict | None:
        """Current escalation-ladder state for one decision (dark-engine audit #77).

        Every tick's ``advance`` fires due rungs (Discord held, then email after the
        configured timeout, both further held during quiet hours) but nothing before
        now exposed WHICH rung a decision is currently sitting on. Read-only — never
        mutates ladder state. Returns ``None`` when there is no active delivery for
        ``dedup_key`` (never sent, already resolved via ``expire``, or fully
        escalated + pruned).
        """
        with self._sent_lock:
            delivery = self._sent.get(dedup_key)
            if delivery is None or not delivery.active:
                return None
            notification = delivery.notification
            rungs = list(delivery.rungs)
        now = self._clock()
        channels: list[dict] = []
        next_channel: str | None = None
        next_due_at: str | None = None
        next_quiet_held = False
        for r in rungs:
            due_at_iso = None if r.fired else datetime.fromtimestamp(r.due_at, tz=UTC).isoformat()
            channels.append({"channel": r.channel, "fired": r.fired, "due_at": due_at_iso})
            if not r.fired and next_channel is None:
                next_channel = r.channel
                next_due_at = due_at_iso
                next_quiet_held = self._channel_quiet_deferred(r.channel, notification, now)
        return {
            "channels": channels,
            "held": next_channel is not None,
            "next_channel": next_channel,
            "next_due_at": next_due_at,
            "quiet_hours_held": next_quiet_held,
        }

    def deliver_now(self, now: datetime | None = None) -> list[str]:
        """Force-flush quiet-hours-held rungs immediately, bypassing the quiet gate (#302).

        The "deliver now" action the user taps to release notifications that were
        held back by an active quiet window. It bypasses the quiet-hours gate (and
        presence pre-emption) for every active delivery, surfacing Discord/email/
        push rungs that are due but sitting held by quiet hours.

        #10: this only flushes rungs whose ``due_at`` has already passed — it never
        force-fires a rung scheduled for the future. Without that guard, tapping
        "Deliver now" to release an overnight digest also instantly fired the
        15-minute email backstop for every open decision (an email the user would
        never otherwise get so soon) since that rung's ``due_at`` just hadn't
        arrived yet, quiet hours or not. Returns the channels flushed on this call.
        """
        ts = (now or self._clock()).timestamp()
        with self._sent_lock:
            snapshot = list(self._sent.values())
        flushed: list[str] = []
        for delivery in snapshot:
            flushed.extend(self._fire_due(delivery, ts, force=True))
        return flushed

    def _prune_sent(self, ts: float) -> None:
        """Drop deliveries whose every rung has fired and which are past timeout.

        A delivery is only removed once ALL its rungs have fired AND it is past the
        email timeout (the last possible rung's window), so a delivery still awaiting
        a future hop is never dropped early. Inactive (acted/expired) deliveries are
        already popped by :meth:`expire`; this catches the abandon/complete paths
        that never call ``acted`` (LEAK-NOTIF-1).
        """
        cutoff = ts - self._email_timeout
        # #235: lock the dict for the duration of the prune so a concurrent expire()
        # call on the API path does not observe a half-pruned _sent dict.
        with self._sent_lock:
            for key in list(self._sent.keys()):
                delivery = self._sent[key]
                if not delivery.active:
                    self._sent.pop(key, None)
                    continue
                all_fired = all(r.fired for r in delivery.rungs)
                last_due = max((r.due_at for r in delivery.rungs), default=0.0)
                if all_fired and last_due <= cutoff:
                    self._sent.pop(key, None)

    def _fire_due(
        self, delivery: _Delivery, ts: float, *, force: bool = False
    ) -> list[str]:
        if not delivery.active:
            return []
        fired: list[str] = []
        when = datetime.fromtimestamp(ts, tz=UTC)
        for rung in delivery.rungs:
            # #10: ``force`` (deliver-now) bypasses the QUIET-HOURS gate below (and
            # presence pre-emption) so a rung that is only being held back by an
            # active quiet window flushes immediately — but it must NOT bypass
            # ``due_at`` itself. A rung scheduled for the future (e.g. the 15-minute
            # email backstop for a decision the user hasn't acted on yet) has not
            # "come due" for any quiet-hours reason; force-firing it meant tapping
            # "Deliver now" to release an overnight digest also instantly emailed
            # every open decision's backstop. Only rungs whose scheduled time has
            # actually arrived are eligible, whether flushed normally or by force.
            if rung.fired or rung.due_at > ts:
                continue
            # Presence pre-emption (FR-NOTIF-2): when the user is verifiably present
            # in the web UI, suppress the Discord push in favor of the in-app surface.
            # #20: ntfy is held on the same schedule as Discord for web-preemptable
            # decisions, so it gets the same presence pre-empt — otherwise it was held
            # like an escalation but never actually preemptable (the worst of both: a
            # delayed alert with no way to skip it). A force flush is an explicit "send
            # everything now" — presence no longer suppresses either channel (the user
            # asked for the held pushes to go out).
            if (
                not force
                and rung.channel
                in (NotificationChannel.DISCORD.value, NotificationChannel.NTFY.value)
                and delivery.notification.web_preemptable
                and self._is_present(when)
            ):
                rung.fired = True
                continue
            # Quiet hours (FR-NOTIF-5): defer NORMAL hops to the next allowed hour;
            # IMMEDIATE/CRITICAL always fire. (Email/Discord deferral; in-app always
            # surfaces.) #302: a per-channel preference can exempt a channel so it
            # still delivers overnight ("hold Discord, let email through"). A force
            # flush (deliver-now) bypasses the quiet gate entirely.
            if not force and self._channel_quiet_deferred(
                rung.channel, delivery.notification, when
            ):
                continue
            # #234: isolate per-channel failures so one bad channel (e.g. Discord
            # webhook unreachable, SMTP misconfigured) never crashes the whole scheduler
            # tick or prevents the remaining ladder rungs from firing. A delivery error
            # is logged and the rung is left UN-fired (#45): each rung's ``due_at`` is
            # fixed at build time and is independent of the other rungs (this loop does
            # not gate a later hop on an earlier one having fired), so leaving a failed
            # rung un-fired simply means the NEXT ``advance()`` tick re-scans it (still
            # ``due_at <= ts`` and ``not fired``) and retries the same dispatch — it
            # cannot wedge the ladder or block a sibling rung from firing on schedule.
            # Marking it fired anyway (the prior behavior) recorded a channel that never
            # actually delivered as "sent" (``sent_channels``/``ladder_status``), so a
            # dead Discord webhook or SMTP outage silently dropped an "agent stuck"
            # alert with no retry and no visible failure.
            try:
                self._dispatch(rung.channel, delivery.notification)
            except Exception as exc:
                log.error(
                    "notification_channel_failed",
                    channel=rung.channel,
                    dedup_key=delivery.notification.dedup_key,
                    error=str(exc),
                )
                continue
            rung.fired = True
            delivery.sent_channels.append(rung.channel)
            fired.append(rung.channel)
        return fired

    def expire(self, dedup_key: str) -> None:
        """Idempotency: acting on one channel expires the others (FR-NOTIF-3).

        Also drops any in-app inbox entries that announced this decision so an
        action-required notification stops persisting once its underlying action
        is resolved (the notification center never double-tracks acted items).
        """
        # #235: lock around _sent mutation to prevent the API expire path from racing
        # the scheduler advance path (which reads _sent on a different thread).
        with self._sent_lock:
            delivery = self._sent.get(dedup_key)
            if delivery is not None:
                delivery.active = False
                for rung in delivery.rungs:
                    rung.fired = True  # cancel any not-yet-fired hops
                self._sent.pop(dedup_key, None)
        if dedup_key:
            self._inbox = [e for e in self._inbox if e.dedup_key != dedup_key]

    # --- in-app sink / presence (FR-UI-3 feed, FR-NOTIF-2) ----------------
    def inbox(self) -> list[CapturedSend]:
        """In-app notifications surfaced in the portal (drains nothing)."""
        return list(self._inbox)

    def list_inbox(self, *, include_seen: bool = False) -> list[CapturedSend]:
        """Current in-app notifications for the notification center.

        Prunes age-expired entries first (so a stale poll never shows day-old
        items), then returns the inbox newest-first, omitting ones the user has
        dismissed unless ``include_seen`` is set.
        """
        self._prune_old(self._inbox, self._clock(), exempt_unseen=True)
        entries = [
            replace(e, seen=e.id in self._dismissed)
            for e in self._inbox
            if include_seen or e.id not in self._dismissed
        ]
        return list(reversed(entries))

    def mark_seen(self, inbox_id: str) -> bool:
        """Dismiss one informational in-app notification by id.

        Returns True if the id matched a current inbox entry. Action-required
        entries are cleared via :meth:`expire` when their pending action resolves,
        not here, so dismissing one does not hide a still-open action.
        """
        for entry in self._inbox:
            if entry.id == inbox_id:
                self._dismissed.add(inbox_id)
                return True
        return False

    def _is_present(self, when: datetime) -> bool:
        """True when the user is verifiably present in the web UI (FR-NOTIF-2).

        Either an injected presence provider reports presence, or a recent
        ``set_presence(True)`` heartbeat is still within its freshness window — so a
        stale, one-shot signal can never keep suppressing Discord (the window decays).
        """
        if self._presence is not None and self._presence():
            return True
        return self._present_until is not None and when <= self._present_until

    def set_presence(self, present: bool) -> None:
        """Record a web-presence heartbeat from the front-door (FR-NOTIF-2).

        ``True`` opens a short freshness window (``_PRESENCE_TTL_SECONDS``); the
        client re-signals while the tab stays focused + active, so presence persists
        only as long as the user is really there. ``False`` (tab blurred / hidden)
        clears it immediately so the Discord escalation resumes at once.
        """
        if present:
            self._present_until = self._clock() + timedelta(seconds=_PRESENCE_TTL_SECONDS)
        else:
            self._present_until = None

    # --- test/contract helpers -------------------------------------------
    def is_active(self, dedup_key: str) -> bool:
        with self._sent_lock:
            return dedup_key in self._sent

    def sent_channels(self, dedup_key: str) -> list[str]:
        with self._sent_lock:
            delivery = self._sent.get(dedup_key)
            return list(delivery.sent_channels) if delivery else []

    def pending_escalations(self, dedup_key: str) -> list[str]:
        """Ladder rungs not yet fired (the next hops the scheduler will fire)."""
        with self._sent_lock:
            delivery = self._sent.get(dedup_key)
            if not delivery:
                return []
            return [r.channel for r in delivery.rungs if not r.fired]

    def captured(self) -> list[CapturedSend]:
        """Every offline-captured dispatch (introspection for tests)."""
        return list(self._captured)
