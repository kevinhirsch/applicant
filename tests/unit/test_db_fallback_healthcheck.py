"""#312 — the engine must FAIL LOUD when it degrades to in-memory storage.

When the database is unreachable, ``_build_storage`` falls back to an
``InMemoryStorage`` so the app can still boot — but that instance MUST report
``healthcheck() is False`` so the degraded, non-persistent mode is detectable and
surfaced (boot warning, lifespan probe) instead of silently pretending to be healthy.

The normal in-memory test/dev adapter (constructed directly, not as a fallback)
stays healthy so the hermetic lane is not falsely reported as degraded.
"""

from __future__ import annotations

import logging

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.config import Settings
from applicant.app.container import _build_storage

# An unreachable DSN: port 1 on loopback is never listening, so make_engine's first
# use raises and _build_storage takes the fallback branch. Credentials in the DSN
# must never appear in the warning (privacy).
UNREACHABLE_DSN = "postgresql+psycopg://u:s3cr3t@127.0.0.1:1/none"


def test_fallback_instance_reports_unhealthy():
    # The genuine DB-unreachable fallback marks the instance so healthcheck() is False.
    storage = InMemoryStorage(is_fallback=True)
    assert storage.healthcheck() is False


def test_normal_in_memory_reports_healthy():
    # The default (test/dev) in-memory adapter is healthy — the hermetic lane must
    # NOT be reported as degraded just because it has no Postgres.
    storage = InMemoryStorage()
    assert storage.healthcheck() is True


def test_build_storage_marks_unreachable_db_as_fallback(caplog):
    # End-to-end through the real wiring site: an unreachable DB yields an in-memory
    # storage that reports unhealthy (the #312 signal is live, not dead code), and
    # the fallback is loud (warning naming the host, never the credentials).
    with caplog.at_level(logging.WARNING):
        engine, _factory, storage = _build_storage(Settings(DATABASE_URL=UNREACHABLE_DSN))

    assert engine is None
    assert isinstance(storage, InMemoryStorage)
    assert storage.healthcheck() is False, "fallback must report degraded for #312"
    # Loud: a warning is emitted about the degrade, and credentials never leak.
    assert "falling back to in-memory storage" in caplog.text
    assert "s3cr3t" not in caplog.text
