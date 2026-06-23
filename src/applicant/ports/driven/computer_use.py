"""ComputerUse (desktop control) port — ``FR-CUA`` (docs/spec/computer-use.md).

Background **computer use**: agentic control of a full desktop (click / type /
scroll / drag over the OS accessibility tree, not just the browser DOM) confined to
the engine-provisioned sandbox/takeover surface (FR-CUA-1). This is the lifted
desktop action vocabulary from the Hermes Agent (MIT) computer-use feature, reduced
to what Applicant needs and wired behind a swappable driven sub-port of the sandbox
(FR-CUA-2, sibling of the browser + remote-view sub-ports).

The bounded action vocabulary (spec §4):

* ``capture`` (``som``/``ax``) — screenshot with numbered elements, or AX-tree only;
  always allowed (read-only).
* ``click`` / ``type_text`` / ``key`` / ``scroll`` / ``drag`` / ``focus_app`` —
  destructive actions, approval-gated (FR-CUA-4), and additionally hard-blocked
  (FR-CUA-5) / no-secret-gated (FR-CUA-6) / stop-boundary-gated (FR-CUA-3) in the
  pure core (``applicant.core.rules.computer_use``).

The adapters (``adapters/sandbox/computer_use/``) MUST call the core guards before
any side effect so the boundary cannot be bypassed by an adapter — exactly as the
browser pre-fill adapter calls ``prefill_boundary.ensure_action_allowed``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# The action vocabulary is DOMAIN vocabulary and lives in the pure core so the core
# guards (``core.rules.computer_use``) depend on nothing outward (hexagonal layering,
# NFR-ARCH-1: core may not import ports). The port re-exports it so adapters/callers
# can keep importing ``DesktopAction`` / ``CaptureMode`` from here.
from applicant.core.rules.computer_use import CaptureMode, DesktopAction

__all__ = [
    "CaptureMode",
    "DesktopAction",
    "CaptureResult",
    "DesktopActionResult",
    "HealthReport",
    "ComputerUsePort",
]


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of a ``capture`` call (read-only) (FR-CUA, spec §4)."""

    mode: CaptureMode
    #: Number of marked/labelled elements available to reference (SOM) — 0 for AX-only.
    element_count: int = 0
    #: Opaque base64 screenshot payload (SOM); empty for ``ax`` mode. Never logged raw.
    image_b64: str = ""
    #: Flat accessibility-tree text (AX), or an empty string in ``som`` mode.
    ax_tree: str = ""


@dataclass(frozen=True)
class DesktopActionResult:
    """Outcome of a destructive desktop action (FR-CUA-8: logged + screenshotted)."""

    action: DesktopAction
    #: Whether the driver reports the action was dispatched.
    performed: bool = True
    #: Free-form driver detail (e.g. the element token acted on), for the action log.
    detail: str = ""


@dataclass(frozen=True)
class HealthReport:
    """Driver preflight (``health_report``) result (FR-CUA-12).

    A failure is a DEPLOY/IMAGE signal — the driver or a display dependency is
    missing from the sandbox image — not a per-request error.
    """

    ok: bool
    #: Backend identifier (``noop``/``cua``) so ops can see which adapter answered.
    backend: str
    #: Human-readable detail for the ops/Debug surface (no codenames in user copy).
    detail: str = ""
    #: Missing/blocking dependencies (e.g. the driver binary, the display stack).
    missing: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class ComputerUsePort(Protocol):
    """Driven port for bounded desktop control inside the sandbox (FR-CUA-2).

    Implementations MUST enforce the core guards (stop-boundary FR-CUA-3, hard-blocks
    FR-CUA-5, no-secret-typing FR-CUA-6) BEFORE any side effect — the ground truth is
    derived in the core, never opted in by a caller-supplied flag (FR-CUA-3).
    """

    def capture(self, mode: CaptureMode = CaptureMode.SOM) -> CaptureResult:
        """Capture the desktop (read-only; always allowed) (spec §4, FR-CUA-11)."""
        ...

    def click(self, element_token: str) -> DesktopActionResult:
        """Activate a control by its opaque ``element_token`` (approval-gated)."""
        ...

    def type_text(self, text: str, *, is_secret: bool = False) -> DesktopActionResult:
        """Type ``text`` (pattern-blocked FR-CUA-5; no-secrets FR-CUA-6).

        ``is_secret`` is the adapter-supplied PROVENANCE of the value (whether it came
        from the vault / a sensitive field), not a caller bypass — a secret value is
        refused regardless (FR-CUA-6).
        """
        ...

    def key(self, keys: str) -> DesktopActionResult:
        """Press a key/chord (combo-blocked FR-CUA-5; approval-gated)."""
        ...

    def scroll(self, element_token: str, *, dy: int = 0, dx: int = 0) -> DesktopActionResult:
        """Scroll the targeted view (approval-gated)."""
        ...

    def drag(self, from_token: str, to_token: str) -> DesktopActionResult:
        """Drag from one element to another (approval-gated)."""
        ...

    def focus_app(self, app: str) -> DesktopActionResult:
        """Target a window in the BACKGROUND, no foreground steal (FR-CUA-7)."""
        ...

    def health(self) -> HealthReport:
        """Driver preflight; a failure is a deploy/image signal (FR-CUA-12)."""
        ...
