import pytest
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "a0-applicant"

PROMPT_FILE = (
    PLUGIN_DIR
    / "agents"
    / "agent0"
    / "prompts"
    / "agent.system.main.specifics.md"
)


@pytest.fixture
def orchestration():
    path = CONFIG_DIR / "intel_orchestration.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def prompt_text():
    assert PROMPT_FILE.exists(), (
        f"Prompt file not found at {PROMPT_FILE}"
    )
    return PROMPT_FILE.read_text()


class TestOverseerPromptContract:
    """Hermetic enforcement for FR-INTEL-5 §9.4 — agent0 overseer doctrine prompt."""

    def test_prompt_file_exists_and_nonempty(self, prompt_text):
        assert prompt_text, "Prompt file must be non-empty"
        assert len(prompt_text) > 100, "Prompt file must contain meaningful content"

    def test_prompt_contains_normative_framing(self, prompt_text):
        """Assert the doctrine's normative framing phrase 'think here, build there' is present."""
        assert "think here, build there" in prompt_text.lower()

    def test_prompt_names_all_six_delegate_profiles(self, prompt_text):
        """Assert all 6 delegate profiles from the delegation list are named in the prompt."""
        profiles = ["coder", "explorer", "test-engineer", "reviewer", "security-auditor", "debugger"]
        text_lower = prompt_text.lower()
        missing = [p for p in profiles if p not in text_lower]
        assert not missing, f"Missing profile references in prompt: {missing}"

    def test_prompt_contains_all_remote_only_ids(self, prompt_text, orchestration):
        """Assert all 9 ids R1 through R9 are present in the prompt."""
        catalog = orchestration["remote_only_catalog"]
        for entry in catalog:
            rid = entry["id"]
            assert rid in prompt_text, f"Remote-only id {rid} missing from prompt"

    def test_prompt_contains_tier_for_each_remote_only_id(self, prompt_text, orchestration):
        """Assert for each R id the corresponding tier string appears in the prompt."""
        catalog = orchestration["remote_only_catalog"]
        for entry in catalog:
            rid = entry["id"]
            tier = entry["tier"]
            assert tier in prompt_text, (
                f"Tier string {tier!r} for {rid} not found in prompt"
            )

    def test_prompt_mentions_concurrency_or_max_local(self, prompt_text):
        """Assert the prompt mentions concurrency or the literal max_local value (2)."""
        text_lower = prompt_text.lower()
        assert "concurrency" in text_lower or "2" in prompt_text, (
            "Prompt must mention concurrency or the value 2 to tie fan-out policy to YAML contract"
        )

    def test_prompt_has_full_suite_acceptance_gate_language(self, prompt_text):
        """Assert the prompt contains language about the full test suite acceptance gate.
        Look for 'full' and 'suite' both present, or the literal phrase 'never module-scoped'."""
        text_lower = prompt_text.lower()
        has_both = "full" in text_lower and "suite" in text_lower
        has_literal = "never module-scoped" in text_lower
        assert has_both or has_literal, (
            "Prompt must contain language about the full test suite / never module-scoped acceptance gate"
        )

    def test_prompt_never_trust_self_assessment_language(self, prompt_text):
        """Assert the prompt contains language matching 'never trust' re self-assessment."""
        text_lower = prompt_text.lower()
        assert "never trust" in text_lower, (
            "Prompt must contain 'never trust' language about self-assessment"
        )
