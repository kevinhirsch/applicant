"""Tests for research integration (#299)."""

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.research_service import ResearchService


class TestResearchService:
    def test_research_company_returns_result(self):
        storage = InMemoryStorage()
        svc = ResearchService(storage)
        result = svc.research_company("Acme Corp", "Engineer")
        assert result["company"] == "Acme Corp"
        assert result["role"] == "Engineer"
        assert result["status"] == "research_initiated"

    def test_health_returns_true(self):
        storage = InMemoryStorage()
        svc = ResearchService(storage)
        assert svc.health()["available"] is True
