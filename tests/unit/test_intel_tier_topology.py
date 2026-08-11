import pytest
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


@pytest.fixture
def topology():
    path = CONFIG_DIR / "intel_tiers.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def test_three_tiers(topology):
    tiers = topology["tiers"]
    assert set(tiers.keys()) == {"local-fast", "cloud-flash", "cloud-pro"}
    assert tiers["local-fast"]["locality"] == "local"
    assert tiers["cloud-flash"]["locality"] == "remote"
    assert tiers["cloud-pro"]["locality"] == "remote"


def test_nine_profiles(topology):
    assert len(topology["profiles"]) == 9


def test_profile_tier_valid(topology):
    tiers = set(topology["tiers"].keys())
    for name, data in topology["profiles"].items():
        assert data["tier"] in tiers, f"Profile {name} has unknown tier {data['tier']}"


def test_profile_locality_matches_tier(topology):
    tiers = topology["tiers"]
    for name, data in topology["profiles"].items():
        expected_locality = tiers[data["tier"]]["locality"]
        assert data["locality"] == expected_locality, f"Profile {name} locality {data['locality']} != tier {data['tier']} locality {expected_locality}"


EXPECTED_PROFILES = {
    "agent0": {"preset": "DeepSeek-Chat", "model": "deepseek-v4-flash", "tier": "cloud-flash", "locality": "remote"},
    "coder": {"preset": "Default", "model": "Qwen3.6-27B", "tier": "local-fast", "locality": "local"},
    "explorer": {"preset": "Default", "model": "Qwen3.6-27B", "tier": "local-fast", "locality": "local"},
    "test-engineer": {"preset": "Default", "model": "Qwen3.6-27B", "tier": "local-fast", "locality": "local"},
    "coder-cloud": {"preset": "DeepSeek-Flash", "model": "deepseek-v4-flash", "tier": "cloud-flash", "locality": "remote"},
    "explorer-cloud": {"preset": "DeepSeek-Flash", "model": "deepseek-v4-flash", "tier": "cloud-flash", "locality": "remote"},
    "reviewer": {"preset": "DeepSeek-Flash", "model": "deepseek-v4-flash", "tier": "cloud-flash", "locality": "remote"},
    "security-auditor": {"preset": "DeepSeek-Flash", "model": "deepseek-v4-flash", "tier": "cloud-flash", "locality": "remote"},
    "debugger": {"preset": "DeepSeek-Pro", "model": "deepseek-v4-pro", "tier": "cloud-pro", "locality": "remote"},
}


@pytest.mark.parametrize("profile_name,expected", list(EXPECTED_PROFILES.items()))
def test_profile_ground_truth(topology, profile_name, expected):
    profiles = topology["profiles"]
    assert profile_name in profiles, f"Profile {profile_name} missing"
    actual = profiles[profile_name]
    for key in ("preset", "model", "tier", "locality"):
        assert actual[key] == expected[key], f"Profile {profile_name}.{key}: expected {expected[key]}, got {actual[key]}"


def test_agent0_is_cloud(topology):
    assert topology["profiles"]["agent0"]["tier"].startswith("cloud-")


def test_required_presets(topology):
    presets = topology["presets"]
    assert "Default" in presets
    assert "DeepSeek-Chat" in presets
    assert "DeepSeek-Flash" in presets
    assert "DeepSeek-Pro" in presets


def test_referential_integrity(topology):
    presets = set(topology["presets"].keys())
    for name, data in topology["profiles"].items():
        assert data["preset"] in presets, f"Profile {name} references unknown preset {data['preset']}"


def test_cloud_presets_exact_set(topology):
    cloud_presets = {k for k, v in topology["presets"].items() if v["tier"].startswith("cloud-")}
    assert cloud_presets == {"DeepSeek-Chat", "DeepSeek-Flash", "DeepSeek-Pro"}


def test_every_tier_used(topology):
    tiers = set(topology["tiers"].keys())
    used_tiers = set(p["tier"] for p in topology["profiles"].values())
    assert tiers == used_tiers, f"Unused tiers: {tiers - used_tiers}"
