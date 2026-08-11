import pytest
from dataclasses import FrozenInstanceError

from applicant.core.rules.posting_risk import (
    PostingRisk,
    assess_posting_risk,
    _has_unrealistic_pay,
)


@pytest.fixture(autouse=True)
def _no_state():
    yield


@pytest.mark.unit
class TestAssessPostingRisk:

    def test_clean_posting_no_signals(self):
        posting = {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "description": "We are looking for a skilled developer. Competitive salary.",
        }
        result = assess_posting_risk(posting)
        assert result.score == 0
        assert result.auto_apply_allowed is True
        assert result.is_high_risk is False
        assert result.requires_human_confirmation is False
        assert result.signals == ()

    def test_unrealistic_compensation_weekly(self):
        posting = {"description": "Earn $5000/week working from home!"}
        result = assess_posting_risk(posting)
        assert "unrealistic_compensation" in result.signals
        assert result.score >= 1

    def test_unrealistic_compensation_daily(self):
        posting = {"description": "Make $900/day with no skills required!"}
        result = assess_posting_risk(posting)
        assert "unrealistic_compensation" in result.signals
        assert result.score >= 1

    def test_pii_harvesting_ssn(self):
        posting = {"description": "Please provide your ssn for verification."}
        result = assess_posting_risk(posting)
        assert "pii_harvesting" in result.signals

    def test_pii_harvesting_bank_account(self):
        posting = {"description": "We need your bank account details to deposit."}
        result = assess_posting_risk(posting)
        assert "pii_harvesting" in result.signals

    def test_pii_harvesting_social_security(self):
        posting = {"title": "Data Entry", "description": "Enter your social security number for background check."}
        result = assess_posting_risk(posting)
        assert "pii_harvesting" in result.signals

    def test_off_platform_telegram(self):
        posting = {"description": "Contact us on telegram for faster processing."}
        result = assess_posting_risk(posting)
        assert "off_platform_contact" in result.signals

    def test_off_platform_whatsapp(self):
        posting = {"description": "Message me on whatsapp to get started."}
        result = assess_posting_risk(posting)
        assert "off_platform_contact" in result.signals

    def test_no_experience_high_pay_combo(self):
        posting = {"description": "No experience needed, earn $5000/week!"}
        result = assess_posting_risk(posting)
        assert "no_experience_high_pay" in result.signals
        assert "unrealistic_compensation" in result.signals
        assert result.score == 2

    def test_multiple_signals_increase_score(self):
        posting = {
            "description": (
                "Earn $5000/week! No experience required. "
                "Provide your ssn and bank account. "
                "Contact us on telegram."
            )
        }
        result = assess_posting_risk(posting)
        assert result.score == 4
        assert "unrealistic_compensation" in result.signals
        assert "pii_harvesting" in result.signals
        assert "off_platform_contact" in result.signals
        assert "no_experience_high_pay" in result.signals

    def test_score_above_threshold_is_high_risk(self):
        posting = {
            "description": (
                "Earn $5000/week! Provide your ssn and bank account. "
                "Contact us on telegram."
            )
        }
        result = assess_posting_risk(posting)
        assert result.score >= 2
        assert result.is_high_risk is True
        assert result.auto_apply_allowed is False
        assert result.requires_human_confirmation is True

    def test_posting_risk_dataclass_frozen(self):
        result = PostingRisk(score=1, signals=("pii_harvesting",))
        with pytest.raises(FrozenInstanceError):
            result.score = 5

    def test_reason_produces_human_readable_labels(self):
        result = PostingRisk(
            score=2,
            signals=("unrealistic_compensation", "pii_harvesting"),
        )
        reason = result.reason
        assert "pay is implausibly high" in reason
        assert "asks for sensitive personal/financial details" in reason

    def test_reason_no_signals(self):
        result = PostingRisk(score=0)
        assert "No scam or ghost-job signals detected." in result.reason

    def test_empty_text_gives_score_zero(self):
        posting = {"title": "", "company": "", "description": ""}
        result = assess_posting_risk(posting)
        assert result.score == 0
        assert result.signals == ()

    def test_case_insensitive_detection(self):
        posting = {"description": "Provide your SSN and BANK ACCOUNT. Contact via TELEGRAM."}
        result = assess_posting_risk(posting)
        assert "pii_harvesting" in result.signals
        assert "off_platform_contact" in result.signals
        assert result.score >= 2

    def test_auto_apply_allowed_low_risk(self):
        result = PostingRisk(score=1, signals=("off_platform_contact",))
        assert result.is_high_risk is False
        assert result.auto_apply_allowed is True
        assert result.requires_human_confirmation is False

    def test_signal_from_title(self):
        posting = {"title": "No experience needed, earn $5000/week!"}
        result = assess_posting_risk(posting)
        assert "no_experience_high_pay" in result.signals

    def test_signal_from_company(self):
        posting = {"company": "Telegram Jobs Inc", "description": "Great opportunity"}
        result = assess_posting_risk(posting)
        assert "off_platform_contact" in result.signals

    def test_amount_below_ceiling_not_flagged(self):
        posting = {"description": "Earn $3000/week with experience."}
        result = assess_posting_risk(posting)
        assert "unrealistic_compensation" not in result.signals
        assert result.score == 0

    def test_daily_amount_below_ceiling_not_flagged(self):
        posting = {"description": "Earn $700/day good pay."}
        result = assess_posting_risk(posting)
        assert "unrealistic_compensation" not in result.signals

    def test_comma_in_amount(self):
        posting = {"description": "Earn $5,000/week great income!"}
        result = assess_posting_risk(posting)
        assert "unrealistic_compensation" in result.signals

    def test_no_experience_alone_no_high_pay_signal(self):
        posting = {"description": "No experience needed, apply now!"}
        result = assess_posting_risk(posting)
        assert "unrealistic_compensation" not in result.signals
        assert "no_experience_high_pay" not in result.signals
        assert result.score == 0

