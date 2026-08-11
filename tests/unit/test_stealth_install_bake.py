"""EPIC STEALTH / stealth-install-bake — a fresh install/update SHIPS the stealth
prerequisites and a rebuild permanently BAKES the browser residential-escalation
patch into the a0 image.

Two layers of coverage, both hermetic (no real docker/browser/network):

1. STRUCTURE — the image/compose/scripts actually carry the wiring:
   * docker/Dockerfile.a0 COPYs the three patched `_browser` files onto
     /a0/plugins/_browser and fails the build loudly if the escalation marker is
     gone after the COPY (so a broken overlay never silently ships un-patched).
   * the staged patch files exist and carry the escalation markers.
   * docker-compose.prod.yml (a0 service) surfaces the residential-proxy env vars
     with the residential DEFAULTS the baked patch reads.
   * install.sh + update.sh source + call the shared stealth preflight.

2. BEHAVIOUR — scripts/lib/stealth-preflight.sh, driven end-to-end in a subprocess
   under an isolated PATH, fails LOUDLY when a stealth prereq is missing and hard-
   aborts under APPLICANT_STEALTH_STRICT (the "never leak the home IP" gate),
   including a home-IP-leak canary (egress IP != the VPS).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
_DOCKERFILE_A0 = _REPO / "docker" / "Dockerfile.a0"
_COMPOSE = _REPO / "docker" / "docker-compose.prod.yml"
_INSTALL = _REPO / "scripts" / "install.sh"
_UPDATE = _REPO / "scripts" / "update.sh"
_LIB = _REPO / "scripts" / "lib" / "stealth-preflight.sh"
_PATCH_DIR = _REPO / "docker" / "a0-browser-patch"
_WG_TEMPLATE = _REPO / "scripts" / "stealth" / "wg-egress.conf.template"


# ---------------------------------------------------------------------------
# 1. STRUCTURE — the patch is baked into the a0 image
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_staged_patch_files_present_with_escalation_markers():
    cfg = (_PATCH_DIR / "helpers" / "config.py").read_text()
    rt = (_PATCH_DIR / "helpers" / "runtime.py").read_text()
    dc = (_PATCH_DIR / "default_config.yaml").read_text()
    assert "def get_residential_proxy_config" in cfg
    assert "_should_escalate_to_residential" in rt
    assert "force-webrtc-ip-handling-policy" in rt  # WebRTC-leak suppression
    assert "residential_proxy_enabled" in dc
    assert "residential_proxy_server" in dc


@pytest.mark.unit
def test_dockerfile_a0_bakes_browser_patch_onto_core_plugin():
    text = _DOCKERFILE_A0.read_text()
    copies = [ln for ln in text.splitlines() if ln.strip().startswith("COPY")]
    joined = "\n".join(copies)
    # All three patch files land on the BAKED core plugin path (not /a0/usr, which a
    # named volume would mask, and not the applicant plugin dir).
    for src, dst in (
        ("docker/a0-browser-patch/helpers/config.py", "/a0/plugins/_browser/helpers/config.py"),
        ("docker/a0-browser-patch/helpers/runtime.py", "/a0/plugins/_browser/helpers/runtime.py"),
        ("docker/a0-browser-patch/default_config.yaml", "/a0/plugins/_browser/default_config.yaml"),
    ):
        assert src in joined and dst in joined, f"Dockerfile.a0 must COPY {src} -> {dst}"


@pytest.mark.unit
def test_dockerfile_a0_fails_loudly_if_patch_marker_missing():
    # A RUN step must assert the escalation marker is present AFTER the COPY, so a
    # base-digest bump that clobbers the overlay fails the build instead of silently
    # shipping an un-patched browser.
    text = _DOCKERFILE_A0.read_text()
    assert "get_residential_proxy_config" in text
    assert "_should_escalate_to_residential" in text
    assert "grep -q" in text, "Dockerfile.a0 must grep-assert the baked patch marker"


# ---------------------------------------------------------------------------
# 1. STRUCTURE — compose surfaces the residential-proxy env with defaults
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_compose_a0_service_surfaces_residential_proxy_defaults():
    spec = yaml.safe_load(_COMPOSE.read_text())
    env = spec["services"]["a0"]["environment"]
    # The baked patch reads exactly these env names (config.py RESIDENTIAL_PROXY_ENV_*).
    enabled = env["A0_BROWSER_RESIDENTIAL_PROXY_ENABLED"]
    server = env["A0_BROWSER_RESIDENTIAL_PROXY"]
    # Present as env-overridable interpolations with the residential presets as default.
    assert "A0_BROWSER_RESIDENTIAL_PROXY_ENABLED" in str(enabled)
    assert ":-true}" in str(enabled)
    assert "10.8.0.1:8880" in str(server)  # the VPS tunnel forwarder default


# ---------------------------------------------------------------------------
# 1. STRUCTURE — install/update ship + verify the stealth deps
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_scripts_are_valid_bash():
    for script in (_INSTALL, _UPDATE, _LIB):
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, f"{script.name}: {res.stderr}"


@pytest.mark.unit
@pytest.mark.parametrize("script", [_INSTALL, _UPDATE])
def test_install_and_update_source_and_call_stealth_preflight(script):
    text = script.read_text()
    assert "scripts/lib/stealth-preflight.sh" in text, f"{script.name} must source the shared lib"
    assert "stealth_preflight" in text, f"{script.name} must call stealth_preflight"
    assert "stealth_verify_image" in text, f"{script.name} must call stealth_verify_image"


@pytest.mark.unit
def test_lib_defines_the_preflight_contract():
    text = _LIB.read_text()
    for fn in ("stealth_preflight()", "stealth_verify_image()", "stealth_is_strict()"):
        assert fn in text, f"stealth-preflight.sh must define {fn}"
    # WireGuard is the concrete host dependency the installer now ships.
    assert "wireguard" in text.lower()
    assert "wg-quick" in text


@pytest.mark.unit
def test_wireguard_config_template_is_parameterized():
    text = _WG_TEMPLATE.read_text()
    assert "[Interface]" in text and "[Peer]" in text
    # VPS endpoint + pubkey + peer address are parameterized (never hardcoded secrets).
    for placeholder in ("${WG_PRIVATE_KEY}", "${WG_VPS_PUBKEY}", "WG_VPS_ENDPOINT", "WG_PEER_ADDRESS"):
        assert placeholder in text
    assert "173.254.204.32" in text  # the documented VPS egress default


# ---------------------------------------------------------------------------
# 2. BEHAVIOUR — drive the preflight lib in an isolated subprocess
# ---------------------------------------------------------------------------
_COREUTILS = ("bash", "sh", "tr", "head", "id", "mkdir", "cp", "ls", "cat", "dirname", "env", "grep", "sleep", "tee")


def _isolated_bin(tmp: Path, *, with_wg: bool, egress_ip: str, proxy_ok: bool) -> Path:
    """Build a bin dir with only coreutils + a scripted curl (+ optional wg)."""
    b = tmp / "bin"
    b.mkdir(parents=True, exist_ok=True)
    for tool in _COREUTILS:
        real = shutil.which(tool)
        if real:
            (b / tool).symlink_to(real)
    # curl: `-x` (proxy probe) exits by proxy_ok; otherwise echoes the egress IP.
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
            ("wg-quick", 'echo "wg-quick $*"\n'),
        ):
            f = b / name
            f.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
            f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return b


def _run_preflight(tmp: Path, *, bin_dir: Path, apply: int = 0, env_extra: dict | None = None):
    env = {"PATH": str(bin_dir), "REPO_ROOT": str(_REPO), "HOME": str(tmp)}
    if env_extra:
        env.update(env_extra)
    script = (
        f'set -euo pipefail\n'
        f'source "{_LIB}"\n'
        f'stealth_preflight {apply}\n'
    )
    return subprocess.run(
        [str(bin_dir / "bash"), "-c", script],
        capture_output=True, text=True, env=env,
    )


@pytest.mark.unit
def test_preflight_green_when_all_present(tmp_path):
    b = _isolated_bin(tmp_path, with_wg=True, egress_ip="173.254.204.32", proxy_ok=True)
    res = _run_preflight(tmp_path, bin_dir=b, env_extra={"APPLICANT_STEALTH_STRICT": "true"})
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "no home-IP leak" in out
    assert "Stealth prerequisites satisfied" in out


@pytest.mark.unit
def test_preflight_warns_loudly_but_proceeds_when_wg_missing_nonstrict(tmp_path):
    b = _isolated_bin(tmp_path, with_wg=False, egress_ip="173.254.204.32", proxy_ok=True)
    res = _run_preflight(tmp_path, bin_dir=b)  # non-strict, dry-run
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "WireGuard client" in out and "MISSING" in out
    assert "HOME IP" in out  # the loud warning names the risk


@pytest.mark.unit
def test_preflight_hard_aborts_when_wg_missing_and_strict(tmp_path):
    b = _isolated_bin(tmp_path, with_wg=False, egress_ip="173.254.204.32", proxy_ok=True)
    res = _run_preflight(tmp_path, bin_dir=b, env_extra={"APPLICANT_STEALTH_STRICT": "true"})
    assert res.returncode != 0, "strict + missing WireGuard client must abort the deploy"
    assert "FAILED (strict)" in (res.stdout + res.stderr)


@pytest.mark.unit
def test_preflight_detects_home_ip_leak_and_aborts_strict(tmp_path):
    # WireGuard is up but egress does NOT exit the VPS -> home-IP leak canary.
    b = _isolated_bin(tmp_path, with_wg=True, egress_ip="72.208.174.40", proxy_ok=False)
    res = _run_preflight(tmp_path, bin_dir=b, env_extra={"APPLICANT_STEALTH_STRICT": "true"})
    out = res.stdout + res.stderr
    assert "HOME-IP LEAK RISK" in out
    assert res.returncode != 0


@pytest.mark.unit
def test_preflight_skips_cleanly_when_disabled(tmp_path):
    b = _isolated_bin(tmp_path, with_wg=False, egress_ip="1.2.3.4", proxy_ok=False)
    res = _run_preflight(tmp_path, bin_dir=b, env_extra={"APPLICANT_STEALTH_ENABLED": "false"})
    assert res.returncode == 0
    assert "DISABLED" in (res.stdout + res.stderr)
