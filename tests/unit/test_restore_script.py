"""Hermetic tests for scripts/restore.sh (P1-7, issue #659).

A fake ``docker`` on PATH stands in for the real CLI, capturing whatever the
script pipes to ``psql``/``tar`` over STDIN. No real docker/postgres is ever
invoked.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tarfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restore.sh"


def test_restore_script_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _make_backup_tarball(path: Path, *, db: bytes | None = b"-- fake dump\n",
                          workspace: bytes | None = b"WORKSPACEDATA",
                          config_env: bytes | None = None) -> None:
    work = path.parent / "_stage"
    work.mkdir(parents=True, exist_ok=True)
    if db is not None:
        (work / "db.sql").write_bytes(db)
    if workspace is not None:
        (work / "workspace-data.tar.gz").write_bytes(workspace)
    if config_env is not None:
        (work / "config").mkdir(exist_ok=True)
        (work / "config" / ".env").write_bytes(config_env)
    (work / "MANIFEST.txt").write_text("Applicant backup manifest\n", encoding="utf-8")
    with tarfile.open(path, "w:gz") as tf:
        for f in work.iterdir():
            tf.add(f, arcname=f.name)


def _fake_docker(bin_dir: Path, captured_psql: Path, captured_tar: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        f'  if [[ "$a" == "psql" ]]; then cat >"{captured_psql}"; exit 0; fi\n'
        "done\n"
        f'if [[ "$*" == *"tar -xzf -"* ]]; then cat >"{captured_tar}"; exit 0; fi\n'
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *args: str, bin_dir: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(tmp_path / "backups")
    # NEVER let this touch the real repo's .env (restore.sh WRITES to it) —
    # always point config restore at a scratch path under tmp_path instead.
    env["APPLICANT_ENV_FILE"] = str(tmp_path / "live.env")
    return subprocess.run(["bash", str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def test_dry_run_touches_nothing(tmp_path):
    (tmp_path / "backups").mkdir()
    tb = tmp_path / "backups" / "applicant-full-20260101T000000Z.tar.gz"
    _make_backup_tarball(tb)
    res = _run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert "(would run)" in res.stdout


def test_no_backup_found_aborts(tmp_path):
    (tmp_path / "backups").mkdir()
    res = _run(tmp_path, "--apply")
    assert res.returncode != 0
    assert "Nothing to restore" in res.stderr or "No backup tarball found" in res.stderr


def test_apply_restores_db_and_workspace_data_over_stdin(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    tb = backups / "applicant-full-20260101T000000Z.tar.gz"
    _make_backup_tarball(tb, db=b"-- SELECT 1;\n", workspace=b"WSBYTES")

    bin_dir = tmp_path / "bin"
    captured_psql = tmp_path / "captured_psql"
    captured_tar = tmp_path / "captured_tar"
    _fake_docker(bin_dir, captured_psql, captured_tar)

    res = _run(tmp_path, "--apply", "--from", str(tb), bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    assert captured_psql.read_bytes() == b"-- SELECT 1;\n"
    assert captured_tar.read_bytes() == b"WSBYTES"


def test_picks_newest_backup_when_no_from_given(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    old = backups / "applicant-full-20250101T000000Z.tar.gz"
    newest = backups / "applicant-full-20260101T000000Z.tar.gz"
    _make_backup_tarball(old, db=b"-- OLD\n")
    _make_backup_tarball(newest, db=b"-- NEWEST\n")
    os.utime(old, (1, 1))
    os.utime(newest, (10_000, 10_000))

    bin_dir = tmp_path / "bin"
    captured_psql = tmp_path / "captured_psql"
    captured_tar = tmp_path / "captured_tar"
    _fake_docker(bin_dir, captured_psql, captured_tar)

    res = _run(tmp_path, "--apply", bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    assert "applicant-full-20260101T000000Z.tar.gz" in res.stdout
    assert captured_psql.read_bytes() == b"-- NEWEST\n"


def test_missing_db_member_skips_db_restore_without_failing(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    tb = backups / "applicant-full-20260101T000000Z.tar.gz"
    _make_backup_tarball(tb, db=None)

    bin_dir = tmp_path / "bin"
    captured_psql = tmp_path / "captured_psql"
    captured_tar = tmp_path / "captured_tar"
    _fake_docker(bin_dir, captured_psql, captured_tar)

    res = _run(tmp_path, "--apply", "--from", str(tb), bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    assert not captured_psql.exists(), "no db.sql member means psql must never be invoked"


def test_config_member_present_is_restored_and_reports_next_steps(tmp_path):
    # ENV_FILE is overridden (via APPLICANT_ENV_FILE, set in _run above) to a
    # scratch path under tmp_path — this must NEVER touch the real repo's .env.
    # The no-clobber guarantee itself (never overwrite an EXISTING .env; write
    # alongside as .env.restored instead) is exercised directly against
    # bkup_restore_config in test_backup_common_lib.py; here we confirm the
    # end-to-end script actually restores the config member and reaches its
    # "Next:" guidance.
    backups = tmp_path / "backups"
    backups.mkdir()
    tb = backups / "applicant-full-20260101T000000Z.tar.gz"
    _make_backup_tarball(tb, config_env=b"POSTGRES_PASSWORD=frombackup\n")

    bin_dir = tmp_path / "bin"
    captured_psql = tmp_path / "captured_psql"
    captured_tar = tmp_path / "captured_tar"
    _fake_docker(bin_dir, captured_psql, captured_tar)

    res = _run(tmp_path, "--apply", "--from", str(tb), bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    assert "Next:" in res.stdout
    restored_env = tmp_path / "live.env"
    assert restored_env.read_text(encoding="utf-8") == "POSTGRES_PASSWORD=frombackup\n"
