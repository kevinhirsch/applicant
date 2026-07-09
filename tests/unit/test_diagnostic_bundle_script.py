"""Hermetic end-to-end coverage for scripts/diagnostic-bundle.sh (P5-1,
"Support machinery").

Mirrors tests/unit/test_backup_restore_drill_script.py's own approach: this
script's real job is to run `docker compose ...` against a live deploy host,
so these tests only ever run it against a FAKE `docker` on PATH (never real
Docker) — but that is enough to exercise the script's full control flow
end-to-end: it reads a scratch `.env`, "collects" fake compose status/logs,
packages everything into a real tarball, and — the actual DoD proof — a known
secret fed through every stage (the .env file AND the fake compose logs) is
verifiably ABSENT from every file the produced archive actually contains.

Fixture "secrets" are concatenation-built (see test_diagnostic_redact.py's own
docstring) so this file's source never contains a contiguous secret-shaped
literal that would trip scripts/ci/secret_scan.py.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tarfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "diagnostic-bundle.sh"

_FAKE_PASSWORD = "hunter2" + "SuperSecretPW9"
_FAKE_TOKEN = "deadbeef" + "cafebabe" + "01234567"
_FAKE_SK_KEY = "sk-ant-api03-" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_FAKE_GH_TOKEN = "ghp_" + "a" * 40


def test_script_is_valid_bash():
    res = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _fake_docker(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "docker"
    # A minimal fake `docker`/`docker compose` that strips the -f/--env-file
    # flags this script always passes, then answers version/ps/config/logs.
    # Both the fake `ps` and `logs` output deliberately embed a secret exactly
    # like a REAL `docker compose` invocation could (a service env var surfaced
    # in `ps`, a connection-string message in `logs`) — proving the script's
    # own redaction catches every collected artifact, not just the .env file.
    body = f"""#!/usr/bin/env bash
if [[ "$1" == "version" ]]; then echo "99.0.0-fake"; exit 0; fi
if [[ "$1" == "compose" ]]; then
  shift
  args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -f) shift 2 ;;
      --env-file) shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  set -- "${{args[@]}}"
  if [[ "$1" == "version" ]]; then echo "fake compose 2.99"; exit 0; fi
  if [[ "$1" == "ps" ]]; then
    echo "NAME  STATUS   CONFIG"
    echo "api   running  POSTGRES_PASSWORD={_FAKE_PASSWORD}"
    exit 0
  fi
  if [[ "$1" == "config" && "$2" == "--services" ]]; then
    printf 'applicant-ui\\napi\\npostgres\\n'
    exit 0
  fi
  if [[ "$1" == "logs" ]]; then
    svc="${{@: -1}}"
    echo "FAKELOG for ${{svc}}: connecting with POSTGRES_PASSWORD={_FAKE_PASSWORD} token={_FAKE_GH_TOKEN}"
    exit 0
  fi
fi
exit 0
"""
    fake.write_text(body, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *args: str, bin_dir: Path | None = None):
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["APPLICANT_ENV_FILE"] = str(tmp_path / "live.env")
    env["APPLICANT_DIAG_DIR"] = str(tmp_path / "out")
    # Point at a scratch compose file so no test implicitly depends on the real
    # docker/docker-compose.prod.yml existing (hermeticity). Its content is
    # irrelevant — the fake `docker` stub ignores the `-f` path — but the file
    # must EXIST, because the script guards its compose steps on `[[ -f ]]`.
    compose = tmp_path / "compose.yml"
    if not compose.exists():
        compose.write_text("services: {}\n", encoding="utf-8")
    env.setdefault("APPLICANT_DIAG_COMPOSE_FILE", str(compose))
    return subprocess.run(["bash", str(_SCRIPT), *args], capture_output=True, text=True, env=env)


def _write_secret_env(tmp_path: Path) -> None:
    (tmp_path / "live.env").write_text(
        "APP_PORT=8123\n"
        f"POSTGRES_PASSWORD={_FAKE_PASSWORD}\n"
        f"APPLICANT_INTERNAL_TOKEN={_FAKE_TOKEN}\n"
        f"LLM_API_KEY={_FAKE_SK_KEY}\n"
        f"DATABASE_URL=postgresql+psycopg://applicant:{_FAKE_PASSWORD}@postgres:5432/applicant\n",
        encoding="utf-8",
    )


def test_runs_without_docker_and_still_produces_an_honest_bundle(tmp_path):
    # Point COMPOSE_FILE at a path that doesn't exist -- deterministically
    # exercises the "docker/compose unavailable" branch regardless of whether
    # a `docker` binary happens to be installed on the host running this test
    # (real Docker Engine can be present with no reachable daemon/stack, which
    # a PATH-scrubbing trick wouldn't reliably simulate). The script must
    # degrade gracefully (H-series: an absent capability is reported, never
    # silently skipped without a trace) rather than crash.
    _write_secret_env(tmp_path)
    env = dict(os.environ)
    env["APPLICANT_ENV_FILE"] = str(tmp_path / "live.env")
    env["APPLICANT_DIAG_DIR"] = str(tmp_path / "out")
    env["APPLICANT_DIAG_COMPOSE_FILE"] = str(tmp_path / "no-such-compose.yml")
    archive = tmp_path / "out" / "bundle.tar.gz"
    res = subprocess.run(
        ["bash", str(_SCRIPT), "--output", str(archive)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, res.stderr + res.stdout
    assert archive.exists()
    with tarfile.open(archive) as tf:
        names = tf.getnames()
        manifest_member = next(n for n in names if n.endswith("MANIFEST.txt"))
        manifest_text = tf.extractfile(manifest_member).read().decode("utf-8")
    # Still collected the env (no docker needed for that) and said so...
    assert "env-sanitized.txt: collected" in manifest_text
    # ...but honestly reports the docker-dependent pieces as skipped, not silently
    # dropped (never renders an absent check as a present one).
    assert "SKIPPED" in manifest_text


def test_end_to_end_bundle_never_leaks_a_known_secret(tmp_path):
    bin_dir = tmp_path / "bin"
    _fake_docker(bin_dir)
    _write_secret_env(tmp_path)
    archive = tmp_path / "out" / "bundle.tar.gz"
    res = _run(tmp_path, "--output", str(archive), bin_dir=bin_dir)
    assert res.returncode == 0, res.stderr + res.stdout
    assert archive.exists()

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with tarfile.open(archive) as tf:
        tf.extractall(extract_dir)  # noqa: S202 - trusted, just-created test fixture

    all_text = ""
    collected_files = []
    for path in extract_dir.rglob("*"):
        if path.is_file():
            collected_files.append(path)
            all_text += path.read_text(encoding="utf-8", errors="replace")

    # The actual DoD proof: none of the known secrets survive ANYWHERE in the
    # produced bundle -- not the sanitized env, not the scrubbed per-service
    # logs, not any other collected file.
    for secret in (_FAKE_PASSWORD, _FAKE_TOKEN, _FAKE_SK_KEY, _FAKE_GH_TOKEN):
        assert secret not in all_text, f"leaked secret: {secret!r}"

    # And it did genuinely collect the things it claims to (not a bundle that
    # merely LOOKS complete because it collected nothing).
    names = {str(p.relative_to(extract_dir)) for p in collected_files}
    assert any(n.endswith("env-sanitized.txt") for n in names)
    assert any(n.endswith("version.txt") for n in names)
    assert any(n.endswith("compose-ps.txt") for n in names)
    assert any("logs" in n and n.endswith("api.log") for n in names)
    assert any(n.endswith("MANIFEST.txt") for n in names)

    # Targeted regression for the compose-ps redaction hole (CodeRabbit finding
    # on PR #783): the `ps` output carried a secret and it must NOT survive into
    # compose-ps.txt — the whole point of piping it through the redactor.
    compose_ps = next(p for p in collected_files if p.name == "compose-ps.txt")
    ps_text = compose_ps.read_text(encoding="utf-8")
    assert _FAKE_PASSWORD not in ps_text
    assert "***REDACTED***" in ps_text


def test_help_flag_exits_zero_without_touching_anything(tmp_path):
    res = _run(tmp_path, "--help")
    assert res.returncode == 0
    assert "Usage" in res.stdout
    assert not (tmp_path / "out").exists()


def test_unknown_flag_is_rejected(tmp_path):
    res = _run(tmp_path, "--bogus-flag")
    assert res.returncode == 2


def test_output_flag_without_a_path_fails_with_a_friendly_message(tmp_path):
    # Under `set -u`, consuming $2 without guarding it would crash with a bash
    # "unbound variable" error; the arg-parse loop must guard the operand and
    # exit 2 with an intentional message instead (Greptile P1 on PR #783).
    res = _run(tmp_path, "--output")
    assert res.returncode == 2
    combined = res.stdout + res.stderr
    assert "requires a path" in combined
    assert "unbound variable" not in combined


def test_output_short_alias_without_a_path_also_fails_friendly(tmp_path):
    res = _run(tmp_path, "-o")
    assert res.returncode == 2
    combined = res.stdout + res.stderr
    assert "requires a path" in combined
    assert "unbound variable" not in combined
