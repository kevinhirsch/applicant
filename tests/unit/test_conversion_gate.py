"""LaTeX conversion preview + accept/reject gate tests (FR-RESUME-3a).

Accept -> LaTeX primary; reject -> docx fallback; choice persists per campaign and
across restarts. The xelatex compile is stubbed behind the LatexTailor seam, so no
TeX install is required in the default lane.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.conversion_service import (
    ENGINE_DOCX,
    ENGINE_LATEX,
    ConversionService,
)

CID = "camp-1"


@pytest.fixture
def store() -> InMemoryAppConfigStore:
    return InMemoryAppConfigStore()


@pytest.fixture
def svc(store) -> ConversionService:
    return ConversionService(latex_tailor=LatexTailor(), config_store=store)


def test_default_engine_is_docx(svc):
    assert svc.get_engine(CID) == ENGINE_DOCX


def test_preview_compiles_without_tex(svc):
    preview = svc.build_preview(CID, "\\section{Skills}\nPython, SQL")
    assert preview.storage_path
    assert preview.page_count >= 1
    assert isinstance(preview.fidelity_ok, bool)


def test_accept_sets_latex_primary(svc):
    assert svc.accept(CID) == ENGINE_LATEX
    assert svc.get_engine(CID) == ENGINE_LATEX


def test_reject_sets_docx_fallback(svc):
    svc.accept(CID)  # accept first
    assert svc.reject(CID) == ENGINE_DOCX
    assert svc.get_engine(CID) == ENGINE_DOCX


def test_choice_persists_per_campaign(store):
    svc1 = ConversionService(latex_tailor=LatexTailor(), config_store=store)
    svc1.accept(CID)
    svc1.reject("other-campaign")
    # New service over same store = restart; choice persists, per campaign.
    svc2 = ConversionService(latex_tailor=LatexTailor(), config_store=store)
    assert svc2.get_engine(CID) == ENGINE_LATEX
    assert svc2.get_engine("other-campaign") == ENGINE_DOCX
