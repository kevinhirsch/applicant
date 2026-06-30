"""App-config key/value store (FR-LLM-2/3, FR-OOBE).

Backs the OOBE wizard's persisted state: the LLM tier ladder, wizard step
completion, and other small JSON settings live in the ``app_config`` table when a
SQLAlchemy session is available, and in an in-memory dict otherwise (tests /
first boot without Postgres). Secrets (api keys) are NOT stored here in plaintext;
the SetupService routes those through the encrypted credential store and persists
only a placeholder marker.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AppConfigStore(Protocol):
    """Tiny JSON key/value store keyed by string."""

    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any]) -> None: ...


class InMemoryAppConfigStore:
    """Default app-config store (hermetic; no DB required)."""

    def __init__(self) -> None:
        self._d: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        v = self._d.get(key)
        return dict(v) if v is not None else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._d[key] = dict(value)


class SqlAlchemyAppConfigStore:
    """App-config store backed by the ``app_config`` table."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def get(self, key: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        from applicant.adapters.storage import models as m

        row = self._session.execute(
            select(m.AppConfigModel).where(m.AppConfigModel.key == key)
        ).scalar_one_or_none()
        return dict(row.value) if row is not None and row.value is not None else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from applicant.adapters.storage import models as m

        # Upsert to avoid the select-then-insert race (#169): concurrent callers
        # both see no row, both insert, and the second raises UniqueViolation.
        stmt = pg_insert(m.AppConfigModel).values(
            id=key, key=key, value=dict(value)
        ).on_conflict_do_update(
            index_elements=["key"],
            set_={"value": dict(value)},
        )
        self._session.execute(stmt)
        self._session.commit()
