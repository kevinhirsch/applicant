"""docx-XML resume-tailoring adapter (fallback) (FR-RESUME-3/4, FR-RESUME-5).

# STAGE B — owned by Phase 3.

In-place docx-XML (OOXML) editing of the user's uploaded file: the load-bearing
fallback used when the LaTeX conversion does not match the hand-tuned design
(§11). It swaps the text runs while preserving the original layout/fonts/spacing,
so adaptation reframes content (FR-RESUME-2) without disturbing design.

Same behavioral contract as ``LatexTailor`` (swappable LaTeX <-> docx-XML). The
em-dash post-filter (FR-RESUME-5) runs on every pass; the real ``docx -> PDF``
fidelity conversion is **stubbed behind a clearly-marked boundary** so the suite
passes WITHOUT LibreOffice/Word installed.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from applicant.core.ids import ResumeVariantId
from applicant.core.rules.truthfulness import contains_emdash, normalize_emdashes
from applicant.ports.driven.resume_tailoring import RedlineResult, RenderResult


@dataclass(frozen=True)
class _ConvertResult:
    storage_path: str
    page_count: int
    fonts_embedded: bool


class DocxTailor:
    """ResumeTailoringPort adapter — docx-XML engine (OOXML in-place edit)."""

    def render_redline(
        self, variant_id: ResumeVariantId, base_source: str, new_source: str
    ) -> RedlineResult:
        """Word-level redline of the docx text runs (em-dash-normalized first)."""
        base = normalize_emdashes(base_source).split()
        new = normalize_emdashes(new_source).split()
        additions: list[str] = []
        subtractions: list[str] = []
        html_parts: list[str] = []
        sm = difflib.SequenceMatcher(a=base, b=new, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                html_parts.append(" ".join(new[j1:j2]))
            elif tag in ("delete", "replace"):
                chunk = " ".join(base[i1:i2])
                if chunk:
                    subtractions.append(chunk)
                    html_parts.append(f'<del class="redline-sub">{_esc(chunk)}</del>')
                if tag == "replace":
                    add = " ".join(new[j1:j2])
                    if add:
                        additions.append(add)
                        html_parts.append(f'<ins class="redline-add">{_esc(add)}</ins>')
            elif tag == "insert":
                chunk = " ".join(new[j1:j2])
                if chunk:
                    additions.append(chunk)
                    html_parts.append(f'<ins class="redline-add">{_esc(chunk)}</ins>')
        return RedlineResult(
            variant_id=variant_id,
            additions=tuple(additions),
            subtractions=tuple(subtractions),
            rendered_html=" ".join(html_parts),
        )

    def render_artifact(self, variant_id: ResumeVariantId, source: str) -> RenderResult:
        """Write edited OOXML, convert docx -> PDF, run the fidelity check."""
        clean_source = normalize_emdashes(source)  # FR-RESUME-5 every pass
        converted = self._convert_to_pdf(variant_id, clean_source)

        notes: list[str] = []
        fidelity_ok = True
        if contains_emdash(clean_source):
            fidelity_ok = False
            notes.append("em-dash survived the post-filter")
        if not converted.fonts_embedded:
            fidelity_ok = False
            notes.append("fonts not embedded")

        return RenderResult(
            storage_path=converted.storage_path,
            fidelity_ok=fidelity_ok,
            page_count=converted.page_count,
            notes="; ".join(notes) if notes else "fidelity check passed",
        )

    # --- CONVERT BOUNDARY (stubbed; no LibreOffice/Word required) ----------
    def _convert_to_pdf(self, variant_id: ResumeVariantId, source: str) -> _ConvertResult:
        """STAGE B BOUNDARY — real docx OOXML write + docx->PDF convert goes here.

        A real install would edit the ``<w:t>`` runs of the user's uploaded .docx
        and run LibreOffice headless (``soffice --convert-to pdf``) with embedded
        fonts, returning the PDF path + actual page count. Stubbed here: no
        subprocess, deterministic synthetic path, font-embedding reported true.
        """
        storage_path = f"artifacts/{variant_id}.docx.pdf"
        return _ConvertResult(storage_path=storage_path, page_count=1, fonts_embedded=True)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
