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
        # The engine-state export uses `run --rm --no-deps --entrypoint tar api -czf ...`
        # (no literal "tar -czf -" substring) — match it before the workspace form.
        # Pin the FULL durable dir list (Greptile finding on #736: secrets alone
        # is not a whole-instance backup) — a shorter list falls through to the
        # generic exit and stages an empty (deleted) member.
        'if [[ "$*" == *"--entrypoint tar"* && "$*" == *"-C /data secrets checkpoints fonts profiles"* ]]; then printf ENGINESTATE; exit 0; fi\n'
        'if [[ "$*" == *"tar -czf -"* ]]; then printf WORKSPACEDATA; exit 0; fi\n'
        'if [[ "$*" == *"--entrypoint tar"* && "$*" == *"-C /a0 usr"* ]]; then printf A0DATA; exit 0; fi\n'
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
        # The engine's durable volumes MUST ride along: the vault master key
        # (without it, sealed credentials in the restored db.sql are permanently
        # undecryptable after a volume wipe) plus checkpoints, fonts, and
        # browser profiles (Greptile findings on #736).
        assert "./engine-state.tar.gz" in names or "engine-state.tar.gz" in names
        assert "./MANIFEST.txt" in names or "MANIFEST.txt" in names
        manifest = tf.extractfile(
            [n for n in tf.getnames() if n.endswith("MANIFEST.txt")][0]
        ).read().decode("utf-8")
        assert "engine-state.tar.gz (vault master key, checkpoints, fonts, browser profiles): present" in manifest
        es_member = tf.extractfile([n for n in tf.getnames() if n.endswith("engine-state.tar.gz")][0])
        assert es_member.read() == b"ENGINESTATE"
        db_member = tf.extractfile([n for n in tf.getnames() if n.endswith("db.sql")][0])
        assert db_member.read().decode("utf-8").strip() == "-- fake dump body"
        ws_member = tf.extractfile([n for n in tf.getnames() if n.endswith("workspace-data.tar.gz")][0])
        assert ws_member.read() == b"WORKSPACEDATA"
        assert "./a0-shell-data.tar.gz" in names or "a0-shell-data.tar.gz" in names
        manifest = tf.extractfile(
            [n for n in tf.getnames() if n.endswith("MANIFEST.txt")][0]
        ).read().decode("utf-8")
        assert "a0-shell-data.tar.gz (a0 user data: settings, chats, memory, skills, plugins): present" in manifest
        a0_member = tf.extractfile([n for n in tf.getnames() if n.endswith("a0-shell-data.tar.gz")][0])
        assert a0_member.read() == b"A0DATA"


def test_a0_data_included_in_tarball(tmp_path):
    """Verify a0-shell-data.tar.gz is present in the backup tarball and manifest."""
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    res = _run(tmp_path, "--apply", bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr
    backups = sorted((tmp_path / "backups").glob("applicant-full-*.tar.gz"))
    assert len(backups) == 1, res.stdout + res.stderr
    with tarfile.open(backups[0], "r:gz") as tf:
        names = set(tf.getnames())
        assert "./a0-shell-data.tar.gz" in names or "a0-shell-data.tar.gz" in names
        assert "./MANIFEST.txt" in names or "MANIFEST.txt" in names
        manifest = tf.extractfile(
            [n for n in tf.getnames() if n.endswith("MANIFEST.txt")][0]
        ).read().decode("utf-8")
        assert "a0-shell-data.tar.gz (a0 user data: settings, chats, memory, skills, plugins): present" in manifest
        a0_member = tf.extractfile([n for n in tf.getnames() if n.endswith("a0-shell-data.tar.gz")][0])
        assert a0_member.read() == b"A0DATA"


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


def test_pg_dump_failure_fails_the_backup_hard(tmp_path):
    # A "backup" without db.sql cannot restore Postgres — automation keying
    # off exit 0 must never archive one, so a failed dump is a hard abort,
    # not a warning (disaster-recovery invariant; Greptile finding on #736).
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
    assert res.returncode != 0
    assert "Backup FAILED" in res.stderr
    backups = sorted((tmp_path / "backups").glob("applicant-full-*.tar.gz"))
    assert backups == []


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
