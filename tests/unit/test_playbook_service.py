"""Unit tests for PlaybookService, Playbook, PlaybookEntry, PlaybookDelta."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from applicant.application.services.playbook_service import Playbook, PlaybookDelta, PlaybookEntry, PlaybookService


@pytest.fixture(autouse=True)
def _no_cache():
    pass


class TestPlaybookEntry:
    """Frozen dataclass: one curated strategy bullet."""

    @pytest.mark.unit
    def test_create_minimal(self):
        entry = PlaybookEntry(key="k1", text="strategy a")
        assert entry.key == "k1"
        assert entry.text == "strategy a"
        assert entry.confidence == 0.5
        assert entry.revision == 1

    @pytest.mark.unit
    def test_create_full(self):
        entry = PlaybookEntry(key="k1", text="strategy a", confidence=0.9, revision=3)
        assert entry.key == "k1"
        assert entry.text == "strategy a"
        assert entry.confidence == 0.9
        assert entry.revision == 3

    @pytest.mark.unit
    def test_frozen_immutable(self):
        entry = PlaybookEntry(key="k1", text="strategy a")
        with pytest.raises(FrozenInstanceError):
            entry.text = "changed"  # type: ignore[misc]

    @pytest.mark.unit
    def test_replace_creates_new(self):
        entry = PlaybookEntry(key="k1", text="original")
        modified = replace(entry, text="updated", revision=2)
        assert entry.text == "original"
        assert entry.revision == 1
        assert modified.text == "updated"
        assert modified.revision == 2
        assert modified.key == "k1"


class TestPlaybookDelta:
    """Frozen dataclass: a single add/revise/retire delta."""

    @pytest.mark.unit
    def test_create_add_delta(self):
        delta = PlaybookDelta(op="add", key="k1", text="new strategy")
        assert delta.op == "add"
        assert delta.key == "k1"
        assert delta.text == "new strategy"

    @pytest.mark.unit
    def test_create_retire_delta_default_text(self):
        delta = PlaybookDelta(op="retire", key="k1")
        assert delta.op == "retire"
        assert delta.key == "k1"
        assert delta.text == ""

    @pytest.mark.unit
    def test_frozen_immutable(self):
        delta = PlaybookDelta(op="add", key="k1", text="text")
        with pytest.raises(FrozenInstanceError):
            delta.op = "retire"  # type: ignore[misc]


class TestPlaybook:
    """Frozen dataclass: immutable curated set of strategies."""

    @pytest.mark.unit
    def test_create_minimal(self):
        pb = Playbook(ats="acme")
        assert pb.ats == "acme"
        assert pb.entries == ()
        assert isinstance(pb.updated_at, datetime)

    @pytest.mark.unit
    def test_create_with_entries(self):
        e1 = PlaybookEntry(key="k1", text="s1")
        e2 = PlaybookEntry(key="k2", text="s2")
        pb = Playbook(ats="acme", entries=(e1, e2))
        assert pb.entries == (e1, e2)

    @pytest.mark.unit
    def test_frozen_immutable(self):
        pb = Playbook(ats="acme")
        with pytest.raises(FrozenInstanceError):
            pb.ats = "other"  # type: ignore[misc]

    @pytest.mark.unit
    def test_get_existing_key(self):
        e1 = PlaybookEntry(key="k1", text="s1")
        pb = Playbook(ats="acme", entries=(e1,))
        assert pb.get("k1") == e1

    @pytest.mark.unit
    def test_get_missing_key(self):
        pb = Playbook(ats="acme")
        assert pb.get("nonexistent") is None


class TestPlaybookService:
    """Apply deltas to a curated playbook."""

    @pytest.mark.unit
    def test_empty_playbook(self):
        svc = PlaybookService()
        pb = svc.empty("acme")
        assert pb.ats == "acme"
        assert pb.entries == ()

    @pytest.mark.unit
    def test_apply_add(self):
        svc = PlaybookService()
        pb = Playbook(ats="acme")
        deltas = [PlaybookDelta(op="add", key="k1", text="strategy one")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert len(applied) == 1
        assert applied[0].key == "k1"
        assert new_pb.get("k1") is not None
        assert new_pb.get("k1").text == "strategy one"

    @pytest.mark.unit
    def test_apply_add_existing_is_noop(self):
        svc = PlaybookService()
        e1 = PlaybookEntry(key="k1", text="original")
        pb = Playbook(ats="acme", entries=(e1,))
        deltas = [PlaybookDelta(op="add", key="k1", text="duplicate")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert applied == []
        assert new_pb.get("k1").text == "original"

    @pytest.mark.unit
    def test_apply_revise(self):
        svc = PlaybookService()
        e1 = PlaybookEntry(key="k1", text="old", revision=1)
        pb = Playbook(ats="acme", entries=(e1,))
        deltas = [PlaybookDelta(op="revise", key="k1", text="new")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert len(applied) == 1
        entry = new_pb.get("k1")
        assert entry.text == "new"
        assert entry.revision == 2

    @pytest.mark.unit
    def test_apply_revise_same_text_noop(self):
        svc = PlaybookService()
        e1 = PlaybookEntry(key="k1", text="same", revision=2)
        pb = Playbook(ats="acme", entries=(e1,))
        deltas = [PlaybookDelta(op="revise", key="k1", text="same")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert applied == []
        assert new_pb.get("k1").revision == 2

    @pytest.mark.unit
    def test_apply_revise_nonexistent_is_noop(self):
        svc = PlaybookService()
        pb = Playbook(ats="acme")
        deltas = [PlaybookDelta(op="revise", key="missing", text="any")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert applied == []
        assert new_pb.get("missing") is None

    @pytest.mark.unit
    def test_apply_retire(self):
        svc = PlaybookService()
        e1 = PlaybookEntry(key="k1", text="gone")
        pb = Playbook(ats="acme", entries=(e1,))
        deltas = [PlaybookDelta(op="retire", key="k1")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert len(applied) == 1
        assert new_pb.get("k1") is None

    @pytest.mark.unit
    def test_apply_retire_nonexistent_is_noop(self):
        svc = PlaybookService()
        pb = Playbook(ats="acme")
        deltas = [PlaybookDelta(op="retire", key="missing")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert applied == []

    @pytest.mark.unit
    def test_apply_deltas_returns_tuple(self):
        svc = PlaybookService()
        pb = Playbook(ats="acme")
        result = svc.apply_deltas(pb, [])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], Playbook)
        assert isinstance(result[1], list)

    @pytest.mark.unit
    def test_apply_add_retain_other_entries(self):
        svc = PlaybookService()
        e1 = PlaybookEntry(key="k1", text="keep me")
        pb = Playbook(ats="acme", entries=(e1,))
        deltas = [PlaybookDelta(op="add", key="k2", text="new")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert len(applied) == 1
        assert new_pb.get("k1").text == "keep me"
        assert new_pb.get("k2").text == "new"

    @pytest.mark.unit
    def test_unrecognized_op_ignored(self):
        svc = PlaybookService()
        pb = Playbook(ats="acme")
        deltas = [PlaybookDelta(op="unknown", key="k1", text="ignored")]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert applied == []
        assert new_pb.get("k1") is None

    @pytest.mark.unit
    def test_mixed_deltas(self):
        svc = PlaybookService()
        e1 = PlaybookEntry(key="k1", text="a")
        e2 = PlaybookEntry(key="k2", text="b")
        pb = Playbook(ats="acme", entries=(e1, e2))
        deltas = [
            PlaybookDelta(op="add", key="k3", text="c"),
            PlaybookDelta(op="revise", key="k1", text="a2"),
            PlaybookDelta(op="retire", key="k2"),
            PlaybookDelta(op="add", key="k1", text="dup"),  # no-op
            PlaybookDelta(op="retire", key="missing"),  # no-op
            PlaybookDelta(op="revise", key="k2", text="gone"),  # no-op (already retired)
        ]
        new_pb, applied = svc.apply_deltas(pb, deltas)
        assert len(applied) == 3
        assert new_pb.get("k1").text == "a2"
        assert new_pb.get("k2") is None
        assert new_pb.get("k3").text == "c"

