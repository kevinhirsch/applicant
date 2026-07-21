"""Hermetic contract test for config/intel_sampling.yaml.

Asserts per-tier sampling & decoding values match the shipped CONTRACT.
Reads only the YAML file — no network, no engine imports.
"""

import pytest
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


@pytest.fixture
def contracts():
    path = CONFIG_DIR / "intel_sampling.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


class TestLocalChat:
    """LOCAL Default.chat contract — the anti-misformat contract for 27B-Int4."""

    def test_temperature(self, contracts):
        assert contracts["tiers"]["local_chat"]["temperature"] == 0.25

    def test_top_p(self, contracts):
        assert contracts["tiers"]["local_chat"]["top_p"] == 0.8

    def test_top_k(self, contracts):
        assert contracts["tiers"]["local_chat"]["top_k"] == 20

    def test_presence_penalty(self, contracts):
        assert contracts["tiers"]["local_chat"]["presence_penalty"] == 0.3

    def test_thinking_off(self, contracts):
        assert contracts["tiers"]["local_chat"]["chat_template_kwargs"]["enable_thinking"] is False

    def test_json_schema_response_format(self, contracts):
        rf = contracts["tiers"]["local_chat"]["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "a0_tool_call"

    def test_json_schema_properties(self, contracts):
        schema = contracts["tiers"]["local_chat"]["response_format"]["json_schema"]["schema"]
        assert set(schema["properties"].keys()) == {"thoughts", "headline", "tool_name", "tool_args"}

    def test_json_schema_required_fields(self, contracts):
        schema = contracts["tiers"]["local_chat"]["response_format"]["json_schema"]["schema"]
        assert set(schema["required"]) == {"thoughts", "tool_name", "tool_args"}

    def test_json_schema_no_additional_properties(self, contracts):
        schema = contracts["tiers"]["local_chat"]["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False

    def test_guided_decoding_backend(self, contracts):
        assert contracts["tiers"]["local_chat"]["extra_body"]["guided_decoding_backend"] == "guidance"


class TestLocalUtility:
    """LOCAL Default.utility — naming/summarisation, needs diversity."""

    def test_temperature(self, contracts):
        assert contracts["tiers"]["local_utility"]["temperature"] == 0.3

    def test_presence_penalty(self, contracts):
        assert contracts["tiers"]["local_utility"]["presence_penalty"] == 1.0

    def test_thinking_off(self, contracts):
        assert contracts["tiers"]["local_utility"]["chat_template_kwargs"]["enable_thinking"] is False


class TestCloudChat:
    """CLOUD DeepSeek.chat — native tool-calling, resilient."""

    def test_temperature(self, contracts):
        assert contracts["tiers"]["cloud_chat"]["temperature"] == 0.6

    def test_top_p(self, contracts):
        assert contracts["tiers"]["cloud_chat"]["top_p"] == 0.95

    def test_stream_options_include_usage(self, contracts):
        assert contracts["tiers"]["cloud_chat"]["stream_options"]["include_usage"] is True

    def test_retry_attempts(self, contracts):
        assert contracts["tiers"]["cloud_chat"]["a0_retry_attempts"] == 5

    def test_retry_delay(self, contracts):
        assert contracts["tiers"]["cloud_chat"]["a0_retry_delay_seconds"] == 3

    def test_no_guided_decoding_backend(self, contracts):
        tier = contracts["tiers"]["cloud_chat"]
        if "extra_body" in tier:
            assert "guided_decoding_backend" not in tier["extra_body"]