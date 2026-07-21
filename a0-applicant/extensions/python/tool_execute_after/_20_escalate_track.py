"""Tool-result struggle tracker: a failing tool call bumps struggle; a clean one resets it.

High-precision failure markers (same set as _loop_breaker) avoid false positives. Runs at _20
(before the failure-streak breaker at _30). A successful tool call means the agent produced a valid
envelope AND made progress -> reset struggle so the next call reverts to local. Self-contained;
state on agent.loop_data.params_persistent. Fail-safe.
"""
from helpers.extension import Extension

STRUGGLE_KEY = "_escalate_struggle"

_FAIL = (
    "traceback (most recent call last)", "command not found", "no such file or directory",
    "permission denied", "non-zero exit", "returned non-zero", "exit code: 1", "exit status 1",
    "modulenotfounderror", "importerror", "syntaxerror", "nameerror",
    "typeerror:", "valueerror:", "keyerror:", "attributeerror:",
    "fatal:", "connection refused", "connection error", "timed out",
    "npm err!", "error: cannot find module", "segmentation fault", "assertionerror",
)


def _looks_failed(msg: str) -> bool:
    m = (msg or "").lower()
    return any(p in m for p in _FAIL)


class EscalateTrackTool(Extension):
    async def execute(self, response=None, **kwargs):
        try:
            if not self.agent or response is None:
                return
            d = getattr(getattr(self.agent, "loop_data", None), "params_persistent", None)
            if not isinstance(d, dict):
                return
            if getattr(response, "break_loop", False):
                d[STRUGGLE_KEY] = 0
                return
            if _looks_failed(getattr(response, "message", "") or ""):
                d[STRUGGLE_KEY] = int(d.get(STRUGGLE_KEY, 0)) + 1
            else:
                d[STRUGGLE_KEY] = 0   # progress -> revert to local next call
        except Exception:
            return
