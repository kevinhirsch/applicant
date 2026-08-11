"""Regression: screening-answer library upsert must key on (campaign_id, question_key).

Before the fix, ``ScreeningAnswerLibraryRepo.upsert`` used a blind ``merge()`` keyed on
``id``. Each call builds a fresh entry id, so the second same-question write staged an
INSERT and the unique constraint ``uq_screening_answer_library_campaign_key`` only fired
at the NEXT unrelated commit -- leaving the shared SQLAlchemy session in an aborted state
(session poisoning). This uses the REAL SQL repo (SQLite) because the bug does not
reproduce on InMemoryStorage.
"""

from __future__ import annotations

import tempfile
from uuid import uuid4

import pytest

from applicant.adapters.storage.models import Base
from applicant.adapters.storage.repositories import SqlAlchemyStorage
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.screening_answer_library import ScreeningAnswerLibraryEntry
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    ScreeningAnswerLibraryEntryId,
)


@pytest.fixture(autouse=True)
def _reset():
    """Prevent cross-test pollution under xdist parallel execution."""
    pass


@pytest.fixture()
def _sqlite_storage():
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    storage = SqlAlchemyStorage(session)
    try:
        yield storage, session, engine
    finally:
        session.close()
        engine.dispose()


def _seed_campaign(storage, cid):
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()


def _entry(cid, question_key, question_text, answer_text, *, essay=False):
    return ScreeningAnswerLibraryEntry(
        id=ScreeningAnswerLibraryEntryId(uuid4().hex),
        campaign_id=cid,
        question_key=question_key,
        question_text=question_text,
        answer_text=answer_text,
        essay=essay,
    )


@pytest.mark.unit
class TestScreeningAnswerLibraryUpsertDupe:
    def test_duplicate_question_updates_instead_of_duplicating(self, _sqlite_storage):
        """Two same-question writes across applications must yield exactly ONE entry."""
        storage, session, engine = _sqlite_storage
        cid = CampaignId(uuid4().hex)
        _seed_campaign(storage, cid)
        key = "why_do_you_want_to_work_here"

        storage.screening_answer_library.upsert(
            _entry(cid, key, "Why do you want to work here?", "First answer.", essay=True)
        )
        storage.screening_answer_library.upsert(
            _entry(cid, key, "Why do you want to work here?", "Updated answer.", essay=True)
        )
        storage.commit()

        rows = storage.screening_answer_library.list_for_campaign(cid)
        assert len(rows) == 1
        assert rows[0].question_text == "Why do you want to work here?"
        assert rows[0].answer_text == "Updated answer."

    def test_unrelated_commit_succeeds_after_dupe_upsert(self, _sqlite_storage):
        """The session must not be poisoned by a duplicate-question upsert."""
        storage, session, engine = _sqlite_storage
        cid = CampaignId(uuid4().hex)
        _seed_campaign(storage, cid)
        key = "notice_period"

        storage.screening_answer_library.upsert(
            _entry(cid, key, "What is your notice period?", "Two weeks.")
        )
        storage.screening_answer_library.upsert(
            _entry(cid, key, "What is your notice period?", "One month.")
        )

        # An unrelated document write + commit in the same session must succeed.
        storage.documents.add(
            GeneratedDocument(
                id=GeneratedDocumentId(uuid4().hex),
                campaign_id=cid,
                application_id=ApplicationId(uuid4().hex),
                type=DocumentType.SCREENING_ANSWER,
                content="unrelated doc",
            )
        )
        storage.commit()

        rows = storage.screening_answer_library.list_for_campaign(cid)
        assert len(rows) == 1
        assert rows[0].answer_text == "One month."
