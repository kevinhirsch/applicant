"""Provider profiles for the OpenAI-compatible LLM adapter (FR-HARVEST-PROVIDER).

A ``ProviderProfile`` captures all provider-specific quirks (detection heuristic,
auth headers, HTTP paths, request shape, response parsing) in one declarative
dataclass. The adapter dispatches through ``PROFILES`` — ordered match-first —
instead of an if/else chain on provider strings.

Adding a new provider requires only a new ``ProviderProfile`` entry in ``PROFILES``;
no transport-branch edits are needed (FR-HARVEST-PROVIDER).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderProfile:
    """Declarative specification of one provider's wire-level quirks.

    Fields
    ------
    name:
        Canonical short name (e.g. ``"ollama"``, ``"openai"``).
    detect:
        Given ``(provider_str, base_url)`` return True iff this profile owns the
        request.  Profiles are tried in ``PROFILES`` order; first match wins.
    headers:
        Given ``api_key`` return the auth-header dict to merge into every request.
        The ``Content-Type`` header is added by the caller and need not be included.
    models_url:
        Callable that takes ``base`` (already normalised / stripped) and returns the
        full URL for the model-list endpoint (FR-LLM-2).
    models_extractor:
        Parse the JSON response body from ``models_url`` into a list of model-id
        strings.
    chat_url:
        Callable that takes ``base`` (already normalised / stripped) and returns the
        full URL for the chat-completion endpoint.
    build_request:
        Build the completion request payload.  Receives the common kwargs shared by
        all providers and must return a ``dict`` ready for ``json=`` serialisation.
        Signature: ``(model, messages, json_schema, max_tokens) -> dict``.
    extract_text:
        Pull the assistant text out of the raw JSON response body.
    supports_prefix_cache:
        True iff the provider honors explicit prefix-cache breakpoints on the
        stable prompt prefix (e.g. an Anthropic-style ``cache_control`` block).
        OpenAI-compatible cloud and local Ollama lanes do NOT — they leave this
        ``False`` so :func:`mark_prefix_cache` is never invoked and prefix caching
        is a clean no-op for those lanes (FR-MIND-8).
    mark_prefix_cache:
        Given the built request ``payload`` dict, return it with cache breakpoints
        applied to the stable prefix. Only consulted when ``supports_prefix_cache``
        is True; defaults to an identity passthrough (no breakpoints).
    supports_tools:
        True iff the provider advertises OpenAI-style function/tool calling
        (``tools=`` + ``tool_calls`` in the response). The OpenAI-compatible cloud
        lane advertises it; the local Ollama ``/api/chat`` shape does not, so it is
        left ``False`` and the chat tool-call loop is never engaged for it — the
        chat does its current single-shot completion exactly as before (FR-MIND-6).
    parse_tool_calls:
        Given the raw response body, return the assistant's requested tool calls as
        a list of ``(call_id, name, arguments_json_str)`` tuples, or ``[]`` when the
        model returned plain text. Only consulted when ``supports_tools`` is True.
    """

    name: str
    detect: Callable[[str, str], bool]
    headers: Callable[[str], dict[str, str]]
    models_url: Callable[[str], str]
    models_extractor: Callable[[dict[str, Any]], list[str]]
    chat_url: Callable[[str], str]
    build_request: Callable[..., dict[str, Any]]
    extract_text: Callable[[dict[str, Any]], str]
    supports_prefix_cache: bool = False
    mark_prefix_cache: Callable[[dict[str, Any]], dict[str, Any]] = (
        lambda payload: payload
    )
    supports_tools: bool = False
    parse_tool_calls: Callable[[dict[str, Any]], list[tuple[str, str, str]]] = (
        lambda raw: []
    )


# ---------------------------------------------------------------------------
# Pure helpers (no IO, no imports from sibling modules)
# ---------------------------------------------------------------------------

def tool_call_arguments(message: dict[str, Any]) -> str | None:
    """Extract the first tool/function call's ``arguments`` JSON string.

    Supports the OpenAI ``tool_calls[].function.arguments`` shape and the legacy
    ``function_call.arguments`` shape. Returns the raw arguments string (which is
    itself a JSON object) or ``None`` when there is no tool call.

    This lives here (not in ``openai_compatible``) so ``_openai_extract_text`` can
    reference it without creating a circular import.
    """
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                return fn["arguments"]
    legacy = message.get("function_call")
    if isinstance(legacy, dict) and isinstance(legacy.get("arguments"), str):
        return legacy["arguments"]
    return None


def _openai_parse_tool_calls(raw: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Parse the assistant's requested tool calls from an OpenAI-style body (FR-MIND-6).

    Returns ``(call_id, name, arguments_json_str)`` tuples for every tool/function
    call the model emitted, supporting both the modern ``tool_calls[]`` shape and the
    legacy ``function_call`` shape. Returns ``[]`` when the assistant replied with
    plain content (the model chose NOT to call a tool) — the caller then treats the
    turn as a final text reply, so a tool-capable model that elects not to use a tool
    behaves exactly like the single-shot path.
    """
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
        return []
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return []
    out: list[tuple[str, str, str]] = []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for i, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            if not isinstance(fn, dict):
                continue
            name = fn.get("name") or ""
            args = fn.get("arguments")
            if not isinstance(args, str):
                args = "{}"
            call_id = call.get("id") or f"call_{i}"
            if name:
                out.append((str(call_id), str(name), args))
    if out:
        return out
    legacy = message.get("function_call")
    if isinstance(legacy, dict) and legacy.get("name"):
        args = legacy.get("arguments")
        out.append(("call_0", str(legacy["name"]), args if isinstance(args, str) else "{}"))
    return out


# ---------------------------------------------------------------------------
# Helper callables shared across profiles
# ---------------------------------------------------------------------------

def _openai_headers(api_key: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _ollama_headers(api_key: str) -> dict[str, str]:  # noqa: ARG001
    """Ollama does not require an auth token."""
    return {}


def _openai_models_url(base: str) -> str:
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def _ollama_models_url(base: str) -> str:
    # Strip /v1 shim suffix before appending /api/tags (FR-LLM-2).
    b = base[: -len("/v1")] if base.endswith("/v1") else base
    return f"{b}/api/tags"


def _openai_models_extractor(data: dict[str, Any]) -> list[str]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("data"), list):
        return [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
    return []


def _ollama_models_extractor(data: dict[str, Any]) -> list[str]:
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("models"), list):
        return [
            m.get("name", m.get("model", ""))
            for m in data["models"]
            if isinstance(m, dict)
        ]
    return []


def _openai_chat_url(base: str) -> str:
    return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"


def _ollama_chat_url(base: str) -> str:
    b = base[: -len("/v1")] if base.endswith("/v1") else base
    return f"{b}/api/chat"


def _openai_build_request(
    model: str,
    messages: list[dict[str, str]],
    json_schema: dict[str, Any] | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "structured", "schema": json_schema},
        }
    return payload


def _ollama_build_request(
    model: str,
    messages: list[dict[str, str]],
    json_schema: dict[str, Any] | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "stream": False, "messages": messages}
    if json_schema is not None:
        payload["format"] = "json"
    if max_tokens:
        payload["options"] = {"num_predict": max_tokens}
    return payload


def _openai_extract_text(raw: dict[str, Any]) -> str:
    """Extract text from an OpenAI-style ``choices[0].message`` response."""
    choices = raw.get("choices") if isinstance(raw, dict) else None
    if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    text = message.get("content") or ""
    if not text:
        text = tool_call_arguments(message) or ""
    return text


def _ollama_extract_text(raw: dict[str, Any]) -> str:
    """Extract text from an Ollama ``message.content`` / ``response`` body."""
    if not isinstance(raw, dict):
        return ""
    message = raw.get("message")
    return (
        (message.get("content") if isinstance(message, dict) else None)
        or raw.get("response")
        or ""
    )


# ---------------------------------------------------------------------------
# Detection predicates
# ---------------------------------------------------------------------------

def _detect_ollama(provider: str, base_url: str) -> bool:
    """Detect an Ollama endpoint by provider name or URL shape (FR-LLM-2).

    An explicitly-named non-Ollama provider (openai, openrouter, …) is NEVER
    Ollama and must short-circuit: the URL-shape heuristic below false-positives
    on OpenRouter's ``https://openrouter.ai/api/v1`` base (it contains ``/api/``),
    which would route cloud completions to Ollama's ``/api/chat``.
    """
    p = provider.strip().lower()
    if p == "ollama":
        return True
    if p:
        return False
    return "11434" in base_url or "/api/" in base_url


def _detect_openai_compatible(provider: str, base_url: str) -> bool:  # noqa: ARG001
    """Default catch-all: any non-Ollama provider (OpenAI, OpenRouter, etc.)."""
    return True


# ---------------------------------------------------------------------------
# Profile registry — ordered; first match wins
# ---------------------------------------------------------------------------

OLLAMA_PROFILE: ProviderProfile = ProviderProfile(
    name="ollama",
    detect=_detect_ollama,
    headers=_ollama_headers,
    models_url=_ollama_models_url,
    models_extractor=_ollama_models_extractor,
    chat_url=_ollama_chat_url,
    build_request=_ollama_build_request,
    extract_text=_ollama_extract_text,
)

OPENAI_PROFILE: ProviderProfile = ProviderProfile(
    name="openai",
    detect=_detect_openai_compatible,
    headers=_openai_headers,
    models_url=_openai_models_url,
    models_extractor=_openai_models_extractor,
    chat_url=_openai_chat_url,
    build_request=_openai_build_request,
    extract_text=_openai_extract_text,
    supports_tools=True,
    parse_tool_calls=_openai_parse_tool_calls,
)

#: Ordered list of profiles.  First profile whose ``detect`` returns True is used.
PROFILES: list[ProviderProfile] = [OLLAMA_PROFILE, OPENAI_PROFILE]


def get_profile(provider: str, base_url: str) -> ProviderProfile:
    """Return the first matching profile for ``(provider, base_url)``.

    Always returns a profile because ``OPENAI_PROFILE`` is the catch-all last
    entry.  Raises ``RuntimeError`` only if ``PROFILES`` is somehow empty.
    """
    for profile in PROFILES:
        if profile.detect(provider, base_url):
            return profile
    raise RuntimeError("No provider profile matched — PROFILES list is empty.")
