import re

import pytest

from applicant.core.ids import (
    CampaignId,
    SYSTEM_CAMPAIGN_ID,
    assert_valid_id,
    new_id,
    validate_id,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    pass


@pytest.mark.unit
class TestValidateId:
    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="ID must not be empty"):
            validate_id("")

    def test_rejects_blank(self) -> None:
        with pytest.raises(ValueError, match="ID must not be empty"):
            validate_id("   ")

    def test_rejects_nul_byte(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain NUL bytes"):
            validate_id("abc\x00def")

    def test_rejects_tab(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain control characters"):
            validate_id("abc\tdef")

    def test_rejects_newline(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain control characters"):
            validate_id("abc\ndef")

    def test_rejects_carriage_return(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain control characters"):
            validate_id("abc\rdef")

    def test_rejects_form_feed(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain control characters"):
            validate_id("abc\fdef")

    def test_rejects_vertical_tab(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain control characters"):
            validate_id("abc\vdef")

    def test_rejects_escape(self) -> None:
        with pytest.raises(ValueError, match="ID must not contain control characters"):
            validate_id("abc\x1bdef")

    def test_rejects_dotdot_slash_prefix(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("../foo")

    def test_rejects_dotdot_backslash_prefix(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("..\\foo")

    def test_rejects_bare_dotdot(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("..")

    def test_rejects_embedded_slash_dotdot_slash(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("a/../b")

    def test_rejects_embedded_backslash_dotdot_backslash(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("a\\..\\b")

    def test_rejects_trailing_slash_dotdot(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("/..")

    def test_rejects_trailing_backslash_dotdot(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            validate_id("\\..")

    def test_rejects_absolute_unix_path(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            validate_id("/etc/passwd")

    def test_rejects_absolute_windows_path(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            validate_id("\\Windows\\System32")

    def test_returns_valid_string(self) -> None:
        result = validate_id("valid-id-123")
        assert result == "valid-id-123"

    def test_returns_valid_with_dashes_and_underscores(self) -> None:
        result = validate_id("abc-def_ghi")
        assert result == "abc-def_ghi"

    def test_returns_valid_with_digits(self) -> None:
        result = validate_id("id42")
        assert result == "id42"

    def test_returns_valid_uuid_hex(self) -> None:
        # Real UUID hex without dashes — perfectly valid
        value = "550e8400e29b41d4a716446655440000"
        result = validate_id(value)
        assert result == value


@pytest.mark.unit
class TestAssertValidId:
    def test_delegates_to_validate_id(self) -> None:
        assert assert_valid_id("abc") == validate_id("abc")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="ID must not be empty"):
            assert_valid_id("")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="path-traversal"):
            assert_valid_id("../etc")

    def test_returns_valid_string(self) -> None:
        result = assert_valid_id("ok-id")
        assert result == "ok-id"


@pytest.mark.unit
class TestNewId:
    def test_returns_non_empty_string(self) -> None:
        result = new_id()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_32_char_hex_string(self) -> None:
        result = new_id()
        assert len(result) == 32
        assert re.fullmatch(r"[0-9a-f]+", result)

    def test_returns_different_values_on_consecutive_calls(self) -> None:
        id1 = new_id()
        id2 = new_id()
        assert id1 != id2


@pytest.mark.unit
class TestSystemCampaignId:
    def test_is_sentinel_string(self) -> None:
        assert SYSTEM_CAMPAIGN_ID == "__system__"
        assert isinstance(SYSTEM_CAMPAIGN_ID, str)


@pytest.mark.unit
class TestNewTypeAliases:
    def test_campaign_id_is_newtype_of_str(self) -> None:
        # Spot-check: CampaignId is a NewType(str)
        value: CampaignId = CampaignId("abc-123")
        assert isinstance(value, str)
        assert value == "abc-123"
