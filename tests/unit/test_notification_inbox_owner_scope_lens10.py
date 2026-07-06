"""Regression coverage for dark-engine audit lens 10 #28 (engine side).

``NotificationService.list_inbox``/``dismiss_notification`` gained an optional
``owner`` keyword, threaded straight to the configured notifier so an
owner-aware notifier can scope the in-app inbox to a caller's identity. Every
notifier shipped in this tree today is single-tenant per deployment (every
entry belongs to the one engine owner), so this is defense-in-depth wiring,
NOT the authorization boundary itself — the actual multi-user boundary for the
front-door lives in the workspace's own proxy (``applicant_portal_routes.py``,
see ``workspace/tests/test_applicant_inbox_owner_scope_lens10.py``), which must
resolve the caller to the engine-owner account before ever reaching this
service.

This file pins down two properties:

* the default (no ``owner`` argument) call is byte-for-byte unchanged, so
  every existing caller/notifier keeps working exactly as before;
* ``owner`` is forwarded when the notifier accepts it, and gracefully dropped
  (no crash) when it doesn't -- so today's single-tenant notifiers are
  completely unaffected by the new parameter.

Hand-verified RED-on-revert / GREEN-on-restore: reverting
``notification_service.py``'s ``list_inbox``/``dismiss_notification`` back to
their pre-fix signatures (no ``owner`` kwarg) makes
``test_list_inbox_forwards_owner_to_an_owner_aware_notifier`` and
``test_dismiss_notification_forwards_owner_to_an_owner_aware_notifier`` (and
the "degrades gracefully" pair) fail with a ``TypeError: unexpected keyword
argument 'owner'``; restoring the fix turns them green again.
"""

from __future__ import annotations

from applicant.application.services.notification_service import NotificationService


class _LegacyNotifier:
    """Mirrors AppriseNotifier's current (pre-fix, owner-unaware) signature."""

    def __init__(self) -> None:
        self.calls: list = []

    def list_inbox(self, *, include_seen: bool = False):
        self.calls.append(("list_inbox", include_seen))
        return ["entry-a", "entry-b"]

    def mark_seen(self, inbox_id: str):
        self.calls.append(("mark_seen", inbox_id))
        return inbox_id != "missing"


class _OwnerAwareNotifier:
    """A hypothetical future notifier that DOES tag entries by owner."""

    def __init__(self) -> None:
        self.calls: list = []

    def list_inbox(self, *, include_seen: bool = False, owner: str | None = None):
        self.calls.append(("list_inbox", include_seen, owner))
        if owner == "intruder":
            return []
        return ["entry-a"]

    def mark_seen(self, inbox_id: str, owner: str | None = None):
        self.calls.append(("mark_seen", inbox_id, owner))
        return owner != "intruder"


# --- default call is byte-for-byte unchanged --------------------------------


def test_list_inbox_default_call_unchanged_for_legacy_notifier():
    notifier = _LegacyNotifier()
    svc = NotificationService(notifier)
    assert svc.list_inbox() == ["entry-a", "entry-b"]
    assert notifier.calls == [("list_inbox", False)]


def test_dismiss_notification_default_call_unchanged_for_legacy_notifier():
    notifier = _LegacyNotifier()
    svc = NotificationService(notifier)
    assert svc.dismiss_notification("n1") is True
    assert notifier.calls == [("mark_seen", "n1")]


# --- graceful degrade against today's single-tenant notifiers ---------------


def test_list_inbox_degrades_gracefully_when_notifier_rejects_owner_kwarg():
    notifier = _LegacyNotifier()
    svc = NotificationService(notifier)
    # An owner IS supplied, but the legacy (single-tenant) notifier doesn't
    # accept it -- must not raise, must fall back to the unscoped call.
    assert svc.list_inbox(owner="alice") == ["entry-a", "entry-b"]


def test_dismiss_notification_degrades_gracefully_when_notifier_rejects_owner_kwarg():
    notifier = _LegacyNotifier()
    svc = NotificationService(notifier)
    assert svc.dismiss_notification("n1", owner="alice") is True


# --- forwarded when the notifier DOES support it ----------------------------


def test_list_inbox_forwards_owner_to_an_owner_aware_notifier():
    notifier = _OwnerAwareNotifier()
    svc = NotificationService(notifier)
    assert svc.list_inbox(owner="alice") == ["entry-a"]
    assert svc.list_inbox(owner="intruder") == []
    assert ("list_inbox", False, "alice") in notifier.calls
    assert ("list_inbox", False, "intruder") in notifier.calls


def test_dismiss_notification_forwards_owner_to_an_owner_aware_notifier():
    notifier = _OwnerAwareNotifier()
    svc = NotificationService(notifier)
    assert svc.dismiss_notification("n1", owner="alice") is True
    assert svc.dismiss_notification("n1", owner="intruder") is False


# --- no in-app sink at all: degrades to empty/False, never crashes ---------


def test_list_inbox_with_no_inbox_support_returns_empty():
    class _NoInbox:
        pass

    svc = NotificationService(_NoInbox())
    assert svc.list_inbox(owner="alice") == []


def test_dismiss_notification_with_no_inbox_support_returns_false():
    class _NoInbox:
        pass

    svc = NotificationService(_NoInbox())
    assert svc.dismiss_notification("n1", owner="alice") is False
