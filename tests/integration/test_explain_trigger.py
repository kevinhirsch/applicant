"""EXPLAIN backend trigger — ViabilityScored -> posting.rationale['breakdown'].

Mirrors ``tests/unit/test_audit_log.py``'s event-bus test style: a fresh
``DomainEventBus`` per test (never the process-global singleton, so tests never
bleed into each other), ``ExplainService(storage, bus=bus).start()``, then
``bus.emit(...)``. Covers:

* the shared (in-memory / no-DB) subscription path — a ``ViabilityScored``
  emission persists the breakdown, MERGED into any existing rationale;
* it self-heals / survives a re-score (a second, different-score emission
  updates the cached breakdown rather than leaving it stale);
* the isolated-per-event-session path (``session_factory`` configured) that
  ``app/lifespan.py`` wires in for the real-DB / scheduler-thread lane —
  mirrors ``AuditLogService``'s ``_persist_isolated`` durability tests.
"""

from __future__ import annotations

import dataclasses

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.explain_service import ExplainService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.events import DomainEventBus, ViabilityScored
from applicant.core.ids import CampaignId, JobPostingId, new_id


def _make_campaign(storage: InMemoryStorage, cid: CampaignId) -> None:
    storage.campaigns.add(
        Campaign(
            id=cid,
            name="Test",
            criteria={"titles": ["Scrum Master"], "keywords": ["Agile"]},
        )
    )
    storage.commit()


def _make_posting(storage: InMemoryStorage, cid: CampaignId, **overrides) -> JobPosting:
    defaults = dict(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Scrum Master",
        company="Acme",
        source_url="https://job-boards.greenhouse.io/acme/jobs/123",
        description="Run Agile ceremonies for two teams.",
    )
    defaults.update(overrides)
    posting = JobPosting(**defaults)
    storage.postings.add(posting)
    storage.commit()
    return posting


@pytest.mark.integration
class TestSharedStorageTrigger:
    def test_viability_scored_persists_breakdown(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        _make_campaign(storage, cid)
        posting = _make_posting(storage, cid)

        bus = DomainEventBus()
        svc = ExplainService(storage, llm=None, embedding=None, bus=bus)
        svc.start()

        bus.emit(ViabilityScored(posting_id=posting.id, score=0.72, campaign_id=cid))

        updated = storage.postings.get(posting.id)
        assert "breakdown" in updated.rationale
        breakdown = updated.rationale["breakdown"]
        assert breakdown["score"] == pytest.approx(0.72)
        assert breakdown["factors"]

    def test_merge_preserves_scoring_services_own_rationale_keys(self):
        """Emulates the real order of operations: ScoringService._persist_score
        writes {text, viable, criteria_sig, learning_sig} FIRST, then emits
        ViabilityScored -- our handler must MERGE 'breakdown' in, not clobber
        those keys."""
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        _make_campaign(storage, cid)
        posting = _make_posting(
            storage,
            cid,
            viability_score=0.72,
            rationale={
                "text": "Match 72/100 from overlap between the role and your criteria.",
                "viable": True,
                "criteria_sig": "abc123",
            },
        )

        bus = DomainEventBus()
        svc = ExplainService(storage, llm=None, embedding=None, bus=bus)
        svc.start()

        bus.emit(ViabilityScored(posting_id=posting.id, score=0.72, campaign_id=cid))

        updated = storage.postings.get(posting.id)
        assert updated.rationale["text"].startswith("Match 72/100")
        assert updated.rationale["viable"] is True
        assert updated.rationale["criteria_sig"] == "abc123"
        assert "breakdown" in updated.rationale

    def test_survives_a_rescore(self):
        """A second ViabilityScored emission (a re-score) self-heals the cached
        breakdown to the NEW score rather than leaving the stale one."""
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        _make_campaign(storage, cid)
        posting = _make_posting(storage, cid)

        bus = DomainEventBus()
        svc = ExplainService(storage, llm=None, embedding=None, bus=bus)
        svc.start()

        bus.emit(ViabilityScored(posting_id=posting.id, score=0.40, campaign_id=cid))
        first = storage.postings.get(posting.id).rationale["breakdown"]
        assert first["score"] == pytest.approx(0.40)

        # Re-score: the posting's persisted viability_score also moves (mirrors
        # ScoringService._persist_score), then the event fires again.
        rescored = dataclasses.replace(storage.postings.get(posting.id), viability_score=0.90)
        storage.postings.add(rescored)
        storage.commit()
        bus.emit(ViabilityScored(posting_id=posting.id, score=0.90, campaign_id=cid))

        second = storage.postings.get(posting.id).rationale["breakdown"]
        assert second["score"] == pytest.approx(0.90)
        assert second["score"] != first["score"]

    def test_unknown_posting_is_a_noop(self):
        """The event carries a posting_id that doesn't exist (already deleted,
        or a race) -- the handler must not raise."""
        storage = InMemoryStorage()
        bus = DomainEventBus()
        svc = ExplainService(storage, llm=None, embedding=None, bus=bus)
        svc.start()

        bus.emit(ViabilityScored(posting_id=JobPostingId("nope"), score=0.5))
        # No exception == pass.


@pytest.mark.integration
class TestIsolatedSessionTrigger:
    """The real-DB / scheduler-thread lane: one fresh session per event.

    Mirrors ``tests/unit/test_audit_log_durability_lens04.py``'s fake
    session-factory + monkeypatched ``SqlAlchemyStorage`` pattern so no real
    database is needed, while still exercising the EXACT isolated-session code
    path ``app/lifespan.py`` wires in via ``session_factory=container.session_factory``.
    """

    def test_isolated_session_path_persists_and_closes_session(self, monkeypatch):
        import applicant.adapters.storage.repositories as repositories_module

        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        _make_campaign(storage, cid)
        posting = _make_posting(storage, cid)

        class _FakeSession:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        sessions: list[_FakeSession] = []

        def _factory():
            s = _FakeSession()
            sessions.append(s)
            return s

        class _WrappingStore:
            """Delegates to the SAME in-memory storage regardless of the fake
            'session' passed in -- proves the isolated code path threads a
            fresh session per event while still exercising real storage
            semantics (add/commit/get)."""

            def __init__(self, _session) -> None:
                self._inner = storage

            def __getattr__(self, name):
                return getattr(self._inner, name)

        monkeypatch.setattr(repositories_module, "SqlAlchemyStorage", _WrappingStore)

        bus = DomainEventBus()
        svc = ExplainService(
            storage, llm=None, embedding=None, bus=bus, session_factory=_factory
        )
        svc.start()

        bus.emit(ViabilityScored(posting_id=posting.id, score=0.65, campaign_id=cid))

        updated = storage.postings.get(posting.id)
        assert updated.rationale["breakdown"]["score"] == pytest.approx(0.65)
        assert len(sessions) == 1
        assert sessions[0].closed is True

    def test_isolated_session_failure_never_raises(self, monkeypatch):
        """A broken isolated-session write must never break the emitting caller
        (the same durability guarantee AuditLogService's isolated path gives)."""
        import applicant.adapters.storage.repositories as repositories_module

        def _factory():
            raise RuntimeError("db unreachable")

        monkeypatch.setattr(
            repositories_module, "SqlAlchemyStorage", lambda session: (_ for _ in ()).throw(
                RuntimeError("should not be constructed")
            )
        )

        bus = DomainEventBus()
        svc = ExplainService(
            InMemoryStorage(), llm=None, embedding=None, bus=bus, session_factory=_factory
        )
        svc.start()

        # Must not raise even though the session factory itself blows up.
        bus.emit(ViabilityScored(posting_id=JobPostingId("p-1"), score=0.5))
