"""Phase 2 ``notif`` push seam (realtime-websocket.md).

Notifications + pending-actions fan a downstream ``notif`` frame over the realtime
registry so the front-door retires its Portal/bell poll (keeping the poll as the
fallback). These are the ENGINE-side tests:

* the registry broadcasts a ``notif`` frame to every live session;
* a created notification and a created/resolved pending-action each publish a
  ``notif`` frame at the SERVICE seam (so every path fans out, not one router);
* the ``notif`` channel stays **upstream-denied** — a crafted upstream frame on it
  can never drive a submit/approve (BE→FE surfacing only, no stop-boundary bypass).
"""

from __future__ import annotations

import asyncio

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.realtime.registry import RealtimeRegistry
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.core.ids import CampaignId, new_id
from applicant.core.realtime.envelope import authorize_upstream, parse_frame
from applicant.ports.driven.notification import Notification

# --- registry broadcast ------------------------------------------------------


def _drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_publish_all_fans_a_notif_frame_to_every_live_session():
    reg = RealtimeRegistry()
    # Two live sessions (e.g. two owner devices / a reconnect) each with a subscriber.
    s1 = reg.get_or_create("owner-a")
    s2 = reg.get_or_create("owner-b")
    q1 = s1.attach()
    q2 = s2.attach()
    reg.publish_all("notif", "pending", {"event": "created"})
    f1 = _drain(q1)
    f2 = _drain(q2)
    assert f1 and f1[0] == {"chan": "notif", "type": "pending", "seq": 0, "data": {"event": "created"}}
    assert f2 and f2[0]["chan"] == "notif" and f2[0]["data"] == {"event": "created"}


async def test_publish_all_is_a_safe_noop_when_no_session_is_connected():
    reg = RealtimeRegistry()
    # No bridge connected yet — the frame is simply dropped (the FE refetches on
    # connect / the poll fallback covers it). Must not raise.
    reg.publish_all("notif", "notification", {"urgency": "immediate"})


# --- notification service seam ----------------------------------------------


class _SpyNotifier:
    def notify(self, n):
        return "handle"

    def expire(self, k):
        pass


def test_creating_a_notification_publishes_a_notif_frame():
    published: list[tuple[str, dict]] = []
    svc = NotificationService(
        _SpyNotifier(), realtime=lambda mtype, data: published.append((mtype, data))
    )
    svc.notify_decision("app-1", title="Approve?", body="Ready for your review.")
    assert len(published) == 1
    mtype, data = published[0]
    assert mtype == "notification"
    # It carries the created notification's dedup key, never a raw action verb.
    assert data.get("dedup_key") == "decision:app-1"


def test_notification_service_without_realtime_is_unchanged():
    # No publisher injected (legacy construction / unit tests) ⇒ raw notifier, no push.
    svc = NotificationService(_SpyNotifier())
    assert svc.notify_error(title="x", body="y") == "handle"


def test_error_notification_also_fans_out():
    published: list[tuple[str, dict]] = []
    svc = NotificationService(
        _SpyNotifier(), realtime=lambda mtype, data: published.append((mtype, data))
    )
    svc.notify_error(title="Something broke", body="Details")
    assert [m for m, _ in published] == ["notification"]


def test_realtime_proxy_delegates_other_port_methods():
    # The publishing proxy is transparent for non-notify port methods (expire, etc.).
    expired: list[str] = []

    class _N:
        def notify(self, n):
            return "h"

        def expire(self, k):
            expired.append(k)

    svc = NotificationService(_N(), realtime=lambda *_: None)
    svc.acted("app-9")  # routes through the proxy to the inner notifier's expire()
    assert expired == ["decision:app-9"]


# --- pending-actions service seam -------------------------------------------


def test_creating_a_pending_action_publishes_a_notif_frame():
    published: list[tuple[str, dict]] = []
    storage = InMemoryStorage()
    pas = PendingActionsService(
        storage, realtime=lambda mtype, data: published.append((mtype, data))
    )
    cid = CampaignId(new_id())
    pas.agent_question(cid, "Which location do you prefer?")
    assert published == [("pending", {"event": "created"})]


def test_resolving_a_pending_action_publishes_a_notif_frame():
    published: list[tuple[str, dict]] = []
    storage = InMemoryStorage()
    pas = PendingActionsService(
        storage, realtime=lambda mtype, data: published.append((mtype, data))
    )
    cid = CampaignId(new_id())
    action = pas.agent_question(cid, "Confirm salary floor?")
    published.clear()
    pas.resolve(action.id)
    assert published == [("pending", {"event": "resolved"})]


def test_resolving_an_already_resolved_action_does_not_publish():
    published: list[tuple[str, dict]] = []
    storage = InMemoryStorage()
    pas = PendingActionsService(
        storage, realtime=lambda mtype, data: published.append((mtype, data))
    )
    cid = CampaignId(new_id())
    action = pas.agent_question(cid, "q")
    pas.resolve(action.id)
    published.clear()
    pas.resolve(action.id)  # already resolved — a no-op transition
    assert published == []


def test_pending_actions_without_realtime_is_unchanged():
    storage = InMemoryStorage()
    pas = PendingActionsService(storage)
    cid = CampaignId(new_id())
    action = pas.agent_question(cid, "q")  # must not raise without a publisher
    assert action.kind == "agent_question"


# --- safety: notif is BE→FE only, never an upstream action verb --------------


def test_notif_channel_rejects_every_upstream_command():
    # A crafted upstream frame on the notif channel can NEVER authorize a
    # consequential action — the socket is surfacing-only and cannot bypass the
    # review-before-submit stop-boundary.
    for verb in ("approve", "submit", "steer", "input", "pending", "notification", "resolve"):
        decision = authorize_upstream("notif", verb)
        assert decision.allowed is False, f"notif/{verb} must be upstream-denied"


async def test_apply_upstream_notif_frame_mutates_nothing():
    from applicant.app.realtime.registry import RealtimeSession

    s = RealtimeSession("s1")
    q = s.attach()
    decision = s.apply_upstream(parse_frame({"chan": "notif", "type": "approve", "data": {}}))
    assert decision.allowed is False
    # A denied upstream command publishes NOTHING downstream — the socket never acted.
    assert _drain(q) == []


def test_notification_dataclass_smoke():
    # Guard against an import-time regression in the port used by the seam above.
    n = Notification(title="t", body="b")
    assert n.title == "t"
