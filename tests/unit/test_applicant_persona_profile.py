"""Applicant persona profile — AZ2-5 unified chat, slice A (D14/D19).

Asserts the fork profile overlay exists and carries the required identity and
routing elements:

* Identity (D14): the persona is named "Applicant", warm-professional,
  job-search-native AND generally capable, with an H5-calibrated voice that
  does not overclaim.
* Consequential job actions (DoD): applying/submitting/saving jobs route
  through the engine and respect its apply-readiness gate.
* Memory routing (D19): "remember this" facts are classified by content
  (job-search facts -> engine mind via curation gate; general preferences ->
  A0 memory) and the user is always told WHERE each item landed.
* Status honesty (H1): job/application status answers are projections of
  engine data only, never synthesized or guessed.
"""

from __future__ import annotations

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PROFILE = _REPO_ROOT / "a0-applicant" / "agents" / "applicant" / "prompts" / "agent.system.main.specifics.md"


def test_applicant_persona_profile_exists() -> None:
    """Guard: the overlay must exist so the content assertions can't silently pass."""
    assert _PROFILE.exists(), "a0-applicant/agents/applicant/prompts/agent.system.main.specifics.md not found"


def test_applicant_persona_identity() -> None:
    """D14: persona is named Applicant with a warm-professional, H5-calibrated identity."""
    text = _PROFILE.read_text(encoding="utf-8")
    assert "Applicant" in text
    assert "warm-professional" in text
    assert "job-search-native" in text
    assert "generally capable" in text
    assert "overclaim" in text


def test_applicant_persona_engine_routing() -> None:
    """DoD: consequential job actions route through the engine with apply-readiness gating."""
    text = _PROFILE.read_text(encoding="utf-8")
    assert "Applying, submitting, or saving a job always goes through the engine capability" in text
    assert "apply_ready" in text
    assert "apply_missing" in text
    assert "Never fabricate or claim a submission that did not go through the engine" in text


def test_applicant_persona_memory_routing_d19() -> None:
    """D19: memory routing classifies by content and names the destination for each item."""
    text = _PROFILE.read_text(encoding="utf-8")
    assert "engine mind, through its curation gate" in text
    assert "A0 memory immediately" in text
    assert "WHERE each item landed" in text


def test_applicant_persona_status_honesty_h1() -> None:
    """H1: job/application status answers are projections of engine data only."""
    text = _PROFILE.read_text(encoding="utf-8")
    assert "projections of engine data ONLY" in text
    assert "If the data isn't available, say so plainly" in text
