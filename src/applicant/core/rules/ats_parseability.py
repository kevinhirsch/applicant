"""ATS-parseability self-check of the GENERATED résumé (Issue #370).

The input résumé parser (``adapters/resume_parser``) already recovers contact +
skills from a clean document. This is the OUTPUT side: after rendering, run a
self-check on the extractable text of the generated résumé and confirm the
contact block, section headers, and key content are machine-readable. A render
whose text cannot be recovered (e.g. text-as-image, a glyph-soup font, an empty
text layer) is flagged for review / regeneration rather than submitted.

Pure core rule (no I/O): the caller supplies the text already extracted from the
render (PDF text layer), so the same definition is shared by the service, the
router, and the BDD specs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: Section headers we expect a real résumé text layer to contain.
_SECTION_CUES: tuple[str, ...] = (
    "experience",
    "education",
    "skills",
    "summary",
    "projects",
    "work history",
    "employment",
)
#: Minimum recoverable characters for a render to be considered to have a real
#: text layer at all (an image-only render extracts to ~nothing).
_MIN_TEXT_CHARS = 40


@dataclass(frozen=True)
class ParseabilityReport:
    """The outcome of the ATS-parseability self-check on a render."""

    parseable: bool
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requires_review(self) -> bool:
        """An unparseable render must be held for review / regeneration."""
        return not self.parseable

    @property
    def reason(self) -> str:
        if self.parseable:
            return "Render is machine-readable."
        return "; ".join(self.issues) or "Render text could not be recovered."


def check_render_parseability(extractable_text: str) -> ParseabilityReport:
    """Self-check that a rendered résumé's text is ATS-recoverable (#370).

    ``extractable_text`` is the text extracted from the rendered document (its
    PDF text layer). A render with no recoverable text layer, no contact email,
    or no recognizable section headers is flagged as not parseable.
    """
    text = extractable_text or ""
    stripped = text.strip()
    issues: list[str] = []

    if len(stripped) < _MIN_TEXT_CHARS:
        # Text-as-image / empty text layer: nothing meaningful to extract.
        return ParseabilityReport(
            parseable=False,
            issues=("no recoverable text layer (the résumé may be rendered as an image)",),
        )

    if not _EMAIL_RE.search(text):
        issues.append("contact email is not recoverable")
    lowered = text.lower()
    if not any(cue in lowered for cue in _SECTION_CUES):
        issues.append("no recognizable section headers")

    return ParseabilityReport(parseable=not issues, issues=tuple(issues))
