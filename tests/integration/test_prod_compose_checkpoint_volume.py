"""Prod compose durability: checkpoint state survives container recreation.

FR-INSTALL-3/FR-DUR-3: with the default ``shim`` backend, durable workflow +
mailbox state lives under ``CHECKPOINT_DIR``. The prod stack must mount a named
volume at that path so an ``up``/recreate does NOT wipe approvals / in-flight
workflows. Before the fix no volume was mounted, so even checkpoint state was lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_COMPOSE = Path(__file__).resolve().parents[2] / "docker" / "docker-compose.prod.yml"


@pytest.mark.integration
def test_prod_api_mounts_named_volume_for_checkpoint_dir():
    spec = yaml.safe_load(_COMPOSE.read_text())
    api = spec["services"]["api"]

    # CHECKPOINT_DIR is set to a stable path inside the container.
    env = api["environment"]
    checkpoint_dir = env["CHECKPOINT_DIR"]
    assert "/data/checkpoints" in checkpoint_dir

    # A named volume is mounted at that path (not a throwaway anonymous mount).
    target = checkpoint_dir.split(":-")[-1].rstrip("}")
    mounts = api.get("volumes", [])
    named = {m.split(":")[0]: m.split(":")[1] for m in mounts if ":" in m}
    assert target in named.values(), f"no volume mounted at {target}: {mounts}"
    vol_name = next(name for name, tgt in named.items() if tgt == target)

    # The mount references a declared top-level named volume (durable across recreate).
    assert vol_name in (spec.get("volumes") or {})
