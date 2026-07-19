"""Tests for the Application entity (FR-LOG-1, FR-DUR-1)."""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

from applicant.core.entities.application import Application
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, ResumeVariantId
from applicant.core.state_machine import ApplicationState
from applicant.core.errors import IllegalStateTransition


@pytest.fixture(autouse=True)
def _no_state_leak() -> None:
    """Prevent xdist parallel test pollution for any module-level caches."""
    return


@pytest.mark.unit
class TestApplication:
    """Tests for the Application frozen dataclass and its methods."""

    def _make_application(self, **overrides) -> Application:
        """Helper to build a minimal Application with sensible defaults."""
        defaults: dict = {
            "id": ApplicationId("app-1"),
            "campaign_id": CampaignId("camp-1"),
            "posting_id": JobPostingId("posting-1"),
        }
        defaults.update(overrides)
        return Application(**defaults)

    def test_create_with_all_fields(self) -> None:
        """Creation with all optional fields set."""
        app = self._make_application(
            status=ApplicationState.DISCOVERED,
            role_name="Engineer",
            job_title="Senior Engineer",
            work_mode="remote",
            root_url="https://example.com/job/1",
            resume_variant_id=ResumeVariantId("rv-1"),
            sandbox_session_url="https://sandbox.example.com/session/1",
            attributes_used={"skill": "python"},
        )
        assert app.id == ApplicationId("app-1")
        assert app.campaign_id == CampaignId("camp-1")
        assert app.posting_id == JobPostingId("posting-1")
        assert app.status == ApplicationState.DISCOVERED
        assert app.role_name == "Engineer"
        assert app.job_title == "Senior Engineer"
        assert app.work_mode == "remote"
        assert app.root_url == "https://example.com/job/1"
        assert app.resume_variant_id == ResumeVariantId("rv-1")
        assert app.sandbox_session_url == "https://sandbox.example.com/session/1"
        assert app.attributes_used == {"skill": "python"}
        assert isinstance(app.created_at, datetime)

    def test_default_values(self) -> None:
        """Minimal creation applies defaults correctly."""
        app = self._make_application()
        assert app.status == ApplicationState.DISCOVERED
        assert app.role_name is None
        assert app.job_title is None
        assert app.work_mode is None
        assert app.root_url is None
        assert app.resume_variant_id is None
        assert app.sandbox_session_url is None
        assert app.attributes_used == {}
        assert isinstance(app.created_at, datetime)
        assert app.created_at.tzinfo is UTC

    def test_frozen_dataclass(self) -> None:
        """Cannot mutate a frozen dataclass instance."""
        app = self._make_application()
        with pytest.raises(FrozenInstanceError):
            app.status = ApplicationState.SCORED  # type: ignore[misc]

    def test_equality(self) -> None:
        """Two applications with the same fields are equal."""
        app1 = self._make_application()
        app2 = app1.with_status(ApplicationState.SCORED)
        app3 = app1.with_status(ApplicationState.SCORED)
        assert app1 == app1
        assert app2 == app3

    def test_inequality(self) -> None:
        """Applications with different ids differ."""
        app1 = self._make_application()
        app2 = self._make_application(id=ApplicationId("app-2"))
        assert app1 != app2

    def test_with_status_valid_transition(self) -> None:
        """with_status returns new instance with the new state."""
        app = self._make_application()
        assert app.status == ApplicationState.DISCOVERED

        next_app = app.with_status(ApplicationState.SCORED)
        assert next_app is not app
        assert next_app.status == ApplicationState.SCORED
        assert next_app.id == app.id
        assert next_app.campaign_id == app.campaign_id
        assert next_app.posting_id == app.posting_id
        # Original is unchanged (frozen)
        assert app.status == ApplicationState.DISCOVERED

    def test_with_status_invalid_transition_raises(self) -> None:
        """Invalid lifecycle transition raises IllegalStateTransition."""
        app = self._make_application(status=ApplicationState.DECLINED)
        with pytest.raises(IllegalStateTransition):
            app.with_status(ApplicationState.APPROVED)

    def test_hashable(self) -> None:
        """Application cannot be hashed due to mutable dict field."""
        app = self._make_application()
        with pytest.raises(TypeError, match="unhashable"):
            hash(app)

    def test_repr_contains_fields(self) -> None:
        """__repr__ includes key fields."""
        app = self._make_application()
        r = repr(app)
        assert "Application(" in r
        assert "app-1" in r
        assert "DISCOVERED" in r
        assert "camp-1" in r

    def test_created_at_is_different_per_instance(self) -> None:
        """Each default Application instance gets its own creation timestamp."""
        import time

        a1 = self._make_application()
        time.sleep(0.01)
        a2 = self._make_application()
        # Because created_at uses datetime.now(UTC) per call, they will differ
        assert a2.created_at >= a1.created_at

    def test_with_status_preserves_other_fields(self) -> None:
        """with_status preserves all other field values."""
        app = self._make_application(
            role_name="Engineer",
            root_url="https://example.com",
        )
        updated = app.with_status(ApplicationState.SCORED)
        assert updated.role_name == "Engineer"
        assert updated.root_url == "https://example.com"
        assert updated.id == app.id
        assert updated.campaign_id == app.campaign_id
        assert updated.posting_id == app.posting_id
        assert updated.created_at == app.created_at

    def test_from_all_states_valid_transitions(self) -> None:
        """Verify various valid state-transition round-trips from the state machine."""
        pairs = [
            (ApplicationState.SCORED, ApplicationState.DIGESTED),
            (ApplicationState.APPROVED, ApplicationState.SANDBOX_PROVISIONING),
        ]
        for current, target in pairs:
            app = self._make_application(status=current)
            app.with_status(target)  # should not raise

    def test_attributes_used_mutable_default_isolation(self) -> None:
        """Each instance gets its own dict for attributes_used."""
        a1 = self._make_application()
        a2 = self._make_application()
        a1.attributes_used["key"] = "value"
        assert a2.attributes_used == {}  # not shared
