import pytest

from applicant.core.rules.source_pacing import (
    DEFAULT_PER_DOMAIN_INTERVAL_SECONDS,
    SourcePacer,
    domain_of,
    next_allowed_at,
)


@pytest.fixture(autouse=True)
def _no_module_state():
    pass


@pytest.mark.unit
class TestDomainOf:
    """domain_of() extracts the bare registrable host from a URL."""

    def test_normal_url_returns_host(self):
        assert domain_of("https://example.com/jobs/123") == "example.com"

    def test_www_prefix_stripped(self):
        assert domain_of("https://www.linkedin.com/jobs") == "linkedin.com"

    def test_subdomain_preserved(self):
        assert domain_of("https://jobs.example.com/") == "jobs.example.com"

    def test_user_pass_stripped(self):
        assert domain_of("https://user:pass@board.example.com/") == "board.example.com"

    def test_port_stripped(self):
        assert domain_of("https://example.com:8080/jobs") == "example.com"

    def test_capitalized_host_lowercased(self):
        assert domain_of("https://Example.COM/Job") == "example.com"

    def test_empty_url_returns_empty_string(self):
        assert domain_of("") == ""

    def test_garbage_url_returns_empty_string(self):
        assert domain_of("not a url at all") == ""

    def test_url_with_only_netloc(self):
        assert domain_of("//example.com/path") == "example.com"


@pytest.mark.unit
class TestNextAllowedAt:
    """next_allowed_at() computes the earliest allowed time for the next request."""

    def test_none_last_allowed_returns_zero(self):
        assert next_allowed_at(None) == 0.0

    def test_none_with_custom_interval_returns_zero(self):
        assert next_allowed_at(None, interval_seconds=5.0) == 0.0

    def test_positive_last_allowed_adds_default_interval(self):
        result = next_allowed_at(100.0)
        assert result == 100.0 + DEFAULT_PER_DOMAIN_INTERVAL_SECONDS

    def test_custom_interval_applied(self):
        result = next_allowed_at(100.0, interval_seconds=5.0)
        assert result == 105.0

    def test_zero_last_allowed(self):
        result = next_allowed_at(0.0)
        assert result == DEFAULT_PER_DOMAIN_INTERVAL_SECONDS

    def test_negative_last_allowed_still_adds_interval(self):
        result = next_allowed_at(-10.0)
        assert result == -10.0 + DEFAULT_PER_DOMAIN_INTERVAL_SECONDS

    def test_negative_interval_clamped(self):
        result = next_allowed_at(100.0, interval_seconds=-3.0)
        assert result == 100.0

    def test_zero_interval(self):
        result = next_allowed_at(100.0, interval_seconds=0.0)
        assert result == 100.0


@pytest.mark.unit
class TestSourcePacerDefaults:
    """SourcePacer default interval and initial state."""

    def test_default_interval(self):
        pacer = SourcePacer()
        assert pacer.interval_seconds == DEFAULT_PER_DOMAIN_INTERVAL_SECONDS

    def test_next_allowed_at_without_history_returns_zero(self):
        pacer = SourcePacer()
        assert pacer.next_allowed_at("https://example.com/job") == 0.0

    def test_ready_returns_true_without_history(self):
        pacer = SourcePacer()
        assert pacer.ready("https://example.com/job", now=0.0) is True

    def test_ready_returns_true_without_history_any_now(self):
        pacer = SourcePacer()
        assert pacer.ready("https://example.com/job", now=100.0) is True


@pytest.mark.unit
class TestSourcePacerRecordAndReady:
    """SourcePacer.record() and .ready() interaction."""

    def test_record_makes_ready_false_immediately(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.ready("https://example.com/job", now=100.0) is False

    def test_ready_true_after_interval_passes(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        now = 100.0 + 10.0
        assert pacer.ready("https://example.com/job", now=now) is True

    def test_ready_false_before_interval_passes(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.ready("https://example.com/job", now=109.999) is False

    def test_different_domains_independent(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.ready("https://other.com/job", now=100.0) is True

    def test_www_url_and_bare_url_same_domain(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://www.example.com/job", now=100.0)
        assert pacer.ready("https://example.com/other", now=100.0) is False

    def test_user_pass_and_port_normalized(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://user:pass@example.com:8080/job", now=100.0)
        assert pacer.ready("https://example.com/other", now=100.0) is False


@pytest.mark.unit
class TestSourcePacerCustomInterval:
    """SourcePacer with a custom interval."""

    def test_custom_interval_constructor(self):
        pacer = SourcePacer(interval_seconds=5.0)
        assert pacer.interval_seconds == 5.0

    def test_custom_interval_applied_to_ready(self):
        pacer = SourcePacer(interval_seconds=5.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.ready("https://example.com/job", now=104.999) is False
        assert pacer.ready("https://example.com/job", now=105.0) is True


@pytest.mark.unit
class TestSourcePacerReset:
    """SourcePacer.reset() clears all per-domain history."""

    def test_reset_clears_recorded_domains(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.ready("https://example.com/job", now=100.0) is False
        pacer.reset()
        assert pacer.ready("https://example.com/job", now=100.0) is True

    def test_reset_multiple_domains(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        pacer.record("https://other.com/job", now=100.0)
        pacer.reset()
        assert pacer.ready("https://example.com/job", now=0.0) is True
        assert pacer.ready("https://other.com/job", now=0.0) is True

    def test_reset_empty_pacer_is_noop(self):
        pacer = SourcePacer()
        pacer.reset()
        assert pacer.next_allowed_at("https://example.com/job") == 0.0


@pytest.mark.unit
class TestSourcePacerNextAllowedAt:
    """SourcePacer.next_allowed_at() delegates to the module-level function."""

    def test_without_history(self):
        pacer = SourcePacer()
        assert pacer.next_allowed_at("https://example.com/job") == 0.0

    def test_after_record(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.next_allowed_at("https://example.com/job") == 110.0

    def test_after_record_different_domain(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("https://example.com/job", now=100.0)
        assert pacer.next_allowed_at("https://other.com/job") == 0.0

    def test_empty_url_uses_empty_domain_bucket(self):
        pacer = SourcePacer(interval_seconds=10.0)
        pacer.record("", now=100.0)
        assert pacer.next_allowed_at("") == 110.0
