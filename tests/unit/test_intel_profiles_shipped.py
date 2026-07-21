import pytest
import yaml
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "a0-applicant"


@pytest.fixture
def topology():
    path = CONFIG_DIR / "intel_tiers.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def _config_path(profile_name: str) -> Path:
    return (
        PLUGIN_DIR
        / "agents"
        / profile_name
        / "plugins"
        / "_model_config"
        / "config.json"
    )


def test_all_nine_config_files_exist(topology):
    """Assert every profile from the topology has a corresponding config.json."""
    missing = []
    for profile_name in topology["profiles"]:
        path = _config_path(profile_name)
        if not path.exists():
            missing.append(str(path))
    assert not missing, f"Missing config.json files:\n" + "\n".join(missing)


@pytest.mark.parametrize("profile_name", [
    "agent0",
    "coder",
    "explorer",
    "test-engineer",
    "coder-cloud",
    "explorer-cloud",
    "reviewer",
    "security-auditor",
    "debugger",
])
def test_config_json_matches_yaml_profile_preset(topology, profile_name):
    """Assert each config.json's model_preset matches the YAML source of truth."""
    path = _config_path(profile_name)
    assert path.exists(), f"{path} does not exist"
    with open(path) as f:
        config = json.load(f)
    expected_preset = topology["profiles"][profile_name]["preset"]
    assert config["model_preset"] == expected_preset, (
        f"{profile_name}: config.json has model_preset={config['model_preset']!r}, "
        f"expected {expected_preset!r} from intel_tiers.yaml"
    )
