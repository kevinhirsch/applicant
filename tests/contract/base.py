"""Abstract contract bases (architecture §6: "each adapter has a contract test").

Each ``XxxPortContract`` asserts the behavioral contract a port promises. Adapter
test classes subclass the base and supply the adapter via the ``adapter`` fixture;
the same contract then runs against any adapter (Postgres, in-memory, etc.).
"""

from __future__ import annotations

import pytest

from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import (
    AgentRunId,
    ApplicationId,
    AttributeId,
    CampaignId,
    DiscoverySourceId,
    FieldMappingId,
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

    def test_screenshot_archive_and_list(self, adapter):
        # FR-LOG-2: per-page screenshots archived + retrievable per application.
        from applicant.core.entities.application_screenshot import ApplicationScreenshot
        from applicant.core.ids import ScreenshotId

        aid = ApplicationId(new_id())
        adapter.screenshots.add(
            ApplicationScreenshot(
                id=ScreenshotId(new_id()),
                application_id=aid,
                page_ref="screenshot://fake/1",
                page_url="https://acme.workday/application/personal",
            )
        )
        adapter.commit()
        shots = adapter.screenshots.list_for_application(aid)
        assert len(shots) == 1
        assert shots[0].page_url.endswith("personal")

    def test_outcomes_list_all(self, adapter):
        # FR-LEARN-2: all conversion events queryable for learning depth.
        aid = ApplicationId(new_id())
        adapter.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=aid, type="submitted")
        )
        adapter.commit()
        assert any(o.type == "submitted" for o in adapter.outcomes.list_all())

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

    def test_discovery_source_upsert_and_yield_stats(self, adapter):
        # FR-DISC-2/5: per-campaign toggle + yield stats persist + upsert in place.
        cid = CampaignId(new_id())
        sid = DiscoverySourceId(new_id())
        adapter.discovery_sources.upsert(
            DiscoverySource(id=sid, campaign_id=cid, source_key="jobspy:indeed", enabled=True)
        )
        adapter.commit()
        adapter.discovery_sources.upsert(
            DiscoverySource(
                id=sid,
                campaign_id=cid,
                source_key="jobspy:indeed",
                enabled=False,
                yield_stats={"matches": 7, "approvals": 2},
            )
        )
        adapter.commit()
        got = adapter.discovery_sources.get(cid, "jobspy:indeed")
        assert got is not None and got.enabled is False
        assert got.yield_stats["matches"] == 7
        assert len(adapter.discovery_sources.list_for_campaign(cid)) == 1

    def test_field_mapping_shared_and_scoped(self, adapter):
        # FR-ATTR-2: shared (global) + per-campaign mappings; find prefers scoped.
        cid = CampaignId(new_id())
        shared = FieldMappingId(new_id())
        scoped = FieldMappingId(new_id())
        adapter.field_mappings.add(
            FieldMapping(
                id=shared,
                site_key="workday",
                field_selector="email",
                attribute_id=AttributeId("attr-shared"),
            )
        )
        adapter.field_mappings.add(
            FieldMapping(
                id=scoped,
                site_key="workday",
                field_selector="email",
                campaign_id=cid,
                attribute_id=AttributeId("attr-scoped"),
            )
        )
        adapter.commit()
        assert len(adapter.field_mappings.list_for_site("workday")) == 2
        assert len(adapter.field_mappings.list_for_campaign(cid)) == 1
        found = adapter.field_mappings.find("workday", "email")
        assert found is not None and found.campaign_id == cid  # scoped wins

    def test_agent_run_roundtrip(self, adapter):
        # FR-AGENT-2/7: run mode + intent sentence persist on the agent_runs row.
        cid = CampaignId(new_id())
        rid = AgentRunId(new_id())
        adapter.agent_runs.add(
            AgentRun(
                id=rid,
                campaign_id=cid,
                intent_sentence="Scan boards next.",
                run_mode=RunMode.UNTIL_N_VIABLE,
                throughput_target=20,
                stats={"viable": 3},
            )
        )
        adapter.commit()
        got = adapter.agent_runs.get(rid)
        assert got is not None
        assert got.intent_sentence == "Scan boards next."
        assert got.run_mode is RunMode.UNTIL_N_VIABLE
        assert got.throughput_target == 20
        assert got.stats["viable"] == 3
        assert len(adapter.agent_runs.list_for_campaign(cid)) == 1

    def test_revision_session_durable_roundtrip(self, adapter):
        # FR-RESUME-8: the interactive redline loop persists + is resumable.
        from applicant.core.entities.generated_document import (
            DocumentType,
            GeneratedDocument,
        )
        from applicant.core.entities.revision_session import (
            RevisionSession,
            RevisionStatus,
            RevisionTurn,
        )
        from applicant.core.ids import (
            GeneratedDocumentId,
            RevisionSessionId,
        )

        cid = CampaignId(new_id())
        aid = ApplicationId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="Rev"))
        adapter.commit()
        did = GeneratedDocumentId(new_id())
        adapter.documents.add(
            GeneratedDocument(
                id=did,
                campaign_id=cid,
                application_id=aid,
                type=DocumentType.COVER_LETTER,
                content="body",
            )
        )
        sid = RevisionSessionId(new_id())
        adapter.revisions.add(
            RevisionSession(
                id=sid,
                material_id=did,
                status=RevisionStatus.OPEN,
                turns=(RevisionTurn(kind="add", instruction="metric", ai_response="Added: metric"),),
                redline_state={"content": "body\nmetric"},
            )
        )
        adapter.commit()
        # Resumable by session id and by material id (the review surface reopens it).
        by_id = adapter.revisions.get(sid)
        by_material = adapter.revisions.get_for_material(did)
        assert by_id is not None and by_material is not None
        assert by_material.id == sid
        assert len(by_material.turns) == 1
        assert by_material.turns[0].kind == "add"
        assert by_material.redline_state["content"].endswith("metric")

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

    def test_capture_banking_mode(self, adapter):
        # FR-VAULT-2: auto-capture during live account-creation, tagged ``captured``.
        cid = CampaignId(new_id())
        adapter.capture(cid, "acme.workday", "kev", "live-secret")
        got = adapter.retrieve(cid, "acme.workday")
        assert got is not None
        assert got.username == "kev" and got.secret == "live-secret"
        assert got.source == "captured"

    def test_manual_banking_mode_is_default(self, adapter):
        # FR-VAULT-2: manual vault entry is the default banking mode.
        cid = CampaignId(new_id())
        adapter.store(cid, Credential(tenant_key="t2", username="u", secret="s"))
        got = adapter.retrieve(cid, "t2")
        assert got is not None and got.source == "manual"

    def test_sealed_at_rest_not_plaintext(self, adapter):
        # NFR-PRIV-1: the stored record must never equal the plaintext secret.
        cid = CampaignId(new_id())
        adapter.store(cid, Credential(tenant_key="t3", username="u", secret="topsecret"))
        # The adapter keeps an internal sealed record; assert it does not leak.
        sealed = getattr(adapter, "_store", {})
        for rec in sealed.values():
            assert "topsecret" not in str(rec)


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

    def test_queue_concurrency_cap_and_pivot(self, adapter):
        # FR-DUR-2: a concurrency cap admits up to N; FR-DUR-4: release pivots to
        # the next waiter so a blocked unit does not stall unrelated work.
        adapter.create_queue("sandbox", concurrency=2)
        assert adapter.acquire("sandbox", "app-1") is True
        assert adapter.acquire("sandbox", "app-2") is True
        # Cap reached: app-3 must wait (it does NOT stall app-1/app-2).
        assert adapter.acquire("sandbox", "app-3") is False
        # app-1 enters a BLOCKED/AWAITING state -> yields capacity (the pivot).
        promoted = adapter.release("sandbox", "app-1")
        assert promoted == "app-3"  # the waiter pivots in

    def test_queue_acquire_is_idempotent(self, adapter):
        adapter.create_queue("llm", concurrency=1)
        assert adapter.acquire("llm", "call-1") is True
        assert adapter.acquire("llm", "call-1") is True  # re-acquire holds same slot
        assert adapter.acquire("llm", "call-2") is False  # cap is still 1

    def test_rate_limiter_bounds_admissions(self, adapter):
        # FR-DUR-2: per-provider LLM rate limit (limit per period seconds).
        adapter.create_queue("openrouter", limiter_limit=2, limiter_period=100.0)
        assert adapter.acquire("openrouter", "a") is True
        assert adapter.acquire("openrouter", "b") is True
        assert adapter.acquire("openrouter", "c") is False  # over the window limit


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
