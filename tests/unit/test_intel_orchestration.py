import pytest
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


@pytest.fixture
def orchestration():
    path = CONFIG_DIR / "intel_orchestration.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def tier_topology():
    path = CONFIG_DIR / "intel_tiers.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def hardware():
    path = CONFIG_DIR / "hardware_profiles.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def escalation():
    path = CONFIG_DIR / "intel_escalation.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


class TestIntelOrchestrationContract:
    """Hermetic enforcement for FR-INTEL-5 orchestration doctrine."""

    # === (a) Doctrine assertions ===

    def test_doctrine_overseer_is_cloud(self, orchestration):
        assert orchestration["doctrine"]["overseer_is_cloud"] is True

    def test_doctrine_overseer_does_not_implement(self, orchestration):
        assert orchestration["doctrine"]["overseer_does_implementation"] is False

    def test_doctrine_overseer_role(self, orchestration):
        assert orchestration["doctrine"]["overseer_role"] == "planner/reviewer, not typist"

    # === (b) Delegation table — exactly 6 rows, correct tier/locality + referential integrity ===

    def test_delegation_has_exactly_six_rows(self, orchestration):
        assert len(orchestration["delegation"]) == 6

    def test_delegation_local_profiles_are_local(self, orchestration):
        """coder, explorer, test-engineer are local-fast + local."""
        local_work = [d for d in orchestration["delegation"] if d["profile"] in ("coder", "explorer", "test-engineer")]
        assert len(local_work) == 3
        for entry in local_work:
            assert entry["tier"] == "local-fast", f"{entry['profile']} should be local-fast"
            assert entry["locality"] == "local", f"{entry['profile']} should be local"

    def test_delegation_reviewer_security_auditor_are_cloud(self, orchestration):
        """reviewer and security-auditor are cloud-flash + remote."""
        for prof in ("reviewer", "security-auditor"):
            entry = next(d for d in orchestration["delegation"] if d["profile"] == prof)
            assert entry["tier"] == "cloud-flash", f"{prof} should be cloud-flash"
            assert entry["locality"] == "remote", f"{prof} should be remote"

    def test_delegation_debugger_is_cloud_pro(self, orchestration):
        entry = next(d for d in orchestration["delegation"] if d["profile"] == "debugger")
        assert entry["tier"] == "cloud-pro", "debugger should be cloud-pro"
        assert entry["locality"] == "remote", "debugger should be remote"

    def test_delegation_referential_integrity_with_tiers(self, orchestration, tier_topology):
        """Every profile named in delegation EXISTS in intel_tiers.yaml with SAME tier+locality."""
        profiles = tier_topology["profiles"]
        for entry in orchestration["delegation"]:
            name = entry["profile"]
            assert name in profiles, f"Profile '{name}' not in intel_tiers.yaml"
            assert profiles[name]["tier"] == entry["tier"], (
                f"{name}: intel_tiers has tier {profiles[name]['tier']} but orchestration says {entry['tier']}"
            )
            assert profiles[name]["locality"] == entry["locality"], (
                f"{name}: intel_tiers has locality {profiles[name]['locality']} but orchestration says {entry['locality']}"
            )

    # === (c) Remote-only catalog — exactly R1..R9, all cloud tiers, cross-checks ===

    def test_remote_only_catalog_has_exactly_nine_entries(self, orchestration):
        catalog = orchestration["remote_only_catalog"]
        assert len(catalog) == 9

    def test_remote_only_catalog_ids_are_unique_and_contiguous(self, orchestration):
        catalog = orchestration["remote_only_catalog"]
        ids = [entry["id"] for entry in catalog]
        assert len(ids) == len(set(ids)), "IDs are not unique"
        expected = [f"R{i}" for i in range(1, 10)]
        assert ids == expected, f"IDs must be R1..R9 contiguous, got {ids}"

    def test_remote_only_catalog_no_local_tiers(self, orchestration):
        """None of the catalog tiers contain 'local-fast' — these are all remote-only."""
        for entry in orchestration["remote_only_catalog"]:
            assert "local" not in entry["tier"].lower(), (
                f"R{entry['id']} has local-sounding tier '{entry['tier']}' but should be remote-only"
            )

    def test_remote_only_catalog_tier_reference_in_tiers_yaml(self, orchestration, tier_topology):
        """Every short-form tier mentioned (cloud-flash, cloud-pro) exists in intel_tiers.yaml."""
        tiers = tier_topology["tiers"]
        existing_tiers = set(tiers.keys())
        for entry in orchestration["remote_only_catalog"]:
            tier_str = entry["tier"]
            # Extract known short tier names from the string
            for known in ("cloud-flash", "cloud-pro"):
                if known in tier_str:
                    assert known in existing_tiers, f"Tier '{known}' referenced in R{entry['id']} but not in intel_tiers"

    # === (d) Fan-out assertions + cross-check ===

    def test_fan_out_max_local_is_2(self, orchestration):
        assert orchestration["fan_out"]["max_local"] == 2

    def test_fan_out_overflow_is_cloud(self, orchestration):
        assert orchestration["fan_out"]["overflow"] == "cloud"

    def test_fan_out_max_local_matches_hardware_concurrency(self, orchestration, hardware):
        """max_local equals the reference profile's concurrency in hardware_profiles.yaml."""
        ref = hardware["reference"]
        assert orchestration["fan_out"]["max_local"] == ref["concurrency"], (
            f"orchestration max_local {orchestration['fan_out']['max_local']} != "
            f"hardware reference concurrency {ref['concurrency']}"
        )

    # === (e) Cross-checks R6 (ctx) and R7 (escalation threshold) ===

    def test_r6_ctx_cap_matches_hardware(self, orchestration, hardware):
        """R6 scenario mentions ~96000 which matches hardware reference ctx_cap."""
        r6 = next(e for e in orchestration["remote_only_catalog"] if e["id"] == "R6")
        assert "ctx_cap" in r6["scenario"].lower() or "96000" in r6["scenario"], (
            f"R6 scenario '{r6['scenario']}' should mention ctx_cap or 96000"
        )
        ref_ctx = hardware["reference"]["ctx_cap"]
        assert str(ref_ctx) in r6["scenario"], (
            f"R6 scenario '{r6['scenario']}' must contain ctx_cap value {ref_ctx}"
        )

    def test_r7_threshold_matches_escalation(self, orchestration, escalation):
        """R7 scenario mentions >=2 (or the escalation threshold) which matches intel_escalation.yaml."""
        r7 = next(e for e in orchestration["remote_only_catalog"] if e["id"] == "R7")
        threshold = escalation["escalation"]["threshold"]
        assert str(threshold) in r7["scenario"], (
            f"R7 scenario '{r7['scenario']}' must contain escalation threshold {threshold}"
        )
