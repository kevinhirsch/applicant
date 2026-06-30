"""Real computer-use adapter — TryCUA ``cua-driver`` over MCP/stdio (FR-CUA-2).

Skeleton of the default real adapter, lifted from the Hermes Agent (MIT) computer-use
feature: it would spawn a ``cua-driver mcp`` child over stdio **inside the sandbox**
and translate the bounded port calls into the driver's MCP tools (see
docs/spec/computer-use.md §4 and docs/adr/0005-computer-use-cua-driver.md).

This file keeps every subprocess / MCP interaction **lazy and guarded** so it imports
and constructs with no extra dependencies:

* The driver binary is detected via :func:`shutil.which` (overridable with the
  ``CUA_DRIVER_CMD`` setting). If absent, the adapter **degrades to noop semantics**
  with a clear one-time warning — mirroring the project's "shell out / silently degrade
  unless baked into the image" gotcha, but loudly (FR-CUA-12). It never raises at
  import or construction just because the driver is missing.
* The core guards (FR-CUA-3/5/6) are applied BEFORE any action would be dispatched, so
  a blocked action is denied whether or not a real driver is present.

Wiring the live MCP transport is deferred to the integration leg (``@pytest.mark.
integration``, skip-when-absent); a skip there signals the deployed sandbox image needs
the driver baked in, not a test quirk.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from typing import Any

from applicant.adapters.sandbox.computer_use.noop import NoopComputerUse
from applicant.core.rules.computer_use import (
    ensure_desktop_action_allowed,
    ensure_key_combo_allowed,
    ensure_type_text_allowed,
    no_secret_typing,
)
from applicant.ports.driven.computer_use import (
    CaptureMode,
    CaptureResult,
    DesktopAction,
    DesktopActionResult,
    HealthReport,
)

logger = logging.getLogger(__name__)

#: Default driver command (upstream ``cua-driver``); overridable via ``CUA_DRIVER_CMD``.
_DEFAULT_DRIVER_CMD = "cua-driver"


class CuaDriverComputerUse:
    """``ComputerUsePort`` adapter backed by the TryCUA ``cua-driver`` (FR-CUA-2).

    Detects the driver binary; degrades to noop semantics when it is missing (FR-CUA-12)
    so the engine boots and runs without the desktop stack. All MCP/subprocess calls are
    lazy; the safety guards are applied unconditionally.
    """

    backend = "cua"

    def __init__(
        self,
        *,
        driver_cmd: str | None = None,
        mode: str = "som",
        approvals: str = "manual",
        telemetry: bool = False,
        engine_submit_authorized: bool = False,
        automated_accounts_enabled: bool = False,
        driver_override_available: str | None = None,
    ) -> None:
        self._driver_cmd = (driver_cmd or _DEFAULT_DRIVER_CMD).strip() or _DEFAULT_DRIVER_CMD
        self._mode = (mode or "som").strip().lower()
        self._approvals = (approvals or "manual").strip().lower()
        self._telemetry = bool(telemetry)
        self._engine_submit_authorized = engine_submit_authorized
        self._automated_accounts_enabled = automated_accounts_enabled
        self._driver_override_available = (driver_override_available or '').strip().lower()
        #: Resolved absolute driver path (lazy, cached); None until probed.
        self._resolved_cmd: str | None = None
        self._probed = False
        #: Fallback used when the driver binary is absent — keeps guards + recording.
        self._fallback = NoopComputerUse(
            mode=self._mode,
            engine_submit_authorized=engine_submit_authorized,
            automated_accounts_enabled=automated_accounts_enabled,
        )
        #: The live MCP session handle, created lazily on first real action.
        self._session: _McpStdioSession | None = None
        #: Test/seam hook: when set, used instead of spawning the real ``cua-driver mcp``
        #: child — lets the JSON-RPC framing + vocabulary mapping be exercised hermetically
        #: without the binary. Production leaves this ``None`` (a real child is spawned).
        self._session_factory = None

    # --- driver detection (lazy) ----------------------------------------
    def _driver_path(self) -> str | None:
        """Resolve the driver binary once (``shutil.which``); cache the result."""
        if not self._probed:
            self._probed = True
            self._resolved_cmd = shutil.which(self._driver_cmd)
            if self._resolved_cmd is None:
                # Loud, one-time warning: a missing driver is a deploy/image signal, not
                # a silent degrade (FR-CUA-12). No upstream codename in any user copy.
                logger.warning(
                    "Desktop-assist driver not found on PATH (%r); the desktop backend "
                    "is degraded to no-op until it is baked into the sandbox image.",
                    self._driver_cmd,
                )
        return self._resolved_cmd

    @property
    def _available(self) -> bool:
        # CUA_DRIVER_OVERRIDE_AVAILABLE can force availability on/off for tests.
        ov = self._driver_override_available
        if ov in ('1', 'true', 'on'):
            return True
        if ov in ('0', 'false', 'off'):
            return False
        return self._driver_path() is not None

    # --- read-only -------------------------------------------------------
    def capture(self, mode: CaptureMode = CaptureMode.SOM) -> CaptureResult:
        """Capture the desktop (read-only). Degrades to a benign empty capture."""
        if not self._available:
            return self._fallback.capture(mode)
        return self._mcp_capture(mode)  # pragma: no cover - integration (real driver)

    # --- destructive (guarded) -------------------------------------------
    def click(self, element_token: str, *, intent: str | None = None) -> DesktopActionResult:
        ensure_desktop_action_allowed(
            DesktopAction.CLICK,
            intent=intent,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        if not self._available:
            return self._fallback.click(element_token, intent=intent)
        return self._mcp_action(  # pragma: no cover - integration (real driver)
            DesktopAction.CLICK, element_token=element_token
        )

    def type_text(
        self, text: str, *, is_secret: bool = False, intent: str | None = None
    ) -> DesktopActionResult:
        no_secret_typing(is_secret=is_secret)  # FR-CUA-6
        ensure_type_text_allowed(text)  # FR-CUA-5
        ensure_desktop_action_allowed(
            DesktopAction.TYPE_TEXT,
            intent=intent,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        if not self._available:
            return self._fallback.type_text(text, is_secret=is_secret, intent=intent)
        return self._mcp_action(DesktopAction.TYPE_TEXT, text=text)  # pragma: no cover

    def key(self, keys: str, *, intent: str | None = None) -> DesktopActionResult:
        ensure_key_combo_allowed(keys)  # FR-CUA-5
        ensure_desktop_action_allowed(
            DesktopAction.KEY,
            intent=intent,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        if not self._available:
            return self._fallback.key(keys, intent=intent)
        return self._mcp_action(DesktopAction.KEY, keys=keys)  # pragma: no cover

    def scroll(self, element_token: str, *, dy: int = 0, dx: int = 0) -> DesktopActionResult:
        ensure_desktop_action_allowed(
            DesktopAction.SCROLL,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        if not self._available:
            return self._fallback.scroll(element_token, dy=dy, dx=dx)
        return self._mcp_action(  # pragma: no cover - integration (real driver)
            DesktopAction.SCROLL, element_token=element_token, dy=dy, dx=dx
        )

    def drag(self, from_token: str, to_token: str) -> DesktopActionResult:
        ensure_desktop_action_allowed(
            DesktopAction.DRAG,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        if not self._available:
            return self._fallback.drag(from_token, to_token)
        return self._mcp_action(  # pragma: no cover - integration (real driver)
            DesktopAction.DRAG, from_token=from_token, to_token=to_token
        )

    def focus_app(self, app: str) -> DesktopActionResult:
        # FR-CUA-7: the driver uses BACKGROUND, pid-scoped focus — no cursor/window steal.
        ensure_desktop_action_allowed(
            DesktopAction.FOCUS_APP,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        if not self._available:
            return self._fallback.focus_app(app)
        return self._mcp_action(DesktopAction.FOCUS_APP, app=app)  # pragma: no cover

    # --- preflight (FR-CUA-12) -------------------------------------------
    def health(self) -> HealthReport:
        """Driver preflight; a missing driver is a deploy/image signal (FR-CUA-12)."""
        if not self._available:
            return HealthReport(
                ok=False,
                backend=self.backend,
                detail=(
                    "Desktop-assist driver is not installed in the sandbox image; "
                    "running degraded (no real desktop control)."
                ),
                missing=(self._driver_cmd,),
            )
        return self._mcp_health()  # pragma: no cover - integration (real driver)

    # --- MCP transport ---------------------------------------------------
    def _ensure_session(self) -> _McpStdioSession:
        """Open (once) the ``cua-driver mcp`` stdio session, or the injected fake."""
        if self._session is None:
            if self._session_factory is not None:
                self._session = self._session_factory()
            else:  # pragma: no cover - spawns the real driver (integration only)
                env = dict(os.environ)
                # Driver anonymous telemetry OFF unless explicitly opted in (FR-CUA,
                # mirrors upstream ``CUA_DRIVER_RS_TELEMETRY_ENABLED``).
                env["CUA_DRIVER_RS_TELEMETRY_ENABLED"] = "1" if self._telemetry else "0"
                self._session = _McpStdioSession(
                    [self._driver_path() or self._driver_cmd, "mcp"], env=env
                )
            self._session.start()
        return self._session

    def _mcp_capture(self, mode: CaptureMode) -> CaptureResult:
        """Run the read-only ``capture`` tool and map its MCP result to ``CaptureResult``."""
        result = self._ensure_session().call_tool(
            _TOOL_NAMES[DesktopAction.CAPTURE], {"mode": mode.value}
        )
        image_b64, ax_tree = "", ""
        for part in result.get("content", []) or []:
            ptype = part.get("type")
            if ptype == "image":
                image_b64 = part.get("data", "") or ""
            elif ptype == "text":
                ax_tree = (ax_tree + "\n" + part.get("text", "")).strip()
        # ``element_count`` is reported in the structured payload when present (SOM marks).
        structured = result.get("structuredContent") or {}
        element_count = int(structured.get("element_count", 0) or 0)
        return CaptureResult(
            mode=mode, element_count=element_count, image_b64=image_b64, ax_tree=ax_tree
        )

    def _mcp_action(self, action: DesktopAction, **kwargs: Any) -> DesktopActionResult:
        """Dispatch one destructive action via its MCP tool (guards already applied)."""
        result = self._ensure_session().call_tool(_TOOL_NAMES[action], kwargs)
        detail = ""
        for part in result.get("content", []) or []:
            if part.get("type") == "text":
                detail = part.get("text", "") or ""
                break
        return DesktopActionResult(
            action=action, performed=not result.get("isError", False), detail=detail
        )

    def _mcp_health(self) -> HealthReport:
        """Run the driver's ``health_report`` MCP tool (FR-CUA-12 preflight)."""
        try:
            result = self._ensure_session().call_tool(_HEALTH_TOOL, {})
        except _McpError as exc:  # transport/handshake failure is itself a health failure
            return HealthReport(
                ok=False, backend=self.backend, detail=f"driver preflight failed: {exc}"
            )
        structured = result.get("structuredContent") or {}
        ok = not result.get("isError", False) and bool(structured.get("ok", True))
        detail = ""
        for part in result.get("content", []) or []:
            if part.get("type") == "text":
                detail = part.get("text", "") or ""
                break
        missing = tuple(structured.get("missing", []) or [])
        return HealthReport(ok=ok, backend=self.backend, detail=detail, missing=missing)

    def close(self) -> None:
        """Best-effort teardown of the driver child (called on sandbox teardown)."""
        if self._session is not None:
            self._session.close()
            self._session = None


class _McpError(RuntimeError):
    """A JSON-RPC/MCP error or transport failure talking to the driver."""


class _McpStdioSession:
    """Minimal JSON-RPC 2.0 / MCP client over a child process's stdio.

    Speaks the standard MCP stdio framing (newline-delimited JSON-RPC): an
    ``initialize`` handshake, a ``notifications/initialized`` notification, then
    ``tools/call`` per action. A daemon reader thread demultiplexes responses by ``id``
    so synchronous calls can wait with a timeout. This is the real protocol — the only
    driver-specific assumption is the tool *names* (``_TOOL_NAMES``), which ``start``
    validates against the driver's own ``tools/list`` and warns on mismatch.
    """

    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, argv: list[str], *, env: dict | None = None, timeout: float = 30.0):
        self._argv = argv
        self._env = env
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, dict] = {}
        self._reader: threading.Thread | None = None

    # -- lifecycle --
    def start(self) -> None:
        if self._proc is not None:
            return
        # argv is engine-controlled (the resolved driver path + "mcp"), never user input.
        self._proc = subprocess.Popen(
            self._argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self._env,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._rpc(
            "initialize",
            {
                "protocolVersion": self._PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "applicant", "version": "1"},
            },
        )
        self._notify("notifications/initialized", {})
        # Validate our tool-name map against what the driver actually exposes.
        try:
            available = self.list_tools()
            expected = set(_TOOL_NAMES.values()) | {_HEALTH_TOOL}
            missing = expected - available
            if missing:
                logger.warning(
                    "cua-driver MCP is missing expected tool(s) %s; reconcile _TOOL_NAMES.",
                    sorted(missing),
                )
        except _McpError:  # pragma: no cover - non-fatal; tools/call still attempted
            logger.warning("cua-driver MCP tools/list unavailable; proceeding optimistically.")

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:  # pragma: no cover - process teardown
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # best-effort teardown — never raise on the way down
            proc.kill()

    # -- protocol --
    def list_tools(self) -> set[str]:
        result = self._rpc("tools/list", {})
        return {t.get("name", "") for t in result.get("tools", []) or []}

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _rpc(self, method: str, params: dict) -> dict:
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            event = threading.Event()
            self._pending[msg_id] = event
        self._write({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        if not event.wait(self._timeout):
            self._pending.pop(msg_id, None)
            raise _McpError(f"timeout waiting for response to {method!r}")
        msg = self._results.pop(msg_id, {})
        if "error" in msg:
            raise _McpError(f"{method}: {msg['error']}")
        return msg.get("result", {}) or {}

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, obj: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise _McpError("driver session is not running")
        try:
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:  # pragma: no cover - transport loss
            raise _McpError(f"driver write failed: {exc}") from exc

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:  # exits when the child closes stdout (on close/kill)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # driver log noise on the wire — ignore non-JSON lines
            msg_id = msg.get("id")
            if msg_id is None:
                continue  # a notification/request from the server — nothing to resolve
            self._results[msg_id] = msg
            event = self._pending.pop(msg_id, None)
            if event is not None:
                event.set()


#: Map the bounded vocabulary onto the driver's MCP tool names (documented cua-driver /
#: Hermes Agent computer-use vocabulary). ``_McpStdioSession.start`` validates these
#: against the driver's real ``tools/list`` and warns on any mismatch — reconcile here
#: if upstream renames a tool.
_TOOL_NAMES = {
    DesktopAction.CAPTURE: "capture",
    DesktopAction.CLICK: "click",
    DesktopAction.TYPE_TEXT: "type",
    DesktopAction.KEY: "key",
    DesktopAction.SCROLL: "scroll",
    DesktopAction.DRAG: "drag",
    DesktopAction.FOCUS_APP: "focus_app",
}
_HEALTH_TOOL = "health_report"
