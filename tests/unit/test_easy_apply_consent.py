"""P2-14 -- Easy Apply assisted mode: server-recorded consent (``SetupService``).

The consent screen is a safety surface, not decoration: ``easy_apply_consent_
status``/``record_easy_apply_consent`` are the ONLY way acceptance is ever
remembered -- there is no caller-supplied flag anywhere that can flip this to
``True`` other than actually calling ``record_easy_apply_consent``. Hermetic:
``InMemoryAppConfigStore``, no DB/network/LLM.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.setup_service import SetupService


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


@pytest.mark.unit
class TestEasyApplyConsent:
    def test_not_given_before_anything_is_recorded(self):
        svc = _svc()
        status = svc.easy_apply_consent_status()
        assert status == {"given": False, "given_at": None}

    def test_recording_consent_flips_given_and_stamps_a_timestamp(self):
        svc = _svc()
        recorded = svc.record_easy_apply_consent()
        assert recorded["given"] is True
        assert recorded["given_at"]  # a non-empty ISO-8601 timestamp

    def test_status_reflects_the_recorded_consent(self):
        svc = _svc()
        svc.record_easy_apply_consent()
        status = svc.easy_apply_consent_status()
        assert status["given"] is True
        assert status["given_at"]

    def test_recording_twice_keeps_the_original_timestamp(self):
        """First acceptance is what "recorded before first use" means -- a
        second call (e.g. the consent screen reopened) must not reset it."""
        svc = _svc()
        first = svc.record_easy_apply_consent()
        second = svc.record_easy_apply_consent()
        assert second["given_at"] == first["given_at"]

    def test_consent_survives_a_new_service_instance_over_the_same_store(self):
        """Persisted through the shared ``AppConfigStore`` -- not per-instance
        state (mirrors ``get_channels``/``get_automation_prefs``)."""
        store = InMemoryAppConfigStore()
        svc_a = _svc(store)
        svc_a.record_easy_apply_consent()
        svc_b = _svc(store)
        assert svc_b.easy_apply_consent_status()["given"] is True
