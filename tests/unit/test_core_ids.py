import pytest
import os

from applicant.core.ids import validate_id, assert_valid_id, new_id


class TestValidateId:
    """Edge-case tests for validate_id."""

    # --- happy path ---
    def test_simple_string(self):
        assert validate_id("abc") == "abc"

    def test_uuid_hex(self):
        uid = "a1b2c3c4d4e2f1f2a1b2c3c4d4e2f1f2"
        assert validate_id(uid) == uid

    def test_with_spaces(self):
        assert validate_id("my id") == "my id"

    def test_unicode(self):
        assert validate_id("über-ïd") == "über-ïd"

    # --- empty / whitespace ---
    def test_empty_string(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_id("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_id("   ")

    def test_single_space(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_id(" ")

    # --- NUL bytes ---
    def test_nul_byte_in_middle(self):
        with pytest.raises(ValueError, match="NUL"):
            validate_id("ab\x00cd")

    def test_nul_byte_at_start(self):
        with pytest.raises(ValueError, match="NUL"):
            validate_id("\x00abc")

    def test_multiple_nul_bytes(self):
        with pytest.raises(ValueError, match="NUL"):
            validate_id("a\x00b\x00c")

    # --- path traversal ---
    def test_dot_slash_slash(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_id("../foo")

    def test_backslash_slash(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_id("..\\foo")

    def test_bare_dot_dot(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_id("..")

    # --- absolute paths ---
    def test_leading_slash(self):
        with pytest.raises(ValueError, match="absolute"):
            validate_id("/foo")

    def test_leading_backslash(self):
        with pytest.raises(ValueError, match="absolute"):
            validate_id("\\foo")

    def test_single_slash(self):
        with pytest.raises(ValueError, match="absolute"):
            validate_id("/")

    def test_single_backslash(self):
        with pytest.raises(ValueError, match="absolute"):
            validate_id("\\")


class TestAssertValidId:
    """assert_valid_id is an alias for validate_id."""

    def test_success(self):
        assert assert_valid_id("abc") == "abc"

    def test_failure_raises_same_as_validate(self):
        with pytest.raises(ValueError, match="must not be empty"):
            assert_valid_id("")


class TestNewId:
    """Tests for new_id generator."""

    def test_returns_string(self):
        assert isinstance(new_id(), str)

    def test_length_is_32_hex_chars(self):
        # UUID4 hex is always 32 lowercase hex characters
        val = new_id()
        assert len(val) == 32
        assert val == val.lower()

    def test_uniqueness(self):
        ids = {new_id() for _ in range(100)}
        assert len(ids) == 100
