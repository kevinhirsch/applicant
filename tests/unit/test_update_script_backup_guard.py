"""update.sh backup guard (FR-INSTALL-2).

The updater must back up BEFORE migrate so rollback is always possible. A FAILED or
EMPTY backup must abort the run before ``alembic upgrade head`` ever executes — the
prior bug swallowed pg_dump failures with ``|| true`` and proceeded to migrate with
no valid backup.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update.sh"


def test_update_script_is_valid_bash():
    # bash -n parses without executing (catches syntax regressions).
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_backup_line_has_no_swallow_and_checks_non_empty():
    text = _SCRIPT.read_text(encoding="utf-8")
    # Control-flow guarantees: no "|| true" swallowing a failed backup, and a
    # non-empty-dump check (-s) gating the migrate step.
    assert "|| true" not in text.split("Pulling new images")[0].split("Backing up")[1]
    assert '[[ ! -s "${DUMP_FILE}" ]]' in text
    # backup still precedes migrate (safe order).
    assert text.index("pg_dump") < text.index("alembic upgrade head")


def _make_fake_compose(tmp_path: Path, *, pg_dump_fails: bool) -> Path:
    """A fake ``docker`` on PATH whose ``compose ... pg_dump`` fails or succeeds.

    The script invokes ``docker compose -f <file> exec -T postgres pg_dump ...``;
    this stub inspects its args and either exits non-zero (failed backup) or emits a
    plausible dump body to stdout (which the script redirects into DUMP_FILE).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    if pg_dump_fails:
        body = (
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do\n'
            '  if [[ "$a" == "pg_dump" ]]; then echo "pg_dump: boom" >&2; exit 1; fi\n'
            "done\n"
            "exit 0\n"
        )
    else:
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


def _run_update(tmp_path: Path, bin_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(tmp_path / "backups")
    return subprocess.run(
        ["bash", str(_SCRIPT), "--apply"],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_aborts_on_backup_failure_before_migrate(tmp_path):
    bin_dir = _make_fake_compose(tmp_path, pg_dump_fails=True)
    res = _run_update(tmp_path, bin_dir)
    assert res.returncode != 0, "a failed backup must abort the update"
    # It must NOT have proceeded to migrate / pull (those run AFTER the backup step).
    assert "Running database migrations" not in res.stdout
    # No garbage dump file left behind.
    dumps = list((tmp_path / "backups").glob("applicant-*.sql"))
    assert dumps == [], "a failed backup must not leave a dump file"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_proceeds_when_backup_succeeds(tmp_path):
    bin_dir = _make_fake_compose(tmp_path, pg_dump_fails=False)
    res = _run_update(tmp_path, bin_dir)
    assert res.returncode == 0, res.stderr
    assert "Running database migrations" in res.stdout
    dumps = list((tmp_path / "backups").glob("applicant-*.sql"))
    assert len(dumps) == 1 and dumps[0].stat().st_size > 0
