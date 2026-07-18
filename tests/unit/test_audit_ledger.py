import pytest

from applicant.audit_ledger import is_audited, audit_note, audited_areas


REAL_AUDITED_PATH = "docker/webtop-chrome/Dockerfile"
REAL_AUDITED_PATH2 = "workspace/static/js/editor/layer-panel.js"
UNAUDITED_PATH = "src/applicant/main.py"
UNAUDITED_PATH2 = ""


class TestIsAudited:
    """Tests for is_audited — checks membership against _BY_PATH."""

    def test_known_path_returns_true(self):
        assert is_audited(REAL_AUDITED_PATH) is True

    def test_another_known_path_returns_true(self):
        assert is_audited(REAL_AUDITED_PATH2) is True

    def test_unknown_path_returns_false(self):
        assert is_audited(UNAUDITED_PATH) is False

    def test_empty_string_returns_false(self):
        assert is_audited(UNAUDITED_PATH2) is False


class TestAuditNote:
    """Tests for audit_note — returns disposition or None."""

    def test_known_path_returns_note(self):
        note = audit_note(REAL_AUDITED_PATH)
        assert isinstance(note, str)
        assert len(note) > 0

    def test_known_path_note_starts_with_keyword(self):
        note = audit_note(REAL_AUDITED_PATH)
        assert note is not None
        assert note.startswith("Audited")

    def test_unknown_path_returns_none(self):
        assert audit_note(UNAUDITED_PATH) is None

    def test_empty_string_returns_none(self):
        assert audit_note(UNAUDITED_PATH2) is None


class TestAuditedAreas:
    """Tests for audited_areas — sorted list of all audited paths."""

    def test_returns_list(self):
        result = audited_areas()
        assert isinstance(result, list)

    def test_includes_known_path(self):
        result = audited_areas()
        assert REAL_AUDITED_PATH in result

    def test_excludes_unknown_path(self):
        result = audited_areas()
        assert UNAUDITED_PATH not in result

    def test_is_sorted(self):
        result = audited_areas()
        assert result == sorted(result)

    def test_returned_list_is_a_copy(self):
        result = audited_areas()
        result.append("foo")
        # second call should still return the original set
        result2 = audited_areas()
        assert "foo" not in result2

    def test_has_expected_count(self):
        result = audited_areas()
        assert len(result) == 8
