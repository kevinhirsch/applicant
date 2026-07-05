"""Regression coverage for performance lens 03 (round 2): ``jd_match._term_pattern``
(``core/rules/jd_match.py``) compiled a fresh regex for ``term`` on every call, even
though ``term`` -> pattern is a pure, deterministic mapping and ``compute_jd_match``
calls it for every one of the ~150 fixed ``KNOWN_SKILL_TERMS`` (checked against the
posting) PLUS every candidate term again (checked against the résumé) on EVERY
``GET /jd-match/{id}`` — recompiling the same fixed regex set from scratch each time.

The fix wraps ``_term_pattern`` in ``functools.lru_cache`` (a pure function of a
single string arg — the ideal ``lru_cache`` case).

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``jd_match.py`` back in, rerun, see the "no cache" assertion fail because
``_term_pattern`` has no ``cache_info``, then restore) this pins that
``_term_pattern`` is memoized AND that ``compute_jd_match``'s score/matched/missing
output is unchanged across repeated calls with the same inputs.
"""

from __future__ import annotations

import pytest

from applicant.core.rules import jd_match
from applicant.core.rules.jd_match import compute_jd_match


@pytest.mark.unit
def test_term_pattern_is_memoized_and_reused_across_calls():
    assert hasattr(jd_match._term_pattern, "cache_info"), (
        "_term_pattern must be wrapped in functools.lru_cache (or equivalent) so "
        "the same deterministic regex isn't recompiled on every call"
    )
    jd_match._term_pattern.cache_clear()

    posting_text = "Senior Python engineer with React and Kubernetes experience."
    resume_text = "I have 5 years of Python and Kubernetes experience."

    result_1 = compute_jd_match(resume_text, posting_text)
    hits_after_first = jd_match._term_pattern.cache_info().hits
    misses_after_first = jd_match._term_pattern.cache_info().misses
    assert misses_after_first > 0, "first call must populate the cache"

    result_2 = compute_jd_match(resume_text, posting_text)
    # Behavior parity: identical inputs must yield an identical result.
    assert result_2 == result_1

    # The second full compute_jd_match call re-checks EVERY known-skill term (and
    # every candidate) again -- with the cache warm, these must be hits, not new
    # compilations. Misses must not grow (same term set); hits must grow a lot.
    assert jd_match._term_pattern.cache_info().misses == misses_after_first
    assert jd_match._term_pattern.cache_info().hits > hits_after_first


@pytest.mark.unit
def test_compute_jd_match_scores_are_unchanged_by_the_cache():
    """Sanity: caching must never change WHICH terms are reported matched/missing."""
    posting_text = "We need a Go and Kubernetes engineer familiar with Terraform."
    resume_text = "I work daily with Go, Docker, and Terraform."

    result = compute_jd_match(resume_text, posting_text)
    assert result["score"] > 0
    matched_lower = {m.lower() for m in result["matched"]}
    missing_lower = {m.lower() for m in result["missing"]}
    assert "go" in matched_lower
    assert "terraform" in matched_lower
    assert "kubernetes" in missing_lower
    assert not (matched_lower & missing_lower)
