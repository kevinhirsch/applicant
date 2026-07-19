"""AZ1-1 (#829) — model-connect bridge: mirror A0's chat model into the Applicant engine.

Connecting a model in A0's model gate must also configure the engine, so setup never
asks twice. A0 fires no chat-model-changed event and ``ApiHandler.process`` is not
``@extensible``, so instead of editing the pristine framework we RECONCILE on
``monologue_start``: read A0's resolved chat-model config and POST it to the engine's
``/api/setup/llm`` — but only when it changed since the last successful sync (idempotent,
cheap, threaded so it never blocks the loop). Fail-safe: a sync error is surfaced
honestly (H2) and never breaks the assistant.

Self-contained (user/plugin modules aren't importable as ``plugins.<name>``); the pure
payload builder is module-level so it can be unit-tested in isolation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import urllib.request

from helpers.extension import Extension

# Reconciliation state for THIS process: the signature of the last config we synced.
_LAST_SYNCED_SIG: dict[str, str] = {}


def build_engine_llm_payload(chat_cfg: dict, api_key: str) -> dict | None:
    """Map A0's resolved chat-model config -> the engine's LLMSettingsIn payload.

    Returns None when no model is connected yet (nothing to sync). Pure + testable.
    """
    provider = str((chat_cfg or {}).get("provider") or "").strip()
    model = str((chat_cfg or {}).get("name") or "").strip()
    if not provider or not model:
        return None
    base_url = str(chat_cfg.get("api_base") or "").strip()
    try:
        ctx = int(chat_cfg.get("ctx_length") or 0)
    except (TypeError, ValueError):
        ctx = 0
    return {
        "provider": provider,
        "base_url": base_url,
        # vLLM/local endpoints ignore the key but the engine field wants a non-empty value.
        "api_key": (api_key or "").strip() or "sk-noop",
        "model": model,
        "context_window": ctx or 8192,
    }


def _config_signature(payload: dict) -> str:
    """Change key that ignores the secret — re-sync only when the model actually changes."""
    basis = f"{payload['provider']}|{payload['model']}|{payload['base_url']}|{payload['context_window']}"
    return hashlib.sha256(basis.encode()).hexdigest()


def _post_engine_llm(engine_url: str, payload: dict) -> None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{engine_url.rstrip('/')}/api/setup/llm",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=8).read()  # 204 No Content on success


class EngineLlmSync(Extension):
    async def execute(self, **kwargs):
        try:
            from plugins._model_config.helpers import model_config
            import models
        except Exception:
            return  # no _model_config plugin -> nothing to bridge

        try:
            chat_cfg = model_config.get_chat_model_config(getattr(self, "agent", None)) or {}
        except Exception:
            return

        api_key = chat_cfg.get("api_key") or ""
        if not api_key:
            try:
                api_key = models.get_api_key(chat_cfg.get("provider", "")) or ""
            except Exception:
                api_key = ""

        payload = build_engine_llm_payload(chat_cfg, api_key)
        if payload is None:
            return  # no model connected yet

        sig = _config_signature(payload)
        if _LAST_SYNCED_SIG.get("sig") == sig:
            return  # already synced this exact model config

        engine_url = os.getenv("ENGINE_URL", "http://api:8000")
        try:
            await asyncio.to_thread(_post_engine_llm, engine_url, payload)
            _LAST_SYNCED_SIG["sig"] = sig  # cache only on success -> retry next turn on failure
        except Exception as exc:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=(
                        "Applicant: couldn't sync your model to the job engine "
                        f"({type(exc).__name__}). The assistant works; automated job "
                        "actions stay unconfigured until this succeeds."
                    ),
                )
            except Exception:
                pass
