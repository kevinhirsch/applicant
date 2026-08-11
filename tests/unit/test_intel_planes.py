"""Test the two-plane reconciliation contract (FR-INTEL-7).

Asserts:
- DISJOINT: no capability appears in both planes.
- plane_a.capabilities == the 9 profiles from config/intel_tiers.yaml.
- plane_b.capabilities is non-empty and each capability is a non-empty string.
- local_only.spans_both_planes is True and env == "LLM_LOCAL_ONLY".
- totality: plane_a and plane_b are the only two planes and both are non-empty.
"""

import yaml
from pathlib import Path

_CONFIG = Path(__file__).parents[2] / "config"


def _load_planes():
    with open(_CONFIG / "intel_planes.yaml") as f:
        return yaml.safe_load(f)


def _load_tiers():
    with open(_CONFIG / "intel_tiers.yaml") as f:
        return yaml.safe_load(f)


class TestPlanes:
    """FR-INTEL-7: two-plane reconciliation contract."""

    def _load(self):
        return _load_planes()

    def test_disjoint_capabilities(self):
        """AC2: no capability appears in both planes."""
        data = self._load()
        a = set(data["plane_a"]["capabilities"])
        b = set(data["plane_b"]["capabilities"])
        overlap = a & b
        assert not overlap, f"Overlapping capabilities: {overlap}"

    def test_plane_a_matches_tier_profiles(self):
        """Plane A capabilities == the 9 profile names from intel_tiers.yaml."""
        data = self._load()
        tiers = _load_tiers()
        profile_names = set(tiers.get("profiles", {}).keys())
        expected = {"agent0", "coder", "explorer", "test-engineer",
                     "coder-cloud", "explorer-cloud", "reviewer",
                     "security-auditor", "debugger"}
        assert profile_names == expected, f"Profile mismatch: {profile_names}"
        assert set(data["plane_a"]["capabilities"]) == profile_names

    def test_plane_b_non_empty(self):
        """Plane B capabilities are non-empty strings."""
        data = self._load()
        caps = data["plane_b"]["capabilities"]
        assert len(caps) > 0, "Plane B must have at least one capability"
        for c in caps:
            assert isinstance(c, str) and len(c) > 0

    def test_plane_b_expected_capabilities_present(self):
        """Assert the 4 expected engine capabilities are present."""
        data = self._load()
        caps = set(data["plane_b"]["capabilities"])
        expected = {"parse_verify", "material_tailoring",
                    "screening_answers", "viability_scoring"}
        assert expected.issubset(caps), f"Missing: {expected - caps}"

    def test_local_only_spans_both(self):
        """local_only spans both planes with LLM_LOCAL_ONLY."""
        data = self._load()
        lo = data["local_only"]
        assert lo["spans_both_planes"] is True
        assert lo["env"] == "LLM_LOCAL_ONLY"

    def test_totality(self):
        """plane_a and plane_b are the only two planes; both non-empty."""
        data = self._load()
        planes = {k: v for k, v in data.items() if k.startswith("plane_")}
        assert set(planes.keys()) == {"plane_a", "plane_b"}
        assert len(planes["plane_a"]["capabilities"]) > 0
        assert len(planes["plane_b"]["capabilities"]) > 0

    def test_plane_a_owner(self):
        """plane_a has the correct owner string."""
        data = self._load()
        assert data["plane_a"]["owner"] == "FR-INTEL suite (shell/agent models)"

    def test_plane_b_owner(self):
        """plane_b has the correct owner string."""
        data = self._load()
        assert data["plane_b"]["owner"] == "engine tier-ladder (/setup/llm/tiers)"
