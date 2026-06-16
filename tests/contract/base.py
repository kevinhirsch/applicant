"""Abstract contract bases (architecture §6: "each adapter has a contract test").

Each ``XxxPortContract`` asserts the behavioral contract a port promises. Adapter
test classes subclass the base and supply the adapter via the ``adapter`` fixture;
the same contract then runs against any adapter (Postgres, in-memory, etc.).
"""

from __future__ import annotations

import pytest

from applicant.core.entities.campaign import Campaign
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    OutcomeEventId,
    PendingActionId,
    new_id,
)
from applicant.ports.driven.credential_store import Credential
from applicant.ports.driven.notification import Notification


class StoragePortContract:
    """Contract for ``StoragePort`` (campaign-scoped CRUD + UoW)."""

    @pytest.fixture
    def adapter(self):
        raise NotImplementedError

    def test_campaign_roundtrip(self, adapter):
        cid = CampaignId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="Test"))
        adapter.commit()
        got = adapter.campaigns.get(cid)
        assert got is not None and got.name == "Test"
        assert cid in {c.id for c in adapter.campaigns.list()}

    def test_get_missing_returns_none(self, adapter):
        assert adapter.campaigns.get(CampaignId("nope")) is None

    def test_outcome_scoped_to_application(self, adapter):
        aid = ApplicationId(new_id())
        adapter.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=aid, type="submitted", source=OutcomeSource.MANUAL)
        )
        adapter.commit()
        events = adapter.outcomes.list_for_application(aid)
        assert len(events) == 1 and events[0].type == "submitted"

    def test_pending_action_resolve(self, adapter):
        cid = CampaignId(new_id())
        pid = PendingActionId(new_id())
        adapter.pending_actions.add(
            PendingAction(id=pid, campaign_id=cid, kind="digest_approval", title="Review")
        )
        adapter.commit()
        assert len(adapter.pending_actions.list_open(cid)) == 1
        adapter.pending_actions.resolve(pid)
        adapter.commit()
        assert adapter.pending_actions.list_open(cid) == []

    def test_healthcheck(self, adapter):
        assert adapter.healthcheck() is True


class CredentialStorePortContract:
    """Contract for ``CredentialStorePort`` (seal on store, unseal on retrieve)."""

    @pytest.fixture
    def adapter(self):
        raise NotImplementedError

    def test_store_and_retrieve_roundtrip(self, adapter):
        cid = CampaignId(new_id())
        cred = Credential(tenant_key="acme.workday", username="kev", secret="hunter2")
        adapter.store(cid, cred)
        got = adapter.retrieve(cid, "acme.workday")
        assert got is not None
        assert got.username == "kev" and got.secret == "hunter2"

    def test_missing_returns_none(self, adapter):
        assert adapter.retrieve(CampaignId(new_id()), "nope") is None

    def test_list_tenants(self, adapter):
        cid = CampaignId(new_id())
        adapter.store(cid, Credential(tenant_key="t1", username="u", secret="s"))
        assert "t1" in adapter.list_tenants(cid)


class NotificationPortContract:
    """Contract for ``NotificationPort`` (dispatch + idempotent expiry)."""

    @pytest.fixture
    def adapter(self):
        raise NotImplementedError

    def test_notify_returns_handle(self, adapter):
        handle = adapter.notify(Notification(title="hi", body="there", dedup_key="k1"))
        assert isinstance(handle, str) and handle

    def test_expire_is_idempotent(self, adapter):
        adapter.notify(Notification(title="x", body="y", dedup_key="k2"))
        adapter.expire("k2")
        adapter.expire("k2")  # no error on second expiry

    def test_is_configured(self, adapter):
        assert isinstance(adapter.is_configured(), bool)


class OrchestrationPortContract:
    """Contract for ``DurableOrchestrationPort`` (idempotent checkpointed steps)."""

    @pytest.fixture
    def adapter(self):
        raise NotImplementedError

    def test_step_runs_once_then_checkpointed(self, adapter):
        calls = []

        def body():
            calls.append(1)
            return {"ok": True}

        r1 = adapter.run_step("wf-1", "s1", body)
        r2 = adapter.run_step("wf-1", "s1", body)  # resumed, must NOT re-run
        assert r1 == r2 == {"ok": True}
        assert calls == [1]

    def test_send_recv_roundtrip(self, adapter):
        adapter.send("wf-2", "approval", {"approved": True})
        assert adapter.recv("wf-2", "approval") == {"approved": True}

    def test_recover_pending_lists_workflows(self, adapter):
        adapter.run_step("wf-3", "s1", lambda: 1)
        assert "wf-3" in adapter.recover_pending()


class ToolRegistryPortContract:
    """Contract for ``ToolRegistryPort`` (toggle + default-enabled)."""

    @pytest.fixture
    def adapter(self):
        raise NotImplementedError

    def test_default_enabled(self, adapter):
        assert adapter.is_enabled("discovery") is True

    def test_toggle_off(self, adapter):
        adapter.set_enabled("discovery", False)
        assert adapter.is_enabled("discovery") is False
        assert adapter.all_tools().get("discovery") is False
