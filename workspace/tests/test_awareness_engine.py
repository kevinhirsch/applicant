"""Pure awareness-engine logic (Phase 2). No app deps — runs everywhere."""

from datetime import datetime, timedelta

from services.awareness import engine as e


# ---- evaluate_condition ----------------------------------------------------

def test_field_comparisons():
    snap = {"next_event_minutes": 25, "unread": 0, "summary": "Standup"}
    assert e.evaluate_condition({"field": "next_event_minutes", "op": "lte", "value": 30}, snap) == e.FIRE
    assert e.evaluate_condition({"field": "next_event_minutes", "op": "gt", "value": 30}, snap) == e.SKIP
    assert e.evaluate_condition({"field": "summary", "op": "exists"}, snap) == e.FIRE
    assert e.evaluate_condition({"field": "missing", "op": "exists"}, snap) == e.SKIP
    assert e.evaluate_condition({"field": "summary", "op": "contains", "value": "Stand"}, snap) == e.FIRE


def test_all_and_any():
    snap = {"a": 5, "b": 1}
    assert e.evaluate_condition({"all": [
        {"field": "a", "op": "gte", "value": 5},
        {"field": "b", "op": "eq", "value": 1},
    ]}, snap) == e.FIRE
    assert e.evaluate_condition({"all": [
        {"field": "a", "op": "gte", "value": 5},
        {"field": "b", "op": "eq", "value": 99},
    ]}, snap) == e.SKIP
    assert e.evaluate_condition({"any": [
        {"field": "a", "op": "eq", "value": 0},
        {"field": "b", "op": "eq", "value": 1},
    ]}, snap) == e.FIRE


def test_fuzzy_and_empty_need_llm():
    assert e.evaluate_condition(None, {}) == e.NEEDS_LLM
    assert e.evaluate_condition({}, {}) == e.NEEDS_LLM
    assert e.evaluate_condition({"fuzzy": "anything urgent?"}, {}) == e.NEEDS_LLM
    # unknown operator can't be decided by rules
    assert e.evaluate_condition({"field": "a", "op": "weird", "value": 1}, {"a": 1}) == e.NEEDS_LLM


def test_all_with_llm_branch_escalates_not_skips():
    snap = {"a": 5}
    v = e.evaluate_condition({"all": [
        {"field": "a", "op": "gte", "value": 5},  # FIRE
        {"fuzzy": "and is it important?"},          # NEEDS_LLM
    ]}, snap)
    assert v == e.NEEDS_LLM


def test_type_mismatch_is_skip_not_crash():
    # comparing a string field to a number must not raise
    assert e.evaluate_condition({"field": "s", "op": "gt", "value": 3}, {"s": "x"}) == e.SKIP
    assert e.evaluate_condition({"field": "s", "op": "lt", "value": 3}, {"s": None}) == e.SKIP


# ---- cooldown / rate-limit -------------------------------------------------

def test_cooldown():
    now = datetime(2026, 6, 2, 12, 0, 0)
    assert e.cooldown_ok(None, 3600, now) is True            # never fired
    assert e.cooldown_ok(now - timedelta(minutes=30), 0, now) is True   # no cooldown set
    assert e.cooldown_ok(now - timedelta(minutes=30), 3600, now) is False
    assert e.cooldown_ok(now - timedelta(minutes=90), 3600, now) is True


def test_rate_limit():
    assert e.rate_limit_ok(0, 0) is True       # 0 = unlimited
    assert e.rate_limit_ok(99, 0) is True
    assert e.rate_limit_ok(2, 5) is True
    assert e.rate_limit_ok(5, 5) is False
    assert e.rate_limit_ok(6, 5) is False


# ---- change detection ------------------------------------------------------

def test_digest_is_stable_and_order_independent():
    a = {"x": 1, "y": [1, 2], "z": "hi"}
    b = {"z": "hi", "y": [1, 2], "x": 1}
    assert e.snapshot_digest(a) == e.snapshot_digest(b)


def test_digest_changes_with_content():
    assert e.snapshot_digest({"x": 1}) != e.snapshot_digest({"x": 2})


def test_digest_handles_datetimes():
    # default=str keeps non-JSON values from blowing up
    d = e.snapshot_digest({"when": datetime(2026, 6, 2)})
    assert isinstance(d, str) and len(d) == 64


def test_should_resynthesize():
    assert e.should_resynthesize(None, "abc") is True
    assert e.should_resynthesize("abc", "abc") is False
    assert e.should_resynthesize("abc", "xyz") is True


# ---- decide_tick (pure orchestration) --------------------------------------

_NOW = datetime(2026, 6, 2, 12, 0, 0)


def _trig(id, cond, **kw):
    base = {"id": id, "condition": cond, "enabled": True, "cooldown_seconds": 0,
            "last_fired_at": None, "name": id}
    base.update(kw)
    return base


def test_decide_fires_matching_rule_trigger():
    trigs = [_trig("t1", {"field": "next_event_minutes", "op": "lte", "value": 30})]
    snap = {"next_event_minutes": 20}
    fired = e.decide_tick(trigs, snap, _NOW, sent_in_window=0, rate_limit=0)
    assert [t["id"] for t in fired] == ["t1"]


def test_decide_skips_disabled_and_cooled_down():
    trigs = [
        _trig("disabled", {"field": "a", "op": "exists"}, enabled=False),
        _trig("cooling", {"field": "a", "op": "exists"},
              cooldown_seconds=3600, last_fired_at=_NOW - timedelta(minutes=30)),
        _trig("ok", {"field": "a", "op": "exists"}),
    ]
    fired = e.decide_tick(trigs, {"a": 1}, _NOW, 0, 0)
    assert [t["id"] for t in fired] == ["ok"]


def test_decide_rate_limit_caps_fires():
    trigs = [_trig(f"t{i}", {"field": "a", "op": "exists"}) for i in range(5)]
    fired = e.decide_tick(trigs, {"a": 1}, _NOW, sent_in_window=0, rate_limit=2)
    assert len(fired) == 2


def test_decide_needs_llm_skipped_without_judge_used_with_judge():
    trigs = [_trig("fuzzy", {"fuzzy": "anything urgent?"})]
    assert e.decide_tick(trigs, {}, _NOW, 0, 0) == []           # no judge -> skip
    fired = e.decide_tick(trigs, {}, _NOW, 0, 0, judge=lambda t, s: True)
    assert [t["id"] for t in fired] == ["fuzzy"]
    assert e.decide_tick(trigs, {}, _NOW, 0, 0, judge=lambda t, s: False) == []


# ---- outcome-driven tuning (Phase 5) ---------------------------------------

def test_update_belief_directions():
    assert e.update_belief(1.0, 1.0, "useful") == (2.0, 1.0)
    assert e.update_belief(1.0, 1.0, "acted") == (3.0, 1.0)
    assert e.update_belief(1.0, 1.0, "dismissed") == (1.0, 2.0)
    assert e.update_belief(2.0, 3.0, "unknown") == (2.0, 3.0)   # no-op


def test_usefulness():
    assert e.usefulness(1.0, 1.0) == 0.5
    assert e.usefulness(0.0, 0.0) == 0.0
    assert e.usefulness(9.0, 1.0) == 0.9


def test_is_noisy_needs_evidence_then_flags():
    # one dismissal isn't enough to judge
    assert e.is_noisy(1.0, 2.0) is False
    # many dismissals -> low usefulness -> noisy
    a, b = 1.0, 1.0
    for _ in range(6):
        a, b = e.update_belief(a, b, "dismissed")
    assert e.is_noisy(a, b) is True
    # consistently useful -> never noisy
    a, b = 1.0, 1.0
    for _ in range(6):
        a, b = e.update_belief(a, b, "useful")
    assert e.is_noisy(a, b) is False
