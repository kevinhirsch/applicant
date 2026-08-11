"""Unit tests for RetentionService — PII retention sweep (#363)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from applicant.application.services.retention_service import RetentionService


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Clear any module-level LRU caches to prevent xdist race conditions."""


class TestRetentionService:
    """Exercise RetentionService delegation to DataLifecycleService."""

    def test_prune_pii_older_than_returns_lifecycle_result(self) -> None:
        """prune_pii_older_than returns what the underlying DataLifecycleService returns."""
        storage = MagicMock()
        storage.prune_pii_older_than.return_value = {"pii": 3}
        storage.commit.return_value = None

        svc = RetentionService(storage, pii_retention_days=30)
        result = svc.prune_pii_older_than(days=7)

        assert result["pruned"] == 3
        assert result["window_days"] == 7
        assert result["by_store"] == {"pii": 3}
        assert "cutoff" in result
        storage.prune_pii_older_than.assert_called_once()
        assert isinstance(
            storage.prune_pii_older_than.call_args[0][0], datetime
        )
        storage.commit.assert_called_once()

    def test_prune_pii_older_than_uses_configured_window_when_days_none(self) -> None:
        """When days=None, use the window passed at construction time."""
        storage = MagicMock()
        storage.prune_pii_older_than.return_value = {"onboarding": 2}
        storage.commit.return_value = None

        svc = RetentionService(storage, pii_retention_days=45)
        result = svc.prune_pii_older_than(days=None)

        assert result["window_days"] == 45
        assert result["pruned"] == 2
        storage.prune_pii_older_than.assert_called_once()

    def test_prune_pii_older_than_returns_skipped_when_window_zero(self) -> None:
        """When configured window is 0 and no days override, skip the prune."""
        storage = MagicMock()

        svc = RetentionService(storage, pii_retention_days=0)
        result = svc.prune_pii_older_than(days=None)

        assert result["skipped"] is True
        assert result["pruned"] == 0
        assert result["by_store"] == {}
        assert result["window_days"] == 0
        storage.prune_pii_older_than.assert_not_called()
        storage.commit.assert_not_called()

    def test_prune_pii_older_than_non_default_window_respected(self) -> None:
        """With a non-default retention window and default days=None."""
        storage = MagicMock()
        storage.prune_pii_older_than.return_value = {"pii": 5}
        storage.commit.return_value = None

        svc = RetentionService(storage, pii_retention_days=90)
        result = svc.prune_pii_older_than()

        assert result["window_days"] == 90
        assert result["pruned"] == 5
        storage.prune_pii_older_than.assert_called_once()
