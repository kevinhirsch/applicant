"""update.sh migrations fail-closed with auto-rollback (FR-INSTALL-2, H1/H4).

A failed ``alembic upgrade head`` must NOT leave a half-migrated schema being served:
the updater auto-restores the dump it just took (host-side file piped into the
container's psql over STDIN) and aborts non-zero, BEFORE the new stack is brought up
to serve traffic. These tests are hermetic — a fake ``docker`` on PATH stands in for
the real CLI; no real docker/postgres is invoked. APPLICANT_SELFTEST=1 keeps the
updater from touching this repo (no git reset, no live heartbeat).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update.sh"


def test_migration_step_has_autorollback_and_gates_serving():
    text = _SCRIPT.read_text(encoding="utf-8")
    # The migration runs as a blocking one-off BEFORE `up -d` serves the new stack.
    assert text.index("alembic upgrade head") < text.index("up -d --build")
    # On migration failure the script auto-restores the dump it just took and exits 1.
    mig = text.split("Running database migrations")[1].split("4/5")[0]
    assert "restore_dump" in mig, "migration failure must auto-restore the backup"
    assert "exit 1" in mig, "migration failure must abort non-zero"


def test_heartbeat_fails_when_engine_healthz_not_green():
    # The heartbeat must only return 0 when BOTH the UI /api/health AND the engine
    # /healthz are green; a degraded engine (UI up, /healthz red) must fall through to
    # the FAILED branch rather than reporting a soft warning + success.
    text = _SCRIPT.read_text(encoding="utf-8")
    hb = text.split("heartbeat() {")[1].split("\n}\n")[0]
    # The success `return 0` lives inside the /healthz success branch (engine green).
    assert "/healthz" in hb
    assert "return 1" in hb, "heartbeat must be able to fail (non-zero) on a red engine"
    # There must be no unconditional `return 0` immediately after the UI-up check that
    # would mask a red engine.
    assert "Engine /healthz not green yet" not in hb, (
        "engine /healthz no longer downgraded to a soft warning; it must fail the heartbeat"
    )


def _make_fake_docker(tmp_path: Path, captured: Path, *, alembic_fails: bool) -> Path:
    """Fake ``docker`` whose compose subcommands behave per the scenario.

    - ``pg_dump`` -> emits a plausible dump body (redirected into DUMP_FILE).
    - ``alembic`` -> exits non-zero when ``alembic_fails`` (simulated bad migration).
    - ``psql``   -> copies STDIN to ``captured`` (proves the auto-restore streamed
      the dump host-side into the container).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    alembic_exit = "1" if alembic_fails else "0"
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "pg_dump" ]]; then echo "-- fake dump"; exit 0; fi\n'
        '  if [[ "$a" == "psql" ]]; then cat >' + str(captured) + "; exit 0; fi\n"
        '  if [[ "$a" == "alembic" ]]; then exit ' + alembic_exit + "; fi\n"
        "done\n"
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_update(tmp_path: Path, bin_dir: Path, backup_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(backup_dir)
    env["APPLICANT_SELFTEST"] = "1"
    return subprocess.run(
        ["bash", str(_SCRIPT), "--apply"],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_failed_migration_autorestores_and_aborts(tmp_path):
    backup_dir = tmp_path / "backups"
    captured = tmp_path / "captured.sql"
    bin_dir = _make_fake_docker(tmp_path, captured, alembic_fails=True)
    res = _run_update(tmp_path, bin_dir, backup_dir)

    assert res.returncode != 0, "a failed migration must abort the update non-zero"
    # The new stack must NOT have been brought up to serve.
    assert "Restarting the stack" not in res.stdout
    # The auto-restore must have streamed the just-taken dump into psql over STDIN.
    assert captured.exists(), "auto-rollback should have restored the backup via psql STDIN"
    assert captured.read_text(encoding="utf-8").strip() == "-- fake dump"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_successful_migration_proceeds_to_restart(tmp_path):
    backup_dir = tmp_path / "backups"
    captured = tmp_path / "captured.sql"
    bin_dir = _make_fake_docker(tmp_path, captured, alembic_fails=False)
    res = _run_update(tmp_path, bin_dir, backup_dir)

    assert res.returncode == 0, res.stderr
    assert "Restarting the stack" in res.stdout
    # No restore should have happened on the happy path.
    assert not captured.exists(), "no auto-rollback should run when the migration succeeds"
