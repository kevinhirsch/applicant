"""Resume-parser adapter (FR-ONBOARD-3, FR-ATTR-1).

Parses an uploaded base resume into a :class:`ParsedResume` so the onboarding
service can bootstrap the per-campaign attribute cloud and reconcile against the
interview answers. Supports docx (python-docx), txt, and PDF (pypdf) at minimum.

Extraction is heuristic and intentionally conservative: it never fabricates. When
a field cannot be found it is left empty, and onboarding fills it from the
interview. Font detection reuses the docx font table (docx) or fontspec directives
(txt/tex) so the font subsystem can prompt for any missing families (FR-FONT-1).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from applicant.observability.logging import get_logger
from applicant.ports.driven.resume_parser import (
    EducationEntry,
    ParsedResume,
    WorkHistoryEntry,
)

log = get_logger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
# A dated work-history line: "Title, Company    Jan 2020 - Present"
_DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|"
    r"April|May|June|July|August|September|October|November|December|\d{1,2})?\.?\s*\d{4})"
    r"\s*(?:-|–|—|to)\s*"
    r"((?:Present|Current|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|May|June|July|August|September|October|November|"
    r"December|\d{1,2})?\.?\s*\d{4}))",
    re.IGNORECASE,
)
_YEAR_RANGE_RE = re.compile(r"(\d{4})\s*(?:-|–|—|to)\s*(\d{4}|Present|Current)", re.IGNORECASE)
_DEGREE_RE = re.compile(
    r"(B\.?S\.?|B\.?A\.?|M\.?S\.?|M\.?A\.?|MBA|Ph\.?D\.?|Bachelor|Master|Doctor|Associate)"
    r"[^,\n]*",
    re.IGNORECASE,
)
_SECTION_RE = re.compile(
    r"^\s*(experience|work experience|employment|professional experience|"
    r"education|skills|technical skills|core competencies)\s*:?\s*$",
    re.IGNORECASE,
)


class ResumeParser:
    """ResumeParserPort adapter for docx / txt / pdf base resumes."""

    def parse(self, document_path: str) -> ParsedResume:
        path = Path(document_path)
        suffix = path.suffix.lower()
        if suffix == ".docx":
            text = self._read_docx(path)
            fonts = self._detect_docx_fonts(path)
        elif suffix == ".pdf":
            text = self._read_pdf(path)
            fonts = ()
        else:  # .txt / .tex / unknown -> treat as plain text
            text = self._read_text(path)
            fonts = self._detect_text_fonts(text)
        return self._extract(text, fonts)

    # --- readers -----------------------------------------------------------
    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def _read_docx(self, path: Path) -> str:
        try:
            from docx import Document
        except Exception:  # pragma: no cover - dep present in prod/test
            return ""
        try:
            doc = Document(str(path))
        except Exception:
            return ""
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                lines.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(lines)

    def _read_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except Exception:  # pragma: no cover
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""

    # --- font detection ----------------------------------------------------
    def _detect_docx_fonts(self, path: Path) -> tuple[str, ...]:
        """Read declared font families from the docx font table (FR-FONT-1)."""
        found: list[str] = []
        try:
            with zipfile.ZipFile(str(path)) as zf:
                names = zf.namelist()
                # Fonts declared in fontTable.xml and styles.xml (w:rFonts).
                for member in ("word/fontTable.xml", "word/styles.xml", "word/document.xml"):
                    if member not in names:
                        continue
                    xml = zf.read(member).decode("utf-8", errors="ignore")
                    for m in re.finditer(r'w:(?:ascii|hAnsi|cs)="([^"]+)"', xml):
                        fam = m.group(1).strip()
                        if fam and fam not in found:
                            found.append(fam)
                    for m in re.finditer(r'<w:font w:name="([^"]+)"', xml):
                        fam = m.group(1).strip()
                        if fam and fam not in found:
                            found.append(fam)
        except (OSError, zipfile.BadZipFile):
            return ()
        return tuple(found)

    def _detect_text_fonts(self, text: str) -> tuple[str, ...]:
        found: list[str] = []
        for pat in (
            r"\\setmainfont(?:\[[^\]]*\])?\{([^}]+)\}",
            r"\\setsansfont(?:\[[^\]]*\])?\{([^}]+)\}",
            r"\\fontspec(?:\[[^\]]*\])?\{([^}]+)\}",
        ):
            for m in re.finditer(pat, text):
                fam = m.group(1).split("-")[0].strip()
                if fam and fam not in found:
                    found.append(fam)
        return tuple(found)

    # --- extraction --------------------------------------------------------
    def _extract(self, text: str, fonts: tuple[str, ...]) -> ParsedResume:
        lines = [ln.rstrip() for ln in text.splitlines()]
        non_empty = [ln for ln in lines if ln.strip()]

        email = _EMAIL_RE.search(text)
        # Avoid matching dates/years as a phone number: require it not to be the email.
        phone = ""
        for m in _PHONE_RE.finditer(text):
            candidate = m.group(0).strip()
            digits = re.sub(r"\D", "", candidate)
            if 9 <= len(digits) <= 15:
                phone = candidate
                break

        full_name = self._guess_name(non_empty, email.group(0) if email else "")
        work_history = self._extract_work_history(lines)
        education = self._extract_education(lines)
        skills = self._extract_skills(lines)

        return ParsedResume(
            full_name=full_name,
            email=email.group(0) if email else "",
            phone=phone,
            work_history=tuple(work_history),
            education=tuple(education),
            skills=tuple(skills),
            detected_fonts=fonts,
            raw_text=text,
        )

    def _guess_name(self, non_empty: list[str], email: str) -> str:
        """First non-contact line of 2-4 capitalized words is the name."""
        for line in non_empty[:5]:
            s = line.strip()
            if email and email in s:
                continue
            if _EMAIL_RE.search(s) or _PHONE_RE.search(s):
                continue
            words = s.split()
            if 1 < len(words) <= 4 and all(w[0:1].isupper() for w in words if w[0:1].isalpha()):
                return s
        return ""

    def _current_section(self, lines: list[str]) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current = "_preamble"
        sections[current] = []
        for line in lines:
            m = _SECTION_RE.match(line)
            if m:
                current = m.group(1).lower()
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        return sections

    def _extract_work_history(self, lines: list[str]) -> list[WorkHistoryEntry]:
        sections = self._current_section(lines)
        body: list[str] = []
        for key in ("experience", "work experience", "employment", "professional experience"):
            body += sections.get(key, [])
        if not body:
            body = lines  # fall back to whole doc
        entries: list[WorkHistoryEntry] = []
        for line in body:
            dm = _DATE_RANGE_RE.search(line)
            if not dm:
                continue
            before = line[: dm.start()].strip(" \t,-|")
            title, company = self._split_title_company(before)
            entries.append(
                WorkHistoryEntry(
                    title=title,
                    company=company,
                    start_date=dm.group(1).strip(),
                    end_date=dm.group(2).strip(),
                )
            )
        return entries

    @staticmethod
    def _split_title_company(text: str) -> tuple[str, str]:
        for sep in (" at ", " @ ", ", ", " | ", "\t", " - "):
            if sep in text:
                left, right = text.split(sep, 1)
                return left.strip(), right.strip()
        return text.strip(), ""

    def _extract_education(self, lines: list[str]) -> list[EducationEntry]:
        sections = self._current_section(lines)
        body = sections.get("education", [])
        if not body:
            body = [ln for ln in lines if _DEGREE_RE.search(ln)]
        entries: list[EducationEntry] = []
        for line in body:
            dm = _DEGREE_RE.search(line)
            if not dm:
                continue
            ym = _YEAR_RANGE_RE.search(line)
            rest = line.replace(dm.group(0), "").strip(" \t,-|")
            inst, _ = self._split_title_company(rest)
            entries.append(
                EducationEntry(
                    degree=dm.group(0).strip(),
                    institution=inst,
                    start_year=ym.group(1) if ym else "",
                    end_year=ym.group(2) if ym else "",
                )
            )
        return entries

    def _extract_skills(self, lines: list[str]) -> list[str]:
        sections = self._current_section(lines)
        body: list[str] = []
        for key in ("skills", "technical skills", "core competencies"):
            body += sections.get(key, [])
        skills: list[str] = []
        for line in body:
            for tok in re.split(r"[,;•|]", line):
                s = tok.strip()
                if s and len(s) <= 40 and s not in skills:
                    skills.append(s)
        return skills
