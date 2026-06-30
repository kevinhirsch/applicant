"""Tests for two-way learning loop (#286, #294)."""

from __future__ import annotations

from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.application.services.learning_loop import LearningLoopService
from applicant.ports.driven.memory_store import KIND_ENVIRONMENT, SCOPE_CAMPAIGN, MemoryEntry


class _FakeAgentMemory:
    def __init__(self):
        self.memory = InMemoryMemoryStore()
        self.skills = InMemorySkillStore()
        self.recall = InMemoryRecallIndex()
        self.backend = "bridge"


class TestReadContext:
    def test_returns_snapshot_skills_recall(self):
        am = _FakeAgentMemory()
        svc = LearningLoopService(am)
        ctx = svc.read_context("c-1")
        assert "snapshot" in ctx
        assert "skills" in ctx
        assert "recall" in ctx

    def test_snapshot_contains_stored_memory(self):
        am = _FakeAgentMemory()
        am.memory.add(MemoryEntry(text="Learned Python", kind=KIND_ENVIRONMENT, scope=SCOPE_CAMPAIGN, campaign_id="c-1"))
        svc = LearningLoopService(am)
        ctx = svc.read_context("c-1")
        snap = ctx["snapshot"]
        assert snap is not None
        assert any("Python" in e.text for e in snap.environment)


class TestWriteLesson:
    def test_write_lesson_succeeds(self):
        am = _FakeAgentMemory()
        svc = LearningLoopService(am)
        ok = svc.write_lesson("c-1", text="User prefers detailed cover letters", kind=KIND_ENVIRONMENT, scope=SCOPE_CAMPAIGN)
        assert ok is True
        ctx = svc.read_context("c-1")
        snap = ctx["snapshot"]
        assert any("cover letters" in e.text for e in snap.environment)

    def test_write_updates_last_write(self):
        am = _FakeAgentMemory()
        svc = LearningLoopService(am)
        assert svc.health()["last_write"] is None
        svc.write_lesson("c-1", text="test")
        assert svc.health()["last_write"] is not None

    def test_write_fails_gracefully(self):
        svc = LearningLoopService(object())
        assert svc.write_lesson("c-1", text="test") is False


class TestHealth:
    def test_health_reports_available(self):
        am = _FakeAgentMemory()
        svc = LearningLoopService(am)
        h = svc.health()
        assert h["memory_available"] is True
        assert h["skills_available"] is True
        assert h["recall_available"] is True
        assert h["backend"] == "bridge"

    def test_health_reports_unavailable(self):
        svc = LearningLoopService(object())
        h = svc.health()
        assert h["memory_available"] is False
