"""Shared test fixtures: fake adapters, fake clock, fast in-memory storage.

This module also carries the **real-Postgres isolation** machinery for the
``@pytest.mark.integration`` lane (``_small_db_pool`` / ``_worker_database`` /
``_reset_real_db``).  It lives at the ROOT conftest — not under ``tests/integration``
— because integration-marked tests are scattered across directories (e.g.
``tests/unit/test_phase5_safety_gates.py`` and ``tests/unit/test_migration_data_
integrity.py`` are integration-marked), and the isolation must cover ALL of them.

Why it is needed: the suite was written assuming a FRESH store per test — true in
the hermetic lane, where every ``create_app()`` builds a brand-new
``InMemoryStorage`` (no FK enforcement, no shared state).  Against a real Postgres
(``DATABASE_URL=postgresql+psycopg://…``) that breaks down — foreign keys are
enforced, every test shares the one database (config + rows leak across tests), and
``addopts``' ``-n auto`` fans the suite across xdist workers that pollute and
deadlock each other on one shared database.  The fixtures below give each worker its
own freshly migrated database and reset its tables before each test, restoring the
per-test-fresh semantics.  Every one of them is a NO-OP when no real Postgres is
reachable (the hermetic in-memory lane uses an unreachable DSN), so the hermetic
lane is completely untouched.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from applicant.adapters.credentials.pg_credential_store import PgCredentialStore
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.storage.session import make_engine
from applicant.adapters.tools.tool_registry import ToolRegistry
from applicant.app.config import Settings


# === Real-Postgres integration-lane isolation ==============================
def _maybe_real_pg_url() -> str | None:
    """Return DATABASE_URL iff it points at a *reachable* Postgres, else None.

    Mirrors the container's storage selection (``_build_storage``): if we cannot
    open a connection we are on the hermetic in-memory lane and every isolation
    fixture below is a no-op.
    """
    url = Settings().database_url
    if not url.startswith(("postgresql", "postgres")):
        return None
    try:
        engine = make_engine(url)
        engine.connect().close()
        engine.dispose()
        return url
    except Exception:
        return None


def _admin_url(url: str) -> str:
    """Return *url* rewritten to target the maintenance ``postgres`` database."""
    base, _, _db = url.rpartition("/")
    return f"{base}/postgres"


def _worker_db_name(url: str) -> str:
    """A per-xdist-worker database name derived from the configured DB name.

    ``gw0``/``gw1``/… under ``-n auto``; ``master`` when run single-process.  Keeps
    each worker's writes in its own database so they never collide.
    """
    base_db = url.rpartition("/")[2].split("?")[0]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    return f"{base_db}_it_{worker}"


def _run_migrations(db_url: str) -> None:
    """Run ``alembic upgrade head`` against *db_url* (mirrors production schema)."""
    from pathlib import Path
    from types import SimpleNamespace

    from alembic import command
    from alembic.config import Config

    project = Path(__file__).resolve().parents[1]
    cfg = Config(str(project / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(project / "src/applicant/adapters/storage/alembic")
    )
    cfg.set_main_option("sqlalchemy.url", db_url)
    # env.py honours -x db_url over $DATABASE_URL — pin the worker URL explicitly.
    cfg.cmd_opts = SimpleNamespace(x=[f"db_url={db_url}"])
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _small_db_pool():
    """Use NullPool for every engine the app builds during the integration lane.

    ``addopts`` fans the suite across xdist workers, and each ``create_app()`` opens
    a pooled engine (default ~5 + 10 overflow) plus a long-lived scheduler session.
    Multiplied by the worker count (and the live engine sharing the server) this
    blows past Postgres ``max_connections`` ("sorry, too many clients already").
    NullPool closes each connection on return, so the concurrent connection count
    stays minimal and the suite no longer exhausts the server.  No-op on the
    hermetic lane (no real Postgres ⇒ nothing connects).
    """
    if _maybe_real_pg_url() is None:
        yield
        return

    import time

    from sqlalchemy import event

    import applicant.adapters.storage.session as _session_mod

    real_make_engine = _session_mod.make_engine

    def _pooled(database_url: str, *, echo: bool = False):
        if database_url.startswith("sqlite"):
            return real_make_engine(database_url, echo=echo)

        engine = create_engine(database_url, echo=echo, future=True, poolclass=NullPool)

        @event.listens_for(engine, "do_connect")
        def _retry_too_many_clients(dialect, conn_rec, cargs, cparams):
            # Retry the brief "too many clients" window that opens when several xdist
            # workers (and a co-running live engine) hit the server's max_connections
            # at once.  NullPool reconnects often, so a short backoff smooths the
            # transient spike instead of failing the test outright.  Returning a live
            # DBAPI connection from this hook short-circuits SQLAlchemy's own connect.
            last: Exception | None = None
            deadline = time.monotonic() + 30.0
            attempt = 0
            while time.monotonic() < deadline:
                try:
                    return dialect.connect(*cargs, **cparams)
                except Exception as exc:  # pragma: no cover - timing dependent
                    if "too many clients" not in str(exc):
                        raise
                    last = exc
                    attempt += 1
                    time.sleep(min(0.05 * attempt, 0.5))
            raise last  # type: ignore[misc]

        return engine

    _session_mod.make_engine = _pooled
    try:
        yield
    finally:
        _session_mod.make_engine = real_make_engine


@pytest.fixture(scope="session", autouse=True)
def _worker_database():
    """Create + migrate a per-worker Postgres database; yield its URL.

    No-op on the hermetic lane.  On a real Postgres, every xdist worker gets its own
    freshly migrated database (dropped at session end) so workers do not share state
    or contend on reset locks.  This fixture does NOT mutate ``DATABASE_URL`` — that
    is done per-test by :func:`_reset_real_db` so the repoint applies symmetrically
    to every integration test wherever it lives.
    """
    url = _maybe_real_pg_url()
    if url is None:
        yield None
        return

    db_name = _worker_db_name(url)
    worker_url = f'{url.rpartition("/")[0]}/{db_name}'

    admin = create_engine(_admin_url(url), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    _run_migrations(worker_url)
    try:
        yield worker_url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(autouse=True)
def _reset_real_db(_worker_database):
    """Point DATABASE_URL at this worker's DB + clear its tables, before each test.

    Gives every integration test the fresh-database state the suite was written
    against, so config (LLM/onboarding/channels) and rows from one test never leak
    into the next.  A no-op when no real Postgres is reachable (hermetic lane), so it
    is harmless for the thousands of hermetic tests it also wraps.
    """
    worker_url = _worker_database
    if worker_url is None:
        yield
        return

    import applicant.adapters.storage.session as _session_mod
    from applicant.adapters.storage.models import Base
    from applicant.app.config import get_settings

    # Use the (possibly NullPool + too-many-clients-retry) engine factory installed by
    # ``_small_db_pool`` so the per-test reset shares the same resilient connect path.
    engine = _session_mod.make_engine(worker_url)
    # DELETE (ROW EXCLUSIVE), not TRUNCATE (ACCESS EXCLUSIVE): the engine's container
    # holds a long-lived session that can still be ``idle in transaction`` (holding an
    # ACCESS SHARE read lock) when the next test resets.  TRUNCATE would block on that
    # lock and deadlock the worker; DELETE does not conflict with ACCESS SHARE, so the
    # reset always makes progress.  Children-before-parents (reverse dependency order)
    # so the FK constraints are satisfied.
    ordered = [t for t in reversed(Base.metadata.sorted_tables) if t.name != "alembic_version"]
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        for table in ordered:
            conn.execute(text(f'DELETE FROM "{table.name}"'))

    # ``get_settings`` is ``@lru_cache``-d, so mutating the env is not enough — clear
    # the cache or ``create_app()`` keeps the original (shared) DSN.
    prev_db = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = worker_url

    # Isolate the durable-orchestrator checkpoint store per test too.  The shim
    # orchestrator persists workflow mailboxes under ``CHECKPOINT_DIR`` (default a
    # single CWD-relative ``.applicant_checkpoints``).  Shared across xdist workers
    # that is a cross-test channel: a ``recv`` can miss the ``send`` it expects when a
    # concurrent test's app clobbers the same directory.  A unique dir per test keeps
    # each test's durable mailboxes its own (matches the per-test-fresh store).
    import tempfile

    prev_ckpt = os.environ.get("CHECKPOINT_DIR")
    ckpt_dir = tempfile.mkdtemp(prefix="applicant_ckpt_")
    os.environ["CHECKPOINT_DIR"] = ckpt_dir

    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, prev in (("DATABASE_URL", prev_db), ("CHECKPOINT_DIR", prev_ckpt)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        get_settings.cache_clear()
        engine.dispose()
        import shutil

        shutil.rmtree(ckpt_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _stub_fc_cache(monkeypatch):
    """Prevent real fc-cache subprocess calls in the hermetic lane.

    fc-cache takes ~2 s on machines where fontconfig is installed.  The few
    tests that explicitly exercise the fc-cache boundary already monkeypatch
    ``shutil.which`` and ``subprocess.run`` on the font-installer module using
    the same function-scoped ``monkeypatch`` fixture — their ``setattr`` calls
    execute after this autouse setup and therefore WIN for the test body, then
    everything is restored together when the fixture tears down.
    """
    import applicant.adapters.fonts.font_installer as _fi_mod

    _real_which = _fi_mod.shutil.which

    monkeypatch.setattr(
        _fi_mod.shutil,
        "which",
        lambda name: None if name == "fc-cache" else _real_which(name),
    )


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


def open_automated_work_gate(client) -> None:
    """Open the full automated-work gate on a TestClient app (FR-UI-5, FR-ONBOARD-2).

    The ``require_automated_work`` dependency 409s until the LLM is configured AND
    onboarding is complete. (Notification channels and the automation sandbox moved
    to Settings and are now OPTIONAL — they no longer gate automated work.) This
    helper satisfies the required preconditions so tests that exercise gated routers
    (discovery, digest, agent-runs, remote) set up real state instead of relying on
    the gate being unenforced. It also configures channels for completeness, though
    that is no longer required to ungate work.
    """
    # 1. LLM gate (FR-UI-5).
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204
    # 2. Notification channels (optional now, but set for completeness).
    r = client.post("/api/setup/channels", json={"discord_webhook_url": "https://discord.test/wh"})
    assert r.status_code == 204
    # 3. Onboarding completion (FR-ONBOARD-2): force the real onboarding gate True.
    client.app.state.container.setup_service._onboarding_gate = lambda: True


@pytest.fixture
def sqlite_storage():
    """A real SQLAlchemy storage backed by an in-memory SQLite DB (schema via metadata).

    Uses ``sqlite:///:memory:`` instead of a temp file so schema creation is
    ~8 ms (pure memory) rather than ~300 ms (file I/O), without changing any
    observable behaviour — the fixture has always been ephemeral.
    """
    from applicant.adapters.storage.models import Base
    from applicant.adapters.storage.repositories import SqlAlchemyStorage
    from applicant.adapters.storage.session import make_engine, make_session_factory

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    yield SqlAlchemyStorage(session)
    session.close()
    engine.dispose()
