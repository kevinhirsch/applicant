"""Hermetic tests for the engine-side ResearchService (Lane B, Stage 2.5).

The WorkspacePort is faked (no network / no real LLM). Covers the contract the
agent's escalation relies on: budget cap enforced, identical queries deduped, a
cache hit served for free (no extra workspace call, no budget charged), and
graceful degrade when the workspace channel is unavailable / raises.
"""

from __future__ import annotations

from applicant.application.services.research_service import (
    ResearchReport,
    ResearchService,
)
from applicant.ports.driven.workspace import WorkspaceError


class FakeWorkspace:
    """Minimal WorkspacePort fake recording calls and returning a canned report."""

    def __init__(self, *, available=True, raise_error=False):
        self._available = available
        self._raise = raise_error
        self.calls: list[dict] = []

    def available(self) -> bool:
        return self._available

    def run_research(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self._raise:
            raise WorkspaceError("workspace down", is_timeout=True)
        return {
            "query": kwargs["query"],
            "summary": f"Report on {kwargs['query']}",
            "key_findings": ["finding A", "finding B"],
            "sources": [{"url": "https://x", "title": "X"}],
        }


CID = "camp-1"


def test_fresh_run_returns_parsed_report():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws)
    report = svc.research(CID, "acme corp culture")
    assert isinstance(report, ResearchReport)
    assert report.cached is False
    assert report.summary.startswith("Report on")
    assert report.key_findings == ["finding A", "finding B"]
    assert report.sources == [{"url": "https://x", "title": "X"}]
    assert len(ws.calls) == 1


def test_optional_fields_forwarded():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws)
    svc.research(CID, "q", company="Acme", role="Engineer", context="ctx", max_time=120)
    assert ws.calls[0]["company"] == "Acme"
    assert ws.calls[0]["role"] == "Engineer"
    assert ws.calls[0]["context"] == "ctx"
    assert ws.calls[0]["max_time"] == 120


def test_dedupe_and_cache_hit_is_free():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws)
    first = svc.research(CID, "Acme   Corp")  # whitespace-insensitive key
    second = svc.research(CID, "acme corp")  # case-insensitive, same key
    assert first.cached is False
    assert second.cached is True
    # Only ONE actual workspace call; the dedupe served the cache.
    assert len(ws.calls) == 1
    # A cache hit must NOT consume budget.
    assert svc.calls_made(CID) == 1


def test_budget_cap_enforced():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws, max_calls=2)
    assert svc.research(CID, "q1") is not None
    assert svc.research(CID, "q2") is not None
    # Third DISTINCT query exceeds the cap -> None, no extra workspace call.
    assert svc.research(CID, "q3") is None
    assert len(ws.calls) == 2
    assert svc.budget_remaining(CID) == 0
    # A cached query still works for free even after the cap is hit.
    assert svc.research(CID, "q1").cached is True


def test_budget_is_per_campaign():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws, max_calls=1)
    assert svc.research("camp-a", "q") is not None
    assert svc.research("camp-a", "other") is None  # camp-a exhausted
    assert svc.research("camp-b", "q") is not None  # separate budget


def test_degrade_when_channel_unavailable():
    ws = FakeWorkspace(available=False)
    svc = ResearchService(workspace=ws)
    assert svc.available() is False
    assert svc.research(CID, "q") is None
    assert ws.calls == []  # never touched the network
    assert svc.calls_made(CID) == 0  # no budget charged


def test_degrade_on_workspace_error():
    ws = FakeWorkspace(raise_error=True)
    svc = ResearchService(workspace=ws)
    assert svc.research(CID, "q") is None
    # A failed run must NOT charge budget (so a retry later is possible).
    assert svc.calls_made(CID) == 0


def test_empty_query_returns_none():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws)
    assert svc.research(CID, "   ") is None
    assert ws.calls == []


def test_force_bypasses_cache_and_charges_budget():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws)
    svc.research(CID, "q")
    again = svc.research(CID, "q", force=True)
    assert again.cached is False
    assert len(ws.calls) == 2
    assert svc.calls_made(CID) == 2


# --- manual trigger (run_for_campaign always returns a report) -------------
def test_manual_run_returns_report():
    ws = FakeWorkspace()
    svc = ResearchService(workspace=ws)
    report = svc.run_for_campaign(CID, "q")
    assert report.unavailable is False
    assert report.summary


def test_manual_run_unavailable_reason():
    svc = ResearchService(workspace=FakeWorkspace(available=False))
    report = svc.run_for_campaign(CID, "q")
    assert report.unavailable is True
    assert report.reason == "workspace_unavailable"


def test_manual_run_budget_exhausted_reason():
    svc = ResearchService(workspace=FakeWorkspace(), max_calls=1)
    svc.run_for_campaign(CID, "q1")
    report = svc.run_for_campaign(CID, "q2")
    assert report.unavailable is True
    assert report.reason == "budget_exhausted"
