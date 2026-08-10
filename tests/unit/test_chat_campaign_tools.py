"""RUX-6 — campaign-chat gated action tools (edit-criteria / re-score / draft / discard).

The "Ask anything to start a new chat" box talks to the campaign agent (ChatService),
which can CHOOSE to take actions through :class:`ChatToolbox`. RUX-6's guardrails:

* every side-effect is CAPABILITY-GATED — a tool is only offered when its backing
  service is wired AND the FR-UI-4 "chat" toggle is on, and it is refused at dispatch
  when the toggle is off;
* every action is REVERSIBLE + TRANSPARENT — an integral criteria change is never
  silently committed (it is held for the user's confirmation, FR-FB-3); a discard is
  archived-with-reason (reversible) and feeds negative learning (FR-FB-1);
* every action is AUDITED — an optional audit sink receives each successful action;
* the agent NEVER auto-submits an application — no tool submits, and draft only
  prepares tailored materials held at the review line.

These tests construct :class:`ChatToolbox` directly (like ``test_chat_job_tools``),
so they are independent of the ChatService wiring the Integrate step performs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from applicant.application.services.chat_tools import ChatToolbox


# --- parallel-safety fixture (convention for xdist) -----------------------
@pytest.fixture(autouse=True)
def _no_cache() -> None:
    yield


class _Registry:
    """FR-UI-4 registry double: ``ensure_enabled`` raises when the toggle is off."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def ensure_enabled(self, key: str) -> None:
        if not self.enabled:
            raise RuntimeError(f"tool {key} is disabled")


class _FakeCriteria:
    """Records edit_criteria calls (never really persists)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, bool]] = []

    def edit_criteria(self, campaign_id, *, changes, confirm=False, clear_learned=False):
        self.calls.append((campaign_id, dict(changes), confirm))
        return SimpleNamespace(**changes)


class _FakeDigest:
    """Records approve/decline/build calls; mirrors DigestService's contract."""

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
        return SimpleNamespace(id="dec-approve")

    def decline(self, application_id, feedback_text="", criteria_delta=None):
        # DigestService.decline rejects a blank reason (FR-FB-1); mirror that so a
        # missing-reason path can never reach a real decline undetected.
        if not (feedback_text or "").strip():
            raise ValueError("decline feedback is required")
        self.declined.append((application_id, feedback_text))
        return SimpleNamespace(id="dec-decline")


def _toolbox(
    *,
    criteria_service=None,
    digest_service=None,
    audit=None,
    registry: _Registry | None = None,
    campaign_id="camp-6",
) -> ChatToolbox:
    return ChatToolbox(
        campaign_id=campaign_id,
        criteria_service=criteria_service,
        digest_service=digest_service,
        audit=audit,
        tool_registry=registry or _Registry(),
    )


# --- capability gating: tools are only offered when their service is wired ---
class TestToolsCapabilityGated:
    @pytest.mark.unit
    def test_edit_criteria_offered_only_with_criteria_service(self) -> None:
        with_crit = _toolbox(criteria_service=_FakeCriteria())
        without = _toolbox(criteria_service=None)
        assert "edit_criteria" in {s["function"]["name"] for s in with_crit.tool_schemas()}
        assert "edit_criteria" not in {s["function"]["name"] for s in without.tool_schemas()}

    @pytest.mark.unit
    def test_digest_tools_offered_only_with_digest_service(self) -> None:
        tb = _toolbox(digest_service=_FakeDigest())
        names = {s["function"]["name"] for s in tb.tool_schemas()}
        assert {"rescore", "draft_application", "discard_job"} <= names
        none = {s["function"]["name"] for s in _toolbox(digest_service=None).tool_schemas()}
        assert not ({"rescore", "draft_application", "discard_job"} & none)

    @pytest.mark.unit
    def test_no_tool_submits_an_application(self) -> None:
        """The never-auto-submit safety line: no tool named/adjacent to submit exists."""
        tb = _toolbox(criteria_service=_FakeCriteria(), digest_service=_FakeDigest())
        names = {s["function"]["name"] for s in tb.tool_schemas()}
        assert not any("submit" in n for n in names)


# --- edit_criteria: non-integral applies; integral is held for confirmation ---
class TestEditCriteria:
    @pytest.mark.unit
    def test_non_integral_field_applies_directly(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit)
        out = tb.dispatch("edit_criteria", json.dumps({"field": "keywords", "value": "Python, Django"}))
        assert crit.calls == [("camp-6", {"keywords": "Python, Django"}, False)]
        assert "updated" in out.lower()

    @pytest.mark.unit
    def test_work_modes_apply_directly(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit)
        tb.dispatch("edit_criteria", json.dumps({"field": "work_modes", "value": "remote"}))
        assert crit.calls and crit.calls[0][1] == {"work_modes": "remote"}

    @pytest.mark.unit
    def test_integral_salary_floor_is_not_silently_applied(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit)
        out = tb.dispatch("edit_criteria", json.dumps({"field": "salary_floor", "value": 150000}))
        # NEVER self-committed — held for the user's confirmation (FR-FB-3).
        assert crit.calls == []
        assert "confirm" in out.lower()

    @pytest.mark.unit
    def test_integral_titles_are_not_silently_applied(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit)
        out = tb.dispatch("edit_criteria", json.dumps({"field": "titles", "value": "Staff Engineer"}))
        assert crit.calls == []
        assert "confirm" in out.lower()

    @pytest.mark.unit
    def test_unknown_field_is_refused(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit)
        out = tb.dispatch("edit_criteria", json.dumps({"field": "favorite_color", "value": "blue"}))
        assert crit.calls == []
        assert isinstance(out, str) and out

    @pytest.mark.unit
    def test_missing_value_is_refused(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit)
        out = tb.dispatch("edit_criteria", json.dumps({"field": "keywords"}))
        assert crit.calls == []
        assert "value" in out.lower()


# --- rescore: re-scores against current criteria; never submits ------------
class TestRescore:
    @pytest.mark.unit
    def test_rescore_rebuilds_and_reports_count(self) -> None:
        digest = _FakeDigest(rows=[{"posting_id": "p1"}, {"posting_id": "p2"}])
        tb = _toolbox(digest_service=digest)
        out = tb.dispatch("rescore", "{}")
        assert digest.built == ["camp-6"]
        assert "2" in out

    @pytest.mark.unit
    def test_rescore_empty_is_truthful(self) -> None:
        digest = _FakeDigest(rows=[])
        tb = _toolbox(digest_service=digest)
        out = tb.dispatch("rescore", "{}")
        assert digest.built == ["camp-6"]
        assert isinstance(out, str) and out


# --- draft_application: prepares materials, never submits ------------------
class TestDraftApplication:
    @pytest.mark.unit
    def test_draft_calls_approve(self) -> None:
        digest = _FakeDigest()
        tb = _toolbox(digest_service=digest)
        out = tb.dispatch("draft_application", json.dumps({"application_id": "p42"}))
        assert digest.approved == ["p42"]
        # Reassures the never-auto-submit boundary.
        assert "submit" in out.lower()

    @pytest.mark.unit
    def test_draft_missing_id_is_refused(self) -> None:
        digest = _FakeDigest()
        tb = _toolbox(digest_service=digest)
        out = tb.dispatch("draft_application", "{}")
        assert digest.approved == []
        assert isinstance(out, str) and out


# --- discard_job: reason required; archived + reversible + feeds learning ---
class TestDiscardJob:
    @pytest.mark.unit
    def test_discard_requires_a_reason(self) -> None:
        digest = _FakeDigest()
        tb = _toolbox(digest_service=digest)
        out = tb.dispatch("discard_job", json.dumps({"application_id": "p9"}))
        # FR-FB-1: no reason => nothing declined.
        assert digest.declined == []
        assert "reason" in out.lower() or "fit" in out.lower()

    @pytest.mark.unit
    def test_discard_with_reason_declines(self) -> None:
        digest = _FakeDigest()
        tb = _toolbox(digest_service=digest)
        out = tb.dispatch(
            "discard_job",
            json.dumps({"application_id": "p9", "reason": "Too junior for me"}),
        )
        assert digest.declined == [("p9", "Too junior for me")]
        assert "archived" in out.lower() or "discard" in out.lower()


# --- FR-UI-4: a disabled chat toggle refuses at dispatch ------------------
class TestRegistryGate:
    @pytest.mark.unit
    def test_disabled_registry_refuses_edit_criteria(self) -> None:
        crit = _FakeCriteria()
        tb = _toolbox(criteria_service=crit, registry=_Registry(enabled=False))
        out = tb.dispatch("edit_criteria", json.dumps({"field": "keywords", "value": "Go"}))
        assert crit.calls == []
        assert "turned off" in out.lower()

    @pytest.mark.unit
    def test_disabled_registry_hides_all_new_tools(self) -> None:
        tb = _toolbox(
            criteria_service=_FakeCriteria(),
            digest_service=_FakeDigest(),
            registry=_Registry(enabled=False),
        )
        names = {s["function"]["name"] for s in tb.tool_schemas()}
        assert not ({"edit_criteria", "rescore", "draft_application", "discard_job"} & names)


# --- audit: every successful gated action leaves a trail -------------------
class TestAudit:
    @pytest.mark.unit
    def test_successful_actions_hit_the_audit_sink(self) -> None:
        events: list[tuple[str, dict]] = []
        crit = _FakeCriteria()
        digest = _FakeDigest(rows=[{"posting_id": "p1"}])
        tb = _toolbox(
            criteria_service=crit,
            digest_service=digest,
            audit=lambda action, detail: events.append((action, detail)),
        )
        tb.dispatch("edit_criteria", json.dumps({"field": "keywords", "value": "Rust"}))
        tb.dispatch("rescore", "{}")
        tb.dispatch("draft_application", json.dumps({"application_id": "p1"}))
        tb.dispatch("discard_job", json.dumps({"application_id": "p2", "reason": "no"}))
        actions = [a for a, _ in events]
        assert actions == ["edit_criteria", "rescore", "draft_application", "discard_job"]
        # Integral proposal is also audited (transparency) but never applies.
        tb.dispatch("edit_criteria", json.dumps({"field": "salary_floor", "value": 200000}))
        assert any(a == "edit_criteria_proposed" for a, _ in events)

    @pytest.mark.unit
    def test_failed_action_does_not_audit_success(self) -> None:
        events: list[tuple[str, dict]] = []
        digest = _FakeDigest()
        tb = _toolbox(
            digest_service=digest,
            audit=lambda action, detail: events.append((action, detail)),
        )
        tb.dispatch("discard_job", json.dumps({"application_id": "p9"}))  # no reason
        assert events == []
