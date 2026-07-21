"""When a local agent has struggled >= THRESHOLD times in a row, run its next call on DeepSeek-Pro.

Runs at _30 — before _failover (_40) and _local_concurrency (_50) — so those correctly see an
already-cloud call and stay out. Reverts to local automatically once a success resets the struggle
counter (see the tool_execute_after tracker). Self-contained: user plugins are not importable as
`plugins.<name>`, so shared state lives on agent.loop_data.params_persistent and helpers are inline.
Fail-safe: any error keeps the original model.
"""
from helpers.extension import Extension
from helpers.print_style import PrintStyle

THRESHOLD = 2                     # consecutive struggles before escalating local -> Pro
STRUGGLE_KEY = "_escalate_struggle"
_PRO_PRESET = "DeepSeek-Pro"
_CLOUD_MARKERS = ("deepseek", "openrouter", "openai.com", "anthropic", "together", "groq", "mistral")
_pro_model = None


def _get_struggle(agent) -> int:
    ld = getattr(agent, "loop_data", None)
    d = getattr(ld, "params_persistent", None)
    return int(d.get(STRUGGLE_KEY, 0)) if isinstance(d, dict) else 0


def _is_local(model) -> bool:
    try:
        conf = getattr(model, "a0_model_conf", None)
        ab = str(getattr(conf, "api_base", "") or "").lower() or str(getattr(model, "model_name", "") or "").lower()
        return bool(ab) and not any(m in ab for m in _CLOUD_MARKERS)
    except Exception:
        return False


def _get_pro_model():
    global _pro_model
    if _pro_model is not None:
        return _pro_model
    try:
        from plugins._model_config.helpers.model_config import get_preset_by_name, build_model_config
        import models as M
        preset = get_preset_by_name(_PRO_PRESET)
        if not preset:
            return None
        mc = build_model_config(preset.get("chat", {}), M.ModelType.CHAT)
        _pro_model = M.get_chat_model(mc.provider, mc.name, model_config=mc, **mc.build_kwargs())
        return _pro_model
    except Exception:
        return None


class ModelEscalate(Extension):
    async def execute(self, call_data: dict | None = None, **kwargs):
        try:
            if not isinstance(call_data, dict) or not self.agent:
                return
            struggle = _get_struggle(self.agent)
            if struggle < THRESHOLD:
                return
            if not _is_local(call_data.get("model")):
                return  # already cloud (or unknown) -> nothing to escalate
            pro = _get_pro_model()
            if pro is None:
                return
            call_data["model"] = pro
            call_data["_escalated_to_pro"] = True
            name = getattr(self.agent, "agent_name", "agent")
            PrintStyle(font_color="magenta", padding=True).print(
                f"{name}: struggling on local ({struggle}x) -> escalating this call to DeepSeek-Pro"
            )
            try:
                self.agent.context.log.log(
                    type="info",
                    content=f"{name}: escalated to DeepSeek-Pro after {struggle} local struggles",
                )
            except Exception:
                pass
        except Exception:
            return  # fail-safe: keep original model
