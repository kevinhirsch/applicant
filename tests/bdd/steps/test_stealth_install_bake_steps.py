"""Step bindings for the stealth-install-bake acceptance spec (EPIC STEALTH).

Real regression coverage for behaviour that ships on this branch: the a0 image
bakes the residential-escalation `_browser` patch, the prod compose surfaces the
residential-proxy env defaults, install/update run a shared stealth preflight, and
that preflight fails LOUDLY (and hard-aborts under strict) when a stealth prereq is
missing — including a home-IP-leak canary.

Nothing here touches a real docker daemon, browser, or network: the image/compose/
scripts are asserted statically, and the shell preflight lib is driven in a
subprocess under an isolated PATH of coreutils + scripted `curl`/`wg` shims.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[3]
_LIB = _REPO / "scripts" / "lib" / "stealth-preflight.sh"

scenarios("../features/enhancements/spec_stealth_install_bake.feature")

_COREUTILS = ("bash", "sh", "tr", "head", "id", "mkdir", "cp", "ls", "cat", "dirname", "env", "grep", "sleep", "tee")


@pytest.fixture
def sctx() -> dict:
    return {}


def _isolated_bin(tmp: Path, *, with_wg: bool, egress_ip: str, proxy_ok: bool) -> Path:
    b = tmp / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for tool in _COREUTILS:
        real = shutil.which(tool)
        if real:
            (b / tool).symlink_to(real)
    curl = b / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do [[ "$a" == "-x" ]] && exit %d; done\n'
        'echo "%s"\n' % (0 if proxy_ok else 1, egress_ip),
        encoding="utf-8",
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    if with_wg:
        for name, body in (
            ("wg", 'case "$1" in --version) echo "wireguard-tools v1.0";; '
                   'show) [[ "$2" == interfaces ]] && echo "wg0" || echo "interface: wg0";; esac\n'),
            ("wg-quick", 'echo wq\n'),
        ):
            f = b / name
            f.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
            f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return b


def _run_preflight(tmp: Path, bin_dir: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": str(bin_dir), "REPO_ROOT": str(_REPO), "HOME": str(tmp)}
    if env_extra:
        env.update(env_extra)
    script = f'set -euo pipefail\nsource "{_LIB}"\nstealth_preflight 0\n'
    return subprocess.run(
        [str(bin_dir / "bash"), "-c", script], capture_output=True, text=True, env=env
    )


# --- Background -------------------------------------------------------------
@given("the Applicant repository checkout")
def repo_checkout(sctx):
    sctx["repo"] = _REPO
    assert _LIB.is_file()


# --- Static structure -------------------------------------------------------
@when("I inspect the a0 image build")
def inspect_a0_image(sctx):
    sctx["dockerfile_a0"] = (_REPO / "docker" / "Dockerfile.a0").read_text()


@then("the three patched _browser files are copied onto the baked core plugin")
def a0_copies_patch(sctx):
    text = sctx["dockerfile_a0"]
    for dst in (
        "/a0/plugins/_browser/helpers/config.py",
        "/a0/plugins/_browser/helpers/runtime.py",
        "/a0/plugins/_browser/default_config.yaml",
    ):
        assert dst in text


@then("the build asserts the escalation marker so a clobbered overlay fails loudly")
def a0_asserts_marker(sctx):
    text = sctx["dockerfile_a0"]
    assert "grep -q" in text
    assert "get_residential_proxy_config" in text
    assert "_should_escalate_to_residential" in text


@when("I inspect the a0 service environment")
def inspect_a0_env(sctx):
    spec = yaml.safe_load((_REPO / "docker" / "docker-compose.prod.yml").read_text())
    sctx["a0_env"] = spec["services"]["a0"]["environment"]


@then("the residential-proxy escalation env vars are present with the residential defaults")
def a0_env_defaults(sctx):
    env = sctx["a0_env"]
    assert ":-true}" in str(env["A0_BROWSER_RESIDENTIAL_PROXY_ENABLED"])
    assert "10.8.0.1:8880" in str(env["A0_BROWSER_RESIDENTIAL_PROXY"])


@when("I inspect the install and update scripts")
def inspect_scripts(sctx):
    sctx["install"] = (_REPO / "scripts" / "install.sh").read_text()
    sctx["update"] = (_REPO / "scripts" / "update.sh").read_text()


@then("both source and call the shared stealth preflight")
def scripts_wire_preflight(sctx):
    for text in (sctx["install"], sctx["update"]):
        assert "scripts/lib/stealth-preflight.sh" in text
        assert "stealth_preflight" in text


# --- Behavioural (subprocess) ----------------------------------------------
@given("a host with the WireGuard client installed and egress exiting the VPS")
def host_ok(sctx, tmp_path):
    sctx["bin"] = _isolated_bin(tmp_path, with_wg=True, egress_ip="173.254.204.32", proxy_ok=True)
    sctx["tmp"] = tmp_path


@given("a host missing the WireGuard client")
def host_no_wg(sctx, tmp_path):
    sctx["bin"] = _isolated_bin(tmp_path, with_wg=False, egress_ip="173.254.204.32", proxy_ok=True)
    sctx["tmp"] = tmp_path


@given("a host whose egress IP is not the VPS")
def host_leak(sctx, tmp_path):
    sctx["bin"] = _isolated_bin(tmp_path, with_wg=True, egress_ip="72.208.174.40", proxy_ok=False)
    sctx["tmp"] = tmp_path


@when("the stealth preflight runs")
def run_default(sctx):
    sctx["res"] = _run_preflight(sctx["tmp"], sctx["bin"])


@when("the stealth preflight runs in non-strict mode")
def run_nonstrict(sctx):
    sctx["res"] = _run_preflight(sctx["tmp"], sctx["bin"], {"APPLICANT_STEALTH_STRICT": "false"})


@when("the stealth preflight runs in strict mode")
def run_strict(sctx):
    sctx["res"] = _run_preflight(sctx["tmp"], sctx["bin"], {"APPLICANT_STEALTH_STRICT": "true"})


@then("it reports no home-IP leak and succeeds")
def ok_no_leak(sctx):
    res = sctx["res"]
    assert res.returncode == 0, res.stderr
    assert "no home-IP leak" in (res.stdout + res.stderr)


@then("it loudly warns about the home-IP risk and still returns success")
def warn_but_ok(sctx):
    res = sctx["res"]
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "MISSING" in out and "HOME IP" in out


@then("it fails and aborts the deploy")
def fail_abort(sctx):
    res = sctx["res"]
    assert res.returncode != 0
    assert "FAILED (strict)" in (res.stdout + res.stderr)


@then("it flags a home-IP leak risk and aborts the deploy")
def leak_abort(sctx):
    res = sctx["res"]
    assert res.returncode != 0
    assert "HOME-IP LEAK RISK" in (res.stdout + res.stderr)
