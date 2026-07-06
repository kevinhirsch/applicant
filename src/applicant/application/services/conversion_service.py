"""ConversionService — LaTeX conversion preview + accept/reject gate (FR-RESUME-3a).

At onboarding, after the base resume is uploaded and fonts are resolved, the system
performs a **real docx->moderncv conversion** (FR-RESUME-3): the uploaded résumé is
parsed (identity, work history with dates, education, skills) and rendered into a
genuine moderncv ("banking") ``.tex`` source via the vendored Jinja2 template, then
COMPILED, and the result is presented for the user to ACCEPT or REJECT:

* ACCEPT -> LaTeX becomes the campaign's primary material engine (the template path).
* REJECT -> fall back to the docx-XML engine.

The choice is persisted as a per-campaign setting (switchable later) so Phase 3
material generation reads it. The real xelatex/lualatex compile sits behind the
LatexTailor compile seam (``_compile_pdf``), which auto-enables when a TeX engine is
present and otherwise returns a deterministic stub, so the default test lane needs
no TeX install; a real-compile test lives behind the integration marker.
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.resume_tailoring.moderncv_converter import ModerncvConverter
from applicant.core.ids import ResumeVariantId, new_id
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: per-campaign app-config key for the chosen material engine (FR-RESUME-3a).
_ENGINE_KEY_PREFIX = "resume.engine."

ENGINE_LATEX = "latex"
ENGINE_DOCX = "docx"
_DEFAULT_ENGINE = ENGINE_DOCX  # default until the user accepts the LaTeX preview


@dataclass(frozen=True)
class ConversionPreview:
    """A compiled preview of the LaTeX conversion, presented for accept/reject.

    ``artifact_available`` mirrors the render's ground truth: True only when a
    real PDF was compiled. When False, ``page_count`` is an internal estimate
    and ``fidelity_ok`` reflects source-level checks only — the HTTP boundary
    must not present either as properties of a document that exists.
    """

    campaign_id: str
    storage_path: str
    page_count: int
    fidelity_ok: bool
    notes: str
    tex_source: str = ""
    artifact_available: bool = False


class ConversionService:
    """Implements the docx->moderncv conversion preview + accept/reject gate."""

    def __init__(self, *, latex_tailor, config_store, converter=None) -> None:
        self._latex = latex_tailor
        self._config = config_store
        # Real docx->moderncv converter (FR-RESUME-3); defaults to the standard
        # resume parser + vendored template so the wiring stays additive.
        self._converter = converter or ModerncvConverter(resume_parser=ResumeParser())

    # --- engine choice (persisted per campaign) ---------------------------
    def _key(self, campaign_id: str) -> str:
        return f"{_ENGINE_KEY_PREFIX}{campaign_id}"

    def get_engine(self, campaign_id: str) -> str:
        rec = self._config.get(self._key(campaign_id))
        if not rec:
            return _DEFAULT_ENGINE
        return rec.get("engine", _DEFAULT_ENGINE)

    def _set_engine(self, campaign_id: str, engine: str) -> None:
        self._config.set(self._key(campaign_id), {"engine": engine})

    # --- preview + gate (FR-RESUME-3a) ------------------------------------
    def build_preview(self, campaign_id: str, base_source: str) -> ConversionPreview:
        """Build the real docx->moderncv conversion preview for accept/reject.

        The uploaded résumé text is parsed and rendered into a genuine moderncv
        ``.tex`` source (FR-RESUME-3) — not passed through as-if-LaTeX — then compiled
        and inspected (compile auto-enables when a TeX engine is present, else stubs).
        """
        conversion = self._converter.convert_text(base_source)
        tex_source = conversion.tex_source
        vid = ResumeVariantId(new_id())
        result = self._latex.render_artifact(vid, tex_source)
        log.info(
            "conversion_preview_built",
            campaign_id=campaign_id,
            fidelity_ok=result.fidelity_ok,
            pages=result.page_count,
            artifact_available=result.artifact_available,
        )
        return ConversionPreview(
            campaign_id=campaign_id,
            storage_path=result.storage_path,
            page_count=result.page_count,
            fidelity_ok=result.fidelity_ok,
            notes=result.notes,
            tex_source=tex_source,
            artifact_available=result.artifact_available,
        )

    def accept(self, campaign_id: str) -> str:
        """ACCEPT -> LaTeX becomes the campaign's primary engine (FR-RESUME-3a)."""
        self._set_engine(campaign_id, ENGINE_LATEX)
        log.info("conversion_accepted", campaign_id=campaign_id, engine=ENGINE_LATEX)
        return ENGINE_LATEX

    def reject(self, campaign_id: str) -> str:
        """REJECT -> fall back to the docx engine (FR-RESUME-3a)."""
        self._set_engine(campaign_id, ENGINE_DOCX)
        log.info("conversion_rejected", campaign_id=campaign_id, engine=ENGINE_DOCX)
        return ENGINE_DOCX
