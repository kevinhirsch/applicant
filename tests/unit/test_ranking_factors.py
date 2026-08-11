"""Unit tests for applicant.core.rules.ranking_factors (round-3 ranking fix).

Pure, deterministic, no IO — see the module docstring. This closes the gap
Kevin reported: the allowlist (round 2) correctly fixed RELEVANCE but never
touched RANKING QUALITY within the allowlisted set, so a real, in-domain
role scored 95 despite being "too low pay, heavily SAFe, posted ~a month
ago, not high-impact". This suite is the ROCK-SOLID deterministic layer
that closes that gap — no LLM involved anywhere in this file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.core.rules.ranking_factors import (
    DEFAULT_TARGET_ANNUAL,
    DEFAULT_TARGET_HOURLY,
    RankingFactor,
    RemoteVerdict,
    classify_remote,
    degree_requirement_multiplier,
    fit_to_profile_multiplier,
    pay_multiplier,
    recency_multiplier,
    safe_penalty_multiplier,
    seniority_multiplier,
)

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


@pytest.mark.unit
class TestRecencyMultiplier:
    def test_fresh_within_a_week_is_full_weight(self) -> None:
        f = recency_multiplier(_NOW - timedelta(days=3), now=_NOW)
        assert f.multiplier == pytest.approx(1.0)

    def test_exactly_seven_days_is_still_full_weight(self) -> None:
        f = recency_multiplier(_NOW - timedelta(days=7), now=_NOW)
        assert f.multiplier == pytest.approx(1.0)

    def test_thirty_days_drops_noticeably(self) -> None:
        """Kevin's own complaint: 'posted ~a month ago' scored as if fresh."""
        f = recency_multiplier(_NOW - timedelta(days=30), now=_NOW)
        assert f.multiplier < 0.9, "a 30-day-old posting must drop noticeably"
        assert f.multiplier == pytest.approx(0.75, abs=0.01)

    def test_decay_is_monotonic_with_age(self) -> None:
        ages = [0, 7, 14, 30, 45, 60, 120]
        mults = [recency_multiplier(_NOW - timedelta(days=a), now=_NOW).multiplier for a in ages]
        assert mults == sorted(mults, reverse=True), "older must never score >= fresher"

    def test_very_old_posting_floors_rather_than_zeroing(self) -> None:
        f = recency_multiplier(_NOW - timedelta(days=365), now=_NOW)
        assert 0.0 < f.multiplier <= 0.55

    def test_missing_date_is_neutral_not_penalized(self) -> None:
        f = recency_multiplier(None, now=_NOW)
        assert f.multiplier == pytest.approx(1.0)

    def test_naive_datetime_does_not_raise(self) -> None:
        naive = datetime(2026, 7, 1, 9, 0)  # no tzinfo
        f = recency_multiplier(naive, now=_NOW)
        assert isinstance(f, RankingFactor)
        assert 0.0 < f.multiplier <= 1.0


@pytest.mark.unit
class TestSafePenaltyMultiplier:
    def test_heavy_safe_title_is_penalized(self) -> None:
        f = safe_penalty_multiplier(
            "Release Train Engineer",
            "Runs PI Planning and Scrum of Scrums for the Agile Release Train under SAFe.",
        )
        assert f.multiplier < 1.0

    def test_less_role_is_not_penalized(self) -> None:
        f = safe_penalty_multiplier(
            "Scrum Master - Large-Scale Scrum (LeSS)",
            "Facilitates Sprint Planning and Overall Retrospective across feature teams.",
        )
        assert f.multiplier == pytest.approx(1.0)

    def test_framework_agnostic_role_is_not_penalized(self) -> None:
        f = safe_penalty_multiplier(
            "Agile Coach", "Coach teams in Scrum and Kanban practices, no specific framework mandated."
        )
        assert f.multiplier == pytest.approx(1.0)

    def test_heavy_safe_ranks_below_light_safe(self) -> None:
        heavy = safe_penalty_multiplier(
            "SAFe RTE",
            "SAFe, Scaled Agile, PI Planning, Release Train Engineer, Agile Release Train.",
        )
        light = safe_penalty_multiplier("Release Train Engineer", "Standard delivery role.")
        agnostic = safe_penalty_multiplier("Scrum Master", "Standard delivery role.")
        assert heavy.multiplier < light.multiplier < agnostic.multiplier + 1e-9
        assert heavy.multiplier <= 0.85

    def test_rte_title_stays_a_ranking_penalty_not_a_zero(self) -> None:
        # Kevin is RTE-certified -- SAFe roles must stay meaningfully scored,
        # just ranked lower, never floored like a non-posting/off-domain role.
        f = safe_penalty_multiplier("Release Train Engineer", "SAFe, PI Planning.")
        assert f.multiplier >= 0.7


@pytest.mark.unit
class TestPayMultiplier:
    def test_clearly_below_annual_target_is_penalized(self) -> None:
        f = pay_multiplier("$70,000 - $85,000", "")
        assert f.multiplier < 0.9

    def test_meets_annual_target_is_neutral(self) -> None:
        f = pay_multiplier("$130,000 - $150,000", "")
        assert f.multiplier == pytest.approx(1.0)

    def test_clearly_below_hourly_target_is_penalized(self) -> None:
        f = pay_multiplier("$45/hr", "")
        assert f.multiplier < 0.9

    def test_meets_hourly_target_is_neutral(self) -> None:
        f = pay_multiplier("$80/hr", "")
        assert f.multiplier == pytest.approx(1.0)

    def test_parses_from_description_when_salary_field_is_null(self) -> None:
        f = pay_multiplier(None, "Salary range $90,000 - $100,000 annually for this role.")
        assert f.multiplier < 1.0

    def test_unparseable_placeholder_salary_is_neutral(self) -> None:
        for placeholder in ("Competitive", "DOE", "Negotiable", "", None):
            f = pay_multiplier(placeholder, "")
            assert f.multiplier == pytest.approx(1.0), placeholder

    def test_missing_pay_everywhere_is_neutral_not_over_penalized(self) -> None:
        f = pay_multiplier(None, "We are hiring a great Scrum Master to join our team.")
        assert f.multiplier == pytest.approx(1.0)

    def test_target_values_are_kevins_stated_numbers(self) -> None:
        assert DEFAULT_TARGET_ANNUAL == pytest.approx(120_000.0)
        assert DEFAULT_TARGET_HOURLY == pytest.approx(75.0)

    def test_somewhat_below_target_is_a_lighter_penalty_than_clearly_below(self) -> None:
        somewhat = pay_multiplier("$110,000", "")
        clearly = pay_multiplier("$70,000", "")
        assert clearly.multiplier < somewhat.multiplier < 1.0


@pytest.mark.unit
class TestSeniorityMultiplier:
    @pytest.mark.parametrize(
        "title", ["Principal Agile Coach", "Staff Program Manager", "Director of Delivery", "Head of Agile Practice"]
    )
    def test_top_tier_titles_are_boosted(self, title: str) -> None:
        f = seniority_multiplier(title)
        assert f.multiplier > 1.0

    @pytest.mark.parametrize("title", ["Senior Scrum Master", "Lead Delivery Manager"])
    def test_mid_tier_titles_are_boosted_less_than_top_tier(self, title: str) -> None:
        mid = seniority_multiplier(title)
        top = seniority_multiplier("Principal " + title)
        assert 1.0 < mid.multiplier < top.multiplier

    @pytest.mark.parametrize("title", ["Associate Program Manager", "Junior Scrum Master", "Entry-Level Delivery Analyst"])
    def test_junior_titles_are_penalized(self, title: str) -> None:
        f = seniority_multiplier(title)
        assert f.multiplier < 1.0

    def test_generic_title_is_neutral(self) -> None:
        f = seniority_multiplier("Scrum Master")
        assert f.multiplier == pytest.approx(1.0)


@pytest.mark.unit
class TestClassifyRemoteGeneral:
    def test_explicit_remote_us_passes(self) -> None:
        v = classify_remote(None, "Remote, United States", "")
        assert v.is_us_remote is True

    def test_remote_work_mode_field_plus_us_location_passes(self) -> None:
        v = classify_remote("remote", "Remote - US", "")
        assert v.is_us_remote is True

    def test_li_remote_hashtag_plus_us_passes(self) -> None:
        v = classify_remote(None, None, "This role is #LI-Remote, United States.")
        assert v.is_us_remote is True

    def test_explicit_onsite_work_mode_fails(self) -> None:
        v = classify_remote("onsite", "Austin, TX", "")
        assert v.is_us_remote is False

    def test_explicit_hybrid_language_fails(self) -> None:
        v = classify_remote(None, None, "This is a hybrid role, 3 days in office.")
        assert v.is_us_remote is False

    def test_named_us_city_with_no_remote_language_fails(self) -> None:
        v = classify_remote(None, "Charlotte, North Carolina, USA", "")
        assert v.is_us_remote is False

    def test_clearance_requirement_fails(self) -> None:
        v = classify_remote(None, None, "Requires an active TS/SCI security clearance.")
        assert v.is_us_remote is False

    def test_no_signal_anywhere_is_ambiguous_not_gated(self) -> None:
        v = classify_remote(None, None, "")
        assert v.is_us_remote is None

    def test_remote_with_no_country_stated_is_ambiguous_not_gated(self) -> None:
        # Explicit per the coordinator: "Ambiguous 'Remote' with no country
        # = don't hard-gate but note it" -- a scraper gap must never bury a
        # real, good, US-remote posting.
        v = classify_remote(None, None, "This is a fully remote position.")
        assert v.is_us_remote is None

    def test_join_us_pronoun_is_not_mistaken_for_a_us_signal(self) -> None:
        v = classify_remote(None, None, "Join us! This is a remote-first company.")
        assert v.is_us_remote is None, "the pronoun 'us' must never be read as a US-location signal"


@pytest.mark.unit
class TestClassifyRemoteUsSpecific:
    """The coordinator's explicit addendum: US-remote specifically, not just remote."""

    def test_remote_bangalore_fails(self) -> None:
        v = classify_remote(None, "Remote, Bangalore", "")
        assert v.is_us_remote is False
        assert "bangalore" in v.reason.lower()

    @pytest.mark.parametrize(
        "location",
        [
            "Remote, India",
            "Remote - UK",
            "Remote, United Kingdom",
            "Remote, Canada",
            "Remote - EMEA",
            "Remote, Mexico City",
            "Remote, Singapore",
        ],
    )
    def test_various_non_us_remote_locations_fail(self, location: str) -> None:
        v = classify_remote(None, location, "")
        assert v.is_us_remote is False, location

    def test_all_remote_company_headquartered_outside_us_but_us_qualified_passes(self) -> None:
        # GitLab-style: an all-remote company; the POSTING itself states US.
        v = classify_remote(None, "Remote, United States", "GitLab is a fully remote company.")
        assert v.is_us_remote is True

    def test_us_city_with_remote_language_passes(self) -> None:
        v = classify_remote(None, "Remote (Austin, TX or anywhere in the US)", "")
        assert v.is_us_remote is True


@pytest.mark.unit
class TestRankingFactorAndRemoteVerdictDataclasses:
    def test_ranking_factor_shape(self) -> None:
        f = RankingFactor(1.0, "neutral")
        assert f.multiplier == 1.0
        assert f.reason == "neutral"

    def test_remote_verdict_shape(self) -> None:
        v = RemoteVerdict(True, "confirmed")
        assert v.is_us_remote is True
        assert v.reason == "confirmed"


@pytest.mark.unit
class TestFitToProfileMultiplier:
    """Round 4: rank Kevin's EXACT title/cert history above the round-3
    STRETCH families -- both stay viable, only ranking changes."""

    @pytest.mark.parametrize(
        "title",
        [
            "Scrum Master",
            "Senior Scrum Master",
            "Lead Scrum Master",
            "Agile Coach",
            "Agile Team Coach",
            "Enterprise Agile Coach",
            "Scrum Coach",
            "Kanban Coach",
            "Delivery Manager",
            "Agile Delivery Manager",
            "Agile Delivery Lead",
            "Iteration Manager",
            "Release Train Engineer",
            "Agile Transformation Lead",
            "Ways of Working Lead",
        ],
    )
    def test_strong_fit_titles_are_boosted(self, title: str) -> None:
        f = fit_to_profile_multiplier(title)
        assert f.multiplier > 1.0, title

    @pytest.mark.parametrize(
        "title",
        [
            "Technical Program Manager",
            "TPM",
            "Program Manager",
            "Senior Program Manager",
            "Project Manager",
            "PMO Lead",
            "Product Operations Manager",
            "Delivery Operations Manager",
            "Chief of Staff",
            "Operations Manager",
        ],
    )
    def test_moderate_fit_titles_are_penalized_relative_to_strong(self, title: str) -> None:
        f = fit_to_profile_multiplier(title)
        assert f.multiplier < 1.0, title

    def test_strong_fit_outranks_moderate_fit_directly(self) -> None:
        strong = fit_to_profile_multiplier("Scrum Master")
        moderate = fit_to_profile_multiplier("Technical Program Manager")
        assert strong.multiplier > moderate.multiplier

    def test_unrecognized_title_is_neutral(self) -> None:
        f = fit_to_profile_multiplier("Warehouse Associate")
        assert f.multiplier == pytest.approx(1.0)

    def test_strong_signal_wins_when_title_names_both_tiers(self) -> None:
        # A TPM title that ALSO explicitly says "Agile Delivery" is closer
        # to Kevin's real background than a generic TPM -- strong wins.
        f = fit_to_profile_multiplier("Technical Program Manager, Agile Delivery & Release Management")
        assert f.multiplier == pytest.approx(1.10)


@pytest.mark.unit
class TestDegreeRequirementMultiplier:
    """Round 4: Kevin has no bachelor's degree (homeschool HS + certs)."""

    @pytest.mark.parametrize(
        "description",
        [
            "Bachelor's degree required in a related field.",
            "Bachelor degree is required.",
            "Must have a Bachelor's degree.",
            "Minimum a Bachelor's degree in Computer Science.",
            "BS in Computer Science required.",
            "Requires a Bachelor's degree or higher.",
        ],
    )
    def test_hard_required_degree_is_penalized(self, description: str) -> None:
        f = degree_requirement_multiplier(description)
        assert f.multiplier < 1.0, description

    @pytest.mark.parametrize(
        "description",
        [
            "Bachelor's degree preferred but not required.",
            "Bachelor's degree or equivalent experience required.",
            "A degree is a plus but not necessary.",
            "10+ years of relevant experience required; no specific degree required.",
        ],
    )
    def test_soft_or_escaped_degree_language_is_neutral(self, description: str) -> None:
        f = degree_requirement_multiplier(description)
        assert f.multiplier == pytest.approx(1.0), description

    def test_no_degree_mention_at_all_is_neutral(self) -> None:
        f = degree_requirement_multiplier("We are seeking an experienced Scrum Master.")
        assert f.multiplier == pytest.approx(1.0)

    def test_empty_description_is_neutral(self) -> None:
        f = degree_requirement_multiplier("")
        assert f.multiplier == pytest.approx(1.0)
        f2 = degree_requirement_multiplier(None)  # type: ignore[arg-type]
        assert f2.multiplier == pytest.approx(1.0)
