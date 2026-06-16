"""ConversionService — LaTeX conversion preview + accept/reject gate (FR-RESUME-3a).

At onboarding, after the base resume is uploaded and fonts are resolved, the system
COMPILES the LaTeX conversion of the base resume (vendored moderncv template) and
presents it for the user to ACCEPT or REJECT:

* ACCEPT -> LaTeX becomes the campaign's primary material engine.
* REJECT -> fall back to the docx engine.

The choice is persisted as a per-campaign setting (switchable later) so Phase 3
material generation reads it. The real xelatex/lualatex compile is stubbed behind
the LatexTailor compile seam (``_compile_pdf``) so the default test lane needs no
TeX install; a real-compile test lives behind the integration marker.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    """A compiled preview of the LaTeX conversion, presented for accept/reject."""

    campaign_id: str
    storage_path: str
    page_count: int
    fidelity_ok: bool
    notes: str


class ConversionService:
    """Implements the LaTeX conversion preview + accept/reject gate."""

    def __init__(self, *, latex_tailor, config_store) -> None:
        self._latex = latex_tailor
        self._config = config_store

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
        """Compile the LaTeX conversion of the base resume for accept/reject."""
        vid = ResumeVariantId(new_id())
        result = self._latex.render_artifact(vid, base_source)
        log.info(
            "conversion_preview_built",
            campaign_id=campaign_id,
            fidelity_ok=result.fidelity_ok,
            pages=result.page_count,
        )
        return ConversionPreview(
            campaign_id=campaign_id,
            storage_path=result.storage_path,
            page_count=result.page_count,
            fidelity_ok=result.fidelity_ok,
            notes=result.notes,
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
