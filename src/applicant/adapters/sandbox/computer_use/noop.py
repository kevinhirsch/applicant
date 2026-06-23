"""No-op computer-use adapter — the test/CI default (FR-CUA-2).

Records every call in an in-memory list and returns benign results, performing **no**
side effects (no desktop, no driver, no subprocess). It is the DEFAULT backend so the
hermetic lane never needs the TryCUA ``cua-driver`` binary or a display stack.

Crucially it STILL calls the pure core guards before "acting", so a hard-blocked
pattern/combo (FR-CUA-5), a secret value (FR-CUA-6), or a stop-boundary action
(FR-CUA-3) raises even in noop — the safety contract is identical to the real adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class RecordedCall:
    """One recorded desktop call (action + the salient arguments) for assertions/logs."""

    action: DesktopAction
    args: dict


class NoopComputerUse:
    """``ComputerUsePort`` adapter that records calls and performs no side effects.

    The test/CI default (FR-CUA-2). Guards are enforced exactly as in the real adapter
    so behavior under the safety machinery is identical without a desktop.
    """

    backend = "noop"

    def __init__(
        self,
        *,
        mode: str = "som",
        engine_submit_authorized: bool = False,
        automated_accounts_enabled: bool = False,
    ) -> None:
        self._mode = (mode or "som").strip().lower()
        # Server-derived config threaded through to the boundary (never a caller flag).
        self._engine_submit_authorized = engine_submit_authorized
        self._automated_accounts_enabled = automated_accounts_enabled
        #: Every call, in order — inspected by tests and mirrored to the action log.
        self.calls: list[RecordedCall] = []

    # --- read-only -------------------------------------------------------
    def capture(self, mode: CaptureMode = CaptureMode.SOM) -> CaptureResult:
        """Record a (read-only) capture; always allowed (FR-CUA, spec §4)."""
        self.calls.append(RecordedCall(DesktopAction.CAPTURE, {"mode": mode.value}))
        return CaptureResult(mode=mode, element_count=0, image_b64="", ax_tree="")

    # --- destructive (guarded) -------------------------------------------
    def click(self, element_token: str, *, intent: str | None = None) -> DesktopActionResult:
        ensure_desktop_action_allowed(
            DesktopAction.CLICK,
            intent=intent,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        self.calls.append(
            RecordedCall(DesktopAction.CLICK, {"element_token": element_token, "intent": intent})
        )
        return DesktopActionResult(DesktopAction.CLICK, detail=element_token)

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
        self.calls.append(
            RecordedCall(DesktopAction.TYPE_TEXT, {"len": len(text or ""), "intent": intent})
        )
        return DesktopActionResult(DesktopAction.TYPE_TEXT)

    def key(self, keys: str, *, intent: str | None = None) -> DesktopActionResult:
        ensure_key_combo_allowed(keys)  # FR-CUA-5
        ensure_desktop_action_allowed(
            DesktopAction.KEY,
            intent=intent,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        self.calls.append(RecordedCall(DesktopAction.KEY, {"keys": keys, "intent": intent}))
        return DesktopActionResult(DesktopAction.KEY, detail=keys)

    def scroll(self, element_token: str, *, dy: int = 0, dx: int = 0) -> DesktopActionResult:
        ensure_desktop_action_allowed(
            DesktopAction.SCROLL,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        self.calls.append(
            RecordedCall(DesktopAction.SCROLL, {"element_token": element_token, "dy": dy, "dx": dx})
        )
        return DesktopActionResult(DesktopAction.SCROLL, detail=element_token)

    def drag(self, from_token: str, to_token: str) -> DesktopActionResult:
        ensure_desktop_action_allowed(
            DesktopAction.DRAG,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        self.calls.append(
            RecordedCall(DesktopAction.DRAG, {"from": from_token, "to": to_token})
        )
        return DesktopActionResult(DesktopAction.DRAG)

    def focus_app(self, app: str) -> DesktopActionResult:
        # FR-CUA-7: background, no foreground steal — recorded, never actually focuses.
        ensure_desktop_action_allowed(
            DesktopAction.FOCUS_APP,
            engine_submit_authorized=self._engine_submit_authorized,
            automated_accounts_enabled=self._automated_accounts_enabled,
        )
        self.calls.append(RecordedCall(DesktopAction.FOCUS_APP, {"app": app}))
        return DesktopActionResult(DesktopAction.FOCUS_APP, detail=app)

    # --- preflight -------------------------------------------------------
    def health(self) -> HealthReport:
        """The noop backend is always healthy (it has no external dependency)."""
        return HealthReport(ok=True, backend=self.backend, detail="No-op desktop backend.")
