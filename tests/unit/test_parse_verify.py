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
    """Returns scripted responses in order; records every (start_tier, max_tokens).

    A ``dict`` response is delivered via ``LLMResult.structured`` (the adapter's
    parsed-JSON path when ``json_schema`` is given) with garbage text, proving the
    layer prefers the structured payload; a ``str`` is plain text; an ``Exception``
    is raised.
    """

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
        if isinstance(nxt, dict):
            return LLMResult(
                text="<thinking noise, not json>",
                tier=start_tier,
                model=f"fake-t{start_tier}",
                structured=nxt,
            )
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
    # The draft's weak/junk entries ("DENVER, CO" with no company) were pruned by
    # the correction and must NOT be resurrected by the omission guard.
    assert v["restored_from_draft"] == []
    assert all("DENVER" not in w.title for w in out.work_history)
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
def test_structured_payload_is_preferred_over_text():
    """When the adapter already parsed the JSON (LLMResult.structured, set on
    json_schema calls), the layer uses it directly — a text field full of
    reasoning noise cannot sink a good structured answer."""
    llm = ScriptedLLM([GOOD_OUT])  # dict -> delivered via .structured, text is noise
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")
    v = _verify_of(out)
    assert v["verified"] is True
    assert v["escalated"] is False
    assert out.work_history[0].company == "Initech"


@pytest.mark.unit
def test_decoy_object_before_the_real_json_is_skipped():
    """A leading decoy object / brace-bearing prose must not sink the response:
    candidates are scanned in order and the shape check skips non-matching ones
    (the review finding on greedy first-{...}-to-last-} extraction)."""
    noisy = (
        'Plan: {"draft": true} and note {"text": "a } brace in a string"} — result:\n'
        + json.dumps(GOOD_OUT)
    )
    llm = ScriptedLLM([noisy])
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")
    v = _verify_of(out)
    assert v["verified"] is True
    assert v["escalated"] is False  # solved at tier 1 — no wasted escalation
    assert out.work_history[0].title == "Senior Platform Engineer"


@pytest.mark.unit
def test_recombined_source_tokens_are_rejected_for_non_dates():
    """The grounding fallback is DATE-ONLY (the review finding): a phrase whose
    tokens all exist somewhere in the source but never contiguously ("Data" +
    "Engineer" from one entry + "Initech" from another) must be dropped, while a
    re-formatted date ("Feb 2018" ~ source "Feb 2018", "Jun 2021" ~ "June 2021")
    still passes."""
    tampered = json.loads(json.dumps(GOOD_OUT))
    tampered["work_history"][0]["company"] = "Data Engineer Initech"  # recombination
    tampered["work_history"][0]["start_date"] = "Jun 2021"  # reformatted date: OK
    llm = ScriptedLLM([json.dumps(tampered)])
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")

    assert out.work_history[0].company == ""  # recombined phrase refused
    assert out.work_history[0].start_date == "Jun 2021"  # date leniency intact
    dropped = " ".join(_verify_of(out)["unsourced_dropped"])
    assert "Data Engineer Initech" in dropped


@pytest.mark.unit
def test_boundary_spanning_phrase_is_rejected():
    """Grounding is window-scoped, never whole-document-flattened: a phrase that
    only exists because two different sections happen to be adjacent after
    collapsing the entire document ("Phoenix, AZ" from the contact line +
    "EXPERIENCE" the section header, separated by a blank line) must be dropped
    even though the flattened document contains it contiguously."""
    tampered = json.loads(json.dumps(GOOD_OUT))
    tampered["skills"].append("Phoenix AZ Experience")  # crosses a blank-line boundary
    llm = ScriptedLLM([json.dumps(tampered)])
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")

    assert "Phoenix AZ Experience" not in out.skills
    assert "Phoenix AZ Experience" in " ".join(_verify_of(out)["unsourced_dropped"])


@pytest.mark.unit
def test_mixed_source_date_is_rejected():
    """The date leniency is window-scoped too: "Jun 18" must NOT ground by taking
    "Jun" from one role's date line (June 2021) and "18" from another's (Feb
    2018) — all tokens must come from the same local window, and numeric tokens
    must match a window token exactly."""
    tampered = json.loads(json.dumps(GOOD_OUT))
    tampered["work_history"][0]["start_date"] = "Jun 18"  # tokens from two date lines
    llm = ScriptedLLM([json.dumps(tampered)])
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")

    assert out.work_history[0].start_date == ""  # refused, surfaced as dropped
    assert "Jun 18" in " ".join(_verify_of(out)["unsourced_dropped"])
    # The same-window reformat stays accepted (proven in the recombination test).


@pytest.mark.unit
def test_omitted_strong_entries_are_restored_not_silently_erased():
    """The silent-omission guard: a shape-valid, confident response that OMITS a
    strong deterministic entry (both title and company; a degree; a parsed skill)
    must not erase it — the entry is restored and the restoration is surfaced in
    the verify metadata. Weak/junk draft entries stay prunable (previous test)."""
    strong_draft = ParsedResume(
        full_name="Jane Engineer",
        email="jane@example.com",
        phone="555",
        work_history=(
            WorkHistoryEntry(title="Senior Platform Engineer", company="Initech"),
            WorkHistoryEntry(title="Data Engineer", company="Hooli",
                             start_date="Feb 2018", end_date="May 2021"),
        ),
        education=(
            EducationEntry(degree="BS Computer Science", institution="State University"),
        ),
        skills=("Python", "SQL"),
        raw_text=SOURCE,
    )
    omitting = json.loads(json.dumps(GOOD_OUT))
    omitting["work_history"] = [omitting["work_history"][0]]  # drops the Hooli role
    omitting["education"] = [omitting["education"][0]]  # drops the BS degree
    omitting["skills"] = ["Python", "Terraform"]  # drops SQL

    llm = ScriptedLLM([json.dumps(omitting)])
    out = LLMVerifiedResumeParser(FakeInner(strong_draft), llm).parse("r.pdf")

    v = _verify_of(out)
    assert v["verified"] is True
    assert any(w.company == "Hooli" for w in out.work_history), "strong role restored"
    assert any("Computer Science" in e.degree for e in out.education), "degree restored"
    assert "SQL" in out.skills, "parsed skill unioned back"
    joined = " ".join(v["restored_from_draft"])
    assert "Hooli" in joined and "BS Computer Science" in joined and "SQL" in joined


@pytest.mark.unit
def test_omitting_one_of_two_roles_at_the_same_company_still_restores_it():
    """Entry-scoped coverage: a title or company appearing in ANOTHER kept entry
    must not suppress restoration — only a single corrected entry carrying BOTH
    identity fields accounts for a draft role (two roles at one company are two
    entries; omitting one is still an omission)."""
    source = (
        "Jane Engineer\n\n"
        "EXPERIENCE\n"
        "Staff Engineer | Initech\n"
        "June 2021 - Present\n\n"
        "Senior Engineer | Initech\n"
        "Feb 2018 - May 2021\n"
    )
    draft = ParsedResume(
        full_name="Jane Engineer",
        work_history=(
            WorkHistoryEntry(title="Staff Engineer", company="Initech"),
            WorkHistoryEntry(title="Senior Engineer", company="Initech"),
        ),
        raw_text=source,
    )
    out = {
        "full_name": "Jane Engineer",
        "work_history": [{"title": "Staff Engineer", "company": "Initech"}],
        "education": [],
        "skills": [],
        "confidence": {"work_history": 0.95},
        "corrections": [],
    }
    parsed = LLMVerifiedResumeParser(FakeInner(draft), ScriptedLLM([out])).parse("r.pdf")
    v = _verify_of(parsed)
    assert v["verified"] is True
    titles = [w.title for w in parsed.work_history]
    assert titles.count("Staff Engineer") == 1, "kept entry not duplicated"
    assert "Senior Engineer" in titles, "same-company omitted role must be restored"
    assert any("Senior Engineer" in r for r in v["restored_from_draft"])


@pytest.mark.unit
def test_renamed_company_in_one_entry_suppresses_duplicate_restoration():
    """A correction that keeps the role under a shortened company name accounts
    for the draft entry (shared 2+-token run inside the SAME corrected entry),
    so no duplicate is restored."""
    source = (
        "Jane Engineer\n\n"
        "EXPERIENCE\n"
        "Lead Engineer | Wells Fargo (via TEKsystems)\n"
        "June 2021 - Present\n"
    )
    draft = ParsedResume(
        full_name="Jane Engineer",
        work_history=(
            WorkHistoryEntry(title="Lead Engineer", company="Wells Fargo (via TEKsystems)"),
        ),
        raw_text=source,
    )
    out = {
        "full_name": "Jane Engineer",
        "work_history": [{"title": "Lead Engineer", "company": "Wells Fargo"}],
        "education": [],
        "skills": [],
        "confidence": {"work_history": 0.9},
        "corrections": ["normalized company"],
    }
    parsed = LLMVerifiedResumeParser(FakeInner(draft), ScriptedLLM([out])).parse("r.pdf")
    v = _verify_of(parsed)
    assert v["verified"] is True
    assert len(parsed.work_history) == 1, "renamed entry must not restore a duplicate"
    assert v["restored_from_draft"] == []


@pytest.mark.unit
def test_education_line_misparsed_as_a_role_is_not_restored_into_work_history():
    """Section-heading gate: the deterministic parser sometimes files an
    education-section line as a strong-looking job (title+company, no bullets).
    When the correction drops it and nothing accounts for it, it must NOT be
    resurrected as a role — its source line sits under a non-work heading, so
    it is prunable junk, not a lost job."""
    draft = ParsedResume(
        full_name="Jane Engineer",
        work_history=(
            WorkHistoryEntry(title="Senior Platform Engineer", company="Initech"),
            # "BS Computer Science, State University" split into a fake job —
            # its source line sits under EDUCATION & CERTIFICATIONS.
            WorkHistoryEntry(title="BS Computer Science", company="State University"),
        ),
        education=(),
        skills=("Python",),
        raw_text=SOURCE,
    )
    out = json.loads(json.dumps(GOOD_OUT))
    out["education"] = [out["education"][0]]  # keeps CKA, drops the BS entry entirely
    parsed = LLMVerifiedResumeParser(FakeInner(draft), ScriptedLLM([out])).parse("r.pdf")
    v = _verify_of(parsed)
    assert v["verified"] is True
    assert all("Computer Science" not in w.title for w in parsed.work_history), (
        "an education line must not resurrect as a job"
    )
    assert v["restored_from_draft"] == []
    # The genuine role kept by the correction is intact, once.
    assert [w.title for w in parsed.work_history] == ["Senior Platform Engineer", "Data Engineer"]


@pytest.mark.unit
def test_non_finite_or_out_of_range_confidence_is_malformed_not_verified():
    """NaN slips past the floor comparison (NaN < x is False) and 1.5 is not a
    probability: both are untrustworthy self-reports — treated as malformed
    output (escalate once, then honest deterministic fallback)."""
    bad = json.loads(json.dumps(GOOD_OUT))
    bad["confidence"] = {"contact": float("nan")}
    worse = json.loads(json.dumps(GOOD_OUT))
    worse["confidence"] = {"contact": 1.5}
    llm = ScriptedLLM([bad, worse])
    out = LLMVerifiedResumeParser(FakeInner(), llm).parse("r.pdf")
    v = _verify_of(out)
    assert v["verified"] is False
    assert v["reason"] == "malformed_output"
    assert len(llm.calls) == 2 and llm.calls[1]["start_tier"] == 2
    assert out.work_history == DRAFT.work_history


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
