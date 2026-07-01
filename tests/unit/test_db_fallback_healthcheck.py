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


def test_build_storage_marks_unreachable_db_as_fallback():
    # End-to-end through the real wiring site: an unreachable DB yields an in-memory
    # storage that reports unhealthy (the #312 signal is live, not dead code), and
    # the fallback is loud (warning naming the host, never the credentials).
    #
    # We deliberately do NOT use pytest's ``caplog`` fixture here: in a full-suite run
    # an earlier test that boots the whole app reconfigures the "applicant" logger
    # (own handler, ``propagate = False``) and/or leaves a process-global
    # ``logging.disable(...)`` set, and caplog's root-attached handler then never sees
    # this warning even though it IS emitted — a capture artifact, not a product bug
    # (the fallback still happens: engine is None, storage is a degraded InMemoryStorage).
    # Instead we attach our OWN handler directly to the emitting logger and neutralize
    # every suppression path (logger level + the global disable) for the capture window,
    # then restore them — so the assertion is robust to ordering and pytest/Python
    # version differences without weakening what it checks.
    captured: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    storage_logger = logging.getLogger("applicant.storage")
    prev_level = storage_logger.level
    prev_disable = logging.root.manager.disable
    grab = _Grab()
    grab.setLevel(logging.WARNING)
    storage_logger.addHandler(grab)
    storage_logger.setLevel(logging.WARNING)
    logging.disable(logging.NOTSET)
    try:
        engine, _factory, storage = _build_storage(Settings(DATABASE_URL=UNREACHABLE_DSN))
    finally:
        storage_logger.removeHandler(grab)
        storage_logger.setLevel(prev_level)
        logging.disable(prev_disable)

    text = "\n".join(captured)
    assert engine is None
    assert isinstance(storage, InMemoryStorage)
    assert storage.healthcheck() is False, "fallback must report degraded for #312"
    # Loud: a warning is emitted about the degrade, and credentials never leak.
    assert "falling back to in-memory storage" in text
    assert "s3cr3t" not in text
