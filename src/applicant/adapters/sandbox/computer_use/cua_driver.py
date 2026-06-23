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

import logging
import shutil

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
    ) -> None:
        self._driver_cmd = (driver_cmd or _DEFAULT_DRIVER_CMD).strip() or _DEFAULT_DRIVER_CMD
        self._mode = (mode or "som").strip().lower()
        self._approvals = (approvals or "manual").strip().lower()
        self._telemetry = bool(telemetry)
        self._engine_submit_authorized = engine_submit_authorized
        self._automated_accounts_enabled = automated_accounts_enabled
        #: Resolved absolute driver path (lazy, cached); None until probed.
        self._resolved_cmd: str | None = None
        self._probed = False
        #: Fallback used when the driver binary is absent — keeps guards + recording.
        self._fallback = NoopComputerUse(
            mode=self._mode,
            engine_submit_authorized=engine_submit_authorized,
            automated_accounts_enabled=automated_accounts_enabled,
        )
        #: The live MCP session handle, created lazily on first real action. The actual
        #: ``cua-driver mcp`` stdio transport is wired in the integration leg.
        self._session = None

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

    # --- MCP transport (integration-only; wired in the integration leg) --
    def _mcp_capture(self, mode: CaptureMode) -> CaptureResult:  # pragma: no cover
        raise NotImplementedError(
            "Live cua-driver MCP transport is wired in the integration leg."
        )

    def _mcp_action(self, action: DesktopAction, **_kwargs) -> DesktopActionResult:  # pragma: no cover
        raise NotImplementedError(
            "Live cua-driver MCP transport is wired in the integration leg."
        )

    def _mcp_health(self) -> HealthReport:  # pragma: no cover
        raise NotImplementedError(
            "Live cua-driver MCP transport is wired in the integration leg."
        )
