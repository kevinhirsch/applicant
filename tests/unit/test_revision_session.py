from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.ids import GeneratedDocumentId, RevisionSessionId


@pytest.fixture(autouse=True)
def _reset():
    pass


@pytest.mark.unit
class TestRevisionSessionStatus:
    def test_open(self):
        assert RevisionStatus.OPEN.value == "open"

    def test_approved(self):
        assert RevisionStatus.APPROVED.value == "approved"

    def test_declined(self):
        assert RevisionStatus.DECLINED.value == "declined"

    def test_is_str_enum(self):
        assert issubclass(RevisionStatus, str)
        assert isinstance(RevisionStatus.OPEN, str)


@pytest.mark.unit
class TestRevisionTurn:
    def test_default_ai_response_empty(self):
        turn = RevisionTurn(kind="add", instruction="Change the title")
        assert turn.ai_response == ""

    def test_all_fields(self):
        turn = RevisionTurn(kind="free_text", instruction="Add a note", ai_response="Done")
        assert turn.kind == "free_text"
        assert turn.instruction == "Add a note"
        assert turn.ai_response == "Done"


@pytest.mark.unit
class TestRevisionSession:
    def _make_ids(self):
        return (
            RevisionSessionId(uuid4()),
            GeneratedDocumentId(uuid4()),
        )

    def test_default_status_open(self):
        sid, mid = self._make_ids()
        session = RevisionSession(id=sid, material_id=mid)
        assert session.status == RevisionStatus.OPEN

    def test_empty_turns(self):
        sid, mid = self._make_ids()
        session = RevisionSession(id=sid, material_id=mid)
        assert session.turns == ()

    def test_empty_redline_state(self):
        sid, mid = self._make_ids()
        session = RevisionSession(id=sid, material_id=mid)
        assert session.redline_state == {}

    def test_construction_with_all_fields(self):
        sid, mid = self._make_ids()
        turn = RevisionTurn(kind="add", instruction="Fix typo", ai_response="Fixed")
        session = RevisionSession(
            id=sid,
            material_id=mid,
            status=RevisionStatus.APPROVED,
            turns=(turn,),
            redline_state={"diff": "abc"},
        )
        assert session.id == sid
        assert session.material_id == mid
        assert session.status == RevisionStatus.APPROVED
        assert session.turns == (turn,)
        assert session.redline_state == {"diff": "abc"}

    def test_frozen_immutability(self):
        sid, mid = self._make_ids()
        session = RevisionSession(id=sid, material_id=mid)
        with pytest.raises(FrozenInstanceError):
            session.status = RevisionStatus.APPROVED

    def test_equality_by_id(self):
        sid = RevisionSessionId(uuid4())
        mid = GeneratedDocumentId(uuid4())
        s1 = RevisionSession(id=sid, material_id=mid)
        s2 = RevisionSession(id=sid, material_id=mid)
        assert s1 == s2

    def test_default_turns_is_empty_tuple(self):
        sid, mid = self._make_ids()
        session = RevisionSession(id=sid, material_id=mid)
        assert session.turns == ()
        assert isinstance(session.turns, tuple)

    def test_default_redline_state_is_empty_dict(self):
        sid, mid = self._make_ids()
        session = RevisionSession(id=sid, material_id=mid)
        assert session.redline_state == {}
