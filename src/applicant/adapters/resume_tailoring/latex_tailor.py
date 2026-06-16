"""LaTeX resume-tailoring adapter (primary) (FR-RESUME-3/4, FR-FONT-2).

# STAGE B — owned by Phase 3; flesh out here.

xelatex/lualatex + fontspec + moderncv; deterministic source-level redline diffing
and font-embedded PDF, guarded by a compile-and-visually-inspect fidelity check.
"""

from __future__ import annotations

from applicant.core.ids import ResumeVariantId
from applicant.ports.driven.resume_tailoring import RedlineResult, RenderResult


class LatexTailor:
    """ResumeTailoringPort adapter — LaTeX engine (stub until Phase 3)."""

    def render_redline(self, variant_id: ResumeVariantId, base_source: str, new_source: str) -> RedlineResult:
        raise NotImplementedError("STAGE B — Phase 3: LaTeX source-level redline.")

    def render_artifact(self, variant_id: ResumeVariantId, source: str) -> RenderResult:
        raise NotImplementedError("STAGE B — Phase 3: xelatex compile + fidelity check.")
