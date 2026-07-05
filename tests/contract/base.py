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

    def test_outcomes_list_for_campaign_scoped(self, adapter):
        # FR-LEARN-2 + FR-CRIT-4: conversion events queryable for learning depth but
        # scoped per campaign — outcomes must NOT bleed across campaigns.
        cid_a = CampaignId(new_id())
        cid_b = CampaignId(new_id())
        adapter.campaigns.add(Campaign(id=cid_a, name="A"))
        adapter.campaigns.add(Campaign(id=cid_b, name="B"))
        aid_a = ApplicationId(new_id())
        aid_b = ApplicationId(new_id())
        from applicant.core.entities.application import Application
        from applicant.core.ids import JobPostingId

        adapter.applications.add(
            Application(id=aid_a, campaign_id=cid_a, posting_id=JobPostingId(""))
        )
        adapter.applications.add(
            Application(id=aid_b, campaign_id=cid_b, posting_id=JobPostingId(""))
        )
        adapter.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=aid_a, type="submitted")
        )
        adapter.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=aid_b, type="rejected")
        )
        adapter.commit()
        a_events = adapter.outcomes.list_for_campaign(cid_a)
        assert [e.type for e in a_events] == ["submitted"]
        assert all(e.type != "rejected" for e in a_events)

    def test_detection_event_persist_and_query(self, adapter):
        # FR-OBS-2: detection signals persisted + retrievable per app + per campaign.
        from applicant.core.entities.application import Application
        from applicant.core.entities.detection_event import DetectionEvent
        from applicant.core.ids import DetectionEventId, JobPostingId

        cid = CampaignId(new_id())
        aid = ApplicationId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="D"))
        adapter.applications.add(
            Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
        )
        adapter.detection_events.add(
            DetectionEvent(
                id=DetectionEventId(new_id()),
                application_id=aid,
                signal_type="captcha",
                detail={"url": "https://acme.test"},
            )
        )
        adapter.commit()
        per_app = adapter.detection_events.list_for_application(aid)
        per_campaign = adapter.detection_events.list_for_campaign(cid)
        assert len(per_app) == 1 and per_app[0].signal_type == "captcha"
        assert len(per_campaign) == 1 and per_campaign[0].application_id == aid

    def test_onboarding_profile_roundtrip(self, adapter):
        # FR-ONBOARD-2: completion record persisted to its own first-class table.
        from applicant.core.entities.onboarding_profile import OnboardingProfile
        from applicant.core.ids import OnboardingProfileId

        cid = CampaignId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="O"))
        adapter.onboarding_profiles.add(
            OnboardingProfile(
                id=OnboardingProfileId(new_id()),
                campaign_id=cid,
                completion_flag=True,
                intake={"identity": {"full_name": "Kev"}},
            )
        )
        adapter.commit()
        got = adapter.onboarding_profiles.get_for_campaign(cid)
        assert got is not None and got.completion_flag is True
        assert got.intake["identity"]["full_name"] == "Kev"

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

    # --- S3 scale: new query methods (shared interface) --------------------

    def test_list_unscored_for_campaign(self, adapter):
        # JobPostingRepository.list_unscored_for_campaign -> postings with no score.
        from applicant.core.entities.job_posting import JobPosting
        from applicant.core.ids import JobPostingId

        cid = CampaignId(new_id())
        scored = JobPostingId("p-scored")
        unscored = JobPostingId("p-unscored")
        adapter.postings.add(
            JobPosting(
                id=scored, campaign_id=cid, title="A", company="c",
                source_url="u1", viability_score=0.9,
            )
        )
        adapter.postings.add(
            JobPosting(
                id=unscored, campaign_id=cid, title="B", company="c", source_url="u2"
            )
        )
        adapter.commit()
        got = adapter.postings.list_unscored_for_campaign(cid)
        assert [p.id for p in got] == [unscored]

    def test_application_get_by_posting(self, adapter):
        from applicant.core.entities.application import Application
        from applicant.core.ids import JobPostingId

        cid = CampaignId(new_id())
        pid = JobPostingId(new_id())
        aid = ApplicationId(new_id())
        adapter.applications.add(
            Application(id=aid, campaign_id=cid, posting_id=pid)
        )
        adapter.commit()
        got = adapter.applications.get_by_posting(cid, pid)
        assert got is not None and got.id == aid
        # Wrong campaign / unknown posting -> None.
        assert adapter.applications.get_by_posting(CampaignId(new_id()), pid) is None
        assert adapter.applications.get_by_posting(cid, JobPostingId("nope")) is None

    def test_application_list_by_status(self, adapter):
        from applicant.core.entities.application import Application
        from applicant.core.ids import JobPostingId
        from applicant.core.state_machine import ApplicationState

        cid = CampaignId(new_id())
        a_disc = ApplicationId("a-disc")
        a_scored = ApplicationId("a-scored")
        a_appr = ApplicationId("a-appr")
        adapter.applications.add(
            Application(id=a_disc, campaign_id=cid, posting_id=JobPostingId(""),
                        status=ApplicationState.DISCOVERED)
        )
        adapter.applications.add(
            Application(id=a_scored, campaign_id=cid, posting_id=JobPostingId(""),
                        status=ApplicationState.SCORED)
        )
        adapter.applications.add(
            Application(id=a_appr, campaign_id=cid, posting_id=JobPostingId(""),
                        status=ApplicationState.APPROVED)
        )
        adapter.commit()
        got = adapter.applications.list_by_status(
            cid, (ApplicationState.SCORED, ApplicationState.APPROVED)
        )
        assert {a.id for a in got} == {a_scored, a_appr}
        assert adapter.applications.list_by_status(cid, ()) == []

    def test_list_approved_postings_for_campaign(self, adapter):
        from applicant.core.entities.application import Application
        from applicant.core.entities.decision import Decision, DecisionType
        from applicant.core.ids import DecisionId, JobPostingId

        cid = CampaignId(new_id())
        p_ok = JobPostingId("p-approved")
        p_no = JobPostingId("p-declined")
        a_ok = ApplicationId("app-ok")
        a_no = ApplicationId("app-no")
        adapter.applications.add(Application(id=a_ok, campaign_id=cid, posting_id=p_ok))
        adapter.applications.add(Application(id=a_no, campaign_id=cid, posting_id=p_no))
        adapter.decisions.add(
            Decision(id=DecisionId(new_id()), application_id=a_ok, type=DecisionType.APPROVE)
        )
        adapter.decisions.add(
            Decision(id=DecisionId(new_id()), application_id=a_no, type=DecisionType.DECLINE)
        )
        adapter.commit()
        approved = adapter.decisions.list_approved_postings_for_campaign(cid)
        assert approved == [p_ok]
        # Scoped: another campaign sees nothing.
        assert adapter.decisions.list_approved_postings_for_campaign(CampaignId(new_id())) == []

    def test_agent_run_count_latest_max_seq(self, adapter):
        from datetime import UTC, datetime

        cid = CampaignId(new_id())
        day = datetime(2026, 6, 17, tzinfo=UTC)
        r1 = AgentRun(
            id=AgentRunId("r1"), campaign_id=cid, intent_sentence="one",
            timestamp=datetime(2026, 6, 17, 1, tzinfo=UTC),
            stats={"pipelines_started": 3},
        )
        r2 = AgentRun(
            id=AgentRunId("r2"), campaign_id=cid, intent_sentence="two",
            timestamp=datetime(2026, 6, 17, 5, tzinfo=UTC),
            stats={"pipelines_started": 4},
        )
        r_other_day = AgentRun(
            id=AgentRunId("r3"), campaign_id=cid, intent_sentence="prev",
            timestamp=datetime(2026, 6, 16, 5, tzinfo=UTC),
            stats={"pipelines_started": 9},
        )
        adapter.agent_runs.add(r1)
        adapter.agent_runs.add(r2)
        adapter.agent_runs.add(r_other_day)
        adapter.commit()
        # count_pipelines_started_on SUMS stats["pipelines_started"] for the day
        # (3 + 4 from r1/r2 today; r_other_day is excluded), not a count of run rows.
        assert adapter.agent_runs.count_pipelines_started_on(cid, day.date()) == 7
        latest = adapter.agent_runs.latest(cid)
        assert latest is not None and latest.id == AgentRunId("r2")
        assert adapter.agent_runs.max_seq(cid) == max(r1.seq, r2.seq, r_other_day.seq)
        # Empty campaign.
        empty = CampaignId(new_id())
        assert adapter.agent_runs.latest(empty) is None
        assert adapter.agent_runs.max_seq(empty) == 0
        assert adapter.agent_runs.count_pipelines_started_on(empty, day.date()) == 0

    def test_agent_run_list_pagination(self, adapter):
        from datetime import UTC, datetime

        cid = CampaignId(new_id())
        for i in range(5):
            adapter.agent_runs.add(
                AgentRun(
                    id=AgentRunId(f"run-{i}"), campaign_id=cid,
                    timestamp=datetime(2026, 6, 17, i, tzinfo=UTC),
                )
            )
        adapter.commit()
        all_runs = adapter.agent_runs.list_for_campaign(cid)
        assert [r.id for r in all_runs] == [AgentRunId(f"run-{i}") for i in range(5)]
        page = adapter.agent_runs.list_for_campaign(cid, limit=2, offset=1)
        assert [r.id for r in page] == [AgentRunId("run-1"), AgentRunId("run-2")]

    def test_agent_run_prune_old_keeps_newest(self, adapter):
        from datetime import UTC, datetime

        cid = CampaignId(new_id())
        other = CampaignId(new_id())
        # 6 runs for cid (ascending timestamp) + 1 for another campaign (untouched).
        for i in range(6):
            adapter.agent_runs.add(
                AgentRun(
                    id=AgentRunId(f"p-{i}"), campaign_id=cid,
                    timestamp=datetime(2026, 6, 17, i, tzinfo=UTC),
                )
            )
        adapter.agent_runs.add(
            AgentRun(
                id=AgentRunId("p-other"), campaign_id=other,
                timestamp=datetime(2026, 6, 17, 0, tzinfo=UTC),
            )
        )
        adapter.commit()

        deleted = adapter.agent_runs.prune_old(cid, keep=2)
        adapter.commit()
        assert deleted == 4
        kept = adapter.agent_runs.list_for_campaign(cid)
        # The newest 2 (by timestamp, seq) survive; the older 4 are gone.
        assert [r.id for r in kept] == [AgentRunId("p-4"), AgentRunId("p-5")]
        # A different campaign's runs are never pruned.
        assert [r.id for r in adapter.agent_runs.list_for_campaign(other)] == [
            AgentRunId("p-other")
        ]
        # Pruning again is a no-op once within the window.
        assert adapter.agent_runs.prune_old(cid, keep=2) == 0

    def test_pending_find_open_by_dedup(self, adapter):
        cid = CampaignId(new_id())
        pid = PendingActionId(new_id())
        adapter.pending_actions.add(
            PendingAction(
                id=pid, campaign_id=cid, kind="digest_approval", title="Review",
                payload={"dedup_key": "digest_approval:post-1"},
            )
        )
        adapter.commit()
        found = adapter.pending_actions.find_open_by_dedup(cid, "digest_approval:post-1")
        assert found is not None and found.id == pid
        assert adapter.pending_actions.find_open_by_dedup(cid, "missing") is None
        # Resolved actions are not returned.
        adapter.pending_actions.resolve(pid)
        adapter.commit()
        assert adapter.pending_actions.find_open_by_dedup(cid, "digest_approval:post-1") is None

    def test_outcome_exists_terminal_for_application(self, adapter):
        aid = ApplicationId(new_id())
        other = ApplicationId(new_id())
        assert adapter.outcomes.exists_terminal_for_application(aid) is False
        adapter.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=aid, type="submitted")
        )
        adapter.outcomes.add(
            OutcomeEvent(id=OutcomeEventId(new_id()), application_id=other, type="rejected")
        )
        adapter.commit()
        assert adapter.outcomes.exists_terminal_for_application(aid) is True
        # Non-terminal outcome does not count.
        assert adapter.outcomes.exists_terminal_for_application(other) is False

    def test_outcomes_list_for_campaign_pagination(self, adapter):
        from applicant.core.entities.application import Application
        from applicant.core.ids import JobPostingId

        cid = CampaignId(new_id())
        aid = ApplicationId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="P"))
        adapter.applications.add(
            Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
        )
        for i in range(4):
            adapter.outcomes.add(
                OutcomeEvent(id=OutcomeEventId(f"oe-{i}"), application_id=aid, type="viewed")
            )
        adapter.commit()
        assert len(adapter.outcomes.list_for_campaign(cid)) == 4
        page = adapter.outcomes.list_for_campaign(cid, limit=2, offset=1)
        assert len(page) == 2

    def test_decision_list_for_campaign(self, adapter):
        """Perf lens 03 (round 2): batch decisions-by-campaign (no N+1 over
        applications) — used by ``feedback_history.FeedbackSummaryProvider``."""
        from applicant.core.entities.application import Application
        from applicant.core.entities.decision import Decision, DecisionType
        from applicant.core.ids import DecisionId, JobPostingId

        cid = CampaignId(new_id())
        other_cid = CampaignId(new_id())
        aid = ApplicationId(new_id())
        other_aid = ApplicationId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="P"))
        adapter.campaigns.add(Campaign(id=other_cid, name="Q"))
        adapter.applications.add(Application(id=aid, campaign_id=cid, posting_id=JobPostingId("")))
        adapter.applications.add(
            Application(id=other_aid, campaign_id=other_cid, posting_id=JobPostingId(""))
        )
        adapter.decisions.add(
            Decision(id=DecisionId(new_id()), application_id=aid, type=DecisionType.DECLINE, feedback_text="no")
        )
        adapter.decisions.add(
            Decision(id=DecisionId(new_id()), application_id=aid, type=DecisionType.APPROVE)
        )
        # A decision on another campaign's application must not leak in.
        adapter.decisions.add(
            Decision(id=DecisionId(new_id()), application_id=other_aid, type=DecisionType.DECLINE)
        )
        adapter.commit()

        decisions = adapter.decisions.list_for_campaign(cid)
        assert len(decisions) == 2
        assert all(d.application_id == aid for d in decisions)
        assert adapter.decisions.list_for_campaign(other_cid)[0].application_id == other_aid

    def test_revision_list_for_materials_batch(self, adapter):
        """Perf lens 03 (round 2): batch revision-session lookup for many
        materials in one call (no N+1 over documents)."""
        from applicant.core.entities.revision_session import RevisionSession, RevisionStatus
        from applicant.core.ids import GeneratedDocumentId, RevisionSessionId

        mid_1 = GeneratedDocumentId(new_id())
        mid_2 = GeneratedDocumentId(new_id())
        mid_none = GeneratedDocumentId(new_id())  # no session for this one
        s1 = RevisionSession(id=RevisionSessionId(new_id()), material_id=mid_1, status=RevisionStatus.OPEN)
        s2 = RevisionSession(id=RevisionSessionId(new_id()), material_id=mid_2, status=RevisionStatus.OPEN)
        adapter.revisions.add(s1)
        adapter.revisions.add(s2)
        adapter.commit()

        found = adapter.revisions.list_for_materials([mid_1, mid_2, mid_none])
        assert {str(s.material_id) for s in found} == {str(mid_1), str(mid_2)}
        # Individual lookups still agree with the batch result (same rows).
        assert adapter.revisions.get_for_material(mid_1) is not None
        assert adapter.revisions.list_for_materials([]) == []

    def test_screenshot_list_for_campaign(self, adapter):
        from applicant.core.entities.application import Application
        from applicant.core.entities.application_screenshot import ApplicationScreenshot
        from applicant.core.ids import JobPostingId, ScreenshotId

        cid = CampaignId(new_id())
        other_cid = CampaignId(new_id())
        aid = ApplicationId(new_id())
        other_aid = ApplicationId(new_id())
        adapter.campaigns.add(Campaign(id=cid, name="S"))
        adapter.campaigns.add(Campaign(id=other_cid, name="S2"))
        adapter.applications.add(
            Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
        )
        adapter.applications.add(
            Application(id=other_aid, campaign_id=other_cid, posting_id=JobPostingId(""))
        )
        adapter.screenshots.add(
            ApplicationScreenshot(id=ScreenshotId(new_id()), application_id=aid, page_ref="r1")
        )
        adapter.screenshots.add(
            ApplicationScreenshot(id=ScreenshotId(new_id()), application_id=aid, page_ref="r2")
        )
        adapter.screenshots.add(
            ApplicationScreenshot(
                id=ScreenshotId(new_id()), application_id=other_aid, page_ref="x"
            )
        )
        adapter.commit()
        got = adapter.screenshots.list_for_campaign(cid)
        assert len(got) == 2 and all(s.application_id == aid for s in got)
        assert len(adapter.screenshots.list_for_campaign(cid, limit=1)) == 1


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
