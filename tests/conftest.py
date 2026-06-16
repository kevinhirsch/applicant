"""Shared test fixtures: fake adapters, fake clock, fast in-memory storage."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime

import pytest

from applicant.adapters.credentials.pg_credential_store import PgCredentialStore
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.tools.tool_registry import ToolRegistry


@pytest.fixture
def storage() -> InMemoryStorage:
    """Fast in-memory StoragePort for unit/contract tests."""
    return InMemoryStorage()


@pytest.fixture
def orchestrator(tmp_path) -> CheckpointShimOrchestrator:
    """File-backed durable orchestrator rooted in a temp dir."""
    return CheckpointShimOrchestrator(str(tmp_path / "checkpoints"))


@pytest.fixture
def credential_store(tmp_path) -> PgCredentialStore:
    return PgCredentialStore(str(tmp_path / "master.key"))


@pytest.fixture
def notifier() -> AppriseNotifier:
    return AppriseNotifier(discord_webhook_url="https://discord.test/webhook")


@pytest.fixture
def tool_registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def fake_clock():
    """A frozen clock for deterministic tests."""

    class _Clock:
        def __init__(self) -> None:
            self.now = datetime(2026, 1, 1, tzinfo=UTC)

        def tick(self, seconds: float) -> None:
            from datetime import timedelta

            self.now = self.now + timedelta(seconds=seconds)

    return _Clock()


@pytest.fixture
def sqlite_storage():
    """A real SQLAlchemy storage backed by SQLite (schema via metadata)."""
    from applicant.adapters.storage.models import Base
    from applicant.adapters.storage.repositories import SqlAlchemyStorage
    from applicant.adapters.storage.session import make_engine, make_session_factory

    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    yield SqlAlchemyStorage(session)
    session.close()
    engine.dispose()
