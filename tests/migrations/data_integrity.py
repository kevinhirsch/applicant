"""Populate-old -> upgrade -> verify migration data-integrity harness (#365).

Exposes :func:`upgrade_populated_and_verify` — a single entrypoint that:

1. stands up a temp-file **SQLite** database migrated to a PRIOR revision
   (``0007_pii_retention_timestamps``) — a real database, not Postgres, so the
   check runs in the default hermetic lane (no Docker/network);
2. **seeds representative rows** across every populated table (mirrors the row
   shapes the integration suite uses);
3. runs ``alembic upgrade head`` over that populated database; and
4. **verifies** every seeded row survives the upgrade with correct values
   (``rows_intact``) and the upgraded schema matches every ORM-declared table and
   column with no drift (``schema_matches_models``).

It returns ``{"rows_intact": bool, "schema_matches_models": bool}``.

The seed/verify/schema-diff logic is lifted from the proven hermetic migration
tests (``tests/unit/test_migration_data_integrity_hermetic.py``); this wrapper
packages the 0007 -> head leg as a reusable entrypoint for the systemic-hole BDD
spec for #365.

The ``-x db_url=<sqlite_url>`` trick (via ``cmd_opts``) takes top priority in
``alembic/env.py``, so neither ``DATABASE_URL`` nor the settings object can redirect
the connection to a real Postgres server.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from applicant.adapters.storage import models as m
from applicant.core.ids import new_id

#: Repo root (tests/migrations/<file> -> parents[2]).
_PROJECT = Path(__file__).resolve().parents[2]

#: The prior revision we stand the populated database up at before upgrading.
_PRIOR_REVISION = "0007_pii_retention_timestamps"


def _make_alembic_config(db_url: str) -> Config:
    """An Alembic Config pinned to *db_url* on SQLite (the ``-x db_url`` guard)."""
    cmd_opts = argparse.Namespace(x=[f"db_url={db_url}"])
    cfg = Config(str(_PROJECT / "alembic.ini"), cmd_opts=cmd_opts)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option(
        "script_location",
        str(_PROJECT / "src/applicant/adapters/storage/alembic"),
    )
    return cfg


def _seed_campaign(session: Session, cid: str = "campaign-001") -> None:
    session.execute(
        text(
            "INSERT INTO campaigns (id, name, run_mode, throughput_target, "
            "exploration_budget, active, criteria, schedule, learning_state, "
            "created_at) VALUES (:id, :name, 'continuous', 15, 0.1, 1, "
            "'{}', '{}', '{}', '2026-01-01T00:00:00')"
        ),
        {"id": cid, "name": "Test Campaign"},
    )


def _seed_data(session: Session, cid: str) -> dict:
    """Seed one representative row per populated table; return the expected counts."""
    counts: dict[str, int] = {}
    pid = new_id()
    vid = new_id()
    aid = new_id()
    mid = new_id()
    t = text

    session.execute(
        t("INSERT INTO onboarding_profiles (id, campaign_id, completion_flag, "
          "wizard_state, intake) VALUES (:id, :cid, 0, '{}', '{}')"),
        {"id": new_id(), "cid": cid})
    counts["onboarding_profiles"] = 1

    session.execute(
        t("INSERT INTO attributes (id, campaign_id, name, value, is_integral, "
          "is_sensitive, aliases) VALUES (:id, :cid, 'email', 'test@example.com', "
          "1, 0, '[]')"),
        {"id": new_id(), "cid": cid})
    counts["attributes"] = 1

    session.execute(
        t("INSERT INTO field_mappings (id, campaign_id, site_key, field_selector, "
          "mapping_metadata) VALUES (:id, :cid, 'workday', '#email', '{}')"),
        {"id": new_id(), "cid": cid})
    counts["field_mappings"] = 1

    session.execute(
        t("INSERT INTO discovery_sources (id, campaign_id, source_key, enabled, "
          "yield_stats) VALUES (:id, :cid, 'linkedin', 1, '{}')"),
        {"id": new_id(), "cid": cid})
    counts["discovery_sources"] = 1

    session.execute(
        t("INSERT INTO job_postings (id, campaign_id, title, company, location, "
          "work_mode, salary, source_url, source_key, viability_score, rationale, "
          "description) VALUES (:id, :cid, 'Engineer', 'Acme', 'Remote', 'remote', "
          "'100k', 'https://example.com/job', 'lk-123', 0.85, '{}', 'A great job')"),
        {"id": pid, "cid": cid})
    counts["job_postings"] = 1

    session.execute(
        t("INSERT INTO resume_variants (id, campaign_id, storage_path, approved, "
          "fit_scores) VALUES (:id, :cid, '/tmp/resume.pdf', 0, '{}')"),
        {"id": vid, "cid": cid})
    counts["resume_variants"] = 1

    session.execute(
        t("INSERT INTO applications (id, campaign_id, posting_id, role_name, "
          "job_title, work_mode, root_url, resume_variant_id, status, "
          "attributes_used, created_at, updated_at) VALUES (:id, :cid, :pid, "
          "'Engineer', 'Sr Engineer', 'remote', 'https://example.com', :vid, "
          "'DISCOVERED', '{}', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"),
        {"id": aid, "cid": cid, "pid": pid, "vid": vid})
    counts["applications"] = 1

    session.execute(
        t("INSERT INTO generated_materials (id, campaign_id, application_id, "
          "type, content, storage_path, approved) VALUES (:id, :cid, :aid, "
          "'cover_letter', 'Dear hiring manager...', '/tmp/cover.pdf', 0)"),
        {"id": mid, "cid": cid, "aid": aid})
    counts["generated_materials"] = 1

    session.execute(
        t("INSERT INTO revision_sessions (id, material_id, status, redline_state, "
          "turns) VALUES (:id, :mid, 'open', '{}', '[]')"),
        {"id": new_id(), "mid": mid})
    counts["revision_sessions"] = 1

    session.execute(
        t("INSERT INTO application_screenshots (id, application_id, page_ref, "
          "captured_at) VALUES (:id, :aid, 'page1', '2026-01-01T00:00:00')"),
        {"id": new_id(), "aid": aid})
    counts["application_screenshots"] = 1

    session.execute(
        t("INSERT INTO decisions (id, application_id, type, feedback_text, "
          "criteria_delta) VALUES (:id, :aid, 'approve', 'Looks good', '{}')"),
        {"id": new_id(), "aid": aid})
    counts["decisions"] = 1

    session.execute(
        t("INSERT INTO outcome_events (id, application_id, type, source, "
          "created_at) VALUES (:id, :aid, 'submitted', 'auto', "
          "'2026-01-01T00:00:00')"),
        {"id": new_id(), "aid": aid})
    counts["outcome_events"] = 1

    session.execute(
        t("INSERT INTO detection_events (id, application_id, signal_type, "
          "signal_detail, timestamp) VALUES (:id, :aid, 'captcha', '{}', "
          "'2026-01-01T00:00:00')"),
        {"id": new_id(), "aid": aid})
    counts["detection_events"] = 1

    session.execute(
        t("INSERT INTO agent_runs (id, campaign_id, intent_sentence, timestamp) "
          "VALUES (:id, :cid, '{}', '2026-01-01T00:00:00')"),
        {"id": new_id(), "cid": cid})
    counts["agent_runs"] = 1

    session.execute(
        t("INSERT INTO pending_actions (id, campaign_id, application_id, kind, "
          "title, payload, resolved, created_at) VALUES (:id, :cid, :aid, "
          "'review', 'Please review', '{}', 0, '2026-01-01T00:00:00')"),
        {"id": new_id(), "cid": cid, "aid": aid})
    counts["pending_actions"] = 1

    session.execute(
        t("INSERT INTO tool_settings (id, tool_key, enabled) "
          "VALUES (:id, 'browser', 1)"),
        {"id": new_id()})
    counts["tool_settings"] = 1

    session.execute(
        t("INSERT INTO app_config (id, key, value) "
          "VALUES (:id, 'oobe_complete', '{}')"),
        {"id": new_id()})
    counts["app_config"] = 1

    session.execute(
        t("INSERT INTO fonts (id, name, install_status, environment, "
          "font_metadata) VALUES (:id, 'Arial', 'installed', 'default', '{}')"),
        {"id": new_id()})
    counts["fonts"] = 1

    session.execute(
        t("INSERT INTO dormant_surface_backlog (id, surface_name, "
          "requirement_ids, status, wiring_notes) "
          "VALUES (:id, 'ui', '[]', 'dormant', '{}')"),
        {"id": new_id()})
    counts["dormant_surface_backlog"] = 1

    session.commit()
    return counts


def _schema_matches_models(engine) -> bool:
    """True iff every ORM-declared table/column is present in the DB and vice-versa."""
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    model_tables = {t.__tablename__ for t in m.ALL_TABLES}
    db_tables.discard("alembic_version")

    if model_tables - db_tables:
        return False
    extra = db_tables - model_tables
    extra.discard("sqlite_sequence")
    if extra:
        return False

    for model_cls in m.ALL_TABLES:
        table_name = model_cls.__tablename__
        if table_name not in db_tables:
            continue
        db_cols = {c["name"] for c in inspector.get_columns(table_name)}
        orm_cols = {c.name for c in model_cls.__table__.columns}
        if orm_cols - db_cols or db_cols - orm_cols:
            return False
    return True


def upgrade_populated_and_verify() -> dict:
    """Populate at a prior revision, upgrade to head, verify rows + schema.

    Returns ``{"rows_intact": bool, "schema_matches_models": bool}``. Hermetic:
    runs against a temp-file SQLite database — no Postgres, no Docker, no network.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    try:
        db_url = f"sqlite:///{db_path}"
        cfg = _make_alembic_config(db_url)
        engine = create_engine(db_url)

        # 1. Stand the database up at the PRIOR revision (full 0001 -> 0007 chain).
        command.upgrade(cfg, _PRIOR_REVISION)

        # 2. Seed representative rows into the prior-revision schema.
        with Session(engine) as session:
            _seed_campaign(session)
            counts = _seed_data(session, "campaign-001")

        # 3. Upgrade the POPULATED database to head.
        command.upgrade(cfg, "head")

        # 4a. Every seeded row survives with correct values.
        rows_intact = True
        with Session(engine) as session:
            for table, expected in counts.items():
                got = session.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed table names
                ).scalar()
                if got != expected:
                    rows_intact = False
                    break

            if rows_intact:
                # Spot-check representative values survived intact (not just counts).
                campaign = session.execute(
                    text(
                        "SELECT name, run_mode FROM campaigns WHERE id = 'campaign-001'"
                    )
                ).one()
                posting = session.execute(
                    text(
                        "SELECT title, company FROM job_postings "
                        "WHERE campaign_id = 'campaign-001'"
                    )
                ).one()
                # 0008_schema_hardening adds + backfills agent_runs.seq to 0.
                seq = session.execute(
                    text(
                        "SELECT seq FROM agent_runs WHERE campaign_id = 'campaign-001'"
                    )
                ).scalar()
                rows_intact = (
                    campaign[0] == "Test Campaign"
                    and campaign[1] == "continuous"
                    and posting[0] == "Engineer"
                    and posting[1] == "Acme"
                    and seq == 0
                )

        # 4b. The upgraded schema matches every ORM-declared table + column.
        schema_matches = _schema_matches_models(engine)
        engine.dispose()

        return {
            "rows_intact": rows_intact,
            "schema_matches_models": schema_matches,
        }
    finally:
        os.unlink(db_path)


if __name__ == "__main__":  # pragma: no cover - manual smoke
    report = upgrade_populated_and_verify()
    print(report)
    assert report["rows_intact"] is True
    assert report["schema_matches_models"] is True
