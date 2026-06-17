"""Awareness loop service (Phase 2, part 2) — owner-scoped, flag-gated.

``decide_tick`` is a pure orchestration over ``engine`` (fully unit-tested).
``AwarenessService`` is the thin DB-backed layer: trigger CRUD, notification
records + outcomes, and an async ``run_tick`` that the (default-off) background
loop calls. Nothing here runs unless ``FIREHOUSE_AWARENESS`` is enabled and the
owner has the ``can_use_awareness`` privilege with ≥1 enabled trigger.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from core.database import SessionLocal
from core.proactive_models import AwarenessTrigger, AwarenessNotification
from services.awareness.engine import decide_tick, update_belief, is_noisy

logger = logging.getLogger(__name__)


def _trigger_dict(t: AwarenessTrigger) -> Dict[str, Any]:
    return {
        "id": t.id,
        "owner": t.owner,
        "name": t.name,
        "description": t.description,
        "condition": t.condition,
        "channel": t.channel,
        "enabled": t.enabled,
        "risk_tier": t.risk_tier,
        "cooldown_seconds": t.cooldown_seconds,
        "last_fired_at": t.last_fired_at,
        "salience_threshold": t.salience_threshold,
    }


def _notif_dict(n: AwarenessNotification) -> Dict[str, Any]:
    return {
        "id": n.id,
        "trigger_id": n.trigger_id,
        "title": n.title,
        "body": n.body,
        "channel": n.channel,
        "status": n.status,
        "outcome": n.outcome,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _owned(query, model, owner: Optional[str]):
    if not owner:
        return query
    return query.filter((model.owner == owner) | (model.owner.is_(None)))


class AwarenessService:
    """DB-backed trigger CRUD + notification records + a single tick."""

    # ----- trigger CRUD -------------------------------------------------
    def list_triggers(self, owner: Optional[str], enabled_only: bool = False) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            q = _owned(db.query(AwarenessTrigger), AwarenessTrigger, owner)
            if enabled_only:
                q = q.filter(AwarenessTrigger.enabled.is_(True))
            return [_trigger_dict(t) for t in q.order_by(AwarenessTrigger.updated_at.desc()).all()]
        finally:
            db.close()

    def create_trigger(self, owner: Optional[str], name: str, condition: Optional[dict] = None,
                       description: str = "", channel: str = "ntfy", cooldown_seconds: int = 0,
                       risk_tier: str = "low", enabled: bool = True) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            t = AwarenessTrigger(id=str(uuid.uuid4()), owner=owner, name=name or "Untitled Trigger",
                                 description=description, condition=condition, channel=channel,
                                 enabled=enabled, risk_tier=risk_tier, cooldown_seconds=cooldown_seconds)
            db.add(t)
            db.commit()
            db.refresh(t)
            return _trigger_dict(t)
        finally:
            db.close()

    def update_trigger(self, owner: Optional[str], trigger_id: str, **fields) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            t = _owned(db.query(AwarenessTrigger).filter(AwarenessTrigger.id == trigger_id),
                       AwarenessTrigger, owner).first()
            if not t:
                return None
            for k in ("name", "description", "condition", "channel", "enabled",
                      "risk_tier", "cooldown_seconds", "salience_threshold"):
                if k in fields and fields[k] is not None:
                    setattr(t, k, fields[k])
            db.commit()
            db.refresh(t)
            return _trigger_dict(t)
        finally:
            db.close()

    def delete_trigger(self, owner: Optional[str], trigger_id: str) -> bool:
        db = SessionLocal()
        try:
            t = _owned(db.query(AwarenessTrigger).filter(AwarenessTrigger.id == trigger_id),
                       AwarenessTrigger, owner).first()
            if not t:
                return False
            db.delete(t)
            db.commit()
            return True
        finally:
            db.close()

    # ----- notifications + outcomes ------------------------------------
    def list_notifications(self, owner: Optional[str], limit: int = 50) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            q = _owned(db.query(AwarenessNotification), AwarenessNotification, owner)
            rows = q.order_by(AwarenessNotification.created_at.desc()).limit(limit).all()
            return [_notif_dict(n) for n in rows]
        finally:
            db.close()

    def record_outcome(self, owner: Optional[str], notif_id: str, outcome: str) -> bool:
        """Record a notification outcome and fold it into the trigger's belief.

        ``useful``/``acted`` reinforce the trigger; ``dismissed`` erodes it.
        Once a trigger is persistently ignored (``is_noisy``) it auto-pauses, so
        proactivity self-corrects instead of nagging.
        """
        db = SessionLocal()
        try:
            n = _owned(db.query(AwarenessNotification).filter(AwarenessNotification.id == notif_id),
                       AwarenessNotification, owner).first()
            if not n:
                return False
            n.outcome = outcome
            trig = None
            if n.trigger_id:
                trig = db.query(AwarenessTrigger).filter(AwarenessTrigger.id == n.trigger_id).first()
            if trig is not None:
                trig.alpha, trig.beta = update_belief(trig.alpha, trig.beta, outcome)
                if is_noisy(trig.alpha, trig.beta):
                    trig.enabled = False
                    logger.info("Auto-paused noisy awareness trigger %s (usefulness too low)", trig.id)
            db.commit()
            return True
        finally:
            db.close()

    def _count_notifications_since(self, owner: Optional[str], since: datetime) -> int:
        db = SessionLocal()
        try:
            return _owned(db.query(AwarenessNotification), AwarenessNotification, owner).filter(
                AwarenessNotification.created_at >= since,
                AwarenessNotification.status == "sent",
            ).count()
        finally:
            db.close()

    def _touch_last_fired(self, trigger_id: str, when: datetime) -> None:
        db = SessionLocal()
        try:
            t = db.query(AwarenessTrigger).filter(AwarenessTrigger.id == trigger_id).first()
            if t:
                t.last_fired_at = when
                db.commit()
        finally:
            db.close()

    def _record_notification(self, owner, trigger_id, title, body, channel, status) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            n = AwarenessNotification(id=str(uuid.uuid4()), owner=owner, trigger_id=trigger_id,
                                      title=title, body=body, channel=channel, status=status)
            db.add(n)
            db.commit()
            db.refresh(n)
            return _notif_dict(n)
        finally:
            db.close()

    # ----- the tick -----------------------------------------------------
    async def run_tick(self, owner: Optional[str], *, collect: Optional[Callable] = None,
                       judge: Optional[Callable] = None, notify: Optional[Callable] = None,
                       daily_limit: int = 0, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Run one awareness tick for ``owner``. Returns a small summary.

        ``collect(owner) -> dict`` builds the signal snapshot; ``notify(title,
        body, note_id, owner)`` dispatches (defaults to the reminder channel
        dispatcher). Both are injectable so the orchestration is testable.
        """
        now = now or datetime.utcnow()
        collect = collect or collect_signals
        if notify is None:
            from routes.note_routes import dispatch_reminder as notify  # lazy: avoid import cycle

        triggers = self.list_triggers(owner, enabled_only=True)
        if not triggers:
            return {"fired": [], "skipped": "no enabled triggers"}

        try:
            snapshot = collect(owner) or {}
        except Exception as ex:  # collectors are best-effort; never crash the loop
            logger.warning("awareness collect failed for %s: %s", owner, ex)
            snapshot = {}

        sent_today = self._count_notifications_since(owner, now - timedelta(days=1))
        fires = decide_tick(triggers, snapshot, now, sent_today, daily_limit, judge=judge)

        fired_ids: List[str] = []
        for t in fires:
            title = t.get("name") or "Heads up"
            body = _render_body(t, snapshot)
            status = "sent"
            try:
                await notify(title, body, str(t["id"]), owner)
            except Exception as ex:
                logger.warning("awareness notify failed: %s", ex)
                status = "failed"
            self._record_notification(owner, t["id"], title, body, t.get("channel"), status)
            self._touch_last_fired(t["id"], now)
            if status == "sent":
                fired_ids.append(t["id"])
        return {"fired": fired_ids, "snapshot_fields": sorted(snapshot.keys())}


def _render_body(trigger: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    """Default body text for a fired trigger (overridable later via templates)."""
    desc = (trigger.get("description") or "").strip()
    return desc or f"Awareness trigger '{trigger.get('name')}' fired."


def collect_signals(owner: Optional[str]) -> Dict[str, Any]:
    """Best-effort signal snapshot fed to trigger conditions.

    Each source is guarded so a failure in one never blocks the others. Phase 3
    adds the calendar source (next-event timing, today's/next-24h counts);
    further sources (unread email, due reminders) can be appended the same way.
    """
    now = datetime.utcnow()
    snap: Dict[str, Any] = {}

    # Calendar: derive next-event timing + counts from upcoming events.
    try:
        from core.database import get_upcoming_events
        from services.awareness import calendar_intel
        events = get_upcoming_events(owner, horizon_days=2, limit=40) or []
        snap.update(calendar_intel.build_snapshot(events, now))
    except Exception as ex:
        logger.debug("awareness calendar collector skipped: %s", ex)

    return snap
