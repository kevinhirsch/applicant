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
    """App-config store backed by the ``app_config`` table.

    This store holds the single *container-level* boot Session — it is built once
    at startup (``container.py`` ``_build_storage``) and lives for the whole process
    (unlike route-handler storage, which is per-request). That makes it resilient-
    fragile: after a transient Postgres blip the boot Session can be left with an
    aborted transaction, and every subsequent ``get``/``set`` then raises
    ``PendingRollbackError: can't reconnect until invalid transaction is rolled
    back`` — wedging the ~25 ``require_llm_configured``-gated routers at HTTP 500
    until an engine restart (K2). To recover WITHOUT a restart, each operation
    rolls the session back and retries once on a recoverable connection/transaction
    error; the engine's ``pool_pre_ping`` then hands the retry a live connection in
    place of the dead pooled one. The happy path is unchanged (no extra round-trip).
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def get(self, key: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        from applicant.adapters.storage import models as m

        def _read() -> dict[str, Any] | None:
            row = self._session.execute(
                select(m.AppConfigModel).where(m.AppConfigModel.key == key)
            ).scalar_one_or_none()
            return dict(row.value) if row is not None and row.value is not None else None

        return self._run_resilient(_read)

    def set(self, key: str, value: dict[str, Any]) -> None:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from applicant.adapters.storage import models as m

        def _write() -> None:
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

        self._run_resilient(_write)

    def _run_resilient(self, op: Any) -> Any:
        """Run ``op`` on the boot Session; recover a poisoned session once (K2).

        On a recoverable error — ``PendingRollbackError`` (the transaction was
        aborted by a prior blip and never rolled back) or ``OperationalError`` (a
        connection-level failure, e.g. server restart / dropped socket) — roll the
        session back so it can begin a fresh transaction, then retry exactly once.
        A second failure propagates (the gate fails closed) rather than looping. All
        other exceptions (programming errors, integrity violations) are NOT retried.
        """
        from sqlalchemy.exc import OperationalError, PendingRollbackError

        try:
            return op()
        except (PendingRollbackError, OperationalError):
            try:
                self._session.rollback()
            except Exception:  # pragma: no cover - rollback itself should not mask the retry
                pass
            return op()
