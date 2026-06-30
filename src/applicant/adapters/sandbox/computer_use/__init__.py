"""Computer-use (desktop control) adapters — ``FR-CUA`` (docs/spec/computer-use.md).

Swappable driven sub-port of the sandbox (FR-CUA-2). Two adapters:

* :class:`~applicant.adapters.sandbox.computer_use.noop.NoopComputerUse` — records
  calls, no side effects; the test/CI **default** backend. Still enforces the core
  guards so a blocked action raises even with no real desktop.
* :class:`~applicant.adapters.sandbox.computer_use.cua_driver.CuaDriverComputerUse` —
  the real adapter that would spawn the TryCUA ``cua-driver mcp`` child over stdio
  inside the sandbox; degrades to ``noop`` semantics when the driver binary is absent.

:func:`build_computer_use` selects by ``COMPUTER_USE_BACKEND`` (``noop`` default,
``cua`` real).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from applicant.adapters.sandbox.computer_use.noop import NoopComputerUse

if TYPE_CHECKING:  # pragma: no cover - typing only
    # ``Settings`` is NOT imported (adapters may not import ``applicant.app`` —
    # hexagonal layering, NFR-ARCH-1); the factory duck-types the settings object.
    from applicant.ports.driven.computer_use import ComputerUsePort

#: Backend identifiers for ``COMPUTER_USE_BACKEND`` (mirrors the config constants).
COMPUTER_USE_BACKEND_NOOP = "noop"
COMPUTER_USE_BACKEND_CUA = "cua"


def build_computer_use(settings: Any) -> ComputerUsePort:
    """Select the computer-use adapter by ``COMPUTER_USE_BACKEND`` (FR-CUA-2).

    ``noop`` (default) → :class:`NoopComputerUse` (no side effects; CI/test default).
    ``cua`` → :class:`CuaDriverComputerUse` (the real TryCUA ``cua-driver`` adapter,
    which itself degrades to noop semantics when the driver binary is missing from the
    sandbox image, FR-CUA-12). Import-safe: the real adapter pulls in no heavy deps at
    import and never spawns a subprocess just to construct.
    """
    backend = (settings.computer_use_backend or "").strip().lower()
    if backend == COMPUTER_USE_BACKEND_CUA:
        from applicant.adapters.sandbox.computer_use.cua_driver import CuaDriverComputerUse

        return CuaDriverComputerUse(
            driver_cmd=settings.cua_driver_cmd or None,
            mode=settings.computer_use_mode,
            approvals=settings.computer_use_approvals,
            telemetry=settings.cua_telemetry,
            engine_submit_authorized=False,
            automated_accounts_enabled=settings.allow_automated_accounts,
            force_available=settings.cua_driver_override_available,
        )
    return NoopComputerUse(
        mode=settings.computer_use_mode,
        automated_accounts_enabled=settings.allow_automated_accounts,
    )


__all__ = [
    "COMPUTER_USE_BACKEND_CUA",
    "COMPUTER_USE_BACKEND_NOOP",
    "NoopComputerUse",
    "build_computer_use",
]
