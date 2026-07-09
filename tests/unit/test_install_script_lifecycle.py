"""Hermetic tests for scripts/install.sh's lifecycle modes (P3-1, DoD: "clean
upgrade and uninstall paths tested").

install.sh already ships full ``--uninstall`` (stop + remove containers, KEEP
data) and ``--purge`` (also destroy volumes/images/.env, confirm-gated) modes —
this file did not previously exist. These tests never touch a real Docker
daemon: a fake ``docker`` shim on PATH records every invocation to a log file so
we can assert exactly what the script would run, without needing docker/compose
installed. The genuine live-stack drill (build real images, bring the stack up,
uninstall, purge) is a manual/CI-dispatch step — see docs/install-targets.md and
the ``install-uninstall-drill`` job in .github/workflows/ci-integration.yml.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install.sh"


def test_install_script_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _fake_docker(bin_dir: Path, log_file: Path) -> None:
    """A docker shim that logs every invocation and always reports success.

    ``docker info`` (reachability probe) and ``docker compose ...`` calls all
    succeed; nothing here talks to a real daemon.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "docker $*" >>"{log_file}"\n'
        'if [[ "$1" == "info" ]]; then exit 0; fi\n'
        'if [[ "$1" == "compose" ]]; then\n'
        '  if [[ "$*" == *"ps --format json"* ]]; then echo -n ""; exit 0; fi\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == "--version" ]]; then echo "Docker version 27.0.0, fake"; exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *args: str, extra_env: dict | None = None, tty: bool = False):
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker.log"
    _fake_docker(bin_dir, log_file)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    # Isolate the .env this run would persist to: install.sh derives ENV_FILE
    # from its own location (REPO_ROOT/.env), which we can't override, so run
    # from a COPY of the script in a scratch checkout-like dir instead of ever
    # touching the real repo's .env.
    scratch_repo = tmp_path / "repo"
    (scratch_repo / "scripts").mkdir(parents=True, exist_ok=True)
    (scratch_repo / "docker").mkdir(parents=True, exist_ok=True)
    script_copy = scratch_repo / "scripts" / "install.sh"
    script_copy.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script_copy.chmod(script_copy.stat().st_mode | stat.S_IEXEC)
    (scratch_repo / "docker" / "docker-compose.prod.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    env["APPLICANT_NO_TUI"] = "1"
    env["APPLICANT_SKIP_DOCKER_INSTALL"] = "1"
    if not tty:
        env.pop("APPLICANT_FORCE_TTY", None)
    if extra_env:
        env.update(extra_env)
    res = subprocess.run(
        ["bash", str(script_copy), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(scratch_repo),
        stdin=subprocess.DEVNULL,  # never a TTY -> no interactive prompt path
    )
    log = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    return res, log, scratch_repo


def test_default_dry_run_touches_no_env_and_makes_no_destructive_docker_call(tmp_path):
    res, log, scratch_repo = _run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert "DRY RUN" in res.stdout or "(would run)" in res.stdout
    # The dry run must never persist credentials (APPLY=0 guards write_env()).
    assert not (scratch_repo / ".env").exists()
    # No compose "up"/"build"/"run" was actually issued — only read-only
    # informational docker calls (--version, info) are allowed to execute for
    # real in a dry run.
    for line in log.splitlines():
        assert not any(
            destructive in line for destructive in ("compose -f", "up -d", "build ", "run --rm")
        ), f"dry run executed a real compose command: {line!r}"


def test_uninstall_stops_containers_but_never_touches_volumes(tmp_path):
    res, log, _ = _run(tmp_path, "--uninstall")
    assert res.returncode == 0, res.stderr
    assert "down --remove-orphans" in log
    # The whole point of --uninstall (vs --purge) is that it MUST NOT pass
    # --volumes/-v or --rmi — that would silently destroy data on an
    # uninstall a operator expected to be reversible.
    assert "--volumes" not in log
    assert "-v " not in log
    assert "--rmi" not in log


def test_purge_without_confirmation_refuses_and_touches_nothing(tmp_path):
    # No -y/--yes and no TTY to prompt -> must refuse rather than silently
    # proceeding to destroy data (never destroy a running stack implicitly).
    res, log, _ = _run(tmp_path, "--purge")
    assert res.returncode != 0
    assert "--volumes" not in log
    assert "confirmation" in (res.stdout + res.stderr).lower()


def test_purge_with_explicit_yes_removes_volumes_images_and_env(tmp_path):
    # Seed a .env at the deterministic scratch-repo path _run() derives ENV_FILE
    # from (REPO_ROOT/.env), so purge has a real file to delete. _run() recreates
    # the dir with exist_ok and rewrites only the script + compose file — it never
    # touches an existing .env — so this pre-seeded file is present when purge runs.
    scratch_repo = tmp_path / "repo"
    scratch_repo.mkdir(parents=True, exist_ok=True)
    env_file = scratch_repo / ".env"
    env_file.write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    res, log, _ = _run(tmp_path, "--purge", "-y")
    assert res.returncode == 0, res.stderr
    assert "down --volumes --rmi local --remove-orphans" in log
    # The regression this guards (Greptile P2 on PR #780): purge must ACTUALLY
    # delete .env, not merely log that it would — assert the file is gone.
    assert not env_file.exists()


def test_doctor_mode_is_read_only(tmp_path):
    res, log, _ = _run(tmp_path, "--doctor")
    # With the fake docker reporting empty `ps` output, doctor should report a
    # diagnosis (exit 0 or 1 depending on health) without ever mutating state.
    assert "up -d" not in log
    assert "build " not in log
    assert "--volumes" not in log


def test_help_lists_all_lifecycle_modes(tmp_path):
    res = subprocess.run(["bash", str(_SCRIPT), "--help"], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    for mode in ("--apply", "--update", "--doctor", "--uninstall", "--purge"):
        assert mode in res.stdout
