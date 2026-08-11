"""Tests for ScreeningAnswerLibraryEntry entity (FR-ANSWER-1)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from dataclasses import FrozenInstanceError

from applicant.core.ids import CampaignId, ScreeningAnswerLibraryEntryId
from applicant.core.entities.screening_answer_library import (
    ScreeningAnswerLibraryEntry,
)


@pytest.fixture(autouse=True)
def _reset():
    """Prevent cross-test pollution under xdist parallel execution."""
    pass


@pytest.mark.unit
class TestScreeningAnswerLibraryEntry:
    """Unit tests for ScreeningAnswerLibraryEntry dataclass."""

    def test_minimum_required_fields(self):
        """Entity can be created with only required positional args."""
        entry_id: ScreeningAnswerLibraryEntryId = ScreeningAnswerLibraryEntryId(
            uuid4().hex
        )
        campaign_id: CampaignId = CampaignId(uuid4().hex)
        entry = ScreeningAnswerLibraryEntry(
            id=entry_id,
            campaign_id=campaign_id,
            question_key="notice_period",
            question_text="What is your notice period?",
            answer_text="Two weeks.",
        )
        assert entry.id == entry_id
        assert entry.campaign_id == campaign_id
        assert entry.question_key == "notice_period"
        assert entry.question_text == "What is your notice period?"
        assert entry.answer_text == "Two weeks."

    def test_default_essay_is_false(self):
        """When essay is not provided, it defaults to False."""
        entry = ScreeningAnswerLibraryEntry(
            id=ScreeningAnswerLibraryEntryId(uuid4().hex),
            campaign_id=CampaignId(uuid4().hex),
            question_key="motivation",
            question_text="Why do you want to work here?",
            answer_text="I admire the company culture.",
        )
        assert entry.essay is False

    def test_essay_true(self):
        """Entity can be created with essay=True."""
        entry = ScreeningAnswerLibraryEntry(
            id=ScreeningAnswerLibraryEntryId(uuid4().hex),
            campaign_id=CampaignId(uuid4().hex),
            question_key="motivation",
            question_text="Why do you want to work here?",
            answer_text="I admire the company culture and values.",
            essay=True,
        )
        assert entry.essay is True

    def test_frozen_immutability(self):
        """Altering any field raises FrozenInstanceError."""
        entry = ScreeningAnswerLibraryEntry(
            id=ScreeningAnswerLibraryEntryId(uuid4().hex),
            campaign_id=CampaignId(uuid4().hex),
            question_key="availability",
            question_text="When can you start?",
            answer_text="Immediately.",
        )
        with pytest.raises(FrozenInstanceError):
            entry.answer_text = "Next month."

    def test_equality_via_id(self):
        """Two entities with the same field values are equal."""
        entry_id = ScreeningAnswerLibraryEntryId(uuid4().hex)
        campaign_id = CampaignId(uuid4().hex)
        entry_a = ScreeningAnswerLibraryEntry(
            id=entry_id,
            campaign_id=campaign_id,
            question_key="salary",
            question_text="What are your salary expectations?",
            answer_text="100k",
        )
        entry_b = ScreeningAnswerLibraryEntry(
            id=entry_id,
            campaign_id=campaign_id,
            question_key="salary",
            question_text="What are your salary expectations?",
            answer_text="100k",
        )
        assert entry_a == entry_b

    def test_inequality_different_fields(self):
        """Entities with different fields are not equal."""
        entry_a = ScreeningAnswerLibraryEntry(
            id=ScreeningAnswerLibraryEntryId(uuid4().hex),
            campaign_id=CampaignId(uuid4().hex),
            question_key="ref1",
            question_text="Reference 1?",
            answer_text="John Doe",
        )
        entry_b = ScreeningAnswerLibraryEntry(
            id=ScreeningAnswerLibraryEntryId(uuid4().hex),
            campaign_id=CampaignId(uuid4().hex),
            question_key="ref1",
            question_text="Reference 1?",
            answer_text="Jane Smith",
        )
        assert entry_a != entry_b

    def test_all_fields_round_trip(self):
        """All field values round-trip correctly after construction."""
        entry_id = ScreeningAnswerLibraryEntryId(uuid4().hex)
        campaign_id = CampaignId(uuid4().hex)
        entry = ScreeningAnswerLibraryEntry(
            id=entry_id,
            campaign_id=campaign_id,
            question_key="relocate",
            question_text="Are you willing to relocate?",
            answer_text="Yes, within 2 months.",
            essay=True,
        )
        assert entry.id == entry_id
        assert entry.campaign_id == campaign_id
        assert entry.question_key == "relocate"
        assert entry.question_text == "Are you willing to relocate?"
        assert entry.answer_text == "Yes, within 2 months."
        assert entry.essay is True

