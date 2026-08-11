"""Count an unusable response (misformat / repeat) as a struggle signal.

Mirrors the core stopper's message-detection so only genuine misformat/repeat warnings count.
Runs at _50, before the core stopper (_90) and local-loop-suspend (_95). Self-contained; state
on agent.loop_data.params_persistent. Fail-safe.
"""
from helpers.extension import Extension

STRUGGLE_KEY = "_escalate_struggle"


class EscalateTrackWarning(Extension):
    def execute(self, data: dict | None = None, **kwargs):
        try:
            if not self.agent or not isinstance(data, dict):
                return
            call_kwargs = data.get("kwargs")
            message = call_kwargs.get("message") if isinstance(call_kwargs, dict) else None
            call_args = data.get("args")
            if message is None and isinstance(call_args, tuple) and len(call_args) > 1:
                message = call_args[1]
            if not isinstance(message, str):
                return
            if message not in {
                self.agent.read_prompt("fw.msg_misformat.md"),
                self.agent.read_prompt("fw.msg_repeat.md"),
            }:
                return  # some other warning -> not an unusable-response struggle
            d = getattr(getattr(self.agent, "loop_data", None), "params_persistent", None)
            if isinstance(d, dict):
                d[STRUGGLE_KEY] = int(d.get(STRUGGLE_KEY, 0)) + 1
        except Exception:
            return
