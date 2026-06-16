"""Persistence sink for the tool registry (FR-UI-4).

Backs ``ToolRegistry`` with the ``tool_settings`` table so per-tool on/off toggles
survive restarts. ``load()`` returns the persisted state (empty on first boot);
``save()`` upserts every tool row. The in-memory variant keeps the contract for
hermetic tests / no-DB boot.
"""

from __future__ import annotations

from typing import Any


class InMemoryToolSettingsSink:
    """Default sink (hermetic; no DB). Holds toggle state in a dict."""

    def __init__(self) -> None:
        self._d: dict[str, bool] = {}

    def load(self) -> dict[str, bool]:
        return dict(self._d)

    def save(self, state: dict[str, bool]) -> None:
        self._d = {k: bool(v) for k, v in state.items()}


class SqlAlchemyToolSettingsSink:
    """Tool-settings sink backed by the ``tool_settings`` table (FR-UI-4)."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def load(self) -> dict[str, bool]:
        from sqlalchemy import select

        from applicant.adapters.storage import models as m

        rows = self._session.execute(select(m.ToolSettingModel)).scalars().all()
        return {row.tool_key: bool(row.enabled) for row in rows}

    def save(self, state: dict[str, bool]) -> None:
        from sqlalchemy import select

        from applicant.adapters.storage import models as m

        for tool_key, enabled in state.items():
            row = self._session.execute(
                select(m.ToolSettingModel).where(m.ToolSettingModel.tool_key == tool_key)
            ).scalar_one_or_none()
            if row is None:
                row = m.ToolSettingModel(id=tool_key, tool_key=tool_key, enabled=bool(enabled))
                self._session.add(row)
            else:
                row.enabled = bool(enabled)
        self._session.commit()
