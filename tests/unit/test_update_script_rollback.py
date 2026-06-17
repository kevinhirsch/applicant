"""update.sh rollback restores the dump via STDIN, not ``psql -f`` (FR-INSTALL-2).

The updater writes its backup host-side (``pg_dump ... > host_file``). Rollback must
therefore read that host file host-side and pipe it into the container's ``psql`` over
STDIN. The prior bug used ``psql -f "${host_path}"``, which makes ``psql`` open the
path INSIDE the postgres container — where the host backup does not exist — so the
restore failed with "No such file or directory" while still reporting success.

These tests are hermetic: a fake ``docker`` on PATH stands in for the real CLI and
captures whatever the script pipes to it. No real docker/postgres is ever invoked.
APPLICANT_SELFTEST=1 keeps the updater from touching this repo (no git reset, no
live heartbeat).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update.sh"


def test_rollback_restore_uses_stdin_not_psql_dash_f():
    # Static guard scoped to the restore: the apply branch must pipe the dump in via a
    # STDIN redirect, and no `psql -f` (which would read the path inside the container).
    text = _SCRIPT.read_text(encoding="utf-8")
    # The restore is now a shared ``restore_dump`` helper (used by --rollback AND the
    # migration auto-rollback), defined before the "update path" marker.
    restore_block = text.split("update path")[0]
    # Real command lines only (skip comments, which legitimately mention `psql -f`).
    restore_lines = [
        ln for ln in restore_block.splitlines()
        if "psql" in ln and not ln.lstrip().startswith("#")
    ]
    assert restore_lines, "restore helper should invoke psql"
    # The applied restore must stream the dump over a STDIN redirect (host-side file
    # piped into the container's psql), e.g. ``... psql ... <"${file}"``.
    assert any('<"${' in ln for ln in restore_lines), (
        "the applied restore must stream the dump over STDIN (host-side redirect)"
    )
    # `psql -f` (text after the `psql` token), as opposed to the compose `-f <file>` flag.
    assert not any("-f " in ln.split("psql", 1)[1] for ln in restore_lines), (
        "restore must not use `psql -f <host_path>` (the path does not exist in-container)"
    )


def _make_fake_docker(tmp_path: Path, captured: Path) -> Path:
    """A fake ``docker`` whose ``compose ... psql`` copies its STDIN to ``captured``.

    If the script (incorrectly) used ``-f <path>`` instead of a STDIN redirect, the
    fake receives no STDIN and ``captured`` stays empty — failing the assertion.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "psql" ]]; then cat >' + str(captured) + "; exit 0; fi\n"
        "done\n"
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_rollback(tmp_path: Path, bin_dir: Path, backup_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(backup_dir)
    env["APPLICANT_SELFTEST"] = "1"
    return subprocess.run(
        ["bash", str(_SCRIPT), "--rollback", "--apply"],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_rollback_streams_latest_backup_over_stdin(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # Two dumps; the newest must be the one restored.
    (backup_dir / "applicant-20250101-000000.sql").write_text("-- OLD\n", encoding="utf-8")
    newest = backup_dir / "applicant-20260101-000000.sql"
    newest.write_text("-- NEWEST DUMP BODY\nSELECT 1;\n", encoding="utf-8")
    # Make mtime ordering unambiguous regardless of write order.
    os.utime(backup_dir / "applicant-20250101-000000.sql", (1, 1))
    os.utime(newest, (10_000, 10_000))

    captured = tmp_path / "captured.sql"
    bin_dir = _make_fake_docker(tmp_path, captured)
    res = _run_rollback(tmp_path, bin_dir, backup_dir)

    assert res.returncode == 0, res.stderr
    assert captured.exists(), "psql received no STDIN — restore likely used `-f` not a pipe"
    assert captured.read_text(encoding="utf-8") == newest.read_text(encoding="utf-8"), (
        "the NEWEST backup must be the one streamed into psql"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_rollback_aborts_when_no_backup_present(tmp_path):
    backup_dir = tmp_path / "empty"
    backup_dir.mkdir()
    captured = tmp_path / "captured.sql"
    bin_dir = _make_fake_docker(tmp_path, captured)
    res = _run_rollback(tmp_path, bin_dir, backup_dir)
    assert res.returncode != 0, "rollback with no backup must fail loudly"
    assert not captured.exists(), "nothing should be piped to psql when there is no backup"


def _make_fake_compose(tmp_path: Path) -> Path:
    """A fake ``docker`` whose ``compose ... pg_dump`` emits a plausible dump body."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "pg_dump" ]]; then echo "-- fake dump"; exit 0; fi\n'
        "done\n"
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_backup_dir_gets_gitignore_so_dumps_are_never_committed(tmp_path):
    # DB dumps contain ALL user data; the backup dir must carry a `*`-ignore so a stray
    # `git add -A` can never commit one (the default dir lives inside the repo tree).
    backup_dir = tmp_path / "backups"
    bin_dir = _make_fake_compose(tmp_path)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(backup_dir)
    env["APPLICANT_SELFTEST"] = "1"
    res = subprocess.run(
        ["bash", str(_SCRIPT), "--apply"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, res.stderr
    gi = backup_dir / ".gitignore"
    assert gi.exists(), "update.sh must drop a .gitignore into the backup dir"
    assert gi.read_text(encoding="utf-8").strip() == "*"
