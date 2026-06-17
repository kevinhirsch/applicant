"""Prod compose durability: the credential vault master key MUST persist.

FR-VAULT-3 / C1: the libsodium master key is a key-file on disk that seals every
banked credential. If it lives on the ephemeral container layer, an
``up --build``/recreate (what install.sh/update.sh do) regenerates it and ALL sealed
secrets become permanently undecryptable. The prod stack must therefore (a) point
CREDENTIAL_KEYFILE at a path under a mounted NAMED volume and (b) declare that volume
top-level. This test guards against a regression that drops the persisted mount.

The takeover-desktop web stream must also be reachable from the host (H3): the
service publishes a host port (gated to its profile) rather than only `expose`-ing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_COMPOSE = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.prod.yml"


@pytest.mark.integration
def test_prod_api_persists_credential_keyfile_on_named_volume():
    spec = yaml.safe_load(_COMPOSE.read_text())
    api = spec["services"]["api"]
    env = api["environment"]

    # CREDENTIAL_KEYFILE points at a stable in-container path (default on the volume).
    keyfile = env["CREDENTIAL_KEYFILE"]
    keydir = keyfile.split(":-")[-1].rstrip("}").rsplit("/", 1)[0]
    assert keydir, f"could not derive key dir from {keyfile!r}"

    # A named volume is mounted at (or above) that key dir.
    mounts = api.get("volumes", [])
    named = {m.split(":")[0]: m.split(":")[1] for m in mounts if ":" in m}
    covering = [tgt for tgt in named.values() if keydir == tgt or keydir.startswith(tgt + "/")]
    assert covering, f"no named volume covers the key dir {keydir}: {mounts}"
    vol_name = next(name for name, tgt in named.items() if tgt in covering)

    # The mount references a declared top-level named volume (durable across recreate).
    assert vol_name in (spec.get("volumes") or {})


@pytest.mark.integration
def test_prod_api_persists_fonts_dir_on_named_volume():
    spec = yaml.safe_load(_COMPOSE.read_text())
    api = spec["services"]["api"]
    fonts_dir = api["environment"]["FONTS_DIR"].split(":-")[-1].rstrip("}")
    mounts = api.get("volumes", [])
    named = {m.split(":")[0]: m.split(":")[1] for m in mounts if ":" in m}
    assert fonts_dir in named.values(), f"no volume mounted at {fonts_dir}: {mounts}"
    assert named[next(n for n, t in named.items() if t == fonts_dir)] == fonts_dir
    vol_name = next(n for n, t in named.items() if t == fonts_dir)
    assert vol_name in (spec.get("volumes") or {})


@pytest.mark.integration
def test_takeover_desktop_publishes_host_port():
    spec = yaml.safe_load(_COMPOSE.read_text())
    svc = spec["services"]["takeover-desktop"]
    ports = svc.get("ports", [])
    assert ports, "takeover-desktop must publish a host port so the human can reach it"
    # Maps some host port -> container 3000 (the web stream), e.g. "${TAKEOVER_PORT:-3001}:3000".
    assert any(str(p).rstrip('"').endswith(":3000") for p in ports), ports


@pytest.mark.integration
def test_ui_waits_for_engine_health():
    spec = yaml.safe_load(_COMPOSE.read_text())
    dep = spec["services"]["applicant-ui"]["depends_on"]
    # The public UI must wait for the engine to be service_healthy (real /healthz).
    assert "api" in dep, "applicant-ui must depend on the engine api"
    assert dep["api"]["condition"] == "service_healthy"
