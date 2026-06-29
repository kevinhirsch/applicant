"""Forward-migration data-integrity test (#365).

Stands up a SQLite database at a prior alembic revision, populates it with
representative rows, runs alembic upgrade head, then asserts:
(a) every seeded row survives with correct values, and
(b) the upgraded schema matches the SQLAlchemy ORM models (no drift).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Allow early sys.path manipulation for alembic imports (#365 migration test).
_PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from applicant.adapters.storage import models as m  # noqa: E402
from applicant.core.ids import new_id  # noqa: E402


def _make_alembic_config(db_url):
    cfg = Config(str(_PROJECT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option(
        "script_location",
        str(_PROJECT / "src/applicant/adapters/storage/alembic"),
    )
    return cfg


def _seed_campaign(session, cid="campaign-001"):
    session.execute(
        text(
            "INSERT INTO campaigns (id, name, run_mode, throughput_target, "
            "exploration_budget, active, criteria, schedule, learning_state, "
            "created_at) VALUES (:id, :name, 'continuous', 15, 0.1, 1, "
            "'{}', '{}', '{}', '2026-01-01T00:00:00')"
        ),
        {"id": cid, "name": "Test Campaign"},
    )


def _seed_data(session, cid):
    counts = {}
    pid = new_id()
    vid = new_id()
    aid = new_id()
    mid = new_id()

    t = text  # alias for brevity

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


@pytest.mark.integration
def test_migrate_from_0001_to_head_data_survives():
    from sqlalchemy import create_engine

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    try:
        db_url = f"sqlite:///{db_path}"
        cfg = _make_alembic_config(db_url)
        engine = create_engine(db_url)

        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            ))
            conn.execute(text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('0001_initial')"
            ))
            conn.commit()

        command.upgrade(cfg, "0001_initial")

        from sqlalchemy.orm import Session
        with Session(engine) as session:
            _seed_campaign(session)
            counts = _seed_data(session, "campaign-001")

        command.upgrade(cfg, "head")

        with Session(engine) as session:
            for table, expected in sorted(counts.items()):
                result = session.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).scalar()
                assert result == expected, (
                    f"{table}: expected {expected} rows, got {result}"
                )

            row = session.execute(
                text("SELECT name, run_mode FROM campaigns "
                     "WHERE id = 'campaign-001'")
            ).one()
            assert row[0] == "Test Campaign"
            assert row[1] == "continuous"

            row = session.execute(
                text("SELECT title, company, viability_score "
                     "FROM job_postings WHERE campaign_id = 'campaign-001'")
            ).one()
            assert row[0] == "Engineer"
            assert row[1] == "Acme"
            assert row[2] == 0.85

            row = session.execute(
                text("SELECT status, role_name FROM applications "
                     "WHERE campaign_id = 'campaign-001'")
            ).one()
            assert row[0] == "DISCOVERED"
            assert row[1] == "Engineer"

        _assert_schema_matches_models(engine)
    finally:
        os.unlink(db_path)


@pytest.mark.integration
def test_migrate_from_0007_to_head_data_survives():
    from sqlalchemy import create_engine

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    try:
        db_url = f"sqlite:///{db_path}"
        cfg = _make_alembic_config(db_url)
        engine = create_engine(db_url)

        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            ))
            conn.execute(text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES ('0001_initial')"
            ))
            conn.commit()

        command.upgrade(cfg, "0007_pii_retention_timestamps")

        from sqlalchemy.orm import Session
        with Session(engine) as session:
            _seed_campaign(session)
            counts = _seed_data(session, "campaign-001")

        command.upgrade(cfg, "head")

        with Session(engine) as session:
            for table, expected in sorted(counts.items()):
                result = session.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).scalar()
                assert result == expected, (
                    f"{table}: expected {expected} rows, got {result}"
                )

            row = session.execute(
                text("SELECT seq FROM agent_runs "
                     "WHERE campaign_id = 'campaign-001'")
            ).one()
            assert row[0] == 0, f"seq should be backfilled to 0, got {row[0]}"

            cols = {c["name"] for c in
                    inspect(engine).get_columns("job_postings")}
            assert "normalized" not in cols, "normalized should be dropped"

            cols = {c["name"] for c in
                    inspect(engine).get_columns("generated_materials")}
            assert "redline_state" not in cols, "redline_state should be dropped"

            ucs = {uc["name"] for uc in
                   inspect(engine).get_unique_constraints("discovery_sources")}
            assert "uq_discovery_sources_campaign_source" in ucs

            ucs = {uc["name"] for uc in
                   inspect(engine).get_unique_constraints("onboarding_profiles")}
            assert "uq_onboarding_profiles_campaign" in ucs

        _assert_schema_matches_models(engine)
    finally:
        os.unlink(db_path)


def _assert_schema_matches_models(engine):
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    model_tables = {t.__tablename__ for t in m.ALL_TABLES}
    db_tables.discard("alembic_version")

    missing = model_tables - db_tables
    assert not missing, f"Tables in models but missing from DB: {missing}"

    extra = db_tables - model_tables
    extra.discard("sqlite_sequence")
    assert not extra, f"Tables in DB but missing from models: {extra}"

    for model_cls in m.ALL_TABLES:
        table_name = model_cls.__tablename__
        if table_name not in db_tables:
            continue
        db_cols = {c["name"] for c in inspector.get_columns(table_name)}
        orm_cols = {c.name for c in model_cls.__table__.columns}
        missing_cols = orm_cols - db_cols
        extra_cols = db_cols - orm_cols
        assert not missing_cols, (
            f"{table_name}: columns in model but not in DB: {missing_cols}"
        )
        assert not extra_cols, (
            f"{table_name}: columns in DB but not in model: {extra_cols}"
        )
