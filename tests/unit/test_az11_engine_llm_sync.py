"""AZ1-1 (#829) model-connect bridge — the A0 chat-model -> engine LLMSettings mapping.

The bridge lives as an a0-applicant monologue_start extension that runs inside the A0
shell (not this repo's runtime), so we load just its module here with the framework
``helpers.extension`` import stubbed, and exercise the pure payload builder + change key.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

EXT_PATH = (
    Path(__file__).resolve().parents[2]
    / "a0-applicant/extensions/python/monologue_start/_50_engine_llm_sync.py"
)


@pytest.fixture()
def bridge():
    # Stub the Agent Zero framework import so the module loads in this repo's env.
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    ext_mod = types.ModuleType("helpers.extension")

    class _Extension:  # minimal stand-in for helpers.extension.Extension
        def __init__(self, *a, **k):
            pass

    ext_mod.Extension = _Extension
    helpers.extension = ext_mod
    sys.modules["helpers.extension"] = ext_mod

    spec = importlib.util.spec_from_file_location("_az11_engine_sync", EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_maps_a0_chat_config_to_engine_payload(bridge):
    cfg = {"provider": "openai", "name": "qwen3.6:27b",
           "api_base": "http://10.0.1.225:8000/v1", "ctx_length": 96000}
    assert bridge.build_engine_llm_payload(cfg, "sk-real") == {
        "provider": "openai",
        "base_url": "http://10.0.1.225:8000/v1",
        "api_key": "sk-real",
        "model": "qwen3.6:27b",
        "context_window": 96000,
    }


def test_none_when_no_model_connected(bridge):
    assert bridge.build_engine_llm_payload({}, "") is None
    assert bridge.build_engine_llm_payload({"provider": "openai"}, "") is None  # no model name
    assert bridge.build_engine_llm_payload({"name": "m"}, "") is None  # no provider


def test_defaults_nonempty_key_and_ctx(bridge):
    p = bridge.build_engine_llm_payload({"provider": "local", "name": "m"}, "")
    assert p["api_key"] == "sk-noop"  # engine field needs a non-empty value; local ignores it
    assert p["context_window"] == 8192  # sane default when ctx_length missing


def test_change_key_ignores_api_key_but_tracks_model(bridge):
    base = {"provider": "o", "name": "m", "api_base": "u", "ctx_length": 100}
    p1 = bridge.build_engine_llm_payload(base, "k1")
    p2 = bridge.build_engine_llm_payload(base, "k2")
    assert bridge._config_signature(p1) == bridge._config_signature(p2)  # key change != re-sync
    p3 = bridge.build_engine_llm_payload({**base, "name": "m2"}, "k1")
    assert bridge._config_signature(p1) != bridge._config_signature(p3)  # model change => re-sync
