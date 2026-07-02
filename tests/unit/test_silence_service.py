"""SilenceService unit tests (#192) — ghosting SLA constant unification.

Hermetic: pure functions over timestamps, no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.application.services.post_submission_service import (
    DEFAULT_SLA_DAYS,
)
from applicant.application.services.silence_service import (
    DEFAULT_GHOST_SLA_DAYS,
    SilenceService,
)


@pytest.mark.unit
def test_ghost_sla_constant_is_unified_across_modules():
    # Regression (#192/#190): PostSubmissionService.DEFAULT_SLA_DAYS and
    # SilenceService's DEFAULT_GHOST_SLA_DAYS used to disagree (14 vs 30).
    # silence_service.py now imports the constant from post_submission_service
    # under its existing public name, so the two references must always be the
    # SAME value — assert equality between the references (not two hardcoded
    # literals) so this survives a future, deliberate, in-sync constant change.
    assert DEFAULT_GHOST_SLA_DAYS == DEFAULT_SLA_DAYS


@pytest.mark.unit
def test_silence_service_default_sla_matches_shared_constant():
    service = SilenceService()
    assert service.sla_days == DEFAULT_SLA_DAYS


@pytest.mark.unit
def test_is_likely_ghosted_uses_the_shared_default_threshold():
    now = datetime.now(UTC)
    submitted_at = now - timedelta(days=DEFAULT_SLA_DAYS)
    days = SilenceService.days_since_submission(submitted_at, now=now)
    assert SilenceService.is_likely_ghosted(days) is True
    assert SilenceService.is_likely_ghosted(days - 1) is False
