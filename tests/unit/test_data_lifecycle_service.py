"""Unit tests for DataLifecycleService — campaign delete + PII retention (#363)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, PropertyMock

import pytest

from applicant.application.services.data_lifecycle_service import DataLifecycleService
from applicant.core.ids import CampaignId


@pytest.fixture(autouse=True)
def _xdist_safe() -> None:
    """No module-level caches in this module, but required for parallel safety."""
    return


def _campaign_id(val: str = "camp-test-1") -> CampaignId:
    return CampaignId(val)


@pytest.mark.unit
class TestDeleteCampaign:
    """Tests for DataLifecycleService.delete_campaign (#363 erasure)."""

    def _make_service(
        self,
        *,
        storage_counts: dict | None = None,
        residual: dict | None = None,
        credentials_purged: int = 0,
        has_credentials: bool = True,
        credentials_raises: bool = False,
    ) -> DataLifecycleService:
        """Build a DataLifecycleService with fully mocked adapters."""
        storage = MagicMock()
        storage.purge_campaign.return_value = storage_counts or {"materials": 3}
        storage.commit.return_value = None

        # Mock _residual_pii indirectly via the internal helpers it calls
        attrs_mock = MagicMock()
        attrs_mock.list_for_campaign.return_value = []
        storage.attributes = attrs_mock

        onboarding_mock = MagicMock()
        onboarding_mock.get_for_campaign.return_value = None
        storage.onboarding_profiles = onboarding_mock

        variants_mock = MagicMock()
        variants_mock.list_for_campaign.return_value = []
        storage.resume_variants = variants_mock

        docs_mock = MagicMock()
        docs_mock.list_for_campaign.return_value = []
        storage.documents = docs_mock

        creds = None
        if has_credentials:
            creds = MagicMock()
            if credentials_raises:
                creds.delete_campaign.side_effect = Exception("store down")
            else:
                creds.delete_campaign.return_value = credentials_purged
            creds.list_tenants.return_value = []

        return DataLifecycleService(storage=storage, credentials=creds)

    def test_delete_campaign_returns_expected_keys(self) -> None:
        """Returned dict contains campaign_id, purged, storage, credentials, residual."""
        svc = self._make_service()
        result = svc.delete_campaign(_campaign_id())
        assert set(result.keys()) == {
            "campaign_id",
            "purged",
            "storage",
            "credentials",
            "residual",
        }

    def test_delete_campaign_includes_storage_counts(self) -> None:
        """The 'storage' key returns whatever purge_campaign returned."""
        svc = self._make_service(storage_counts={"materials": 2, "candidates": 5})
        result = svc.delete_campaign(_campaign_id())
        assert result["storage"] == {"materials": 2, "candidates": 5}

    def test_delete_campaign_reports_credentials_count(self) -> None:
        """Credentials count is passed through from the credential store."""
        svc = self._make_service(credentials_purged=7)
        result = svc.delete_campaign(_campaign_id())
        assert result["credentials"] == 7

    def test_delete_campaign_zero_when_no_credentials(self) -> None:
        """No credential store yields count 0."""
        svc = self._make_service(has_credentials=False)
        result = svc.delete_campaign(_campaign_id())
        assert result["credentials"] == 0
        assert result["residual"] == {}

    def test_delete_campaign_credential_error_does_not_raise(self) -> None:
        """A failing credential store logs a warning but does not abort."""
        svc = self._make_service(credentials_raises=True)
        # Should not raise
        result = svc.delete_campaign(_campaign_id())
        assert result["credentials"] == 0

    def test_purged_true_when_no_residual(self) -> None:
        """purged is True when no residual PII remains."""
        svc = self._make_service()
        result = svc.delete_campaign(_campaign_id())
        assert result["purged"] is True
        assert result["residual"] == {}

    def test_purged_false_when_residual_attributes(self) -> None:
        """purged is False when attributes survive the purge."""
        svc = self._make_service()
        # Inject residual through the storage mock
        svc._storage.attributes.list_for_campaign.return_value = ["attr-1"]
        result = svc.delete_campaign(_campaign_id())
        assert result["purged"] is False
        assert "attributes" in result["residual"]

    def test_purged_false_when_residual_onboarding_profile(self) -> None:
        """purged is False when an onboarding profile survives."""
        svc = self._make_service()
        svc._storage.onboarding_profiles.get_for_campaign.return_value = {
            "id": "op-1"
        }
        result = svc.delete_campaign(_campaign_id())
        assert result["purged"] is False
        assert "onboarding_profiles" in result["residual"]

    def test_purged_false_when_residual_variants(self) -> None:
        """purged is False when resume variants survive."""
        svc = self._make_service()
        svc._storage.resume_variants.list_for_campaign.return_value = ["rv-1"]
        result = svc.delete_campaign(_campaign_id())
        assert result["purged"] is False
        assert "resume_variants" in result["residual"]

    def test_purged_false_when_residual_documents(self) -> None:
        """purged is False when documents survive."""
        svc = self._make_service()
        svc._storage.documents.list_for_campaign.return_value = ["doc-1"]
        result = svc.delete_campaign(_campaign_id())
        assert result["purged"] is False
        assert "documents" in result["residual"]

    def test_purged_false_when_residual_credentials(self) -> None:
        """purged is False when credential tenants survive."""
        svc = self._make_service()
        svc._credentials.list_tenants.return_value = ["tenant-1"]
        result = svc.delete_campaign(_campaign_id())
        assert result["purged"] is False
        assert "credentials" in result["residual"]

    def test_delete_campaign_calls_commit(self) -> None:
        """The service calls storage.commit() after purge."""
        svc = self._make_service()
        svc.delete_campaign(_campaign_id())
        svc._storage.commit.assert_called_once()

    def test_delete_campaign_stringifies_campaign_id(self) -> None:
        """Returned campaign_id is a string."""
        svc = self._make_service()
        result = svc.delete_campaign(_campaign_id("camp-xyz"))
        assert result["campaign_id"] == "camp-xyz"
        assert isinstance(result["campaign_id"], str)


@pytest.mark.unit
class TestPrunePiiOlderThan:
    """Tests for DataLifecycleService.prune_pii_older_than (#363 retention)."""

    def _make_service(self, *, pii_retention_days: int = 0) -> DataLifecycleService:
        storage = MagicMock()
        storage.prune_pii_older_than.return_value = {"attributes": 2, "profiles": 1}
        storage.commit.return_value = None
        # Store the cutoff so we can inspect it
        return DataLifecycleService(
            storage=storage,
            credentials=MagicMock(),
            pii_retention_days=pii_retention_days,
        )

    def test_skipped_when_window_is_zero(self) -> None:
        """prune returns skipped with pruned=0 when window <= 0."""
        svc = self._make_service(pii_retention_days=0)
        result = svc.prune_pii_older_than()
        assert result == {
            "pruned": 0,
            "window_days": 0,
            "by_store": {},
            "skipped": True,
        }

    def test_skipped_when_window_is_negative(self) -> None:
        """Negative retention is clamped to 0 and is skipped."""
        svc = self._make_service(pii_retention_days=-5)
        result = svc.prune_pii_older_than()
        assert result["window_days"] == 0
        assert result["skipped"] is True
        assert result["pruned"] == 0

    def test_uses_configured_retention_when_no_arg(self) -> None:
        """Without an argument, uses self._pii_retention_days."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than()
        assert result["window_days"] == 30
        assert result["pruned"] == 3
        assert "cutoff" in result
        assert "skipped" not in result

    def test_uses_explicit_days_argument(self) -> None:
        """Passing days overrides the configured retention."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than(days=90)
        assert result["window_days"] == 90
        assert result["pruned"] == 3
        assert "cutoff" in result
        assert "skipped" not in result

    def test_explicit_days_zero_is_skipped(self) -> None:
        """Explicit days=0 is also skipped."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than(days=0)
        assert result["window_days"] == 0
        assert result["skipped"] is True

    def test_explicit_days_clamped_to_zero(self) -> None:
        """Negative explicit days are clamped to 0."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than(days=-1)
        assert result["window_days"] == 0
        assert result["skipped"] is True

    def test_by_store_from_adapter(self) -> None:
        """The by_store dict comes through from storage.prune_pii_older_than."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than()
        assert result["by_store"] == {"attributes": 2, "profiles": 1}

    def test_total_is_sum_of_by_store(self) -> None:
        """pruned equals the sum of all by_store values."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than()
        assert result["pruned"] == 3

    def test_cutoff_is_datetime_isoformat(self) -> None:
        """cutoff is an ISO-format datetime string."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than(days=1)
        assert isinstance(result["cutoff"], str)
        # Should be parseable as an ISO datetime
        dt = datetime.fromisoformat(result["cutoff"])
        assert dt.tzinfo is not None

    def test_cutoff_is_now_minus_window(self) -> None:
        """cutoff should be approximately now - window_days."""
        svc = self._make_service(pii_retention_days=30)
        result = svc.prune_pii_older_than(days=1)
        cutoff = datetime.fromisoformat(result["cutoff"])
        now = datetime.now(UTC)
        diff = now - cutoff
        # Should be roughly 1 day, with some fudge for execution time
        assert timedelta(hours=23) < diff < timedelta(hours=25)

    def test_calls_commit(self) -> None:
        """The service calls storage.commit() after pruning."""
        svc = self._make_service(pii_retention_days=30)
        svc.prune_pii_older_than(days=1)
        svc._storage.commit.assert_called_once()

    def test_calls_prune_pii_older_than_with_cutoff(self) -> None:
        """The underlying storage is called with the computed cutoff."""
        svc = self._make_service(pii_retention_days=30)
        svc.prune_pii_older_than(days=7)
        svc._storage.prune_pii_older_than.assert_called_once()
        (cutoff_arg,) = svc._storage.prune_pii_older_than.call_args[0]
        assert isinstance(cutoff_arg, datetime)
        assert cutoff_arg.tzinfo is not None
        # Should be roughly 7 days ago
        now = datetime.now(UTC)
        diff = now - cutoff_arg
        assert timedelta(days=6, hours=23) < diff < timedelta(days=7, hours=1)
