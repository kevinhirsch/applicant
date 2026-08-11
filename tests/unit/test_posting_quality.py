"""Unit tests for applicant.core.rules.posting_quality (non-posting gate).

Pure, deterministic, no IO — see the module docstring for the layered
detection design (known non-job domains -> URL index patterns -> title
patterns -> description boilerplate). This suite covers each layer directly,
PLUS a full pass over the same real-world labeled fixture used by the live
scoring-calibration eval (``tests/eval/fixtures/agile_delivery_scoring_labels
.json``) so the rule module and the LLM rubric are validated against the
identical ground truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from applicant.core.rules.posting_quality import (
    PostingQualityVerdict,
    check_posting_quality,
    is_real_posting,
)

_FIXTURE_PATH = (
    Path(__file__).parent.parent / "eval" / "fixtures" / "agile_delivery_scoring_labels.json"
)


@pytest.mark.unit
class TestKnownNonJobDomains:
    def test_scaledagile_framework_subdomain_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master/Team Coach - Scaled Agile Framework",
            "https://framework.scaledagile.com/scrum-master-team-coach",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "known_non_job_domain"

    def test_scaledagile_apex_domain_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "SAFe Release Train Engineer - Scaled Agile",
            "https://scaledagile.com/certification/safe-release-train-engineer/",
        )
        assert verdict.is_posting is False

    def test_reddit_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "r/agile on Reddit: what is an Agile Release Train Engineer?",
            "https://www.reddit.com/r/agile/comments/1b2hdst/x/",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "known_non_job_domain"

    def test_medium_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "From Scrum Master to Release Train Engineer",
            "https://medium.com/lean-agile-mindset/from-scrum-master-to-rte-1",
        )
        assert verdict.is_posting is False

    def test_knowledgehut_blog_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "The Scrum Master Career Path Guide 2026",
            "https://www.knowledgehut.com/blog/agile/scrum-master-career-path",
        )
        assert verdict.is_posting is False

    def test_unrelated_domain_is_not_flagged(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master",
            "https://job-boards.greenhouse.io/acme/jobs/12345",
        )
        assert verdict.is_posting is True


@pytest.mark.unit
class TestUrlIndexPatterns:
    def test_indeed_search_query_url_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "Agile Release Train Engineer Jobs, Employment | Indeed",
            "https://www.indeed.com/q-agile-release-train-engineer-jobs.html",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "url_index_pattern"

    def test_indeed_specific_job_url_is_not_flagged_by_url_layer(self) -> None:
        # A real Indeed job view URL never starts with "/q-".
        verdict = check_posting_quality(
            "Release Train Engineer",
            "https://www.indeed.com/viewjob?jk=abc123",
        )
        assert verdict.signal != "url_index_pattern"

    def test_dice_search_query_url_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "Agile release train engineer jobs | Dice.com",
            "https://www.dice.com/jobs/q-agile+release+train+engineer-jobs",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "url_index_pattern"

    def test_ziprecruiter_capitalized_jobs_query_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "$51-$83/hr Scrum Master Release Train Engineer Jobs",
            "https://www.ziprecruiter.com/Jobs/Scrum-Master-Release-Train-Engineer",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "url_index_pattern"

    def test_linkedin_posts_article_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master vs Agile Delivery Manager",
            "https://www.linkedin.com/posts/someone_scrum-master-vs-activity-1",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "url_index_pattern"

    def test_linkedin_pulse_article_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "SAFe Scrum Master Vs. Release Train Engineer",
            "https://www.linkedin.com/pulse/safe-scrum-master-vs-rte-decoding-agile",
        )
        assert verdict.is_posting is False

    def test_linkedin_jobs_search_listing_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "132 Scrum Master - Release Train Engineer jobs in United States",
            "https://www.linkedin.com/jobs/scrum-master-release-train-engineer-jobs",
        )
        assert verdict.is_posting is False

    def test_linkedin_jobs_view_specific_listing_is_not_flagged_by_url_layer(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master",
            "https://www.linkedin.com/jobs/view/scrum-master-at-acme-4450619178",
        )
        assert verdict.signal != "url_index_pattern"

    def test_motionrecruitment_category_listing_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "Agile Coach/Scrum Master Jobs | Motion Recruitment",
            "https://motionrecruitment.com/tech-jobs/agile-coach-scrum-master",
        )
        assert verdict.is_posting is False

    def test_workgenius_find_listing_is_non_posting(self) -> None:
        verdict = check_posting_quality(
            "Hire Scrum Masters | Agile Coaches & SAFe Experts | WorkGenius",
            "https://workgenius.com/find/scrum-master/",
        )
        assert verdict.is_posting is False


@pytest.mark.unit
class TestTitlePatterns:
    def test_comparison_article_title(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master vs Release Train Engineer",
            "https://example-unknown-blog.com/scrum-master-vs-rte",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "title_pattern"

    def test_career_guide_title(self) -> None:
        verdict = check_posting_quality(
            "The Scrum Master Career Path Guide 2026",
            "https://example-unknown-blog.com/scrum-master-guide",
        )
        assert verdict.is_posting is False

    def test_jobs_pipe_site_suffix_title(self) -> None:
        verdict = check_posting_quality(
            "Release Train Engineer Jobs, Employment | SomeSite",
            "https://some-unlisted-aggregator.example/q-rte-jobs",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "title_pattern"

    def test_clearedjobs_pipe_suffix_is_not_flagged(self) -> None:
        # "| ClearedJobs" is a site-name suffix, NOT "jobs |" — a real single
        # posting must not be caught by the aggregator title pattern.
        verdict = check_posting_quality(
            "Lead Scrum Master / Release Train Engineer in Arlington, Virginia | ClearedJobs",
            "https://clearedjobs.net/job/lead-scrum-master-release-train-engineer-1",
        )
        assert verdict.signal != "title_pattern"

    def test_leading_result_count_title(self) -> None:
        verdict = check_posting_quality(
            "1,000+ Release Train Engineer Scrum Master jobs in United States",
            "https://example-unlisted-board.example/search",
        )
        assert verdict.is_posting is False

    def test_top_n_jobs_title(self) -> None:
        verdict = check_posting_quality(
            "Top 158 Agile release train engineer (rte) Jobs | SimplyHired",
            "https://www.simplyhired.com/search?q=rte",
        )
        assert verdict.is_posting is False

    def test_hourly_rate_query_title(self) -> None:
        verdict = check_posting_quality(
            "$40-$96/hr Scrum Master Release Manager Jobs (NOW HIRING)",
            "https://example-unlisted-board.example/search",
        )
        assert verdict.is_posting is False

    def test_jobs_near_me_marketing_title(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master Jobs Near Me (New & Hiring Now) - Monster.com",
            "https://www.monster.com/jobs/search?q=scrum-master",
        )
        assert verdict.is_posting is False

    def test_ordinary_specific_title_is_not_flagged(self) -> None:
        verdict = check_posting_quality(
            "Senior Release Train Engineer in Charlotte, North Carolina, USA",
            "https://careers.teksystems.com/us/en/job/JP-006193499/x",
        )
        assert verdict.is_posting is True


@pytest.mark.unit
class TestDescriptionBoilerplate:
    def test_linkedin_sidebar_boilerplate_flagged_even_on_a_view_url(self) -> None:
        # A "/jobs/view/..." URL looks like a real single listing, but if the
        # captured "description" is really the related-jobs sidebar, it must
        # still be caught.
        verdict = check_posting_quality(
            "Agile Coach and Release Train Engineer - LinkedIn",
            "https://www.linkedin.com/jobs/view/agile-coach-and-rte-at-acme-1",
            "4 days ago ... Project Manager Scrum Master jobs. 45,261 open jobs "
            "· Delivery Manager ... Technical Program Manager jobs · "
            "Senior Lead Developer jobs.",
        )
        assert verdict.is_posting is False
        assert verdict.signal == "description_boilerplate"

    def test_blocked_description_is_not_penalized(self) -> None:
        verdict = check_posting_quality(
            "Senior Consultant - Scrum Master/Release Train Engineer",
            "https://apply.deloitte.com/en_US/careers/JobDetail/x/353916",
            "We cannot provide a description for this page right now",
        )
        assert verdict.is_posting is True

    def test_real_description_is_not_penalized(self) -> None:
        verdict = check_posting_quality(
            "Scrum Master",
            "https://job-boards.greenhouse.io/acme/jobs/12345",
            "We are seeking an experienced Scrum Master to support Agile "
            "Transformation and Product Delivery.",
        )
        assert verdict.is_posting is True


@pytest.mark.unit
class TestEdgeCases:
    def test_empty_everything_is_treated_as_a_posting(self) -> None:
        # A negative gate: nothing to match against means nothing fires.
        verdict = check_posting_quality("", "")
        assert verdict.is_posting is True

    def test_malformed_url_does_not_raise(self) -> None:
        verdict = check_posting_quality("Scrum Master", "not a url at all::::")
        assert isinstance(verdict, PostingQualityVerdict)

    def test_www_prefix_is_normalized(self) -> None:
        verdict = check_posting_quality(
            "r/agile thread", "https://www.reddit.com/r/agile/comments/x/"
        )
        assert verdict.is_posting is False

    def test_is_real_posting_bool_wrapper_matches_check(self) -> None:
        title = "Agile release train engineer jobs | Dice.com"
        url = "https://www.dice.com/jobs/q-agile+release+train+engineer-jobs"
        assert is_real_posting(title, url) == check_posting_quality(title, url).is_posting
        assert is_real_posting(title, url) is False


@pytest.mark.unit
class TestAgainstLabeledFixture:
    """Cross-validated against the SAME real-world labels the live scoring
    eval uses (``tests/eval/fixtures/agile_delivery_scoring_labels.json``).

    Every ``NON_POSTING``-labeled row must be caught; every row labeled
    RELEVANT/OFF_DOMAIN/NON_REMOTE is a real specific posting and must NOT be
    caught by this rule (those categories are about domain-fit/remote-fit,
    which is the LLM rubric's job, not this structural gate's).
    """

    @pytest.fixture(scope="class")
    @classmethod
    def fixture_rows(cls) -> list[dict]:
        if not _FIXTURE_PATH.exists():  # pragma: no cover - defensive
            pytest.skip(f"fixture not found at {_FIXTURE_PATH}")
        return json.loads(_FIXTURE_PATH.read_text())

    def test_every_non_posting_row_is_caught(self, fixture_rows: list[dict]) -> None:
        misses = []
        for row in fixture_rows:
            if row["label"] != "NON_POSTING":
                continue
            verdict = check_posting_quality(
                row["title"], row["source_url"], row.get("description") or ""
            )
            if verdict.is_posting:
                misses.append(row["id"])
        assert not misses, f"NON_POSTING rows not caught by the rule: {misses}"

    def test_every_real_posting_row_passes(self, fixture_rows: list[dict]) -> None:
        false_positives = []
        for row in fixture_rows:
            if row["label"] == "NON_POSTING":
                continue
            verdict = check_posting_quality(
                row["title"], row["source_url"], row.get("description") or ""
            )
            if not verdict.is_posting:
                false_positives.append((row["id"], verdict.reason))
        assert not false_positives, f"real postings wrongly flagged: {false_positives}"
