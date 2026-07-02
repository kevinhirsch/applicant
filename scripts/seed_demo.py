#!/usr/bin/env python
"""CLI wrapper: seed a realistic demo dataset for one owner/campaign (dev/playtest only).

This is the single blocker-buster for *rendering / auditing the trust-core flows*:
without rows in the database the Portal is empty, the digest has nothing to review,
the redline session has no material, and live-takeover / chat have nothing to point
at. The pure derivation + persistence logic lives in
``applicant.application.services.dev_seed`` (shared with the equivalent HTTP route,
``POST /api/dev/seed`` on the ``api`` service — see ``applicant.app.routers.dev_seed``)
so the CLI and the route can never drift apart; this script is just the terminal
entry point + the env-gate + DB wiring.

Safety:

* Execution is gated behind ``APPLICANT_ALLOW_SEED=1``. Without it the script refuses
  to run (so it can never fire in prod by accident).
* Re-running is safe: the repos ``merge`` by id (upsert) and the pending actions are
  deduped, so a second run replaces the demo rows rather than piling up duplicates.
* ``--reset`` purges the demo campaign instead of seeding it (reuses the same
  campaign-purge cascade the front-door "delete campaign" action uses, #363).

Invocation::

    APPLICANT_ALLOW_SEED=1 DATABASE_URL=postgresql+psycopg://applicant:applicant@localhost:5432/applicant \\
        uv run python scripts/seed_demo.py

    APPLICANT_ALLOW_SEED=1 DATABASE_URL=... uv run python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import os
import sys

from applicant.application.services import dev_seed


def _build_storage():
    """Build a real ``SqlAlchemyStorage`` over the app's own session factory.

    Reuses the exact engine/sessionmaker the container uses (``make_engine`` /
    ``make_session_factory``) against the configured ``DATABASE_URL``. Raises if
    the DB is unreachable — the seed is a write path and must not silently no-op.
    """
    from applicant.adapters.storage.repositories import SqlAlchemyStorage
    from applicant.adapters.storage.session import make_engine, make_session_factory
    from applicant.app.config import get_settings

    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    storage = SqlAlchemyStorage(session_factory())
    if not storage.healthcheck():
        raise RuntimeError(
            "Database healthcheck failed — the demo seed needs a reachable, "
            "migrated Postgres (run `uv run alembic upgrade head` first)."
        )
    return storage


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Gated behind ``APPLICANT_ALLOW_SEED=1``."""
    args = list(sys.argv[1:] if argv is None else argv)

    if os.environ.get("APPLICANT_ALLOW_SEED") != "1":
        print(
            "Refusing to seed demo data: set APPLICANT_ALLOW_SEED=1 to confirm.\n"
            "This inserts DEMO rows and must never run against production by accident.\n\n"
            "  APPLICANT_ALLOW_SEED=1 DATABASE_URL=... uv run python scripts/seed_demo.py",
            file=sys.stderr,
        )
        return 2

    storage = _build_storage()

    if "--reset" in args:
        counts = dev_seed.purge(storage, dev_seed.DEMO_CAMPAIGN_ID)
        print(f"Reset demo dataset for campaign '{dev_seed.DEMO_CAMPAIGN_ID}':")
        for key, count in sorted(counts.items()):
            print(f"  {key:24s}: {count}")
        return 0

    bundle = dev_seed.build_demo_bundle()
    counts = dev_seed.persist(storage, bundle)

    print(f"Seeded demo dataset for campaign '{bundle.campaign.id}' ({bundle.campaign.name}):")
    for key in (
        "campaign",
        "postings",
        "resume_variants",
        "applications",
        "materials",
        "revision_sessions",
        "submission_snapshots",
        "outcome_events",
        "pending_actions",
    ):
        print(f"  {key:18s}: {counts.get(key, 0)}")
    print(
        "\nPortal pending-action kinds: "
        + ", ".join(sorted({a.kind for a in bundle.pending_actions}))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
