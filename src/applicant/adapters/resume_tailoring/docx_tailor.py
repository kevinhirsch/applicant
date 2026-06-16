"""docx-XML resume-tailoring adapter (fallback) (FR-RESUME-3/4).

# STAGE B — owned by Phase 3; flesh out here.

In-place docx-XML editing of the user's uploaded file, used when the LaTeX
conversion doesn't match the hand-tuned design (the load-bearing fallback, §11).
"""

from __future__ import annotations

from applicant.core.ids import ResumeVariantId
from applicant.ports.driven.resume_tailoring import RedlineResult, RenderResult


class DocxTailor:
    """ResumeTailoringPort adapter — docx-XML engine (stub until Phase 3)."""

    def render_redline(self, variant_id: ResumeVariantId, base_source: str, new_source: str) -> RedlineResult:
        raise NotImplementedError("STAGE B — Phase 3: docx-XML redline.")

    def render_artifact(self, variant_id: ResumeVariantId, source: str) -> RenderResult:
        raise NotImplementedError("STAGE B — Phase 3: docx->PDF/docx + fidelity check.")
