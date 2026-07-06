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

#: Below this many recoverable characters an UPLOADED résumé is readable but
#: suspiciously thin — almost certainly not a complete résumé (a real one runs
#: well past this), so the upload health check flags it instead of celebrating.
_MIN_UPLOAD_TEXT_CHARS = 150

#: Upload-health verdict levels (deterministic, derived — never defaulted).
UPLOAD_HEALTH_GOOD = "good"
UPLOAD_HEALTH_ISSUES = "issues"
UPLOAD_HEALTH_UNREADABLE = "unreadable"


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


@dataclass(frozen=True)
class UploadHealthReport:
    """Deterministic health verdict for a résumé the user UPLOADS at onboarding.

    Unlike :class:`ParseabilityReport` (the render-side self-check), this verdict
    also incorporates what the parser ACTUALLY recovered (name / email / phone),
    so the product can never claim a résumé "reads cleanly" while the very same
    parse found no name or contact details. Every level is computed from ground
    truth — there is no optimistic default.
    """

    verdict: str  # UPLOAD_HEALTH_GOOD | UPLOAD_HEALTH_ISSUES | UPLOAD_HEALTH_UNREADABLE
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def parseable(self) -> bool:
        """Back-compat boolean: only an explicit GOOD verdict counts as healthy."""
        return self.verdict == UPLOAD_HEALTH_GOOD


def check_upload_health(
    *,
    raw_text: str,
    full_name: str = "",
    email: str = "",
    phone: str = "",
) -> UploadHealthReport:
    """Derive the upload-time resume-health verdict from the actual parse results.

    Pure rule (no I/O): the caller supplies the extractable text plus the fields
    the parser recovered. A résumé missing its name / email / phone, with no
    recognizable section headers, or with almost no recoverable text yields an
    honest warning naming exactly what is missing — NEVER "looks good".
    """
    text = (raw_text or "").strip()
    if len(text) < _MIN_TEXT_CHARS:
        # Nothing meaningful could be read at all: the health of the content
        # cannot even be assessed, which is its own (worst) verdict.
        return UploadHealthReport(
            verdict=UPLOAD_HEALTH_UNREADABLE,
            issues=("no recoverable text layer (the résumé may be rendered as an image)",),
        )

    issues: list[str] = []
    if not (full_name or "").strip():
        issues.append("your name is not detectable in the text")
    if not ((email or "").strip() or _EMAIL_RE.search(text)):
        issues.append("contact email is not recoverable")
    if not (phone or "").strip():
        issues.append("a phone number is not detectable in the text")
    lowered = text.lower()
    if not any(cue in lowered for cue in _SECTION_CUES):
        issues.append("no recognizable section headers")
    if len(text) < _MIN_UPLOAD_TEXT_CHARS:
        issues.append("very little text could be read from this file")

    return UploadHealthReport(
        verdict=UPLOAD_HEALTH_GOOD if not issues else UPLOAD_HEALTH_ISSUES,
        issues=tuple(issues),
    )


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
