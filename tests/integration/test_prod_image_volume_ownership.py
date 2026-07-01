"""Prod image: the non-root api must be able to WRITE its runtime named volumes.

FR-VAULT-3 / #161: the api container runs as the non-root ``applicant`` user, but
compose mounts several NAMED volumes at paths OUTSIDE /app (/data/* and /control).
Docker creates a fresh volume's mountpoint owned by root UNLESS the image already
contains that directory — in which case the volume inherits the image dir's owner.
So the Dockerfile must pre-create each such mountpoint owned by ``applicant``;
otherwise the non-root process cannot write the vault master key (/data/secrets) or
checkpoints, ``/healthz`` returns 503 ("degraded"), and the container never becomes
healthy (so the UI, which waits on ``api: service_healthy``, never starts).

These are the sibling tests to the compose-declaration guards in
``test_prod_compose_vault_key_volume.py`` — those check the volume is declared and
durable; this one checks it comes up WRITABLE for the non-root runtime user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker" / "docker-compose.prod.yml"
_DOCKERFILE = _ROOT / "docker" / "Dockerfile"

# The non-root account the api image drops to (Dockerfile `USER`).
_RUNTIME_USER = "applicant"


def _api_named_volume_targets() -> list[str]:
    """In-container mountpoints of the api service's declared top-level volumes."""
    spec = yaml.safe_load(_COMPOSE.read_text())
    declared = set((spec.get("volumes") or {}).keys())
    api = spec["services"]["api"]
    targets = []
    for mount in api.get("volumes", []):
        if ":" not in mount:
            continue
        src, tgt = mount.split(":")[0], mount.split(":")[1]
        # Named volumes only (a bind mount source starts with . or /).
        if src in declared:
            targets.append(tgt)
    return targets


def _covered_by(paths: list[str], target: str) -> bool:
    """True if `target` equals or is nested under one of `paths`."""
    return any(target == p or target.startswith(p.rstrip("/") + "/") for p in paths)


@pytest.mark.integration
def test_image_precreates_and_owns_api_volume_mountpoints():
    targets = _api_named_volume_targets()
    assert targets, "expected the api service to mount named volumes"

    dockerfile = _DOCKERFILE.read_text()
    assert f"USER {_RUNTIME_USER}" in dockerfile, "api image must drop to the non-root user"

    # Collapse backslash line-continuations so a multi-line `mkdir -p a b \\\n c d`
    # is one logical segment, then split on `&&` into individual shell commands.
    joined = dockerfile.replace("\\\n", " ")
    segments = [seg.strip() for line in joined.splitlines() for seg in line.split("&&")]

    # Collect every directory created via `mkdir -p ...` and every path handed to a
    # `chown ... <runtime_user> ...` in the image build.
    mkdir_dirs: list[str] = []
    chown_dirs: list[str] = []
    for seg in segments:
        if seg.startswith("mkdir -p"):
            mkdir_dirs += [t for t in seg.split("mkdir -p", 1)[1].split() if t.startswith("/")]
        if "chown" in seg and _RUNTIME_USER in seg:
            chown_dirs += [t for t in seg.split() if t.startswith("/")]

    for tgt in targets:
        assert _covered_by(mkdir_dirs, tgt), (
            f"volume mountpoint {tgt} is not pre-created (mkdir) in the image, so a "
            f"fresh named volume would come up root-owned and unwritable by "
            f"{_RUNTIME_USER}. mkdir dirs: {mkdir_dirs}"
        )
        assert _covered_by(chown_dirs, tgt), (
            f"volume mountpoint {tgt} is not chown'd to {_RUNTIME_USER} in the image. "
            f"chown dirs: {chown_dirs}"
        )
