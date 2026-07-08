"""P2-3 security pass — the .docx XXE / entity-bomb guard on résumé ingest.

python-docx parses a .docx archive's XML parts with an entity-RESOLVING lxml
parser, so a crafted "résumé template" (an attacker-supplied upload) could carry
a DTD that mounts an XXE local-file read or a billion-laughs entity-expansion
bomb. ``ResumeParser._read_docx`` rejects any part declaring a DTD BEFORE
python-docx parses it (``_docx_has_dtd``), so the hole is closed for every
installed lxml version — not only the one that happens to be patched.

Hermetic: builds .docx-shaped zip archives in-test; no external files.
"""

from __future__ import annotations

import zipfile

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser, _docx_has_dtd

# A minimal well-formed document.xml body (one paragraph).
_CLEAN_DOCUMENT_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>Jane Q Candidate</w:t></w:r></w:p></w:body></w:document>"
)

# The same, but prefaced with an external-entity DTD (the XXE payload shape).
_XXE_DOCUMENT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>"
)

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
    '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)


def _write_docx(path, document_xml: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/document.xml", document_xml)


@pytest.mark.unit
def test_docx_has_dtd_detects_the_entity_payload(tmp_path):
    clean = tmp_path / "clean.docx"
    poisoned = tmp_path / "poisoned.docx"
    _write_docx(clean, _CLEAN_DOCUMENT_XML)
    _write_docx(poisoned, _XXE_DOCUMENT_XML)

    assert _docx_has_dtd(clean) is False
    assert _docx_has_dtd(poisoned) is True


@pytest.mark.unit
def test_docx_has_dtd_fails_closed_on_a_corrupt_archive(tmp_path):
    """A non-zip / truncated file cannot be classified safe — report True so the
    caller skips python-docx (which would fail on it anyway)."""
    bogus = tmp_path / "bogus.docx"
    bogus.write_bytes(b"not a zip file at all")
    assert _docx_has_dtd(bogus) is True


@pytest.mark.unit
def test_read_docx_refuses_a_dtd_bearing_file_and_returns_empty(tmp_path):
    """The guard is wired into the reader: a poisoned .docx yields empty text,
    so no entity is ever resolved and the pipeline sees an empty parse."""
    poisoned = tmp_path / "poisoned.docx"
    _write_docx(poisoned, _XXE_DOCUMENT_XML)

    assert ResumeParser()._read_docx(poisoned) == ""


@pytest.mark.unit
def test_read_docx_still_reads_a_clean_file(tmp_path):
    """Positive control: the guard is specific — a normal .docx still parses,
    so the refusal above is the policy, not a broken reader."""
    clean = tmp_path / "clean.docx"
    _write_docx(clean, _CLEAN_DOCUMENT_XML)

    assert "Jane Q Candidate" in ResumeParser()._read_docx(clean)
