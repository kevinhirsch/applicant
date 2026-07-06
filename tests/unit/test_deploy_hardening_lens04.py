"""Deploy/infra hardening — audit lens 04 (Tier 3: install/update recovery), #18-21/#23.

Five related failure paths in the install/update/stack recovery story:

- #18/#20: a migration could succeed while `docker compose up -d` or the post-update
  heartbeat still failed, leaving a half-updated stack (new schema, old/mixed
  containers) with only PRINTED rollback guidance and no automated recovery. update.sh
  now retries `up -d` a bounded number of times and, on either failure, EXECUTES the
  same rollback machinery the manual `--rollback` flag uses (revert code+images,
  restore the DB, redeploy) instead of only telling the operator to run it themselves.
- #19: the "smart-skip" migration decision matched only a hardcoded path
  (`.../alembic/versions/`), so a migration reachable any other way (a renamed dir, a
  vendored migration, an env.py data-fix) would be silently skipped while new code
  that needs the new schema deployed. update.sh now also compares the DB's actually
  applied revision against the repo's alembic head(s) on disk and forces a migrate on
  disagreement, regardless of which files the diff touched.
- #21: a fresh `install.sh --apply` ran migrations with no backup at all (only
  `--update` backed up first). A re-run of install against an EXISTING volume (a
  common operator mistake) therefore had nothing to restore from if a migration
  half-applied. install.sh now takes the same best-effort pre-migration snapshot on
  every provisioning apply, not just `--update`.
- #23: `chromadb` and `ntfy` had no `healthcheck:` at all (the UI only waited for
  `service_started` on chromadb), and `postgres` had no `start_period`, so a slow first
  boot could burn all of `pg_isready`'s retries. ntfy/postgres got sensible
  healthchecks/start_period. chromadb's was later removed and its contract reconciled
  (see below): the unpinned `:latest` tag pulled Chroma 1.x — a minimal image with no
  python/curl to run a healthcheck, persisting to `/data` — so chromadb is now pinned,
  mounts its volume at `/data`, and the UI gates it on `service_started` (the RAG client
  retries an unready store).

The update.sh behavioral tests are hermetic: a fake ``docker`` on PATH stands in for
the real CLI and captures/decides based on the invoked subcommand tokens, following
the same pattern as the neighboring ``test_update_script_*`` tests. APPLICANT_SELFTEST=1
keeps the script from touching this repo (no git reset) or running the live heartbeat.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UPDATE_SCRIPT = _REPO_ROOT / "scripts" / "update.sh"
_INSTALL_SCRIPT = _REPO_ROOT / "scripts" / "install.sh"
_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.prod.yml"


def _load_compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Shell syntax sanity (fast fail before the behavioral tests below)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scripts_are_valid_bash():
    for script in (_UPDATE_SCRIPT, _INSTALL_SCRIPT):
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, f"{script}: {res.stderr}"


# ---------------------------------------------------------------------------
# #18/#20 — up -d / heartbeat failure triggers EXECUTED recovery, not just guidance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_shared_rollback_helper_used_by_both_manual_and_automatic_paths():
    text = _UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert "auto_rollback()" in text, "rollback machinery must be a reusable function"
    # The manual `--rollback` CLI path calls it.
    rollback_path = text.split("manual --rollback CLI invocation")[1].split("update path")[0]
    assert "auto_rollback" in rollback_path

    # The 4/5 restart step retries `up -d` a bounded number of times and, on
    # persistent failure, actually invokes the recovery (not just an echo).
    restart_block = text.split("4/5 Restarting")[1].split("5/5 Update applied")[0]
    assert "auto_rollback" in restart_block, (
        "an up -d failure (after bounded retries) must trigger automated recovery"
    )
    # Bounded retry, not infinite / not a single unguarded attempt.
    assert "for _up_attempt in 1 2 3" in restart_block or "attempt" in restart_block.lower()

    # The heartbeat-failure branch also invokes it (#20) rather than only printing
    # "Roll back with: ..." and stopping.
    heartbeat_block = text.split("5/5 Update applied")[1]
    assert "heartbeat" in heartbeat_block.lower()
    assert "auto_rollback" in heartbeat_block, (
        "a failed post-update heartbeat must trigger automated recovery, not just guidance"
    )
    assert "exit 1" in heartbeat_block


def _make_fake_docker(tmp_path: Path, captured: Path, *, up_d_always_fails: bool) -> Path:
    """Fake ``docker`` used to drive the up -d retry/auto-rollback scenario.

    - ``pg_dump`` -> emits a plausible dump body (the pre-migrate backup).
    - ``alembic`` -> always succeeds (migration itself is not under test here).
    - ``psql``    -> copies STDIN to ``captured`` (proves the auto-rollback restored
      the dump host-side into the container, over STDIN).
    - a command containing BOTH the ``up`` and ``-d`` tokens (i.e. `... up -d`, used
      both by the restart step's retry loop and by auto_rollback's redeploy) fails
      when ``up_d_always_fails`` — simulating a stack that never comes back up.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    up_exit = "1" if up_d_always_fails else "0"
    body = (
        "#!/usr/bin/env bash\n"
        "has_psql=0; has_pgdump=0; has_alembic=0; has_up=0; has_dashd=0\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    psql) has_psql=1 ;;\n"
        "    pg_dump) has_pgdump=1 ;;\n"
        "    alembic) has_alembic=1 ;;\n"
        "    up) has_up=1 ;;\n"
        "    -d) has_dashd=1 ;;\n"
        "  esac\n"
        "done\n"
        'if [[ "$has_psql" == 1 ]]; then cat >' + str(captured) + "; exit 0; fi\n"
        'if [[ "$has_pgdump" == 1 ]]; then echo "-- fake dump"; exit 0; fi\n'
        'if [[ "$has_alembic" == 1 ]]; then exit 0; fi\n'
        'if [[ "$has_up" == 1 && "$has_dashd" == 1 ]]; then exit ' + up_exit + "; fi\n"
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_update(tmp_path: Path, bin_dir: Path, backup_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(backup_dir)
    # Never let the updater hard-reset this repo or run the live heartbeat in tests.
    env["APPLICANT_SELFTEST"] = "1"
    return subprocess.run(
        ["bash", str(_UPDATE_SCRIPT), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_up_d_failure_retries_then_auto_rollback_restores_db(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # Pre-seed the pre-update snapshot auto_rollback needs (normally written by the
    # "Snapshot the pre-update deployable state" step, which is itself SELFTEST-gated
    # to avoid touching this repo's images in tests — mirrors the existing rollback
    # tests' setup).
    (backup_dir / "last-deploy.images").write_text(
        "GIT_REV=deadbeef\nAPI_IMAGE_ID=sha256:aaa\nUI_IMAGE_ID=sha256:bbb\n", encoding="utf-8"
    )
    captured = tmp_path / "captured.sql"
    bin_dir = _make_fake_docker(tmp_path, captured, up_d_always_fails=True)

    res = _run_update(tmp_path, bin_dir, backup_dir)

    assert res.returncode != 0, "an up -d that never succeeds must abort the update non-zero"
    # Bounded retry actually happened (not a single silent attempt).
    assert res.stderr.count("docker compose up -d failed") >= 3, res.stderr
    # Automated recovery was EXECUTED (not just printed as a suggestion): the backup
    # taken during the update was restored via psql over STDIN.
    assert captured.exists(), "auto-rollback should have restored the DB via psql STDIN"
    assert "fake dump" in captured.read_text(encoding="utf-8")
    # auto_rollback's own progress lines go through log() (stdout); the caller's
    # follow-up messaging goes to stderr — recovery was EXECUTED either way.
    assert "AUTO-RECOVERY" in res.stdout + res.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_up_d_succeeds_on_first_try_no_recovery_needed(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    captured = tmp_path / "captured.sql"
    bin_dir = _make_fake_docker(tmp_path, captured, up_d_always_fails=False)

    res = _run_update(tmp_path, bin_dir, backup_dir)

    assert res.returncode == 0, res.stderr
    assert "Restarting the stack" in res.stdout
    assert "AUTO-RECOVERY" not in res.stderr
    assert not captured.exists(), "no rollback restore should run on the happy path"


# ---------------------------------------------------------------------------
# #19 — migration-skip decision has a non-path-based fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_skip_has_alembic_heads_vs_current_fallback():
    text = _UPDATE_SCRIPT.read_text(encoding="utf-8")
    smart_skip = text.split("Smart-skip:")[1].split("Snapshot the pre-update deployable state")[0]
    # The original path-glob decision must still be present (still the fast path)...
    assert "alembic/versions/" in smart_skip
    # ...but it is no longer the ONLY signal: an independent comparison of the DB's
    # actually-applied revision against the repo's computed head(s) can force a
    # migrate even when no path matched.
    assert "alembic_version" in smart_skip, "must consult the DB's applied revision, not just paths"
    assert "RUN_MIGRATE=1" in smart_skip.split("Migration-skip robustness")[1]


# ---------------------------------------------------------------------------
# #21 — install.sh backs up before migrating on every apply, not just --update
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_install_backs_up_before_migrate_on_fresh_apply_too():
    text = _INSTALL_SCRIPT.read_text(encoding="utf-8")
    after_marker = text.split("Migrating the schema")[1]
    migrate_phase = after_marker.split("Phase 5")[0]
    assert "pg_dump" in migrate_phase
    # The backup step must run whenever we are actually applying, not be gated to
    # MODE == "update" only (that was the #21 gap: a fresh --apply had no backup).
    assert 'MODE}" == "update" && "${APPLY}' not in migrate_phase
    assert '"${APPLY}" -eq 1' in migrate_phase
    # Still precedes the actual migration (safe order) — both indices computed from
    # the same (unsliced) remainder so they are directly comparable. rindex for the
    # migration command since "alembic upgrade head" also appears earlier, in the
    # phase's own descriptive title string.
    assert after_marker.index("pg_dump") < after_marker.rindex("alembic upgrade head")


# ---------------------------------------------------------------------------
# #23 — chromadb/ntfy healthchecks, postgres start_period
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compose_parses_with_nonempty_services():
    spec = _load_compose()
    assert isinstance(spec, dict)
    services = spec.get("services")
    assert isinstance(services, dict) and services


@pytest.mark.unit
def test_chromadb_is_pinned_persists_to_data_and_ui_gates_on_it():
    # Reconciled from the original issue-#23 "chromadb must have a healthcheck +
    # service_healthy" contract: the unpinned chromadb/chroma:latest tag pulled
    # Chroma 1.x, a minimal Rust image with NO python/curl/wget — so the old
    # python heartbeat healthcheck failed exit-127 forever and blocked the deploy,
    # and 1.x persists to /data (not /chroma/chroma). The corrected invariants:
    spec = _load_compose()
    chromadb = spec["services"]["chromadb"]

    # 1) Pinned off :latest so a fresh --build can't silently pull a new major.
    image = chromadb.get("image", "")
    tag = image.rsplit("/", 1)[-1]
    assert ":" in tag and not tag.endswith(":latest"), (
        f"chromadb image must be pinned to an explicit version tag, not :latest (got {image!r})"
    )

    # 2) Named volume mounts at /data — Chroma 1.x's persist dir — or vectors land
    #    in the throwaway container layer and are lost on recreate.
    targets = [v.split(":", 1)[1] for v in chromadb.get("volumes", []) if isinstance(v, str) and ":" in v]
    assert "/data" in targets, f"chromadb volume must mount at /data (got {chromadb.get('volumes')!r})"

    # 3) The 1.x image ships no healthcheck and no in-image HTTP client to build one
    #    with, so the UI gates on service_started; the RAG client retries.
    ui_depends = spec["services"]["applicant-ui"]["depends_on"]
    assert ui_depends["chromadb"]["condition"] == "service_started", (
        "the UI should gate chromadb on service_started (Chroma 1.x has no usable in-container healthcheck)"
    )


@pytest.mark.unit
def test_ntfy_has_a_healthcheck():
    spec = _load_compose()
    ntfy = spec["services"]["ntfy"]
    hc = ntfy.get("healthcheck")
    assert hc, "ntfy must declare a healthcheck (issue #23)"
    assert hc.get("test"), "ntfy healthcheck must define a test command"


@pytest.mark.unit
def test_postgres_healthcheck_has_start_period():
    spec = _load_compose()
    postgres = spec["services"]["postgres"]
    hc = postgres.get("healthcheck")
    assert hc, "postgres must keep its existing healthcheck"
    assert hc.get("start_period"), (
        "postgres needs a start_period so a slow first boot doesn't burn all pg_isready retries"
    )
