"""
context_estimate — deterministically size a step's context and recommend local vs cloud.

The local Qwen box has a measured envelope (see ~/Desktop/vLLM-Benchmarks.md): it is fast
below ~40K tokens, usable-but-slow to ~96K, and cannot go past ~96K (ctx cap) or run two
long-context requests at once (OOM). This tool counts the real size of the files/text a step
will consume (chars ÷ 3.5, conservative for code) + a base for the system prompt, and returns
a routing recommendation — so the overseer routes on measured size, not a guess.
"""
from __future__ import annotations

import glob
import json
import os

from helpers.tool import Tool, Response

# Benchmark-derived thresholds (tokens).
_DUAL_OK = 40000      # below this: local, and 2 concurrent local steps are efficient
_LOCAL_MAX = 90000    # below this: local single-file; above: must go cloud (local ctx cap ~96K)
_CHARS_PER_TOKEN = 3.5  # conservative (slightly over-estimates) for source code


def _as_list(x):
    if isinstance(x, list):
        return x
    s = str(x or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            v = json.loads(s)
            return v if isinstance(v, list) else [s]
        except Exception:
            pass
    return [p.strip() for p in s.replace(",", " ").split() if p.strip()]


class ContextEstimate(Tool):
    async def execute(self, paths="", text="", base_tokens=9000, **kwargs) -> Response:
        chars, counted = 0, 0
        for item in _as_list(paths):
            try:
                for f in glob.glob(item, recursive=True):
                    if os.path.isfile(f):
                        chars += os.path.getsize(f)
                        counted += 1
            except Exception:
                pass
        chars += len(str(text or ""))
        try:
            base = int(base_tokens)
        except Exception:
            base = 9000
        est = int(chars / _CHARS_PER_TOKEN) + base

        if est < _DUAL_OK:
            rec = "LOCAL — use coder/explorer; safe to run up to 2 concurrent local steps."
        elif est < _LOCAL_MAX:
            rec = ("LOCAL-SINGLE — use coder/explorer but run it ALONE (never pair two local "
                   "steps this large: the local model slows sharply and 2 concurrent long-context "
                   "requests crash the server).")
        else:
            rec = ("CLOUD — exceeds the local ~96K practical limit; route to coder-cloud / "
                   "explorer-cloud (DeepSeek). Or split the inputs into focused <40K chunks and "
                   "keep them local.")

        return Response(message=json.dumps({
            "estimated_tokens": est,
            "files_counted": counted,
            "recommendation": rec,
            "thresholds": {"local_dual_below": _DUAL_OK, "local_single_below": _LOCAL_MAX,
                           "chars_per_token": _CHARS_PER_TOKEN},
        }, indent=2), break_loop=False)
