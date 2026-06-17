"""OpenAI-compatible LLM adapter (FR-LLM-1..5).

Talks to any OpenAI-compatible endpoint (OpenRouter / OpenAI cloud) or a
local/network Ollama install over real HTTP via ``httpx``. Implements:

* model auto-pull (FR-LLM-2) — OpenAI-style ``/models`` and Ollama ``/api/tags``;
* the capability-ranked tier ladder + escalation (FR-LLM-3/4) — start at the
  lowest sufficient tier and climb on low-confidence signals or context overflow,
  picking the next tier whose ``context_window`` actually fits;
* defensive structured-output parsing (FR-LLM-4a) — native JSON/response-format
  first, then a prompt-based fallback, parsed/validated defensively, never sending
  a prompt that exceeds the active tier's context window;
* token frugality (FR-LLM-5/NFR-TOKEN-1) — cheapest tier (L1) is the default.

The adapter NEVER logs secrets (api keys). It is fully hermetic in tests via an
injected ``httpx`` transport.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import (
    ChatMessage,
    LLMLadderExhausted,
    LLMNotConfigured,
    LLMResult,
    TierConfig,
    TierLadder,
)

log = get_logger(__name__)

#: Rough chars-per-token heuristic for the local overflow estimate (cheap, no
#: tokenizer dependency). Conservative on purpose so we escalate before overflow.
_CHARS_PER_TOKEN = 4

#: Phrases that signal the model is not confident — climb the ladder (FR-LLM-4).
_LOW_CONFIDENCE_MARKERS = (
    "i'm not sure",
    "i am not sure",
    "i cannot determine",
    "i don't have enough",
    "i do not have enough",
    "insufficient information",
    "unable to answer",
)


def _ollama_provider(provider: str, base_url: str) -> bool:
    """Detect an Ollama endpoint by provider name or URL shape (FR-LLM-2)."""
    if provider.lower() == "ollama":
        return True
    return "11434" in base_url or "/api/" in base_url


def _normalize_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _estimate_tokens(messages: list[ChatMessage]) -> int:
    chars = sum(len(m.role) + len(m.content) for m in messages)
    return max(1, chars // _CHARS_PER_TOKEN)


def _looks_low_confidence(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _LOW_CONFIDENCE_MARKERS)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Defensively pull a JSON object out of free-form model text (FR-LLM-4a)."""
    if not text:
        return None
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Last resort: grab the outermost {...} span.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _validate_against_schema(obj: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Shallow required-keys check (defensive, no jsonschema dependency)."""
    required = schema.get("required") or list((schema.get("properties") or {}).keys())
    return all(key in obj for key in required)


class _Overflow(Exception):
    """Internal: the prompt does not fit the active tier's context window."""


class OpenAICompatibleLLM:
    """LLMPort adapter over httpx. Configuration drives the OOBE gate (FR-UI-5).

    Construct either from a :class:`TierLadder` (preferred, FR-LLM-3) or from the
    legacy single-tier kwargs (``provider``/``base_url``/``api_key``/``model``),
    which are promoted into a one-tier ladder for backward compatibility.
    """

    def __init__(
        self,
        *,
        ladder: TierLadder | None = None,
        provider: str = "",
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        context_window: int = 8192,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        if ladder is None and (provider or model):
            ladder = TierLadder(
                tiers=[
                    TierConfig(
                        provider=provider,
                        base_url=base_url,
                        model=model,
                        api_key=api_key,
                        context_window=context_window,
                    )
                ]
            )
        self._ladder = ladder
        self._transport = transport
        self._timeout = timeout

    # --- helpers ----------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=self._timeout)

    def _headers(self, tier: TierConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if tier.api_key and not _ollama_provider(tier.provider, tier.base_url):
            headers["Authorization"] = f"Bearer {tier.api_key}"
        return headers

    # --- FR-LLM-2: model auto-pull ----------------------------------------
    def list_models(self, *, tier_index: int = 0) -> list[str]:
        """Auto-populate the model list from the configured provider (FR-LLM-2)."""
        if self._ladder is None:
            return []
        tier = self._ladder.at(tier_index)
        base = _normalize_base(tier.base_url)
        if _ollama_provider(tier.provider, tier.base_url):
            # Ollama base may include a trailing /v1 (OpenAI-compat shim) — strip it,
            # exactly as _call_ollama does, so /api/tags is hit (FR-LLM-2).
            if base.endswith("/v1"):
                base = base[: -len("/v1")]
            url = f"{base}/api/tags"
        else:
            # OpenAI-compatible: tolerate base_url with or without /v1.
            url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        try:
            with self._client() as client:
                resp = client.get(url, headers=self._headers(tier))
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log.warning("llm_list_models_failed", provider=tier.provider, error=str(exc))
            return []
        return self._parse_models(data)

    @staticmethod
    def _parse_models(data: dict[str, Any]) -> list[str]:
        if not isinstance(data, dict):
            return []
        # Ollama: {"models": [{"name": "llama3.1:8b", ...}, ...]}
        if isinstance(data.get("models"), list):
            return [
                m.get("name", m.get("model", ""))
                for m in data["models"]
                if isinstance(m, dict)
            ]
        # OpenAI/OpenRouter: {"data": [{"id": "gpt-4o", ...}, ...]}
        if isinstance(data.get("data"), list):
            return [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
        return []

    # --- FR-LLM-3/4: tier ladder + escalation -----------------------------
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        start_tier: int = 1,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        if self._ladder is None:
            raise LLMNotConfigured("No LLM tier ladder is configured (FR-UI-5).")

        required = _estimate_tokens(messages) + (max_tokens or 0)
        idx = max(0, start_tier - 1)
        # If the starting tier can't hold the prompt, jump to the first that can.
        if self._ladder.at(idx).context_window < required:
            fit = self._ladder.first_fitting(required, from_index=idx)
            if fit is None:
                raise LLMLadderExhausted(
                    f"Prompt needs ~{required} tokens; no tier's context window fits "
                    "(FR-LLM-4a)."
                )
            idx = fit

        last_error: Exception | None = None
        while idx < len(self._ladder):
            tier = self._ladder.at(idx)
            try:
                result = self._call_tier(tier, idx + 1, messages, json_schema, max_tokens)
            except _Overflow:
                # Context overflow surfaced by the provider — climb to next fit.
                nxt = self._ladder.first_fitting(required, from_index=idx + 1)
                if nxt is None:
                    raise LLMLadderExhausted(
                        "Context overflow and no larger tier available (FR-LLM-4).",
                    ) from None
                idx = nxt
                continue
            except (httpx.HTTPError, LLMNotConfigured, ValueError) as exc:
                # ValueError covers json.JSONDecodeError (a ValueError subclass): a
                # non-JSON 200 (proxy/CDN HTML) must climb the ladder / exhaust
                # gracefully, never crash the caller (FR-LLM-4).
                last_error = exc
                log.warning("llm_tier_failed", tier=idx + 1, error=str(exc))
                idx += 1
                continue

            if result.low_confidence and idx + 1 < len(self._ladder):
                # Low confidence: climb one rung (next rung is by definition >= cost).
                log.info("llm_escalate_low_confidence", from_tier=idx + 1)
                idx += 1
                continue
            return result

        raise LLMLadderExhausted(
            "Tier ladder exhausted; top tier is the ceiling (FR-LLM-4).",
            last_error=last_error,
        )

    def _call_tier(
        self,
        tier: TierConfig,
        tier_no: int,
        messages: list[ChatMessage],
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> LLMResult:
        # Never send a prompt exceeding the active tier's window (FR-LLM-4a).
        if _estimate_tokens(messages) > tier.context_window:
            raise _Overflow()

        if _ollama_provider(tier.provider, tier.base_url):
            return self._call_ollama(tier, tier_no, messages, json_schema, max_tokens)
        return self._call_openai(tier, tier_no, messages, json_schema, max_tokens)

    # --- provider calls ---------------------------------------------------
    def _call_openai(
        self,
        tier: TierConfig,
        tier_no: int,
        messages: list[ChatMessage],
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> LLMResult:
        base = _normalize_base(tier.base_url)
        url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": tier.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        native_json = False
        if json_schema is not None:
            # Try native structured output (FR-LLM-4a).
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured", "schema": json_schema},
            }
            native_json = True

        text, raw = self._post_openai(tier, url, payload)
        structured = None
        if json_schema is not None:
            structured = _extract_json(text)
            if structured is None or not _validate_against_schema(structured, json_schema):
                # Native mode failed → prompt-based fallback (FR-LLM-4a).
                if native_json:
                    payload.pop("response_format", None)
                fb_messages = self._with_schema_prompt(messages, json_schema)
                if _estimate_tokens(fb_messages) > tier.context_window:
                    raise _Overflow()
                payload["messages"] = [
                    {"role": m.role, "content": m.content} for m in fb_messages
                ]
                text, raw = self._post_openai(tier, url, payload)
                # Re-validate the fallback against the schema (FR-LLM-4a): a
                # malformed-but-parseable object must not be returned as structured.
                structured = _extract_json(text)
                if structured is not None and not _validate_against_schema(
                    structured, json_schema
                ):
                    structured = None

        return LLMResult(
            text=text,
            tier=tier_no,
            model=tier.model,
            raw=raw,
            structured=structured,
            low_confidence=_looks_low_confidence(text),
        )

    def _post_openai(
        self, tier: TierConfig, url: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        with self._client() as client:
            resp = client.post(url, headers=self._headers(tier), json=payload)
            if resp.status_code in (400, 413, 422) and self._is_context_error(resp):
                raise _Overflow()
            resp.raise_for_status()
            raw = resp.json()
        choices = raw.get("choices") if isinstance(raw, dict) else None
        text = ""
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                text = message.get("content") or ""
        return text, raw

    def _call_ollama(
        self,
        tier: TierConfig,
        tier_no: int,
        messages: list[ChatMessage],
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> LLMResult:
        base = _normalize_base(tier.base_url)
        # Ollama base may include a trailing /v1 (OpenAI-compat shim) — strip it.
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        url = f"{base}/api/chat"
        msgs = messages
        payload: dict[str, Any] = {
            "model": tier.model,
            "stream": False,
        }
        if json_schema is not None:
            # Ollama supports a JSON "format" hint; also reinforce via prompt.
            payload["format"] = "json"
            msgs = self._with_schema_prompt(messages, json_schema)
            if _estimate_tokens(msgs) > tier.context_window:
                raise _Overflow()
        payload["messages"] = [{"role": m.role, "content": m.content} for m in msgs]
        if max_tokens:
            payload["options"] = {"num_predict": max_tokens}

        with self._client() as client:
            resp = client.post(url, headers=self._headers(tier), json=payload)
            resp.raise_for_status()
            raw = resp.json()
        if not isinstance(raw, dict):
            raw = {}
        message = raw.get("message")
        text = (
            (message.get("content") if isinstance(message, dict) else None)
            or raw.get("response")
            or ""
        )
        structured = _extract_json(text) if json_schema is not None else None
        return LLMResult(
            text=text,
            tier=tier_no,
            model=tier.model,
            raw=raw,
            structured=structured,
            low_confidence=_looks_low_confidence(text),
        )

    @staticmethod
    def _is_context_error(resp: httpx.Response) -> bool:
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            return False
        msg = json.dumps(body).lower()
        return "context" in msg or "maximum context" in msg or "too long" in msg

    @staticmethod
    def _with_schema_prompt(
        messages: list[ChatMessage], json_schema: dict[str, Any]
    ) -> list[ChatMessage]:
        instruction = (
            "Respond ONLY with a single JSON object that conforms to this JSON "
            f"schema. Do not add prose or code fences.\nSchema: {json.dumps(json_schema)}"
        )
        return [*messages, ChatMessage(role="system", content=instruction)]

    # --- FR-UI-5: OOBE gate ----------------------------------------------
    def is_configured(self) -> bool:
        if self._ladder is None:
            return False
        first = self._ladder.at(0)
        return bool(first.provider and first.model)

    @property
    def ladder(self) -> TierLadder | None:
        return self._ladder
