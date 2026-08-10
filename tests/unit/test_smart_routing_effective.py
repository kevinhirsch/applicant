"""Integrate step: the smart-routing RUNTIME override folds over the env default.

EPIC MODEL-CONFIG persists a runtime smart-routing override via
``SetupService.set_smart_routing`` (which fires the llm_config_change hook). The
container's ``_effective_smart_routing`` helper is the single place that folds that
stored override over the env/Settings default, read fresh on every ladder resolve so an
operator's toggle takes effect without a restart. This pins the precedence rules.
"""
from __future__ import annotations

from types import SimpleNamespace

from applicant.app.container import _effective_smart_routing


def _settings(*, enabled: bool, prefer_local: bool):
    return SimpleNamespace(
        llm_smart_routing=enabled, llm_smart_routing_prefer_local=prefer_local
    )


def _setup(stored: dict | None):
    return SimpleNamespace(get_smart_routing=lambda: stored)


def test_env_default_used_when_no_override():
    setup = _setup({"enabled": None, "prefer_local": None})
    assert _effective_smart_routing(setup, _settings(enabled=True, prefer_local=False)) == (
        True,
        False,
    )


def test_stored_override_wins_over_env():
    # env says ON+prefer_local, operator persisted OFF -> OFF wins.
    setup = _setup({"enabled": False, "prefer_local": None})
    assert _effective_smart_routing(setup, _settings(enabled=True, prefer_local=True)) == (
        False,
        True,  # prefer_local not overridden -> env default retained
    )


def test_partial_override_only_prefer_local():
    setup = _setup({"enabled": None, "prefer_local": True})
    assert _effective_smart_routing(setup, _settings(enabled=False, prefer_local=False)) == (
        False,
        True,
    )


def test_missing_getter_degrades_to_env():
    setup = SimpleNamespace()  # no get_smart_routing
    assert _effective_smart_routing(setup, _settings(enabled=True, prefer_local=True)) == (
        True,
        True,
    )


def test_getter_raising_degrades_to_env():
    def _boom():
        raise RuntimeError("store down")

    setup = SimpleNamespace(get_smart_routing=_boom)
    assert _effective_smart_routing(setup, _settings(enabled=False, prefer_local=False)) == (
        False,
        False,
    )
