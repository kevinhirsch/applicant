"""docx -> moderncv LaTeX converter (FR-RESUME-3/3a).

Turns an uploaded base resume into a **real** moderncv ("banking") ``.tex`` source.
The conversion is structured, not a passthrough: the resume is parsed (identity,
work history with dates, education, skills) by the ``ResumeParser`` and the parsed
data is rendered through the vendored ``templates/latex/moderncv/main.tex.j2``
Jinja2 template (FR-RESUME-3). Every value is:

* **LaTeX-escaped** (``&``, ``%``, ``$``, ``#``, ``_``, ``{``, ``}``, ``~``, ``^``,
  ``\\``) so the candidate's real text never breaks the compile, and
* **em-dash-stripped** via the deterministic truthfulness post-filter
  (``normalize_emdashes``, FR-RESUME-5) so no AI tell survives into the source.

The converter is **truthful** (FR-RESUME-2, NFR-TRUTH-1): it only templates fields
the parser actually found; it never fabricates a section, date, or skill. Missing
fields are simply omitted from the rendered ``.tex``.

This module is pure (no TeX/network); the real compile of the rendered source lives
behind the ``LatexTailor`` compile seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from applicant.core.rules.truthfulness import normalize_emdashes
from applicant.ports.driven.resume_parser import ParsedResume, ResumeParserPort

# Repo-root-relative location of the vendored LaTeX templates.
_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "templates" / "latex" / "moderncv"
_TEMPLATE_NAME = "main.tex.j2"

# LaTeX special characters and their escaped forms. Order matters: backslash first
# so we do not double-escape the replacements we introduce.
_LATEX_ESCAPES: tuple[tuple[str, str], ...] = (
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
)


def latex_escape(text: str) -> str:
    """Escape LaTeX special chars after stripping em-dashes (FR-RESUME-5).

    Em-dash normalization runs first so the post-filter guarantee holds, then every
    LaTeX-special character is escaped so the candidate's real text compiles.
    """
    out = normalize_emdashes(text or "")
    for raw, esc in _LATEX_ESCAPES:
        out = out.replace(raw, esc)
    return out


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (first, last); single-token names keep last empty."""
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _date_range(start: str, end: str) -> str:
    """Render a moderncv date span from a start/end pair (truthful; may be empty)."""
    start = (start or "").strip()
    end = (end or "").strip()
    if start and end:
        return f"{start} - {end}"
    return start or end


@dataclass(frozen=True)
class ConversionResult:
    """Output of the docx->moderncv conversion: the rendered ``.tex`` + its source."""

    tex_source: str
    parsed: ParsedResume


class ModerncvConverter:
    """Builds a real moderncv ``.tex`` source from a parsed base resume (FR-RESUME-3)."""

    def __init__(
        self,
        *,
        resume_parser: ResumeParserPort,
        template_dir: Path | None = None,
    ) -> None:
        self._parser = resume_parser
        # LaTeX-safe delimiters so the template never collides with TeX braces:
        # expressions << >>, statements <% %>, comments <# #>.
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir or _TEMPLATE_DIR)),
            autoescape=select_autoescape(enabled_extensions=()),  # LaTeX, not HTML
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            block_start_string="<%",
            block_end_string="%>",
            variable_start_string="<<",
            variable_end_string=">>",
            comment_start_string="<#",
            comment_end_string="#>",
        )

    # --- public API --------------------------------------------------------
    def convert_file(self, document_path: str) -> ConversionResult:
        """Parse ``document_path`` and render it to a moderncv ``.tex`` source."""
        parsed = self._parser.parse(document_path)
        return self.convert_parsed(parsed)

    def convert_text(self, raw_text: str) -> ConversionResult:
        """Convert in-memory résumé text by writing it through the parser path.

        The onboarding preview supplies the base resume as already-extracted text;
        we run it through the same structured parser so the conversion is genuine
        (sections/dates/skills), not a passthrough.
        """
        parsed = self._parse_text(raw_text)
        return self.convert_parsed(parsed)

    def convert_parsed(self, parsed: ParsedResume) -> ConversionResult:
        """Render a parsed resume into a moderncv ``.tex`` source (FR-RESUME-3)."""
        context = self._build_context(parsed)
        template = self._env.get_template(_TEMPLATE_NAME)
        tex = template.render(**context)
        # Defensive: the post-filter must hold on the whole rendered source too.
        tex = normalize_emdashes(tex)
        return ConversionResult(tex_source=tex, parsed=parsed)

    # --- context construction ---------------------------------------------
    def _parse_text(self, raw_text: str) -> ParsedResume:
        """Parse raw text via the parser's text extraction without touching disk."""
        # ResumeParser exposes _extract over flattened text + detected fonts; reuse it
        # so text-only previews and file uploads share identical extraction logic.
        extract = getattr(self._parser, "_extract", None)
        detect = getattr(self._parser, "_detect_text_fonts", None)
        if callable(extract):
            fonts = detect(raw_text) if callable(detect) else ()
            return extract(raw_text, fonts)
        return ParsedResume(raw_text=raw_text)

    def _build_context(self, parsed: ParsedResume) -> dict:
        first, last = _split_name(parsed.full_name)
        experience = [
            {
                "dates": latex_escape(_date_range(w.start_date, w.end_date)),
                "title": latex_escape(w.title),
                "company": latex_escape(w.company),
                "location": latex_escape(w.location),
                "bullets": [],
            }
            for w in parsed.work_history
        ]
        education = [
            {
                "dates": latex_escape(_date_range(e.start_year, e.end_year)),
                "degree": latex_escape(e.degree),
                "institution": latex_escape(e.institution),
                "location": "",
                "detail": "",
            }
            for e in parsed.education
        ]
        skills = [latex_escape(s) for s in parsed.skills]
        return {
            "first_name": latex_escape(first),
            "last_name": latex_escape(last),
            "address": "",
            "phone": latex_escape(parsed.phone),
            "email": latex_escape(parsed.email),
            "extra_info": "",
            "profile_statement": "",
            "competencies": [],
            "experience": experience,
            "education": education,
            "skills": skills,
            "skills_line": ", ".join(skills),
        }
