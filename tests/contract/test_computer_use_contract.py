"""ComputerUsePort contract (FR-CUA-2).

Asserts the behavioral contract a ``ComputerUsePort`` promises: the default
``NoopComputerUse`` satisfies the runtime-checkable Protocol and round-trips the full
bounded vocabulary (capture / click / type / key / scroll / drag / focus-app / health)
with the right result types. The ``cua`` adapter, when constructed without a driver on
PATH, degrades to the same noop semantics under one identical contract.
"""

from __future__ import annotations

import pytest

from applicant.adapters.sandbox.computer_use import build_computer_use
from applicant.adapters.sandbox.computer_use.cua_driver import CuaDriverComputerUse
from applicant.adapters.sandbox.computer_use.noop import NoopComputerUse
from applicant.app.config import Settings
from applicant.ports.driven.computer_use import (
    CaptureMode,
    CaptureResult,
    ComputerUsePort,
    DesktopAction,
    DesktopActionResult,
    HealthReport,
)


@pytest.mark.contract
class TestComputerUseContract:
    @pytest.fixture
    def adapter(self) -> NoopComputerUse:
        return NoopComputerUse()

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, ComputerUsePort)

    def test_cua_adapter_satisfies_port_protocol(self):
        # Constructs with no driver on PATH; still satisfies the Protocol and degrades
        # to noop semantics (no subprocess at construction).
        assert isinstance(CuaDriverComputerUse(), ComputerUsePort)

    def test_vocabulary_round_trips(self, adapter):
        cap = adapter.capture(CaptureMode.SOM)
        assert isinstance(cap, CaptureResult)

        assert isinstance(adapter.click("el-1"), DesktopActionResult)
        assert isinstance(adapter.type_text("hello"), DesktopActionResult)
        assert isinstance(adapter.key("ctrl+c"), DesktopActionResult)
        assert isinstance(adapter.scroll("el-1", dy=10), DesktopActionResult)
        assert isinstance(adapter.drag("el-1", "el-2"), DesktopActionResult)
        assert isinstance(adapter.focus_app("Files"), DesktopActionResult)

        health = adapter.health()
        assert isinstance(health, HealthReport)

    def test_capture_mode_is_honored(self, adapter):
        assert adapter.capture(CaptureMode.AX).mode is CaptureMode.AX

    def test_action_results_carry_their_action(self, adapter):
        assert adapter.click("el-1").action is DesktopAction.CLICK
        assert adapter.focus_app("Files").action is DesktopAction.FOCUS_APP


@pytest.mark.contract
def test_factory_defaults_to_noop():
    adapter = build_computer_use(Settings(_env_file=None))
    assert isinstance(adapter, NoopComputerUse)
    assert isinstance(adapter, ComputerUsePort)


@pytest.mark.contract
def test_factory_selects_cua_backend():
    settings = Settings(_env_file=None, COMPUTER_USE_BACKEND="cua")
    adapter = build_computer_use(settings)
    assert isinstance(adapter, CuaDriverComputerUse)
    assert isinstance(adapter, ComputerUsePort)
    # No driver on PATH in CI -> health reports not-ok (a deploy/image signal, FR-CUA-12).
    assert adapter.health().ok is False
