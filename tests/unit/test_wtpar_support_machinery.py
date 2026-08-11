"""Hermetic tests for the support-request handling scaffold (UNIT-703).

Asserts the ``SupportRequest`` record schema (frozen dataclass fields) and the
``SupportMachinery`` capture / retrieval contract. No external services.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from applicant.application.services.support_machinery import (
    SupportMachinery,
    SupportRequest,
)


# ---------------------------------------------------------------------------
# Autouse fixture for xdist parallel safety
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_machinery() -> None:
    """Each test gets a clean module state; this fixture is a no-op since
    SupportMachinery instances are test-scoped, but it prevents xdist cross-talk
    in case of global state in the future."""
    return


# ---------------------------------------------------------------------------
# SupportRequest record schema
# ---------------------------------------------------------------------------

class TestSupportRequestSchema:
    """Frozen dataclass contract for the SupportRequest record."""

    @pytest.mark.unit
    def test_is_frozen_dataclass(self) -> None:
        r = SupportRequest(subject="Sub", body="Body")
        with pytest.raises(AttributeError):
            r.subject = "changed"  # frozen — should raise

    @pytest.mark.unit
    def test_required_fields(self) -> None:
        r = SupportRequest(subject="help", body="I need help")
        assert r.subject == "help"
        assert r.body == "I need help"

    @pytest.mark.unit
    def test_context_defaults_to_empty_dict(self) -> None:
        r = SupportRequest(subject="s", body="b")
        assert r.context == {}

    @pytest.mark.unit
    def test_id_defaults_to_zero_when_not_set(self) -> None:
        r = SupportRequest(subject="s", body="b")
        assert r.id == 0

    @pytest.mark.unit
    def test_created_at_is_utc_datetime(self) -> None:
        r = SupportRequest(subject="s", body="b")
        assert isinstance(r.created_at, datetime)
        assert r.created_at.tzinfo is not None
        assert r.created_at.tzinfo.utcoffset(r.created_at) == timezone.utc.utcoffset(r.created_at)

    @pytest.mark.unit
    def test_created_at_is_recent(self) -> None:
        before = datetime.now(timezone.utc)
        r = SupportRequest(subject="s", body="b")
        after = datetime.now(timezone.utc)
        assert before <= r.created_at <= after

    @pytest.mark.unit
    def test_context_accepts_dict(self) -> None:
        ctx = {"page": "settings", "feature": "notifications"}
        r = SupportRequest(subject="s", body="b", context=ctx)
        assert r.context == ctx

    @pytest.mark.unit
    def test_can_pass_id_explicitly(self) -> None:
        r = SupportRequest(subject="s", body="b", id=42)
        assert r.id == 42


# ---------------------------------------------------------------------------
# SupportMachinery capture contract
# ---------------------------------------------------------------------------

class TestSupportMachineryCapture:
    """Capture logic: id assignment, storage, retrieval."""

    @pytest.mark.unit
    def test_capture_returns_record_with_auto_id(self) -> None:
        svc = SupportMachinery()
        r = svc.capture(subject="Can't log in", body="Password not working")
        assert isinstance(r, SupportRequest)
        assert r.subject == "Can't log in"
        assert r.body == "Password not working"
        assert r.id == 1  # first request

    @pytest.mark.unit
    def test_capture_increments_id(self) -> None:
        svc = SupportMachinery()
        r1 = svc.capture(subject="A", body="a")
        r2 = svc.capture(subject="B", body="b")
        r3 = svc.capture(subject="C", body="c")
        assert r1.id == 1
        assert r2.id == 2
        assert r3.id == 3

    @pytest.mark.unit
    def test_capture_stores_context(self) -> None:
        svc = SupportMachinery()
        ctx = {"page": "dashboard", "browser": "Chrome 120"}
        r = svc.capture(subject="Bug", body="Crash on load", context=ctx)
        assert r.context == ctx

    @pytest.mark.unit
    def test_capture_without_context_stores_empty(self) -> None:
        svc = SupportMachinery()
        r = svc.capture(subject="Q", body="How do I reset?")
        assert r.context == {}

    @pytest.mark.unit
    def test_list_returns_all_requests_in_order(self) -> None:
        svc = SupportMachinery()
        svc.capture(subject="First", body="1")
        svc.capture(subject="Second", body="2")
        svc.capture(subject="Third", body="3")
        requests = svc.list_requests()
        assert len(requests) == 3
        assert [r.subject for r in requests] == ["First", "Second", "Third"]

    @pytest.mark.unit
    def test_list_returns_copy_not_reference(self) -> None:
        svc = SupportMachinery()
        svc.capture(subject="A", body="a")
        reqs = svc.list_requests()
        svc.clear()
        # The returned list should be a snapshot, not affected by later clear.
        assert len(reqs) == 1

    @pytest.mark.unit
    def test_get_request_finds_by_id(self) -> None:
        svc = SupportMachinery()
        svc.capture(subject="First", body="1")
        r2 = svc.capture(subject="Second", body="2")
        svc.capture(subject="Third", body="3")
        found = svc.get_request(2)
        assert found is not None
        assert found.subject == "Second"

    @pytest.mark.unit
    def test_get_request_returns_none_for_missing(self) -> None:
        svc = SupportMachinery()
        assert svc.get_request(99) is None

    @pytest.mark.unit
    def test_get_request_returns_none_on_empty(self) -> None:
        svc = SupportMachinery()
        assert svc.get_request(1) is None

    @pytest.mark.unit
    def test_clear_removes_all_requests(self) -> None:
        svc = SupportMachinery()
        svc.capture(subject="A", body="a")
        svc.capture(subject="B", body="b")
        svc.clear()
        assert svc.list_requests() == []

    @pytest.mark.unit
    def test_capture_after_clear_resets_id(self) -> None:
        svc = SupportMachinery()
        svc.capture(subject="A", body="a")  # id=1
        svc.clear()
        r = svc.capture(subject="B", body="b")  # should be id=1 again since storage is empty
        assert r.id == 1

    @pytest.mark.unit
    def test_initial_storage_injection(self) -> None:
        preexisting = [
            SupportRequest(subject="Old", body="o", id=10),
            SupportRequest(subject="Existing", body="e", id=20),
        ]
        svc = SupportMachinery(storage=preexisting)
        assert len(svc.list_requests()) == 2
        # New capture should get next id based on injected storage length.
        r = svc.capture(subject="New", body="n")
        assert r.id == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestSupportMachineryEdgeCases:
    """Boundary conditions on the support machinery."""

    @pytest.mark.unit
    def test_empty_subject_allowed(self) -> None:
        svc = SupportMachinery()
        r = svc.capture(subject="", body="Just a note")
        assert r.subject == ""

    @pytest.mark.unit
    def test_empty_body_allowed(self) -> None:
        svc = SupportMachinery()
        r = svc.capture(subject="FYI", body="")
        assert r.body == ""

    @pytest.mark.unit
    def test_very_long_subject_and_body(self) -> None:
        svc = SupportMachinery()
        long_subj = "x" * 10_000
        long_body = "y" * 100_000
        r = svc.capture(subject=long_subj, body=long_body)
        assert len(r.subject) == 10_000
        assert len(r.body) == 100_000

    @pytest.mark.unit
    def test_list_on_empty_service(self) -> None:
        svc = SupportMachinery()
        assert svc.list_requests() == []

    @pytest.mark.unit
    def test_clear_on_empty_service(self) -> None:
        svc = SupportMachinery()
        svc.clear()  # should not raise
        assert svc.list_requests() == []

    @pytest.mark.unit
    def test_request_ids_are_isolated_per_instance(self) -> None:
        svc1 = SupportMachinery()
        svc2 = SupportMachinery()
        r1 = svc1.capture(subject="Svc1", body="first")
        r2 = svc2.capture(subject="Svc2", body="first")
        # Both start counting at 1 independently
        assert r1.id == 1 and r2.id == 1
