"""Hermetic tests for scripts/backup.sh (P1-7, issue #659).

A fake ``docker`` on PATH stands in for the real CLI (pg_dump / tar streams).
``APPLICANT_BACKUP_DIR`` keeps every artifact under ``tmp_path`` — nothing here
ever touches the real repo's .backups/ or .env.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tarfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup.sh"


def test_backup_script_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _fake_docker(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    body = (
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "pg_dump" ]]; then echo "-- fake dump body"; exit 0; fi\n'
        "done\n"
        'if [[ "$*" == *"tar -czf -"* ]]; then printf WORKSPACEDATA; exit 0; fi\n'
        "exit 0\n"
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run(tmp_path: Path, *args: str, bin_dir: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(tmp_path / "backups")
    # Never let this read the real repo's .env — point it at a scratch path.
    env["APPLICANT_ENV_FILE"] = str(tmp_path / "live.env")
    return subprocess.run(["bash", str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def test_dry_run_creates_nothing(tmp_path):
    res = _run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert not (tmp_path / "backups").exists()
    assert "(would run)" in res.stdout


def test_apply_produces_one_tarball_with_expected_members(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    res = _run(tmp_path, "--apply", bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    backups = sorted((tmp_path / "backups").glob("applicant-full-*.tar.gz"))
    assert len(backups) == 1, res.stdout + res.stderr
    with tarfile.open(backups[0], "r:gz") as tf:
        names = set(tf.getnames())
        assert "./db.sql" in names or "db.sql" in names
        assert "./workspace-data.tar.gz" in names or "workspace-data.tar.gz" in names
        assert "./MANIFEST.txt" in names or "MANIFEST.txt" in names
        db_member = tf.extractfile([n for n in tf.getnames() if n.endswith("db.sql")][0])
        assert db_member.read().decode("utf-8").strip() == "-- fake dump body"
        ws_member = tf.extractfile([n for n in tf.getnames() if n.endswith("workspace-data.tar.gz")][0])
        assert ws_member.read() == b"WORKSPACEDATA"


def test_apply_leaves_gitignore_in_backup_dir(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    _run(tmp_path, "--apply", bin_dir=bin_dir)
    gi = tmp_path / "backups" / ".gitignore"
    assert gi.exists()
    assert gi.read_text(encoding="utf-8").strip() == "*"


def test_reuse_db_dump_skips_a_second_pg_dump(tmp_path):
    bin_dir = tmp_path / "bin"
    # A docker stub whose pg_dump branch FAILS -- proves the reused dump path
    # never calls pg_dump at all when --reuse-db-dump is given.
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "pg_dump" ]]; then echo "pg_dump should not run" >&2; exit 1; fi\n'
        "done\n"
        'if [[ "$*" == *"tar -czf -"* ]]; then printf WORKSPACEDATA; exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    pre_dump = tmp_path / "already-dumped.sql"
    pre_dump.write_text("-- pre-existing dump\n", encoding="utf-8")

    res = _run(tmp_path, "--apply", "--reuse-db-dump", str(pre_dump), bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    assert "reusing an already-taken dump" in res.stdout
    backups = sorted((tmp_path / "backups").glob("applicant-full-*.tar.gz"))
    assert len(backups) == 1
    with tarfile.open(backups[0], "r:gz") as tf:
        db_member = tf.extractfile([n for n in tf.getnames() if n.endswith("db.sql")][0])
        assert db_member.read().decode("utf-8").strip() == "-- pre-existing dump"


def test_pg_dump_failure_still_bundles_a_tarball_with_a_warning(tmp_path):
    # Best-effort: a failed DB dump degrades to a WARNING, not a hard abort --
    # this is a "download my data" style safety net, not the migration-gating
    # dump update.sh's own inline step already guards strictly.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "pg_dump" ]]; then exit 1; fi\n'
        "done\n"
        'if [[ "$*" == *"tar -czf -"* ]]; then printf WORKSPACEDATA; exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    res = _run(tmp_path, "--apply", bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    assert "will NOT include a db.sql member" in res.stderr
    assert "NO Postgres dump" in res.stderr
    backups = sorted((tmp_path / "backups").glob("applicant-full-*.tar.gz"))
    assert len(backups) == 1


def test_retention_prunes_older_full_backups(tmp_path):
    # Pre-seed two "old" full backups with distinct mtimes (rather than looping
    # the real script, which could mint the SAME once-per-second timestamp
    # filename twice and mask a broken prune behind a filename collision).
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True)
    old1 = backups_dir / "applicant-full-20250101T000000Z.tar.gz"
    old2 = backups_dir / "applicant-full-20250102T000000Z.tar.gz"
    old1.write_bytes(b"old1")
    old2.write_bytes(b"old2")
    os.utime(old1, (1, 1))
    os.utime(old2, (2, 2))

    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_BACKUP_DIR"] = str(backups_dir)
    env["APPLICANT_ENV_FILE"] = str(tmp_path / "live.env")
    env["BACKUP_KEEP_COUNT"] = "1"
    res = subprocess.run(["bash", str(_SCRIPT), "--apply"], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr

    backups = list(backups_dir.glob("applicant-full-*.tar.gz"))
    assert len(backups) == 1, "retention must prune down to BACKUP_KEEP_COUNT"
    assert old1 not in backups and old2 not in backups, "the two OLD backups must be the ones pruned"
