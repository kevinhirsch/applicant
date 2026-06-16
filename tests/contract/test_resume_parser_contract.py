"""ResumeParser contract (FR-ONBOARD-3, FR-ATTR-1).

Architecture §6: every adapter ships a contract test. Proves ResumeParser
satisfies the ``ResumeParserPort`` protocol and returns a well-formed
``ParsedResume`` for txt and docx without external services.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.ports.driven.resume_parser import ParsedResume, ResumeParserPort


@pytest.mark.contract
class TestResumeParserContract:
    @pytest.fixture
    def adapter(self) -> ResumeParser:
        return ResumeParser()

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, ResumeParserPort)

    def test_parse_returns_parsed_resume(self, adapter, tmp_path):
        p = tmp_path / "r.txt"
        p.write_text("Ada Lovelace\nada@analytical.engine\n", encoding="utf-8")
        result = adapter.parse(str(p))
        assert isinstance(result, ParsedResume)
        assert result.email == "ada@analytical.engine"

    def test_parse_missing_file_never_raises(self, adapter):
        result = adapter.parse("/no/such.txt")
        assert isinstance(result, ParsedResume)
        assert result.raw_text == ""
