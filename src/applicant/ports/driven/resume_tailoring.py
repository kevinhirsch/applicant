"""ResumeTailoring port (FR-RESUME-3/4, FR-FONT-2).

LaTeX primary (xelatex/lualatex+fontspec, moderncv) / docx-XML fallback; produces
a redline (add+subtract highlights) and a font-embedded export, guarded by a
compile-and-visually-inspect fidelity check. The truthfulness post-filter
(``core.rules.truthfulness``) is applied to generated text by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from applicant.core.ids import ResumeVariantId


@dataclass(frozen=True)
class RedlineResult:
    """A rendered redline of a variant against its parent/base."""

    variant_id: ResumeVariantId
    additions: tuple[str, ...] = ()
    subtractions: tuple[str, ...] = ()
    rendered_html: str = ""


@dataclass(frozen=True)
class RenderResult:
    """A rendered, font-embedded artifact plus its fidelity verdict.

    HONESTY CONTRACT: ``artifact_available`` is True ONLY when a real PDF was
    produced by an available toolchain (the file at ``storage_path`` exists).
    When it is False, ``page_count`` is a source-based ESTIMATE used by the
    internal page-fit modeling — no user-facing surface may present it as a
    measured property of a document, and ``fidelity_ok`` must never be
    presented as "faithful match" (no artifact was inspected). The default is
    conservative (False) so a hand-rolled result can't claim an artifact.
    """

    storage_path: str
    fidelity_ok: bool
    page_count: int
    notes: str = ""
    artifact_available: bool = False


@runtime_checkable
class ResumeTailoringPort(Protocol):
    """Outbound port for tailoring/rendering resumes and cover letters."""

    def render_redline(self, variant_id: ResumeVariantId, base_source: str, new_source: str) -> RedlineResult:
        """Render add/subtract highlights of ``new_source`` vs ``base_source`` (FR-RESUME-8)."""
        ...

    def render_artifact(self, variant_id: ResumeVariantId, source: str) -> RenderResult:
        """Compile a font-embedded PDF/docx and run the fidelity check (FR-RESUME-4)."""
        ...
