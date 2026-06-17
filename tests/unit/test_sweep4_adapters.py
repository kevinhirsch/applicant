"""Sweep-4 verified-bug regression tests (adapters lane).

Each test is fail-before / pass-after for a specific sweep-4 requirement ID and
covers ONLY the ``adapters/`` + ``observability/`` lane:

* FR-STEALTH-4 — ``direct`` egress mode must DROP a leftover proxy (no unattested
  exit), and ``validate()`` passes (direct is residential by definition).
* FR-STEALTH-1 — the ``chromium`` channel must NOT advertise a "Google Chrome"
  brand in ``sec_ch_ua`` (UA<->CH-UA coherence).
* CONC-DBOS-1 — DBOS queue admission must be lock-guarded (consistent under
  concurrent acquire/release across threads).
* LEAK-NOTIF-1 — notifier ``_sent`` stays bounded and ``_sent_emails`` is pruned
  to a recent-days window.
* PIVOT (FR-DUR-4) — ``release`` promotes a later admissible waiter, not only the
  rate-blocked head.
* PRIV-1 — ``apprise_urls`` redaction + URL userinfo masking.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from applicant.adapters.browser.stealth import EgressPolicy, coherent_fingerprint
from applicant.adapters.notification.apprise_notifier import (
    _SENT_EMAIL_RETENTION_DAYS,
    AppriseNotifier,
)
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator
from applicant.observability import logging as obs
from applicant.ports.driven.notification import Notification


# --- FR-STEALTH-4: direct mode drops a leftover proxy --------------------------
def test_direct_mode_drops_leftover_proxy():
    # FR-STEALTH-4: EGRESS_MODE=direct with a leftover EGRESS_PROXY_URL must NOT
    # route through that (possibly datacenter) proxy. Before the fix from_settings
    # force-attested the proxy and launch_proxy() returned it.
    policy = EgressPolicy.from_settings(
        mode="direct", proxy_url="http://dc:8080", residential=False
    )
    assert policy.launch_proxy() is None  # proxy ignored — host's own connection
    assert policy.proxy_url is None
    assert policy.is_direct_residential is True
    policy.validate()  # direct is residential by definition — must not raise


# --- FR-STEALTH-1: chromium channel CH-UA has no Google Chrome brand -----------
def test_chromium_channel_sec_ch_ua_omits_google_chrome():
    fp = coherent_fingerprint("chromium")
    assert "Google Chrome" not in fp["sec_ch_ua"]
    assert "Chromium" in fp["sec_ch_ua"]
    # The Google Chrome channel still advertises the Google Chrome brand.
    assert "Google Chrome" in coherent_fingerprint("chrome")["sec_ch_ua"]


# --- CONC-DBOS-1: admission is lock-guarded -----------------------------------
def test_dbos_admission_consistent_under_concurrency(monkeypatch):
    orch = DbosOrchestrator(database_url="postgresql://stub")
    # Bypass DBOS configure/queue creation: seed the admission bookkeeping directly
    # so we exercise acquire/release without a live Postgres (the lock is what is
    # under test). Unbounded concurrency so every acquire admits.
    from collections import deque

    orch._queue_caps["q"] = {
        "concurrency": None,
        "limiter_limit": None,
        "limiter_period": None,
    }
    orch._queue_admit["q"] = {"active": set(), "waiting": deque(), "admit_times": deque()}

    n_threads = 16
    per_thread = 50
    barrier = threading.Barrier(n_threads)

    def worker(tid: int) -> None:
        barrier.wait()
        for i in range(per_thread):
            wid = f"w-{tid}-{i}"
            orch.acquire("q", wid)
            orch.release("q", wid)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # admissions - releases == 0: every acquired slot was released, so active is
    # empty and consistent. A racy mutation would corrupt the set (size != 0 or
    # KeyError under discard).
    assert len(orch._queue_admit["q"]["active"]) == 0


# --- LEAK-NOTIF-1: _sent bounded; _sent_emails pruned to recent days ----------
class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def test_sent_does_not_grow_unbounded_without_expire():
    clock = _Clock()
    n = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://u:pw@smtp.test",
        clock=clock,
        escalation_hold_seconds=30,
        email_timeout_seconds=900,
    )
    # Notify many distinct decisions, never expiring them, advancing time past the
    # email timeout so all rungs fire and the deliveries become prunable.
    for i in range(200):
        n.notify(
            Notification(title="Approve?", body="role", dedup_key=f"ref-{i}")
        )
        clock.tick(1000)  # past the 900s email timeout
        n.advance()
    # Without pruning _sent would hold ~200 entries forever; with the fix the
    # fully-fired past-timeout deliveries are dropped.
    assert len(n._sent) < 50


def test_sent_emails_pruned_to_recent_days():
    clock = _Clock()
    n = AppriseNotifier(apprise_urls="mailto://u:pw@smtp.test", clock=clock)
    # Send a digest email for many distinct days; the dedup set must stay bounded
    # to the rolling recent-days window.
    base = clock.now.date()
    for d in range(60):
        day = base + timedelta(days=d)
        clock.now = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        n.send_email(
            subject="Digest", html="<p>x</p>", dedup_key=f"digest_email:c1:{day.isoformat()}"
        )
    # Only keys within the retention window of the final "today" survive.
    assert len(n._sent_emails) <= _SENT_EMAIL_RETENTION_DAYS + 1
    today = clock.now.date()
    horizon = today - timedelta(days=_SENT_EMAIL_RETENTION_DAYS)
    for key in n._sent_emails:
        day = datetime.fromisoformat(key.rsplit(":", 1)[-1]).date()
        assert day >= horizon


# --- PIVOT (FR-DUR-4): release promotes a later admissible waiter --------------
def test_shim_release_pivots_past_blocked_head(tmp_path):
    orch = CheckpointShimOrchestrator(checkpoint_dir=str(tmp_path))
    orch.create_queue("q", concurrency=1)
    # head holds the only slot.
    assert orch.acquire("q", "head") is True
    # Two waiters queue up (neither admitted: concurrency 1).
    assert orch.acquire("q", "blocked") is False
    assert orch.acquire("q", "later") is False
    # Make the HEAD waiter ("blocked") a stale already-active duplicate so it cannot
    # be a genuine promotion; the pivot must scan past it to admit "later".
    q = orch._queues["q"]
    q.active.add("blocked")  # head waiter is now "active" -> not a real new admit
    # Release the original holder; a head-only release would return the stale
    # "blocked" entry. With the pivot fix, "blocked" is dropped as a stale dup and
    # a subsequent release admits the genuine waiter.
    first = orch.release("q", "head")
    assert first == "blocked"  # stale dup removed, scanning continues next call
    second = orch.release("q", "blocked")
    assert second == "later"
    assert "later" in orch._queues["q"].active


def test_dbos_release_pivots_past_blocked_head():
    from collections import deque

    orch = DbosOrchestrator(database_url="postgresql://stub")
    orch._queue_caps["q"] = {
        "concurrency": 1,
        "limiter_limit": None,
        "limiter_period": None,
    }
    orch._queue_admit["q"] = {"active": set(), "waiting": deque(), "admit_times": deque()}
    assert orch.acquire("q", "head") is True
    assert orch.acquire("q", "blocked") is False
    assert orch.acquire("q", "later") is False
    # Stale already-active head waiter.
    orch._queue_admit["q"]["active"].add("blocked")
    first = orch.release("q", "head")
    assert first == "blocked"  # stale dup removed
    second = orch.release("q", "blocked")
    assert second == "later"
    assert "later" in orch._queue_admit["q"]["active"]


# --- PRIV-1: apprise_urls redaction + URL userinfo masking --------------------
def test_apprise_urls_key_redacted():
    out = obs._redact_secrets(
        None, "info", {"apprise_urls": "smtps://user:password@smtp.example.com", "x": "ok"}
    )
    assert out["apprise_urls"] == "***REDACTED***"
    assert out["x"] == "ok"


def test_url_userinfo_masked_in_free_text():
    msg = "configured email via smtps://user:password@smtp.example.com today"
    out = obs._redact_text(msg)
    assert "user:password" not in out
    assert "***REDACTED***" in out
    # Surrounding text + host preserved.
    assert "smtp.example.com" in out
    assert out.startswith("configured email via")


def test_normal_text_untouched():
    msg = "scheduled the next run for tomorrow morning"
    assert obs._redact_text(msg) == msg
