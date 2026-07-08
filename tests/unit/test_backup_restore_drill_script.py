"""Hermetic tests for scripts/backup-restore-drill.sh (P1-7, issue #659, DoD
item 3: the scripted backup -> destroy volumes -> restore drill).

This script is inherently destructive against a REAL compose stack (`docker
compose down -v`), so these tests only ever run it against a fake ``docker`` on
PATH (never real docker/postgres) and set ``APPLICANT_SELFTEST=1`` to skip the
live heartbeat's retry loop (mirrors update.sh's own SELFTEST guard around its
heartbeat). The genuine live-stack drill is a manual/deploy-verification step
(see docs/backup-restore.md) — these tests cover the script's CONTROL FLOW
(each step runs in order, a failure at any step aborts non-zero) hermetically.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup-restore-drill.sh"


def test_drill_script_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _fake_docker(bin_dir: Path, *, alembic_fails: bool = False) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    alembic_exit = "1" if alembic_fails else "0"
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "pg_dump" ]]; then echo "-- fake dump"; exit 0; fi\n'
        '  if [[ "$a" == "psql" ]]; then cat >/dev/null; exit 0; fi\n'
        f'  if [[ "$a" == "alembic" ]]; then exit {alembic_exit}; fi\n'
        "done\n"
        'if [[ "$*" == *"tar -czf -"* ]]; then printf WORKSPACEDATA; exit 0; fi\n'
        'if [[ "$*" == *"tar -xzf -"* ]]; then cat >/dev/null; exit 0; fi\n'
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *args: str, bin_dir: Path | None = None, selftest: bool = True):
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(tmp_path / "backups")
    # Never let the backup.sh/restore.sh calls this script makes touch the real
    # repo's .env — point it at a scratch path.
    env["APPLICANT_ENV_FILE"] = str(tmp_path / "live.env")
    if selftest:
        env["APPLICANT_SELFTEST"] = "1"
    return subprocess.run(["bash", str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def test_without_confirm_destroy_prints_plan_and_touches_nothing(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert "DRY RUN" in res.stdout
    assert "down -v" in res.stdout
    assert not (tmp_path / "backups").exists()


def test_confirmed_drill_passes_end_to_end_hermetically(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    res = _run(tmp_path, "--confirm-destroy", bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr + res.stdout
    assert "DRILL PASSED" in res.stdout
    # A real full backup tarball must have actually been produced along the way.
    backups = list((tmp_path / "backups").glob("applicant-full-*.tar.gz"))
    assert len(backups) == 1


def test_migration_failure_aborts_the_drill_non_zero(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir, alembic_fails=True)
    res = _run(tmp_path, "--confirm-destroy", bin_dir=bin_dir)
    assert res.returncode != 0
    assert "DRILL PASSED" not in res.stdout
    assert "alembic upgrade head failed" in res.stderr.lower() or "migration" in res.stderr.lower()
