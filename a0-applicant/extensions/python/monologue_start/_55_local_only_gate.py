"""
AZ1-1 (#829) — Local-only awareness gate.

Reads LLM_LOCAL_ONLY from the environment and exposes pure functions:
- is_local_only() -> bool
- filter_cloud_presets(presets, local_only) -> list[dict]

In execute(), when local-only mode is active, logs an informational
caveat rather than blocking; the loop continues uninterrupted.

Self-contained (no sibling imports); pure functions are module-level
so they can be unit-tested in isolation.
"""
from __future__ import annotations

import os

import yaml
from pathlib import Path

from helpers.extension import Extension

_CFG_PATH = Path(__file__).resolve().parents[4] / "config" / "intel_tiers.yaml"


def is_local_only() -> bool:
    """Return True when LLM_LOCAL_ONLY is set to a truthy value (case-insensitive)."""
    val = os.environ.get("LLM_LOCAL_ONLY", "").strip().lower()
    return val in ("true", "1", "yes")


def _load_tier_locality() -> dict[str, str]:
    """Load the tier->locality map from config/intel_tiers.yaml."""
    try:
        with open(_CFG_PATH) as f:
            data = yaml.safe_load(f)
        tiers = data.get("tiers", {})
        return {t: info.get("locality", "local") for t, info in tiers.items()}
    except Exception:
        return {}


def filter_cloud_presets(presets: list[dict], local_only: bool) -> list[dict]:
    """When local_only is True, drop presets whose tier resolves to 'remote' locality.

    When local_only is False, return the list unchanged.
    """
    if not local_only:
        return presets
    tier_locality = _load_tier_locality()
    return [p for p in presets if tier_locality.get(p.get("tier", ""), "local") != "remote"]


class LocalOnlyGate(Extension):
    async def execute(self, **kwargs):
        try:
            if not is_local_only():
                return
            try:
                self.agent.context.log.log(
                    type="info",
                    content=(
                        "LLM_LOCAL_ONLY is active: cloud presets are hidden. "
                        "Only local-only models will be offered in the UI."
                    ),
                )
            except Exception:
                pass
        except Exception:
                pass
