"""Step bindings for RUX-6 — the campaign chat's gated action tools.

Real regression coverage (no ``@pending`` tag): the tools ship on this branch. The
steps drive the actual :class:`ChatToolbox` through in-memory service doubles — never UI
internals, never network/DB — asserting the RUX-6 guardrails: capability-gated,
transparent, reversible, and NEVER auto-submitting.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.application.services.chat_tools import ChatToolbox

scenarios("../features/rux6_campaign_chat.feature")


class _Registry:
    def ensure_enabled(self, key: str) -> None:
        return None


class _FakeCriteria:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, bool]] = []

    def edit_criteria(self, campaign_id, *, changes, confirm=False, clear_learned=False):
        self.calls.append((campaign_id, dict(changes), confirm))
        return SimpleNamespace(**changes)


class _FakeDigest:
    def __init__(self, rows=()) -> None:
        self.rows = list(rows)
        self.built: list[str] = []
        self.approved: list[str] = []
        self.declined: list[tuple[str, str]] = []

    def build_digest_payload(self, campaign_id, criteria=None) -> dict:
        self.built.append(campaign_id)
        return {"rows": list(self.rows)}

    def approve(self, application_id):
        self.approved.append(application_id)
        return SimpleNamespace(id="d1")

    def decline(self, application_id, feedback_text="", criteria_delta=None):
        if not (feedback_text or "").strip():
            raise ValueError("reason required")
        self.declined.append((application_id, feedback_text))
        return SimpleNamespace(id="d2")


@pytest.fixture
def rux6ctx() -> dict:
    return {}


@given("a campaign chat with criteria and digest tools wired")
def _wired(rux6ctx: dict) -> None:
    rux6ctx["criteria"] = _FakeCriteria()
    rux6ctx["digest"] = _FakeDigest(rows=[{"posting_id": "p1"}])
    rux6ctx["box"] = ChatToolbox(
        campaign_id="camp-rux6",
        criteria_service=rux6ctx["criteria"],
        digest_service=rux6ctx["digest"],
        tool_registry=_Registry(),
    )


@when("the assistant edits the key skills through the chat tool")
def _edit_skills(rux6ctx: dict) -> None:
    rux6ctx["reply"] = rux6ctx["box"].dispatch(
        "edit_criteria", json.dumps({"field": "keywords", "value": "Python, Go"})
    )


@then("the criteria service records the edit")
def _criteria_recorded(rux6ctx: dict) -> None:
    assert rux6ctx["criteria"].calls == [
        ("camp-rux6", {"keywords": "Python, Go"}, False)
    ]


@when("the assistant tries to change the salary floor through the chat tool")
def _edit_salary(rux6ctx: dict) -> None:
    rux6ctx["reply"] = rux6ctx["box"].dispatch(
        "edit_criteria", json.dumps({"field": "salary_floor", "value": 175000})
    )


@then("the criteria service is not touched and the reply asks for confirmation")
def _salary_held(rux6ctx: dict) -> None:
    assert rux6ctx["criteria"].calls == []
    assert "confirm" in rux6ctx["reply"].lower()


@when("the assistant re-scores through the chat tool")
def _rescore(rux6ctx: dict) -> None:
    rux6ctx["reply"] = rux6ctx["box"].dispatch("rescore", "{}")


@then("the digest is rebuilt and nothing is submitted")
def _rescored(rux6ctx: dict) -> None:
    assert rux6ctx["digest"].built == ["camp-rux6"]
    # No submit surface exists on the digest double; the reply reassures the boundary.
    assert "submit" in rux6ctx["reply"].lower()


@when("the assistant tries to discard a role with no reason")
def _discard_no_reason(rux6ctx: dict) -> None:
    rux6ctx["reply"] = rux6ctx["box"].dispatch(
        "discard_job", json.dumps({"application_id": "p1"})
    )


@then("no role is discarded and the assistant asks why")
def _discard_refused(rux6ctx: dict) -> None:
    assert rux6ctx["digest"].declined == []
    low = rux6ctx["reply"].lower()
    assert "reason" in low or "fit" in low


@when("the assistant discards a role with a reason")
def _discard_with_reason(rux6ctx: dict) -> None:
    rux6ctx["reply"] = rux6ctx["box"].dispatch(
        "discard_job",
        json.dumps({"application_id": "p1", "reason": "Not senior enough"}),
    )


@then("the role is declined with that reason for learning")
def _declined(rux6ctx: dict) -> None:
    assert rux6ctx["digest"].declined == [("p1", "Not senior enough")]
    assert "archived" in rux6ctx["reply"].lower()


@then("no offered tool can submit an application")
def _no_submit(rux6ctx: dict) -> None:
    names = {s["function"]["name"] for s in rux6ctx["box"].tool_schemas()}
    assert names  # the campaign tools ARE offered
    assert not any("submit" in n for n in names)
