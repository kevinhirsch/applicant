"""Tool-settings persistence (FR-UI-4): toggles survive a registry rebuild.

The ToolRegistry persists through a sink to ``tool_settings`` (SQLAlchemy) or an
in-memory dict; a disabled tool stays disabled across restarts, and dispatch
enforcement honours the persisted state.
"""

from __future__ import annotations

import pytest

from applicant.adapters.tools.tool_registry import ToolDisabledError, ToolRegistry
from applicant.adapters.tools.tool_settings_sink import (
    InMemoryToolSettingsSink,
    SqlAlchemyToolSettingsSink,
)


def test_inmemory_sink_persists_toggle_across_rebuild():
    sink = InMemoryToolSettingsSink()
    reg = ToolRegistry(sink=sink)
    reg.set_enabled("discovery", False)

    # A fresh registry over the same sink loads the persisted toggle.
    reloaded = ToolRegistry(sink=sink)
    assert reloaded.is_enabled("discovery") is False
    with pytest.raises(ToolDisabledError):
        reloaded.ensure_enabled("discovery")


def test_sqlalchemy_sink_persists_to_tool_settings_table(sqlite_storage):
    session = sqlite_storage._session
    sink = SqlAlchemyToolSettingsSink(session)
    reg = ToolRegistry(sink=sink)
    reg.set_enabled("notifications", False)
    reg.set_enabled("chat", False)

    # New sink + registry over the same DB session sees the persisted rows.
    reloaded = ToolRegistry(sink=SqlAlchemyToolSettingsSink(session))
    assert reloaded.is_enabled("notifications") is False
    assert reloaded.is_enabled("chat") is False
    assert reloaded.is_enabled("discovery") is True  # untouched defaults stay enabled
