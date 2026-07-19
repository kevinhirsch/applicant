from pathlib import Path
import pytest

GUIDANCE = Path(__file__).resolve().parents[2] / "a0-applicant/prompts/agent_guidance.md"


@pytest.fixture(scope="module")
def text() -> str:
    return GUIDANCE.read_text(encoding="utf-8")


def test_mentions_apply_ready(text):
    assert "apply_ready" in text


def test_instructs_defer_automated_apply(text):
    lower = text.lower()
    assert "defer" in lower or "do not" in lower or "don't" in lower
    assert "automatic" in lower or "automat" in lower
    assert "appl" in lower  # covers "application" / "apply"
