"""Tests for tasks integration (#295)."""

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.tasks_service import TasksService


class TestTasksService:
    def test_list_tasks_returns_empty_when_none(self):
        storage = InMemoryStorage()
        svc = TasksService(storage)
        assert svc.list_tasks("c-1") == []

    def test_health_returns_true(self):
        storage = InMemoryStorage()
        svc = TasksService(storage)
        assert svc.health()["available"] is True

    def test_health_returns_false_without_storage(self):
        svc = TasksService(object())
        assert svc.health()["available"] is False
