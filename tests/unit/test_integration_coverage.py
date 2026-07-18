from __future__ import annotations

import dataclasses
import threading
from datetime import UTC, datetime

import pytest

from applicant.observability.integration_coverage import (
    LEDGER,
    UnexercisedBoundary,
    IntegrationCoverageLedger,
    coverage_report,
    record_unexercised_boundary,
)


# ── Module-level autouse: reset the process-lived singleton before every test ──
# CRITICAL for xdist parallel safety — the module-level LEDGER singleton persists
# across tests and between workers, so each test must start with a clean slate.

@pytest.fixture(autouse=True)
def _clear_ledger() -> None:
    """Clear the shared LEDGER singleton before every test."""
    LEDGER.clear()


class TestUnexercisedBoundary:
    """UnexercisedBoundary dataclass: construction, defaults, frozen."""

    def test_construction(self) -> None:
        entry = UnexercisedBoundary(boundary="resume_render.latex", reason="texlive not installed")
        assert entry.boundary == "resume_render.latex"
        assert entry.reason == "texlive not installed"
        assert entry.test_id == ""
        assert isinstance(entry.recorded_at, datetime)

    def test_all_fields_explicit(self) -> None:
        fixed = datetime(2026, 7, 18, tzinfo=UTC)
        entry = UnexercisedBoundary(
            boundary="browser.prefill",
            reason="headless chrome not available",
            test_id="tests/unit/test_browser.py::test_prefill",
            recorded_at=fixed,
        )
        assert entry.boundary == "browser.prefill"
        assert entry.reason == "headless chrome not available"
        assert entry.test_id == "tests/unit/test_browser.py::test_prefill"
        assert entry.recorded_at == fixed

    def test_recorded_at_defaults_to_now_utc(self) -> None:
        before = datetime.now(UTC)
        entry = UnexercisedBoundary(boundary="storage.postgres", reason="pg not reachable")
        after = datetime.now(UTC)
        assert before <= entry.recorded_at <= after

    def test_is_frozen(self) -> None:
        entry = UnexercisedBoundary(boundary="tex.render", reason="missing lualatex")
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.boundary = "other"  # type: ignore[misc]

    def test_string_representation(self) -> None:
        entry = UnexercisedBoundary(
            boundary="ocr.tesseract",
            reason="tesseract not installed",
            test_id="test_ocr.py",
        )
        s = repr(entry)
        assert "ocr.tesseract" in s
        assert "tesseract not installed" in s


class TestIntegrationCoverageLedger:
    """IntegrationCoverageLedger: record, gaps, boundaries, is_empty, clear, report."""

    def test_new_ledger_is_empty(self) -> None:
        ledger = IntegrationCoverageLedger()
        assert ledger.is_empty()
        assert ledger.gaps() == []
        assert ledger.boundaries() == set()

    def test_record_returns_entry(self) -> None:
        ledger = IntegrationCoverageLedger()
        entry = ledger.record("resume_render.latex", "texlive not installed")
        assert isinstance(entry, UnexercisedBoundary)
        assert entry.boundary == "resume_render.latex"
        assert entry.reason == "texlive not installed"

    def test_record_adds_to_gaps(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("browser.prefill", "chrome missing")
        assert not ledger.is_empty()
        gaps = ledger.gaps()
        assert len(gaps) == 1
        assert gaps[0].boundary == "browser.prefill"

    def test_record_with_optional_test_id(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("storage.postgres", "pg down", test_id="test_db.py::test_connect")
        gaps = ledger.gaps()
        assert gaps[0].test_id == "test_db.py::test_connect"

    def test_record_without_test_id_two_records(self) -> None:
        ledger = IntegrationCoverageLedger()
        t1 = ledger.record("tex.render", "no lualatex")
        t2 = ledger.record("browser.prefill", "no chrome")
        assert len(ledger.gaps()) == 2
        assert t1 != t2

    def test_gaps_returns_copy(self) -> None:
        """Mutating the result of gaps() must not affect the ledger."""
        ledger = IntegrationCoverageLedger()
        ledger.record("ocr.tesseract", "package missing")
        copy = ledger.gaps()
        copy.clear()
        # The ledger's internal list should still have the entry
        assert ledger.gaps() != []
        assert len(ledger.gaps()) == 1

    def test_boundaries_distinct_set(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("tex.render", "no lualatex")
        ledger.record("browser.prefill", "no chrome")
        ledger.record("tex.render", "no lualatex (again)")
        assert ledger.boundaries() == {"tex.render", "browser.prefill"}

    def test_empty_boundaries_on_clean_ledger(self) -> None:
        ledger = IntegrationCoverageLedger()
        assert ledger.boundaries() == set()

    def test_is_empty_new(self) -> None:
        ledger = IntegrationCoverageLedger()
        assert ledger.is_empty()

    def test_is_empty_after_record(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("smtp.send", "smtp server unreachable")
        assert not ledger.is_empty()

    def test_is_empty_after_clear(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("smtp.send", "smtp server unreachable")
        ledger.clear()
        assert ledger.is_empty()
        assert ledger.gaps() == []

    def test_clear_empties_ledger(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("a", "reason 1")
        ledger.record("b", "reason 2")
        ledger.record("c", "reason 3")
        ledger.clear()
        assert len(ledger.gaps()) == 0
        assert ledger.is_empty()

    def test_report_shape(self) -> None:
        ledger = IntegrationCoverageLedger()
        ledger.record("tex.render", "no lualatex", test_id="test_a")
        ledger.record("browser.prefill", "no chrome", test_id="test_b")
        report = ledger.report()
        assert isinstance(report, dict)
        assert report["unexercised_count"] == 2
        assert report["boundaries"] == ["browser.prefill", "tex.render"]
        assert len(report["gaps"]) == 2
        assert report["gaps"][0]["boundary"] == "tex.render"
        assert report["gaps"][0]["reason"] == "no lualatex"
        assert report["gaps"][0]["test_id"] == "test_a"
        assert report["gaps"][1]["boundary"] == "browser.prefill"

    def test_report_empty(self) -> None:
        ledger = IntegrationCoverageLedger()
        report = ledger.report()
        assert report == {"unexercised_count": 0, "boundaries": [], "gaps": []}


class TestIntegrationCoverageLedgerThreadSafety:
    """Stress-test concurrent record() calls from multiple threads."""

    def test_concurrent_records(self) -> None:
        """100 threads each recording 10 entries must see all 1000 entries."""
        ledger = IntegrationCoverageLedger()
        n_threads = 100
        entries_per_thread = 10
        errors: list[Exception] = []
        barrier = threading.Barrier(n_threads)

        def _worker() -> None:
            barrier.wait()  # all threads start at roughly the same time
            try:
                for i in range(entries_per_thread):
                    ledger.record(
                        f"boundary.{threading.get_ident()}.{i}",
                        "concurrent stress",
                        test_id=f"test_{threading.get_ident()}_{i}",
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"{len(errors)} thread(s) raised exceptions: {errors[:3]}"
        assert len(ledger.gaps()) == n_threads * entries_per_thread
        assert ledger.boundaries() == {f"boundary.{tid}.{i}" for tid in {t.ident for t in threads} for i in range(entries_per_thread)}


class TestRecordUnexercisedBoundary:
    """record_unexercised_boundary convenience function."""

    def test_delegates_to_ledger(self) -> None:
        assert LEDGER.is_empty()
        entry = record_unexercised_boundary(
            "tex.render",
            "lualatex missing",
            test_id="tests/unit/test_tex.py",
        )
        assert isinstance(entry, UnexercisedBoundary)
        assert entry.boundary == "tex.render"
        assert not LEDGER.is_empty()

    def test_appears_in_report(self) -> None:
        record_unexercised_boundary("browser.prefill", "no headless chrome")
        report = coverage_report()
        assert report["unexercised_count"] >= 1
        assert "browser.prefill" in report["boundaries"]


class TestCoverageReport:
    """coverage_report convenience function."""

    def test_returns_dict(self) -> None:
        result = coverage_report()
        assert isinstance(result, dict)

    def test_reflects_ledger_state(self) -> None:
        record_unexercised_boundary("storage.postgres", "pg not reachable")
        report = coverage_report()
        assert report["unexercised_count"] == 1
        assert "storage.postgres" in report["boundaries"]
