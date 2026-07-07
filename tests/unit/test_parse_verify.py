"""P1-1a — the LLM parse-verify layer over the deterministic résumé parse.

Hermetic: a fake inner parser supplies the deterministic DRAFT and a scripted
fake LLM supplies verify responses (recorded fixtures — no live model, per the
story's DoD). The live tier study that sized this layer is
``docs/studies/2026-07-07-parse-verify-tier-study.md``.

Contract under test (the slotting contract):
* a good verify response corrects mis-slotted fields and records confidence,
  corrections, model/tier in ``extra["verify"]``;
* low confidence or malformed output escalates ONE tier, and only once;
* every failure path (no model, unconfigured ladder, ladder error, still-
  malformed) returns the deterministic parse unchanged with an honest
  ``verified: False`` + reason — ingest never breaks, and never silently
  pretends the parse was checked (H2);
* grounding: a corrected value that does not trace to the source text is
  DROPPED and counted — re-filing never introduces facts (P1-13 adjacent).
"""

from __future__ import annotations

import json

import pytest

from applicant.adapters.resume_parser.llm_verify import LLMVerifiedResumeParser
from applicant.ports.driven.llm import (
    LLMLadderExhausted,
    LLMNotConfigured,
    LLMResult,
)
from applicant.ports.driven.resume_parser import (
    EducationEntry,
    ParsedResume,
    WorkHistoryEntry,
)

SOURCE = (
    "Jane Engineer\n"
    "jane@example.com | (555) 012-3456 | Phoenix, AZ\n\n"
    "EXPERIENCE\n"
    "Senior Platform Engineer | Initech\n"
    "PHOENIX, AZ | June 2021 - Present\n"
    "Cut deploy time 40% by rebuilding the CI pipeline.\n\n"
    "Data Engineer | Hooli\n"
    "DENVER, CO | Feb 2018 - May 2021\n\n"
    "EDUCATION & CERTIFICATIONS\n"
    "Certified Kubernetes Administrator (CKA) - 2022\n"
    "BS Computer Science, State University - 2017\n\n"
    "SKILLS\n"
    "Python, SQL, Terraform, Airflow\n"
)

# The deterministic draft mis-slots badly (the real-world failure this layer fixes):
# the first role's title swallowed the company, the second role is a location line,
# education missed the certification, skills missed Terraform/Airflow.
DRAFT = ParsedResume(
    full_name="Jane Engineer",
    email="jane@example.com",
    phone="555) 012-3456",
    work_history=(
        WorkHistoryEntry(title="Senior Platform Engineer | Initech", company=""),
        WorkHistoryEntry(title="DENVER, CO", company=""),
    ),
    education=(EducationEntry(degree="BS Computer Science", institution="State University"),),
    skills=("Python", "SQL"),
    raw_text=SOURCE,
)

GOOD_OUT = {
    "full_name": "Jane Engineer",
    "email": "jane@example.com",
    "phone": "(555) 012-3456",
    "work_history": [
        {
            "title": "Senior Platform Engineer",
            "company": "Initech",
            "location": "Phoenix, AZ",
            "start_date": "June 2021",
            "end_date": "Present",
            "achievements": ["Cut deploy time 40% by rebuilding the CI pipeline."],
        },
        {
            "title": "Data Engineer",
            "company": "Hooli",
            "location": "Denver, CO",
            "start_date": "Feb 2018",
            "end_date": "May 2021",
        },
    ],
    "education": [
        {"name": "Certified Kubernetes Administrator (CKA)", "issuer": "", "year": "2022"},
        {"name": "BS Computer Science", "issuer": "State University", "year": "2017"},
    ],
    "skills": ["Python", "SQL", "Terraform", "Airflow"],
    "confidence": {"contact": 1.0, "work_history": 0.95, "education": 0.9, "skills": 0.95},
    "corrections": ["split title|company", "recovered second role", "added certification"],
}


class FakeInner:
    def __init__(self, parsed: ParsedResume = DRAFT) -> None:
        self._parsed = parsed
        self.calls: list[str] = []

    def parse(self, document_path: str) -> ParsedResume:
        self.calls.append(document_path)
        return self._parsed


class ScriptedLLM:
    """Returns scripted responses in order; records every (start_tier, max_tokens)."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.calls.append(
            {"start_tier": start_tier, "max_tokens": max_tokens, "n_messages": len(messages)}
        )
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResult(text=str(nxt), tier=start_tier, model=f"fake-t{start_tier}")


def _verify_of(parsed: ParsedResume) -> dict:
    return parsed.extra["verify"]


@pytest.mark.unit
def test_good_response_corrects_the_draft_and_records_metadata():
    llm = ScriptedLLM([json.dumps(GOOD_OUT)])
    parser = LLMVerifiedResumeParser(FakeInner(), llm)
    out = parser.parse("resume.pdf")

    # Mis-slotted draft fixed: split title|company, junk location entry replaced.
    assert out.work_history[0].title == "Senior Platform Engineer"
    assert out.work_history[0].company == "Initech"
    assert out.work_history[0].achievements  # bullet preserved under its role
    assert out.work_history[1].company == "Hooli"
    # Missed certification recovered alongside the degree.
    assert any("Kubernetes" in e.degree for e in out.education)
    # Missed skills recovered.
    assert "Terraform" in out.skills and "Airflow" in out.skills
    v = _verify_of(out)
    assert v["verified"] is True
    assert v["escalated"] is False
    assert v["confidence"]["work_history"] == 0.95
    assert v["corrections"]
    assert v["model"] == "fake-t1" and v["tier"] == 1
    # One call, at the ladder floor, with the generous budget (the study's trap).
    assert llm.calls == [{"start_tier": 1, "max_tokens": 6000, "n_messages": 2}]


@pytest.mark.unit
def test_low_confidence_escalates_exactly_one_tier():
    low = dict(GOOD_OUT, confidence={"contact": 1.0, "work_history": 0.5})
    llm = ScriptedLLM([json.dumps(low), json.dumps(GOOD_OUT)])
    parser = LLMVerifiedResumeParser(FakeInner(), llm)
    out = parser.parse("resume.pdf")
    assert [c["start_tier"] for c in llm.calls] == [1, 2]
    v = _verify_of(out)
    assert v["verified"] is True
    assert v["escalated"] is True
    assert v["attempts"][0]["problem"] == "low_confidence"
    assert v["tier"] == 2


@pytest.mark.unit
def test_malformed_then_malformed_falls_back_to_deterministic():
    llm = ScriptedLLM(["I could not help thinking about it...", "{not json"])
    parser = LLMVerifiedResumeParser(FakeInner(), llm)
    out = parser.parse("resume.pdf")
    # Exactly two attempts (floor + one escalation), then an honest fallback.
    assert [c["start_tier"] for c in llm.calls] == [1, 2]
    assert out.work_history == DRAFT.work_history  # deterministic parse unchanged
    v = _verify_of(out)
    assert v["verified"] is False
    assert v["reason"] == "malformed_output"
    assert len(v["attempts"]) == 2


@pytest.mark.unit
def test_no_model_and_disabled_paths_mark_unverified():
    out_no_model = LLMVerifiedResumeParser(FakeInner(), None).parse("r.pdf")
    assert _verify_of(out_no_model) == {"verified": False, "reason": "no_model"}

    out_disabled = LLMVerifiedResumeParser(
        FakeInner(), ScriptedLLM([]), enabled=False
    ).parse("r.pdf")
    assert _verify_of(out_disabled) == {"verified": False, "reason": "disabled"}


@pytest.mark.unit
def test_ladder_errors_degrade_honestly_not_fatally():
    unconfigured = LLMVerifiedResumeParser(
        FakeInner(), ScriptedLLM([LLMNotConfigured("no ladder")])
    ).parse("r.pdf")
    assert _verify_of(unconfigured)["reason"] == "no_model"

    exhausted = LLMVerifiedResumeParser(
        FakeInner(), ScriptedLLM([LLMLadderExhausted("all tiers failed")])
    ).parse("r.pdf")
    assert _verify_of(exhausted)["reason"] == "model_error"
    # The deterministic parse still came through in both cases.
    assert exhausted.full_name == DRAFT.full_name


@pytest.mark.unit
def test_unsourced_values_are_dropped_and_counted():
    """The slotting contract: re-filing never introduces facts. A hallucinated
    employer that is nowhere in the source is dropped (entry survives on its
    sourced fields) and the drop is visible in the verify metadata."""
    tampered = json.loads(json.dumps(GOOD_OUT))
    tampered["work_history"][0]["company"] = "Globex Corporation"  # not in SOURCE
    tampered["skills"].append("Kubernetes")  # appears in SOURCE (cert line) -> kept
    tampered["skills"].append("Snowflake")  # nowhere in SOURCE -> dropped
    llm = ScriptedLLM([json.dumps(tampered)])
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")

    assert out.work_history[0].company == ""  # hallucinated employer refused
    assert out.work_history[0].title == "Senior Platform Engineer"  # sourced fields kept
    assert "Kubernetes" in out.skills
    assert "Snowflake" not in out.skills
    dropped = " ".join(_verify_of(out)["unsourced_dropped"])
    assert "Globex" in dropped and "Snowflake" in dropped


@pytest.mark.unit
def test_late_binding_enables_verification_after_construction():
    """Container wiring order: the parser exists before the ladder; bind_llm()
    upgrades it in place (both onboarding services share the instance)."""
    parser = LLMVerifiedResumeParser(FakeInner())
    assert _verify_of(parser.parse("r.pdf"))["reason"] == "no_model"
    parser.bind_llm(ScriptedLLM([json.dumps(GOOD_OUT)]))
    assert _verify_of(parser.parse("r.pdf"))["verified"] is True


@pytest.mark.unit
def test_ingest_records_verify_block_in_the_intake(tmp_path):
    """Reachability of the metadata: ingest_base_resume persists the verify
    outcome into the base-résumé intake record the review UI reads."""
    from applicant.adapters.storage.in_memory import InMemoryStorage
    from applicant.application.services.onboarding_service import OnboardingService
    from applicant.core.entities.campaign import Campaign
    from applicant.core.ids import CampaignId, new_id

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="dogfood"))
    storage.commit()

    resume = tmp_path / "resume.txt"
    resume.write_text(SOURCE, encoding="utf-8")

    class _Cfg:
        def __init__(self):
            self._d = {}

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value

    parser = LLMVerifiedResumeParser(FakeInner(), ScriptedLLM([json.dumps(GOOD_OUT)]))
    svc = OnboardingService(storage=storage, config_store=_Cfg(), resume_parser=parser)
    svc.ingest_base_resume(str(cid), str(resume))

    state = svc.get_state(str(cid))
    block = state.intake["base_resume"]
    assert block["verify"]["verified"] is True
    assert block["verify"]["confidence"]["work_history"] == 0.95
