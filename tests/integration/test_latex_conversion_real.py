"""Real-compile LaTeX conversion preview (FR-RESUME-3a) — integration only.

The default test lane stubs the xelatex/lualatex compile behind the LatexTailor
seam (no TeX install). This test exercises the real-compile path ONLY when a TeX
engine is actually present, so the hermetic suite never requires fontconfig/TeX.
"""

from __future__ import annotations

import shutil

import pytest

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.conversion_service import ConversionService

_HAS_TEX = shutil.which("lualatex") or shutil.which("xelatex")


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_TEX, reason="No TeX engine (lualatex/xelatex) installed.")
def test_real_latex_conversion_preview_compiles():
    svc = ConversionService(latex_tailor=LatexTailor(), config_store=InMemoryAppConfigStore())
    preview = svc.build_preview("camp-real", "\\section{Skills}\nPython, SQL")
    assert preview.storage_path
    assert preview.page_count >= 1
