import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def load_escalation_yaml():
    path = CONFIG_DIR / "intel_escalation.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_tiers_yaml():
    path = CONFIG_DIR / "intel_tiers.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


class TestIntelEscalationContract:
    """Hermetic contract enforcement for FR-INTEL-4 (config/intel_escalation.yaml)."""

    def setup_method(self):
        self.data = load_escalation_yaml()
        self.escalation = self.data["escalation"]

    # --- Constant pinning (AC5) ---

    def test_threshold_is_pinned_int(self):
        """AC5: threshold is a single named constant pinned to 2."""
        assert isinstance(self.escalation["threshold"], int)
        assert self.escalation["threshold"] == 2

    def test_struggle_key(self):
        assert self.escalation["struggle_key"] == "_escalate_struggle"

    def test_target_preset(self):
        assert self.escalation["target_preset"] == "DeepSeek-Pro"

    def test_target_tier(self):
        assert self.escalation["target_tier"] == "cloud-pro"

    def test_applies_to(self):
        assert self.escalation["applies_to"] == "local-only"

    def test_reverts_on_success(self):
        assert self.escalation["reverts_on_success"] is True

    def test_fail_safe(self):
        assert self.escalation["fail_safe"] is True

    def test_observable(self):
        assert self.escalation["observable"] is True

    def test_hooks_exactly_three(self):
        expected = ["chat_model_call_before", "hist_add_warning", "tool_execute_after"]
        assert self.escalation["hooks"] == expected

    def test_ordering(self):
        assert self.escalation["ordering"] == "runs before _failover and _local_concurrency"

    # --- Referential integrity with FR-INTEL-1 (config/intel_tiers.yaml) ---

    def test_target_preset_exists_in_tiers(self):
        tiers = load_tiers_yaml()
        assert self.escalation["target_preset"] in tiers["presets"], (
            f"target_preset '{self.escalation['target_preset']}' not found in intel_tiers.yaml presets"
        )

    def test_target_preset_tier_matches_target_tier(self):
        tiers = load_tiers_yaml()
        preset = tiers["presets"][self.escalation["target_preset"]]
        assert preset["tier"] == self.escalation["target_tier"], (
            f"'{self.escalation['target_preset']}' has tier '{preset['tier']}' but escalation contract says '{self.escalation['target_tier']}'"
        )
