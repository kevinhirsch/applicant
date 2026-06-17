"""Risk-tier action policy (Phase 0). Pure-Python, no app deps required."""

import importlib

import src.policy as policy


def test_known_actions_classify_to_expected_tiers():
    assert policy.classify_action("web_search") == policy.LOW
    assert policy.classify_action("read_email") == policy.LOW
    assert policy.classify_action("create_document") == policy.MEDIUM
    assert policy.classify_action("manage_memory") == policy.MEDIUM
    assert policy.classify_action("send_email") == policy.HIGH
    assert policy.classify_action("bash") == policy.HIGH
    assert policy.classify_action("ha_call_service") == policy.HIGH


def test_unknown_action_defaults_to_medium():
    assert policy.classify_action("totally_made_up_tool") == policy.DEFAULT_TIER
    assert policy.classify_action(None) == policy.DEFAULT_TIER
    assert policy.classify_action("") == policy.DEFAULT_TIER


def test_no_confirmation_when_enforcement_off():
    # Phase 0 default: enforcement off => never blocks, even for high-risk.
    assert policy.requires_confirmation("bash", enforced=False) is False
    assert policy.requires_confirmation("send_email", enforced=False) is False


def test_high_risk_requires_confirmation_when_enforced():
    assert policy.requires_confirmation("send_email", enforced=True) is True
    assert policy.requires_confirmation("ha_call_service", enforced=True) is True


def test_pre_authorized_high_risk_skips_confirmation():
    assert policy.requires_confirmation("send_email", enforced=True, pre_authorized=True) is False


def test_low_and_medium_do_not_require_confirmation_even_when_enforced():
    assert policy.requires_confirmation("web_search", enforced=True) is False
    assert policy.requires_confirmation("create_document", enforced=True) is False


def test_min_tier_override_can_gate_medium():
    # Caller may lower the bar to MEDIUM for a stricter context.
    assert policy.requires_confirmation("create_document", enforced=True, min_tier=policy.MEDIUM) is True
    assert policy.requires_confirmation("web_search", enforced=True, min_tier=policy.MEDIUM) is False


def test_is_enforced_reads_env(monkeypatch):
    monkeypatch.setenv("APPLICANT_RISK_POLICY", "1")
    importlib.reload(policy)
    assert policy.is_enforced() is True
    monkeypatch.setenv("APPLICANT_RISK_POLICY", "0")
    importlib.reload(policy)
    assert policy.is_enforced() is False
