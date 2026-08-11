"""FR-INTEL-4 (#867) runtime escalation — the three Python extensions that implement
consecutive-struggle -> DeepSeek-Pro escalation for local-only agents.

Each module lives as an a0-applicant extension that runs inside the A0 shell (not this
repo's runtime), so we load each module here with framework imports stubbed and exercise
the full execute cycle with fake Agent-like objects.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[2] / "a0-applicant/extensions/python"

MODEL_ESCALATE_PATH = BASE / "chat_model_call_before/_30_model_escalate.py"
TRACK_TOOL_PATH = BASE / "tool_execute_after/_20_escalate_track.py"
TRACK_WARNING_PATH = BASE / "hist_add_warning/end/_50_escalate_track.py"


# ── Sentinels ──────────────────────────────────────────────────────────────
MISFORMAT_SENTINEL = "misformat warning message"
REPEAT_SENTINEL = "repeat warning message"


# ── Stub helpers ───────────────────────────────────────────────────────────

def _force_stub_all() -> None:
    """Unconditionally replace every stub module so xdist workers always get a fresh env."""
    # Purge any earlier test-loading of these modules
    for k in list(sys.modules):
        if k in ("helpers", "helpers.extension", "helpers.print_style",
                 "plugins", "plugins._model_config",
                 "plugins._model_config.helpers",
                 "plugins._model_config.helpers.model_config",
                 "models"):
            sys.modules.pop(k, None)

    # helpers
    helpers = types.ModuleType("helpers")
    sys.modules["helpers"] = helpers

    ext_mod = types.ModuleType("helpers.extension")
    class _Extension:
        def __init__(self, *a, **k):
            self.agent = None
    ext_mod.Extension = _Extension
    helpers.extension = ext_mod
    sys.modules["helpers.extension"] = ext_mod

    ps_mod = types.ModuleType("helpers.print_style")
    class _PrintStyle:
        def __init__(self, *a, **k):
            pass
        def print(self, *a, **k):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a, **k):
            pass
    ps_mod.PrintStyle = _PrintStyle
    helpers.print_style = ps_mod
    sys.modules["helpers.print_style"] = ps_mod

    # plugins._model_config.helpers.model_config
    plugins_pkg = types.ModuleType("plugins")
    sys.modules["plugins"] = plugins_pkg

    mc_mod = types.ModuleType("plugins._model_config")
    sys.modules["plugins._model_config"] = mc_mod
    plugins_pkg._model_config = mc_mod

    mc_helpers = types.ModuleType("plugins._model_config.helpers")
    sys.modules["plugins._model_config.helpers"] = mc_helpers
    mc_mod.helpers = mc_helpers

    mc_model_config = types.ModuleType("plugins._model_config.helpers.model_config")
    sys.modules["plugins._model_config.helpers.model_config"] = mc_model_config

    class _FakeModelConfig2:
        def __init__(self, provider="fake", name="fake-model", api_base="http://10.0.1.225:8000/v1"):
            self.provider = provider
            self.name = name
            self.api_base = api_base
        def build_kwargs(self):
            return {"api_base": self.api_base}

    PRESET = {
        "provider": "deepseek",
        "name": "deepseek-chat",
        "chat": {
            "provider": "deepseek",
            "name": "deepseek-chat",
            "api_base": "https://api.deepseek.com/v1",
        },
    }

    def _get_preset_by_name(name):
        return PRESET if name == "DeepSeek-Pro" else None

    def _build_model_config(chat_cfg, model_type):
        return _FakeModelConfig2(
            chat_cfg.get("provider", ""),
            chat_cfg.get("name", ""),
        )

    mc_model_config.get_preset_by_name = _get_preset_by_name
    mc_model_config.build_model_config = _build_model_config
    mc_helpers.model_config = mc_model_config

    # models
    models_mod = types.ModuleType("models")
    models_mod.ModelType = type("ModelType", (), {"CHAT": "chat"})()
    models_mod.ModelConfig = _FakeModelConfig2

    def _get_chat_model(provider, name, model_config=None, **kw):
        obj = type("Model", (), {})()
        obj.a0_model_conf = type("conf", (), {"api_base": "https://api.deepseek.com/v1"})()
        obj.model_name = "deepseek-chat"
        return obj

    models_mod.get_chat_model = _get_chat_model
    sys.modules["models"] = models_mod


class _FakeModel:
    def __init__(self, api_base="http://10.0.1.225:8000/v1", model_name="local-model"):
        self.a0_model_conf = type("conf", (), {"api_base": api_base})()
        self.model_name = model_name


class FakeAgent:
    def __init__(self):
        self.agent_name = "test-agent"
        self.loop_data = type("ld", (), {"params_persistent": {}})()
        self._prompts = {
            "fw.msg_misformat.md": MISFORMAT_SENTINEL,
            "fw.msg_repeat.md": REPEAT_SENTINEL,
        }
        self.context = type(
            "ctx",
            (),
            {
                "log": type(
                    "lg",
                    (),
                    {"log": staticmethod(lambda *a, **k: None)},
                )()
            },
        )()

    def read_prompt(self, name):
        return self._prompts.get(name, "")


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def warn_mod():
    _force_stub_all()
    sys.modules.pop("_test_esc_warn", None)
    spec = importlib.util.spec_from_file_location("_test_esc_warn", TRACK_WARNING_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def track_mod():
    _force_stub_all()
    sys.modules.pop("_test_esc_track", None)
    spec = importlib.util.spec_from_file_location("_test_esc_track", TRACK_TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def escalate_mod():
    _force_stub_all()
    sys.modules.pop("_test_esc", None)
    spec = importlib.util.spec_from_file_location("_test_esc", MODEL_ESCALATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def local_model():
    return _FakeModel(api_base="http://10.0.1.225:8000/v1", model_name="local-qwen")


# ── Helpers ────────────────────────────────────────────────────────────────

async def _add_fail(track_mod, agent, msg: str) -> None:
    t = track_mod.EscalateTrackTool()
    t.agent = agent
    await t.execute(
        response=type("Resp", (), {"break_loop": False, "message": msg})()
    )


async def _esc_call(escalate_mod, agent, call_data: dict) -> None:
    e = escalate_mod.ModelEscalate()
    e.agent = agent
    await e.execute(call_data=call_data)


async def _add_success(track_mod, agent) -> None:
    t = track_mod.EscalateTrackTool()
    t.agent = agent
    await t.execute(
        response=type("Resp", (), {"break_loop": True, "message": "ok"})()
    )


async def _add_warning(warn_mod, agent, message: str) -> None:
    w = warn_mod.EscalateTrackWarning()
    w.agent = agent
    w.execute(data={"kwargs": {"message": message}})


# ── Tests ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [2, 3])
def test_two_struggles_then_escalate(
    escalate_mod, track_mod, warn_mod, local_model, n
):
    """Struggle counter >= THRESHOLD + local model -> escalate to Pro."""
    agent = FakeAgent()

    async def run():
        for _ in range(n):
            await _add_fail(
                track_mod, agent, "Traceback (most recent call last): Error"
            )
        call_data = {"model": local_model}
        await _esc_call(escalate_mod, agent, call_data)
        return call_data

    call_data = asyncio.run(run())
    assert agent.loop_data.params_persistent["_escalate_struggle"] == n
    assert call_data.get("_escalated_to_pro") is True
    assert call_data["model"].a0_model_conf.api_base == "https://api.deepseek.com/v1"


def test_clean_result_resets_counter(escalate_mod, track_mod, warn_mod, local_model):
    """A clean tool result resets struggle to 0."""
    agent = FakeAgent()
    agent.loop_data.params_persistent["_escalate_struggle"] = 2

    async def run():
        await _add_success(track_mod, agent)
        call_data = {"model": local_model}
        await _esc_call(escalate_mod, agent, call_data)
        return call_data

    call_data = asyncio.run(run())
    assert agent.loop_data.params_persistent["_escalate_struggle"] == 0
    assert call_data.get("_escalated_to_pro") is None
    assert call_data["model"] is local_model


def test_cloud_agent_never_escalates(escalate_mod, track_mod, warn_mod):
    """Agent on a cloud provider is never escalated."""
    agent = FakeAgent()
    agent.loop_data.params_persistent["_escalate_struggle"] = 5
    cloud = _FakeModel(
        api_base="https://api.deepseek.com/v1", model_name="deepseek-chat"
    )
    call_data = {"model": cloud}
    asyncio.run(_esc_call(escalate_mod, agent, call_data))
    assert call_data.get("_escalated_to_pro") is None
    assert call_data["model"] is cloud


def test_fail_safe_on_exception(escalate_mod, track_mod, warn_mod, local_model):
    """Exception in _get_pro_model should not propagate; model unchanged."""
    agent = FakeAgent()
    agent.loop_data.params_persistent["_escalate_struggle"] = 2

    def _broken():
        raise RuntimeError("boom")
    escalate_mod._get_pro_model = _broken

    call_data = {"model": local_model}
    asyncio.run(_esc_call(escalate_mod, agent, call_data))
    assert call_data.get("_escalated_to_pro") is None
    assert call_data["model"] is local_model


def test_threshold_is_pinned_and_movable(escalate_mod, track_mod, warn_mod):
    """Default THRESHOLD == 2; can be changed to 3."""
    assert escalate_mod.THRESHOLD == 2
    local = _FakeModel(api_base="http://10.0.1.225:8000/v1")

    # At THRESHOLD=2 (default), struggle=2 fires
    agent = FakeAgent()
    agent.loop_data.params_persistent["_escalate_struggle"] = 2
    cd = {"model": local}
    asyncio.run(_esc_call(escalate_mod, agent, cd))
    assert cd.get("_escalated_to_pro") is True

    # Bump threshold to 3
    escalate_mod.THRESHOLD = 3

    # At struggle=2 with THRESHOLD=3, does NOT fire
    agent2 = FakeAgent()
    agent2.loop_data.params_persistent["_escalate_struggle"] = 2
    cd2 = {"model": _FakeModel(api_base="http://10.0.1.225:8000/v1")}
    asyncio.run(_esc_call(escalate_mod, agent2, cd2))
    assert cd2.get("_escalated_to_pro") is None

    # At struggle=3, fires
    agent2.loop_data.params_persistent["_escalate_struggle"] = 3
    cd3 = {"model": _FakeModel(api_base="http://10.0.1.225:8000/v1")}
    asyncio.run(_esc_call(escalate_mod, agent2, cd3))
    assert cd3.get("_escalated_to_pro") is True
