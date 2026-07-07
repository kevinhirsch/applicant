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

Provider-specific quirks (auth headers, URL shapes, request/response formats) are
declared in :mod:`applicant.adapters.llm.provider_profiles` via
:class:`~applicant.adapters.llm.provider_profiles.ProviderProfile`.  Adding a new
provider requires only a new profile entry — no transport-branch edits here
(FR-HARVEST-PROVIDER).

The adapter NEVER logs secrets (api keys). It is fully hermetic in tests via an
injected ``httpx`` transport.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from applicant.adapters.llm.context_window import ContextWindowManager
from applicant.adapters.llm.provider_profiles import (
    get_profile,
    tool_call_arguments,
)
from applicant.adapters.llm.rate_limit import LLMRateLimiter
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import (
    ChatMessage,
    LLMLadderExhausted,
    LLMNotConfigured,
    LLMRateLimited,
    LLMResult,
    TierConfig,
    TierLadder,
    ToolCall,
    ToolCallResult,
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

# Re-export for backward compatibility with code that imports _tool_call_arguments
# from this module (e.g. tests).
_tool_call_arguments = tool_call_arguments


def _normalize_base(base_url: str) -> str:
    return base_url.rstrip("/")


def _tool_message_dict(m: ChatMessage) -> dict[str, Any]:
    """Serialize one ``ChatMessage`` to the OpenAI wire shape, tool-aware (FR-MIND-6).

    A plain (role, content) message serializes exactly as before. An assistant message
    carrying ``tool_calls`` echoes them back (so the provider can thread the
    conversation), and a ``role="tool"`` result message carries its ``tool_call_id``.
    """
    if m.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": m.tool_call_id or "",
            "content": m.content,
        }
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in m.tool_calls
        ]
    return out


def _estimate_tokens(messages: list[ChatMessage]) -> int:
    chars = sum(len(m.role) + len(m.content) for m in messages)
    return max(1, chars // _CHARS_PER_TOKEN)


def _looks_low_confidence(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _LOW_CONFIDENCE_MARKERS)


def _strip_trailing_commas(candidate: str) -> str:
    """Remove a trailing comma before a closing ``}``/``]`` (lenient JSON)."""
    return re.sub(r",(\s*[}\]])", r"\1", candidate)


def _try_load_object(candidate: str) -> dict[str, Any] | None:
    """Parse ``candidate`` as a JSON object, tolerating a trailing comma."""
    for attempt in (candidate, _strip_trailing_commas(candidate)):
        try:
            obj = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def balanced_object_spans(text: str):
    """Yield every balanced ``{...}`` substring, brace-/string-aware.

    Scans left-to-right tracking brace depth while skipping braces that appear
    inside string literals (so ``{"k": "a } b"}`` is one span, not a false end).
    Each top-level balanced object is yielded in document order, so a decoy
    ``{...}`` before the real object is tried first and a later parseable object
    is still reachable.

    PUBLIC contract: also consumed by the résumé parse-verify layer
    (``adapters/resume_parser/llm_verify.py``) for defensive extraction of a
    model's JSON answer — rename/removal breaks that adapter, not just this one.
    """
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    yield text[start : i + 1]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Defensively pull a JSON object out of free-form model text (FR-LLM-4a).

    Robust to: prose-wrapped JSON, a decoy ``{...}`` appearing before the real
    object, trailing commas, and braces inside string values. Strategy: strip
    code fences, try a whole-string parse, then scan every balanced ``{...}``
    span (in order) and return the first one that parses as an object.
    """
    if not text:
        return None
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Fast path: the whole (fenced) text is JSON.
    whole = _try_load_object(text)
    if whole is not None:
        return whole
    # Scan balanced-brace candidates in document order; first parseable wins.
    for candidate in balanced_object_spans(text):
        obj = _try_load_object(candidate)
        if obj is not None:
            return obj
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

    Provider-specific transport quirks are resolved at call time via
    :func:`~applicant.adapters.llm.provider_profiles.get_profile`; no if/else
    branching on provider strings lives in this class (FR-HARVEST-PROVIDER).
    """

    def __init__(
        self,
        *,
        ladder: TierLadder | None = None,
        ladder_provider: Callable[[], TierLadder | None] | None = None,
        provider: str = "",
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        context_window: int = 8192,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
        context_manager: ContextWindowManager | None = None,
        app_context_manager: Any | None = None,
        prefix_cache: str = "auto",
        rate_limiter: LLMRateLimiter | None = None,
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
        # The ladder may be supplied directly (frozen — the legacy/test path, byte
        # identical to before) OR resolved lazily through ``ladder_provider`` (the
        # composition root re-reads it from the config store + applies smart routing).
        # The provider path makes a model connected AT RUNTIME take effect with no
        # engine restart: ``refresh_ladder()`` (called from setup_service on every
        # ``configure_llm``) drops the cache so the next completion re-resolves. When
        # no provider is wired the cache is seeded with the supplied ladder and never
        # re-resolved, so existing call sites + tests are unchanged.
        self._ladder_provider = ladder_provider
        self._ladder_cache = ladder
        self._ladder_resolved = ladder_provider is None
        self._transport = transport
        self._timeout = timeout
        # FR-MIND-8: bound the context (compress middle turns over budget). A
        # disabled (token_budget=0) manager is a pure no-op, so the default path
        # is byte-identical to before.
        self._context_manager = context_manager or ContextWindowManager()
        # FR-MIND-8: an OPTIONAL richer application-layer context manager
        # (duck-typed ``.compress(...) -> result.turns``) that supersedes the
        # placeholder when wired — it summarizes the middle turns with parent/child
        # lineage instead of a generic placeholder. Adapter-layer code must NOT import
        # the application type (that would invert the hexagonal layering), so it is
        # held untyped and consulted by duck-typing. ``None`` (the default) keeps the
        # current placeholder path, so existing call sites + tests are byte-identical.
        self._app_context_manager = app_context_manager
        # FR-MIND-8: prefix-cache posture. "auto"/"on" apply provider cache
        # breakpoints where the provider advertises support; "off" never does.
        # Local/OpenAI-compatible providers advertise no support, so this is a
        # clean no-op for them regardless of the setting.
        self._prefix_cache = (prefix_cache or "auto").strip().lower()
        # Per-provider LLM call rate gate (FR-DUR-2, #48). ``None`` (default) builds a
        # DISABLED limiter (limit=None) so every existing call site/test is
        # byte-identical unless the composition root wires a real one from config.
        self._rate_limiter = rate_limiter or LLMRateLimiter(None, None)

    # --- runtime-reloadable ladder ---------------------------------------
    @property
    def _ladder(self) -> TierLadder | None:
        """The active tier ladder, resolved lazily through the provider if wired.

        Without a ``ladder_provider`` this returns the frozen ladder supplied at
        construction (byte-identical to before). With one, it resolves+caches the
        ladder on first read after construction or after :meth:`refresh_ladder`, so
        a model connected at runtime (which re-runs the provider with fresh config)
        is picked up without rebuilding the adapter. A provider that raises or
        returns ``None`` leaves the last good cache in place rather than stranding
        the engine.
        """
        if not self._ladder_resolved and self._ladder_provider is not None:
            try:
                resolved = self._ladder_provider()
            except Exception:  # pragma: no cover - defensive: never break dispatch
                log.warning("llm_ladder_provider_failed", exc_info=True)
                resolved = None
            if resolved is not None:
                self._ladder_cache = resolved
            # Mark resolved even when the provider returned None, so we don't re-run
            # it on every call; ``refresh_ladder`` re-arms it when config changes.
            self._ladder_resolved = True
        return self._ladder_cache

    def refresh_ladder(self) -> None:
        """Re-arm the ladder provider so the next read re-resolves from config.

        Wired as a config-change hook on the SetupService: connecting a model at
        runtime persists the new tier, then calls this to drop the cached ladder so
        the very next completion walks the freshly-configured tiers — no restart.
        A no-op when no provider is wired (the ladder is frozen by design).
        """
        if self._ladder_provider is not None:
            self._ladder_resolved = False

    # --- helpers ----------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=self._timeout)

    @staticmethod
    def _rate_key(tier: TierConfig) -> str:
        """Rolling-window bucket key: per provider/endpoint, not per model (#48).

        Two tiers on the SAME provider/base_url (e.g. differing only by model) share
        one budget -- the limit is a per-provider call cap, not a per-model one.
        """
        return f"{tier.provider}|{_normalize_base(tier.base_url)}"

    def _gate_rate_limit(self, tier: TierConfig) -> None:
        """Admit this call under the tier's rate bucket or raise (FR-DUR-2, #48).

        A disabled limiter (the default, or ``LLM_RATE_LIMIT=0``) returns True
        immediately with zero overhead -- byte-identical to no gating. When enabled
        and the bucket is over its rolling-window limit, :meth:`LLMRateLimiter.acquire`
        waits once (bounded by the configured period) and retries; still exhausted
        after that bounded wait raises :class:`LLMRateLimited`, which the ladder loop
        catches exactly like a transient tier failure and climbs past.
        """
        if not self._rate_limiter.acquire(self._rate_key(tier)):
            raise LLMRateLimited(
                f"Rate limit exceeded for provider {tier.provider!r} at {tier.base_url!r}."
            )

    def _headers(self, tier: TierConfig) -> dict[str, str]:
        profile = get_profile(tier.provider, tier.base_url)
        headers = {"Content-Type": "application/json"}
        headers.update(profile.headers(tier.api_key))
        return headers

    def _bound_context(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Bound the multi-turn message list before dispatch (FR-MIND-8).

        Prefers the richer application-layer context manager (lineage-aware middle-turn
        summarization) when one is wired; otherwise falls back to the placeholder
        ``ContextWindowManager``. Both are no-ops below threshold, so the default path
        (neither over budget) is byte-identical to before.
        """
        app = self._app_context_manager
        if app is not None and hasattr(app, "compress"):
            result = app.compress(messages)
            turns = getattr(result, "turns", None)
            if isinstance(turns, list):
                return turns
        return self._context_manager.apply(messages)

    # --- FR-LLM-2: model auto-pull ----------------------------------------
    def list_models(self, *, tier_index: int = 0) -> list[str]:
        """Auto-populate the model list from the configured provider (FR-LLM-2)."""
        if self._ladder is None:
            return []
        tier = self._ladder.at(tier_index)
        base = _normalize_base(tier.base_url)
        profile = get_profile(tier.provider, tier.base_url)
        url = profile.models_url(base)
        try:
            with self._client() as client:
                resp = client.get(url, headers=self._headers(tier))
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log.warning("llm_list_models_failed", provider=tier.provider, error=str(exc))
            return []
        return profile.models_extractor(data)

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
            raise LLMNotConfigured("No LLM tier ladder is configured.")

        # FR-MIND-8: bound the conversation before dispatch. With the manager
        # disabled (the default) this returns the same list — a single-shot
        # (system+user) call is unaffected; only a long multi-turn conversation
        # over budget gets its middle turns compressed.
        messages = self._bound_context(messages)

        required = _estimate_tokens(messages) + (max_tokens or 0)
        # Clamp the 1-based starting rung into the ladder. A heavy task may request a
        # higher start tier (e.g. start_tier=2 to skip the cheap L1 for résumé/cover
        # writing); if the configured ladder has fewer rungs, fall back to its top
        # tier rather than indexing past the end (FR-LLM-3/4).
        idx = min(max(0, start_tier - 1), len(self._ladder) - 1)
        # If the starting tier can't hold the prompt, jump to the first that can.
        if self._ladder.at(idx).context_window < required:
            fit = self._ladder.first_fitting(required, from_index=idx)
            if fit is None:
                raise LLMLadderExhausted(
                    f"Prompt needs ~{required} tokens; no tier's context window fits."
                )
            idx = fit

        # Remember where the climb began so a total upward failure can fall back to
        # the LOWER configured rungs below it (downward fallback, see after the loop).
        start_index = idx
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
                        "Context overflow and no larger tier available.",
                    ) from None
                idx = nxt
                continue
            except (httpx.HTTPError, LLMNotConfigured, LLMRateLimited, ValueError) as exc:
                # ValueError covers json.JSONDecodeError (a ValueError subclass): a
                # non-JSON 200 (proxy/CDN HTML) must climb the ladder / exhaust
                # gracefully, never crash the caller (FR-LLM-4). LLMRateLimited (#48)
                # is treated the same way: a tier over its per-provider rate budget
                # is a transient soft failure, not a hard error -- climb past it.
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

        # The upward climb exhausted. A heavy task can start ABOVE the bottom rung
        # (e.g. start_tier=2), so a hard auth/transport failure on the upper tier(s)
        # would otherwise raise without ever trying a LOWER configured tier that is
        # healthy. Fall back DOWN those rungs (highest-below-start first) so a
        # misconfigured top tier degrades to a working lower one rather than to the
        # canned deterministic fallback (FR-LLM-3/4).
        down = start_index - 1
        while down >= 0:
            tier = self._ladder.at(down)
            if tier.context_window < required:
                down -= 1
                continue
            try:
                result = self._call_tier(tier, down + 1, messages, json_schema, max_tokens)
            except (
                httpx.HTTPError,
                LLMNotConfigured,
                LLMRateLimited,
                ValueError,
                _Overflow,
            ) as exc:
                last_error = exc
                log.warning("llm_tier_failed", tier=down + 1, error=str(exc), direction="down")
                down -= 1
                continue
            log.info("llm_fallback_down", from_start_tier=start_index + 1, to_tier=down + 1)
            return result

        raise LLMLadderExhausted(
            "Tier ladder exhausted; top tier is the ceiling.",
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
        # Per-provider rate gate (FR-DUR-2, #48): a disabled limiter is a no-op.
        self._gate_rate_limit(tier)

        profile = get_profile(tier.provider, tier.base_url)
        base = _normalize_base(tier.base_url)

        if profile.name == "ollama":
            return self._call_ollama(tier, tier_no, messages, json_schema, max_tokens, profile, base)
        return self._call_openai(tier, tier_no, messages, json_schema, max_tokens, profile, base)

    # --- provider calls ---------------------------------------------------
    def _call_openai(
        self,
        tier: TierConfig,
        tier_no: int,
        messages: list[ChatMessage],
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
        profile: Any | None = None,
        base: str | None = None,
    ) -> LLMResult:
        if base is None:
            base = _normalize_base(tier.base_url)
        if profile is None:
            profile = get_profile(tier.provider, tier.base_url)

        url = profile.chat_url(base)
        raw_messages = [{"role": m.role, "content": m.content} for m in messages]
        payload = profile.build_request(tier.model, raw_messages, json_schema, max_tokens)
        payload = self._apply_prefix_cache(profile, payload)

        text, raw = self._post_openai(tier, url, payload)
        structured = None
        if json_schema is not None:
            structured = _extract_json(text)
            if structured is None or not _validate_against_schema(structured, json_schema):
                # Native mode failed → prompt-based fallback (FR-LLM-4a).
                fb_messages = self._with_schema_prompt(messages, json_schema)
                if _estimate_tokens(fb_messages) > tier.context_window:
                    raise _Overflow()
                # Rebuild request without native response_format, with schema prompt.
                fb_raw_messages = [{"role": m.role, "content": m.content} for m in fb_messages]
                fb_payload = profile.build_request(tier.model, fb_raw_messages, None, max_tokens)
                fb_payload = self._apply_prefix_cache(profile, fb_payload)
                text, raw = self._post_openai(tier, url, fb_payload)
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
        profile = get_profile(tier.provider, tier.base_url)
        with self._client() as client:
            resp = client.post(url, headers=self._headers(tier), json=payload)
            if resp.status_code in (400, 413, 422) and self._is_context_error(resp):
                raise _Overflow()
            resp.raise_for_status()
            raw = resp.json()
        if not isinstance(raw, dict):
            raw = {}
        text = profile.extract_text(raw)
        return text, raw

    def _call_ollama(
        self,
        tier: TierConfig,
        tier_no: int,
        messages: list[ChatMessage],
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
        profile: Any | None = None,
        base: str | None = None,
    ) -> LLMResult:
        if base is None:
            base = _normalize_base(tier.base_url)
        if profile is None:
            profile = get_profile(tier.provider, tier.base_url)

        url = profile.chat_url(base)
        msgs = messages
        if json_schema is not None:
            # Reinforce JSON output via a schema prompt (Ollama hint is in build_request).
            msgs = self._with_schema_prompt(messages, json_schema)
            if _estimate_tokens(msgs) > tier.context_window:
                raise _Overflow()

        raw_messages = [{"role": m.role, "content": m.content} for m in msgs]
        payload = profile.build_request(tier.model, raw_messages, json_schema, max_tokens)
        payload = self._apply_prefix_cache(profile, payload)

        with self._client() as client:
            resp = client.post(url, headers=self._headers(tier), json=payload)
            resp.raise_for_status()
            raw = resp.json()
        if not isinstance(raw, dict):
            raw = {}
        text = profile.extract_text(raw)
        structured = _extract_json(text) if json_schema is not None else None
        return LLMResult(
            text=text,
            tier=tier_no,
            model=tier.model,
            raw=raw,
            structured=structured,
            low_confidence=_looks_low_confidence(text),
        )

    def _apply_prefix_cache(
        self, profile: Any, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Add provider prefix-cache breakpoints when enabled and supported.

        A clean no-op unless the configured posture is ``auto``/``on`` AND the
        resolved provider profile advertises prefix-cache support. Local Ollama
        and OpenAI-compatible cloud advertise none, so this returns the payload
        unchanged for them regardless of the posture (FR-MIND-8).
        """
        if self._prefix_cache == "off":
            return payload
        if not getattr(profile, "supports_prefix_cache", False):
            return payload
        marked = profile.mark_prefix_cache(payload)
        return marked if isinstance(marked, dict) else payload

    # Specific phrases / error codes that signal a real context-window overflow.
    # The bare substring "context" is intentionally absent — a content-filter
    # rejection that mentions "in the context of the request policy" must NOT
    # trigger an overflow escalation (#285).
    _CONTEXT_OVERFLOW_CODES = frozenset(
        {
            "context_length_exceeded",
            "context_window_exceeded",
        }
    )
    _CONTEXT_OVERFLOW_PHRASES = (
        "maximum context length",
        "context window",
        "context_length_exceeded",
        "context_window_exceeded",
        "too many tokens",
        "token limit exceeded",
        "tokens limit exceeded",
        "reduce the length",
    )

    @classmethod
    def _is_context_error(cls, resp: httpx.Response) -> bool:
        """Return True only for genuine context-window overflow signals (#285).

        Matches provider error codes (``context_length_exceeded`` /
        ``context_window_exceeded``) or specific phrases that appear in real
        overflow responses — NOT the bare substring "context", which is too broad
        and mis-classifies unrelated rejections (content-filter, auth, rate-limit)
        that happen to mention "context" in their human-readable text.
        """
        return cls._is_context_error_strict(resp)

    @classmethod
    def _is_context_error_strict(cls, resp: httpx.Response) -> bool:
        """Strict context-overflow classifier — same logic as ``_is_context_error`` (#285)."""
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            return False
        # Check the structured error code field first (exact, case-insensitive).
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code = str(err.get("code") or "").lower()
            if code in cls._CONTEXT_OVERFLOW_CODES:
                return True
        # Fall back to a phrase scan over the full serialised body.
        msg = json.dumps(body).lower()
        return any(phrase in msg for phrase in cls._CONTEXT_OVERFLOW_PHRASES)

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

    # --- FR-MIND-6: optional tool/function calling ------------------------
    def supports_tools(self) -> bool:
        """True iff the configured provider profile advertises tool calling.

        Detected from the provider profile (the OpenAI-compatible lane does; the
        local Ollama ``/api/chat`` lane does not). False keeps callers on the
        single-shot ``complete`` path, so default behavior is unchanged (FR-MIND-6).
        """
        if self._ladder is None:
            return False
        tier = self._ladder.at(0)
        return bool(get_profile(tier.provider, tier.base_url).supports_tools)

    def complete_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        *,
        start_tier: int = 1,
        max_tokens: int | None = None,
    ) -> ToolCallResult:
        """One tool-capable completion turn over the OpenAI-compatible lane (FR-MIND-6).

        Single-tier dispatch (the caller drives the multi-round loop). The active tier
        starts at ``start_tier`` and climbs on a transport error / context overflow,
        exactly like :meth:`complete`. Returns the model's requested tool calls (parsed
        from the provider's ``tool_calls`` shape) or its final text reply.
        """
        if self._ladder is None:
            raise LLMNotConfigured("No LLM tier ladder is configured.")

        messages = self._bound_context(messages)
        required = _estimate_tokens(messages) + (max_tokens or 0)
        idx = min(max(0, start_tier - 1), len(self._ladder) - 1)
        if self._ladder.at(idx).context_window < required:
            fit = self._ladder.first_fitting(required, from_index=idx)
            if fit is None:
                raise LLMLadderExhausted(
                    f"Prompt needs ~{required} tokens; no tier's context window fits."
                )
            idx = fit

        last_error: Exception | None = None
        while idx < len(self._ladder):
            tier = self._ladder.at(idx)
            try:
                return self._call_tier_with_tools(tier, idx + 1, messages, tools, max_tokens)
            except _Overflow:
                nxt = self._ladder.first_fitting(required, from_index=idx + 1)
                if nxt is None:
                    raise LLMLadderExhausted(
                        "Context overflow and no larger tier available.",
                    ) from None
                idx = nxt
                continue
            except (httpx.HTTPError, LLMNotConfigured, LLMRateLimited, ValueError) as exc:
                last_error = exc
                log.warning("llm_tool_tier_failed", tier=idx + 1, error=str(exc))
                idx += 1
                continue

        raise LLMLadderExhausted(
            "Tier ladder exhausted; top tier is the ceiling.",
            last_error=last_error,
        )

    def _call_tier_with_tools(
        self,
        tier: TierConfig,
        tier_no: int,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        max_tokens: int | None,
    ) -> ToolCallResult:
        if _estimate_tokens(messages) > tier.context_window:
            raise _Overflow()
        # Per-provider rate gate (FR-DUR-2, #48): a disabled limiter is a no-op.
        self._gate_rate_limit(tier)
        profile = get_profile(tier.provider, tier.base_url)
        base = _normalize_base(tier.base_url)
        url = profile.chat_url(base)

        payload: dict[str, Any] = {
            "model": tier.model,
            "messages": [_tool_message_dict(m) for m in messages],
            "tools": tools,
            "tool_choice": "auto",
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload = self._apply_prefix_cache(profile, payload)

        with self._client() as client:
            resp = client.post(url, headers=self._headers(tier), json=payload)
            if resp.status_code in (400, 413, 422) and self._is_context_error(resp):
                raise _Overflow()
            resp.raise_for_status()
            raw = resp.json()
        if not isinstance(raw, dict):
            raw = {}
        calls = [
            ToolCall(id=cid, name=name, arguments=args)
            for cid, name, args in profile.parse_tool_calls(raw)
        ]
        text = "" if calls else profile.extract_text(raw)
        return ToolCallResult(
            text=text,
            tool_calls=tuple(calls),
            tier=tier_no,
            model=tier.model,
            raw=raw,
        )
