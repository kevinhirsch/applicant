#!/usr/bin/env python
"""P1-2 live model-call proof — exercises the engine's own LLM adapter end to end.

The pre-fill loop's non-deterministic steps (free-text answers, material tailoring,
parse-verify) are model-backed. This probe proves those calls work against a REAL
provider using the engine's production ``OpenAICompatibleLLM`` tier ladder — the same
class the container wires — so the "live proof" covers the model portion of the loop,
not just the browser.

Credentials and model id come ONLY from the environment and are NEVER printed:

    OPENROUTER_API_KEY   the provider key (sourced into env; never echoed/committed)
    OPENROUTER_MODEL     the model slug to call (kept out of the repo per white-label)
    OPENROUTER_BASE_URL  optional; defaults to the OpenRouter v1 endpoint

Usage:
    set -a; source path/to/openrouter.env; set +a
    OPENROUTER_MODEL=<slug> uv run python scripts/proof/live_model_probe.py

Prints a redacted JSON record (tier, reported token usage, a truncated reply). Exit
non-zero if the call fails or credentials are absent.
"""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("OPENROUTER_MODEL", "").strip()
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
    if not key or not model:
        print(
            "SKIP: set OPENROUTER_API_KEY and OPENROUTER_MODEL to run the live model probe.",
            file=sys.stderr,
        )
        return 3

    from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
    from applicant.ports.driven.llm import ChatMessage

    llm = OpenAICompatibleLLM(
        provider="openrouter",
        base_url=base_url,
        api_key=key,
        model=model,
        context_window=8192,
        timeout=60.0,
    )
    # A benign, loop-representative task: answer a short application free-text
    # question from stored résumé facts (no PII, no fabrication) — the same shape of
    # call the pre-fill loop makes before a human reviews the answer.
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You help a candidate answer job-application questions truthfully and "
                "concisely, using only the facts provided. Reply in one short sentence."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                "Facts: 6 years backend Python, led a payments migration. "
                "Question: Why are you a good fit for a senior backend role?"
            ),
        ),
    ]
    started = time.monotonic()
    try:
        res = llm.complete(messages)
    except Exception as exc:
        # Keep the failure record REDACTED: only the exception *type* is emitted.
        # The message of an HTTP/provider error can carry response bodies or echoed
        # request headers, so it is never printed — same posture as the credential.
        record = {
            "ok": False,
            "provider": "openrouter",
            "base_url": base_url,
            "error_type": type(exc).__name__,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "credential_printed": False,
        }
        print(json.dumps(record, indent=2))
        return 1
    elapsed = round(time.monotonic() - started, 2)

    record = {
        "ok": True,
        "provider": "openrouter",
        "base_url": base_url,
        "tier_used": getattr(res, "tier", None),
        "reported_usage": getattr(res, "usage", None),
        "elapsed_seconds": elapsed,
        "reply_preview": (res.text or "").strip()[:280],
        "credential_printed": False,
    }
    print(json.dumps(record, indent=2))
    return 0 if (res.text or "").strip() else 1


if __name__ == "__main__":
    raise SystemExit(main())
