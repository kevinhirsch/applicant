"""Local inference envelope: hardware-profile data accessor and routing predicates (FR-INTEL-2).

This is a pure, hermetic module that reads the version-controlled
config/hardware_profiles.yaml and exposes the envelope accessor + predicates.
No network calls, no engine logic, no live vLLM probe.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
_PROFILES_PATH = _HERE.parents[3] / "config" / "hardware_profiles.yaml"


def load_profiles() -> dict[str, Any]:
    """Load all hardware profiles from the YAML file."""
    with open(_PROFILES_PATH) as f:
        return yaml.safe_load(f)


def envelope(profile_name: str) -> dict[str, Any]:
    """Return the hardware envelope dict for a named profile.

    Raises KeyError with a clear message if the profile is unknown.
    """
    profiles = load_profiles()
    if profile_name not in profiles:
        raise KeyError(f"Unknown hardware profile: {profile_name!r}. Known: {sorted(profiles)}")
    return profiles[profile_name]


def max_local_concurrency(profile_name: str) -> int:
    """Return the maximum local concurrency for a profile (0 for cloud-only)."""
    return envelope(profile_name)["concurrency"]


def is_local_capable(profile_name: str, est_tokens: int) -> bool:
    """Return True if the profile can run locally for a task of est_tokens.

    False if concurrency == 0 (cloud-only) or est_tokens > ctx_cap (exceeds usable context).
    """
    prof = envelope(profile_name)
    return prof["concurrency"] > 0 and est_tokens <= prof["ctx_cap"]


def supports_vision(profile_name: str) -> bool:
    """Return True if the profile supports vision inputs."""
    return envelope(profile_name)["vision"]
