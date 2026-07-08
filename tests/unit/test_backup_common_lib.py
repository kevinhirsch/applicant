"""Hermetic unit tests for scripts/lib/backup-common.sh (P1-7, issue #659).

These call the shared bash functions directly (not through backup.sh/restore.sh)
with fully caller-supplied paths, so they never touch the real repo's .env or
docker/docker-compose.prod.yml. A fake ``docker`` on PATH stands in for the real
CLI; no real docker/postgres is ever invoked.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "scripts" / "lib" / "backup-common.sh"


def test_lib_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_LIB)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _fake_docker(bin_dir: Path, *, pg_dump_ok: bool = True, tar_ok: bool = True) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    if pg_dump_ok:
        pg_dump_line = '  if [[ "$a" == "pg_dump" ]]; then echo "-- fake dump"; exit 0; fi\n'
    else:
        pg_dump_line = '  if [[ "$a" == "pg_dump" ]]; then echo boom >&2; exit 1; fi\n'
    if tar_ok:
        tar_export_line = 'if [[ "$*" == *"tar -czf -"* ]]; then printf FAKEDATA; exit 0; fi\n'
    else:
        tar_export_line = 'if [[ "$*" == *"tar -czf -"* ]]; then exit 1; fi\n'
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        + pg_dump_line
        + '  if [[ "$a" == "psql" ]]; then cat >"$CAPTURE_PSQL_STDIN" 2>/dev/null || cat >/dev/null; exit 0; fi\n'
        "done\n"
        # tar export (docker compose exec ... tar -czf - ...): emit bytes on stdout.
        + tar_export_line
        + 'if [[ "$*" == *"tar -xzf -"* ]]; then cat >"$CAPTURE_TAR_STDIN" 2>/dev/null || cat >/dev/null; exit 0; fi\n'
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(bash_snippet: str, tmp_path: Path, *, bin_dir: Path | None = None, env_extra: dict | None = None):
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    if env_extra:
        env.update(env_extra)
    script = f'set -euo pipefail\nsource "{_LIB}"\n{bash_snippet}\n'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=tmp_path, env=env)


# --- bkup_load_env -----------------------------------------------------------


def test_load_env_does_not_clobber_explicit_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from_file\nBAR=also_from_file\n", encoding="utf-8")
    res = _run(
        f'bkup_load_env "{env_file}"; echo "FOO=$FOO"; echo "BAR=$BAR"',
        tmp_path,
        env_extra={"FOO": "from_caller"},
    )
    assert res.returncode == 0, res.stderr
    assert "FOO=from_caller" in res.stdout
    assert "BAR=also_from_file" in res.stdout


def test_load_env_missing_file_is_a_noop(tmp_path):
    res = _run(f'bkup_load_env "{tmp_path}/nope.env"; echo done', tmp_path)
    assert res.returncode == 0, res.stderr
    assert "done" in res.stdout


# --- bkup_dump_database --------------------------------------------------------


def test_dump_database_dry_run_touches_nothing(tmp_path):
    out = tmp_path / "db.sql"
    res = _run(
        f'bkup_dump_database compose.yml postgres applicant applicant "{out}" 0',
        tmp_path,
    )
    assert res.returncode == 0, res.stderr
    assert not out.exists()


def test_dump_database_apply_success(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir, pg_dump_ok=True)
    out = tmp_path / "db.sql"
    res = _run(
        f'bkup_dump_database compose.yml postgres applicant applicant "{out}" 1',
        tmp_path,
        bin_dir=bin_dir,
    )
    assert res.returncode == 0, res.stderr
    assert out.read_text(encoding="utf-8").strip() == "-- fake dump"


def test_dump_database_apply_failure_leaves_no_partial_file(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir, pg_dump_ok=False)
    out = tmp_path / "db.sql"
    res = _run(
        f'if bkup_dump_database compose.yml postgres applicant applicant "{out}" 1; then echo OK; else echo FAIL; fi',
        tmp_path,
        bin_dir=bin_dir,
    )
    assert res.returncode == 0, res.stderr
    assert "FAIL" in res.stdout
    assert not out.exists()


# --- bkup_restore_database -----------------------------------------------------


def test_restore_database_streams_dump_over_stdin_not_dash_f(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    captured = tmp_path / "captured_psql_stdin"
    dump = tmp_path / "db.sql"
    dump.write_text("-- SELECT 1;\n", encoding="utf-8")
    res = _run(
        f'bkup_restore_database compose.yml postgres applicant applicant "{dump}" 1',
        tmp_path,
        bin_dir=bin_dir,
        env_extra={"CAPTURE_PSQL_STDIN": str(captured)},
    )
    assert res.returncode == 0, res.stderr
    assert captured.read_text(encoding="utf-8") == "-- SELECT 1;\n"


def test_restore_database_dry_run_touches_nothing(tmp_path):
    res = _run('bkup_restore_database compose.yml postgres applicant applicant db.sql 0', tmp_path)
    assert res.returncode == 0, res.stderr
    assert "(would run)" in res.stdout


# --- bkup_export_workspace_data / bkup_restore_workspace_data -----------------


def test_export_workspace_data_apply_success(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir, tar_ok=True)
    out = tmp_path / "workspace-data.tar.gz"
    res = _run(
        f'bkup_export_workspace_data compose.yml applicant-ui "{out}" 1',
        tmp_path,
        bin_dir=bin_dir,
    )
    assert res.returncode == 0, res.stderr
    assert out.read_bytes() == b"FAKEDATA"


def test_export_workspace_data_failure_is_reported_and_cleaned_up(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir, tar_ok=False)
    out = tmp_path / "workspace-data.tar.gz"
    res = _run(
        f'if bkup_export_workspace_data compose.yml applicant-ui "{out}" 1; then echo OK; else echo FAIL; fi',
        tmp_path,
        bin_dir=bin_dir,
    )
    assert "FAIL" in res.stdout
    assert not out.exists()


def test_restore_workspace_data_streams_file_over_stdin(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    captured = tmp_path / "captured_tar_stdin"
    src = tmp_path / "workspace-data.tar.gz"
    src.write_bytes(b"ROUNDTRIP-BYTES")
    res = _run(
        f'bkup_restore_workspace_data compose.yml applicant-ui "{src}" 1',
        tmp_path,
        bin_dir=bin_dir,
        env_extra={"CAPTURE_TAR_STDIN": str(captured)},
    )
    assert res.returncode == 0, res.stderr
    assert captured.read_bytes() == b"ROUNDTRIP-BYTES"


# --- bkup_collect_config / bkup_restore_config --------------------------------


def test_collect_config_missing_env_is_not_an_error(tmp_path):
    out_dir = tmp_path / "config"
    res = _run(
        f'if bkup_collect_config "{tmp_path}/nope.env" "{out_dir}" 1; then echo OK; else echo FAIL; fi',
        tmp_path,
    )
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout
    assert not (out_dir / ".env").exists()


def test_collect_config_copies_at_mode_600(tmp_path):
    env_file = tmp_path / "src.env"
    env_file.write_text("SECRET=1\n", encoding="utf-8")
    out_dir = tmp_path / "config"
    res = _run(f'bkup_collect_config "{env_file}" "{out_dir}" 1', tmp_path)
    assert res.returncode == 0, res.stderr
    dest = out_dir / ".env"
    assert dest.read_text(encoding="utf-8") == "SECRET=1\n"
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_restore_config_writes_dot_restored_when_dest_exists(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".env").write_text("FROM_BACKUP=1\n", encoding="utf-8")
    dest = tmp_path / ".env"
    dest.write_text("LIVE=1\n", encoding="utf-8")
    res = _run(f'bkup_restore_config "{config_dir}" "{dest}" 1', tmp_path)
    assert res.returncode == 0, res.stderr
    assert dest.read_text(encoding="utf-8") == "LIVE=1\n", "must never clobber a live .env"
    restored = tmp_path / ".env.restored"
    assert restored.read_text(encoding="utf-8") == "FROM_BACKUP=1\n"


def test_restore_config_writes_directly_when_no_dest_exists(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".env").write_text("FROM_BACKUP=1\n", encoding="utf-8")
    dest = tmp_path / ".env"
    res = _run(f'bkup_restore_config "{config_dir}" "{dest}" 1', tmp_path)
    assert res.returncode == 0, res.stderr
    assert dest.read_text(encoding="utf-8") == "FROM_BACKUP=1\n"


def test_restore_config_noop_when_backup_has_no_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    dest = tmp_path / ".env"
    res = _run(
        f'if bkup_restore_config "{config_dir}" "{dest}" 1; then echo OK; else echo FAIL; fi',
        tmp_path,
    )
    assert "OK" in res.stdout
    assert not dest.exists()


# --- bkup_make_tarball / bkup_extract_tarball ---------------------------------


def test_make_and_extract_tarball_roundtrip(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "db.sql").write_text("-- dump\n", encoding="utf-8")
    out = tmp_path / "out.tar.gz"
    dest = tmp_path / "extracted"
    res = _run(
        f'bkup_make_tarball "{out}" "{work_dir}" 1 && bkup_extract_tarball "{out}" "{dest}" 1',
        tmp_path,
    )
    assert res.returncode == 0, res.stderr
    assert (dest / "db.sql").read_text(encoding="utf-8") == "-- dump\n"


def test_make_tarball_dry_run_touches_nothing(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    out = tmp_path / "out.tar.gz"
    res = _run(f'bkup_make_tarball "{out}" "{work_dir}" 0', tmp_path)
    assert res.returncode == 0, res.stderr
    assert not out.exists()


# --- bkup_write_manifest -------------------------------------------------------


def test_write_manifest_reports_presence_honestly(tmp_path):
    out = tmp_path / "MANIFEST.txt"
    res = _run(f'bkup_write_manifest "{out}" 1 0 1', tmp_path)
    assert res.returncode == 0, res.stderr
    text = out.read_text(encoding="utf-8")
    assert "db.sql (Postgres dump): present" in text
    assert "workspace-data.tar.gz (front-door UI data/): MISSING" in text
    assert "config/.env: present" in text
