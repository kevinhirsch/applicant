"""RT Phase 2 — retire the remaining applicant front-end polls over the WS.

Each surface that still ran its OWN data poll now RETIRES it while the realtime
push channel is live and RESTORES it on WS loss (the honesty invariant: no silent
dead UI — the poll is the fallback, never deleted). The engine's `notif`/`tracker`
push is surfaced to these data surfaces by ``applicantRealtime.js`` as the
``applicant:data-changed`` document event; the shell-level Portal/bell already ride
``applicant:pending-changed``.

These modules self-boot on import (they touch WebSocket/document at eval time), so
— exactly like ``test_applicant_topbar_bell.py`` — the reuse seams are pinned at the
SOURCE level here; the PURE helper (``dataChangedRefresh``) is exercised for real
headlessly in ``tests/js/applicantRealtime.test.js``.

Each assertion was hand-verified to go RED when the piece it protects is reverted.
"""

from __future__ import annotations

import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_REALTIME_JS = _JS_DIR / "applicantRealtime.js"
_RESULTS_JS = _JS_DIR / "applicantResults.js"
_TODAY_JS = _JS_DIR / "applicantToday.js"
_BELL_JS = _JS_DIR / "applicantBell.js"
_ACTIVITY_JS = _JS_DIR / "applicantActivity.js"


@pytest.fixture(scope="module")
def realtime_src() -> str:
    return _REALTIME_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def results_src() -> str:
    return _RESULTS_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def today_src() -> str:
    return _TODAY_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bell_src() -> str:
    return _BELL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def activity_src() -> str:
    return _ACTIVITY_JS.read_text(encoding="utf-8")


# ── applicantRealtime.js: the push → data-surface fan-out ─────────────────────


def test_realtime_notif_handler_fans_a_data_changed_event(realtime_src: str) -> None:
    # The notif channel drives BOTH the Portal/bell badge (notifRefresh) AND the
    # data surfaces that read their own feed (dataChangedRefresh) on one frame.
    assert "function dataChangedRefresh(frame)" in realtime_src
    assert "applicant:data-changed" in realtime_src
    assert "notifRefresh(); dataChangedRefresh(frame);" in realtime_src
    # Exported so the JS harness can slice + execute it, and reachable to callers.
    assert realtime_src.count("dataChangedRefresh,") >= 2  # module object + named export


# ── applicantResults.js: retire the 60s poll while live, restore on loss ──────


def test_results_retires_its_poll_while_live_and_restores_on_loss(results_src: str) -> None:
    assert "let _realtimeLive = false;" in results_src
    # A live push channel retires the poll; WS loss restores it (the fallback).
    assert "function _applyRealtimeLive(live)" in results_src
    assert "_startPollIfNeeded" in results_src
    # The poll is gated on NOT being live (retired while pushing).
    assert "if (!_isOpen() || _realtimeLive || _pollStop) return;" in results_src
    # Retire-on-live tears the running poll down.
    assert "if (_pollStop) { _pollStop(); _pollStop = null; }" in results_src


def test_results_listens_for_the_realtime_and_data_changed_signals(results_src: str) -> None:
    assert "addEventListener('applicant:realtime'" in results_src
    assert "addEventListener('applicant:data-changed'" in results_src
    # Refetch on a push goes through the EXISTING _load (with its fingerprint guard).
    assert "function _onDataChanged()" in results_src
    assert "_load(false)" in results_src
    # Reconcile a socket that opened before this listener existed (level, not just edge).
    assert "window.__applicantRealtimeLive" in results_src


# ── applicantToday.js: refetch on push; fallback poll gated on WS-live ────────


def test_today_refetches_on_push_and_gates_a_fallback_poll_on_ws_live(today_src: str) -> None:
    assert "let _realtimeLive = false;" in today_src
    assert "let _todayPollStop = null;" in today_src
    assert "function _applyRealtimeLive(live)" in today_src
    # The fallback poll starts only when NOT live (retired while pushing) and open.
    assert "function _startTodayPollIfNeeded()" in today_src
    assert "if (!_todayOpen() || _realtimeLive || _todayPollStop) return;" in today_src
    # A visibility-aware interval drives the fallback cadence (no immediate re-load on
    # open — the deck was just loaded), and it refetches through _maybeRefetch.
    assert "setInterval(_maybeRefetch, 60000)" in today_src


def test_today_refetch_is_guarded_against_disrupting_a_walkthrough(today_src: str) -> None:
    # A background refetch must never discard typed input or yank the user off a
    # mid-walkthrough card (it re-renders from _idx 0); guard both.
    assert "function _maybeRefetch()" in today_src
    assert "if (_hasUnsavedInput()) return;" in today_src
    assert "if (_state === 'ready' && _idx > 0) return;" in today_src


def test_today_listens_for_the_realtime_and_data_changed_signals(today_src: str) -> None:
    assert "addEventListener('applicant:realtime'" in today_src
    assert "addEventListener('applicant:data-changed'" in today_src
    assert "window.__applicantRealtimeLive" in today_src


# ── applicantBell.js: retire the 45s fallback poll while live, restore on loss ─


def test_bell_retires_its_fallback_poll_while_live_and_restores_on_loss(bell_src: str) -> None:
    assert "let _realtimeLive = false;" in bell_src
    # start() will not arm the interval while the push channel is live.
    assert "if (timer == null && !_realtimeLive)" in bell_src
    # applyLive retires (stop) on live and restores (start) on WS loss.
    assert "const applyLive = (live) =>" in bell_src
    assert "addEventListener('applicant:realtime'" in bell_src
    # The bell still re-reads on the shared pending-changed push while live.
    assert "addEventListener(PENDING_CHANGED_EVENT" in bell_src
    # Teardown removes the realtime listener too (no leak on remount).
    assert "removeEventListener('applicant:realtime', onRealtime)" in bell_src
    assert "window.__applicantRealtimeLive" in bell_src


# ── applicantActivity.js: retire the status-strip poll while live, restore on loss ─


def test_activity_retires_its_status_poll_while_live_and_restores_on_loss(activity_src: str) -> None:
    assert "let _realtimeLive = false;" in activity_src
    # A live push channel retires the poll; WS loss restores it (the fallback).
    assert "function _applyRealtimeLive(live)" in activity_src
    assert "function _startStatusPollIfNeeded()" in activity_src
    # The poll starts only when NOT live (retired while pushing) and none is running.
    assert "if (_realtimeLive || _statusPollStop) return;" in activity_src
    # The literal fallback poll call is preserved (also pinned by the wave-1 polling test).
    assert "pollVisible(refreshStatus, STATUS_POLL_MS)" in activity_src
    # Retire-on-live tears the running poll down.
    assert "if (_statusPollStop) { _statusPollStop(); _statusPollStop = null; }" in activity_src


def test_activity_listens_for_the_realtime_and_data_changed_signals(activity_src: str) -> None:
    assert "addEventListener('applicant:realtime'" in activity_src
    assert "addEventListener('applicant:data-changed'" in activity_src
    # Refresh on a push goes through the EXISTING refreshStatus.
    assert "document.addEventListener('applicant:data-changed', () => { refreshStatus(); });" in activity_src
    # Reconcile a socket that opened before this listener existed (level, not just edge).
    assert "window.__applicantRealtimeLive" in activity_src
