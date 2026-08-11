import re

from applicant.version import __version__


class TestVersion:
    def test_version_value(self):
        assert __version__ == "0.1.0"

    def test_version_is_string(self):
        assert isinstance(__version__, str)

    def test_version_is_semver_like(self):
        assert re.match(r"^\d+\.\d+\.\d+$", __version__), "Version should be a valid semver-like format (e.g. 0.1.0)"
