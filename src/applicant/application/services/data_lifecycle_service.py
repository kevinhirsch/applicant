"""Data-lifecycle service — campaign-delete purge + PII retention (#363).

Issue #363 (FR-CRIT-4, NFR-PRIV-1): deleting a campaign MUST purge ALL of its
associated data — résumés/variants, parsed PII, EEO/sensitive answers, generated
materials, attributes, the application-scoped children (decisions/outcomes/
screenshots/detection events/redline sessions), discovery sources, agent runs,
pending actions, the onboarding intake, AND the banked credentials — verifiably
absent afterwards. A configurable PII retention policy bounds how long stored PII is
kept, pruning parsed PII / EEO answers + onboarding intakes older than the window.

This is the ONE cohesive service that cascades the purge across the stores: the
storage adapter (``StoragePort.purge_campaign`` / ``prune_pii_older_than``) and the
sealed-off credential store (``CredentialStorePort.delete_campaign``), which live in
different backends. The thin ``ErasureService`` / ``RetentionService`` wrappers are
named views over this same logic so each concern has a single source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from applicant.core.ids import CampaignId
from applicant.observability.logging import get_logger

log = get_logger(__name__)


class DataLifecycleService:
    """Campaign-delete erasure + PII retention cascade (#363)."""

    def __init__(
        self,
        storage: Any,  # StoragePort
        credentials: Any = None,  # CredentialStorePort (optional)
        *,
        pii_retention_days: int = 0,
    ) -> None:
        self._storage = storage
        self._credentials = credentials
        # 0 (default) = keep PII until the campaign is deleted (no time-based prune).
        self._pii_retention_days = max(0, int(pii_retention_days))

    # --- #363 erasure --------------------------------------------------------
    def delete_campaign(self, campaign_id: CampaignId) -> dict:
        """Purge a campaign and ALL its associated data (FR-CRIT-4, NFR-PRIV-1).

        Cascades across both stores — the relational storage (PII/materials/résumés/
        attributes/children) and the sealed credential vault (banked credentials) —
        then verifies nothing PII-bearing survives. Returns a structured result with
        per-store counts and a ``purged`` flag the caller (and the acceptance spec) can
        assert on. Idempotent: deleting an absent campaign reports ``purged`` True with
        zero counts.
        """
        cid = campaign_id
        storage_counts = self._storage.purge_campaign(cid)
        credentials_purged = 0
        if self._credentials is not None and hasattr(
            self._credentials, "delete_campaign"
        ):
            try:
                credentials_purged = int(self._credentials.delete_campaign(cid) or 0)
            except Exception:  # pragma: no cover - credential store best-effort
                log.warning("credential_purge_failed", campaign_id=str(cid))
        self._storage.commit()

        residual = self._residual_pii(cid)
        purged = not residual
        log.info(
            "campaign_purged",
            campaign_id=str(cid),
            purged=purged,
            credentials=credentials_purged,
        )
        return {
            "campaign_id": str(cid),
            "purged": purged,
            "storage": storage_counts,
            "credentials": credentials_purged,
            "residual": residual,
        }

    def _residual_pii(self, cid: CampaignId) -> dict[str, int]:
        """Count any PII-bearing rows that survived the purge (must be empty).

        Verifies the erasure is COMPLETE rather than trusting the delete counts: any
        non-zero entry here means the purge left PII behind and ``purged`` is False.
        """
        residual: dict[str, int] = {}
        attrs = len(self._storage.attributes.list_for_campaign(cid))
        if attrs:
            residual["attributes"] = attrs
        profile = self._storage.onboarding_profiles.get_for_campaign(cid)
        if profile is not None:
            residual["onboarding_profiles"] = 1
        variants = len(self._storage.resume_variants.list_for_campaign(cid))
        if variants:
            residual["resume_variants"] = variants
        if hasattr(self._storage.documents, "list_for_campaign"):
            docs = len(self._storage.documents.list_for_campaign(cid))
            if docs:
                residual["documents"] = docs
        if self._credentials is not None:
            tenants = self._credentials.list_tenants(cid)
            if tenants:
                residual["credentials"] = len(tenants)
        return residual

    # --- #363 retention ------------------------------------------------------
    def prune_pii_older_than(self, days: int | None = None) -> dict:
        """Prune PII older than the retention window (#363).

        ``days`` overrides the configured ``PII_RETENTION_DAYS``. A window of 0 (the
        default) means "keep PII until the campaign is deleted" — no time-based prune
        runs and ``pruned`` is 0. Otherwise parsed PII / EEO answers (attributes) and
        onboarding intakes recorded before ``now - days`` are deleted while in-window
        PII is retained. Returns a result with the cutoff + per-store + total counts.
        """
        window = self._pii_retention_days if days is None else max(0, int(days))
        if window <= 0:
            return {"pruned": 0, "window_days": window, "by_store": {}, "skipped": True}
        cutoff = datetime.now(UTC) - timedelta(days=window)
        by_store = self._storage.prune_pii_older_than(cutoff)
        self._storage.commit()
        total = sum(by_store.values())
        log.info(
            "pii_retention_swept",
            window_days=window,
            pruned=total,
        )
        return {
            "pruned": total,
            "window_days": window,
            "cutoff": cutoff.isoformat(),
            "by_store": by_store,
        }
