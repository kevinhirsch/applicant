"""Tests for ConversionService — LaTeX conversion preview + accept/reject gate (FR-RESUME-3a)."""

from unittest.mock import MagicMock

import pytest

from applicant.application.services.conversion_service import (
    ConversionService,
    ConversionPreview,
    ENGINE_LATEX,
    ENGINE_DOCX,
    _DEFAULT_ENGINE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache():
    """No lru_cache on this module; fixture exists for xdist parallel safety."""
    pass


def _mock_store() -> MagicMock:
    """Build a config_store mock with dict-backed .get() / .set()."""
    m = MagicMock()
    _data: dict[str, dict] = {}

    def _get(key: str) -> dict | None:
        return _data.get(key)

    def _set(key: str, value: dict) -> None:
        _data[key] = value

    m.get.side_effect = _get
    m.set.side_effect = _set
    return m


def _mock_latex(**overrides) -> MagicMock:
    """Build a latex_tailor mock returning a pre-configured render result."""
    result = MagicMock()
    defaults = {
        "storage_path": "/tmp/preview.pdf",
        "page_count": 1,
        "fidelity_ok": True,
        "notes": "",
        "artifact_available": False,
    }
    for k, v in {**defaults, **overrides}.items():
        setattr(result, k, v)
    m = MagicMock()
    m.render_artifact.return_value = result
    return m


def _mock_converter(tex_source: str = "\\begin{document}Hello\\end{document}") -> MagicMock:
    """Build a converter mock returning a result with .tex_source."""
    result = MagicMock()
    result.tex_source = tex_source
    m = MagicMock()
    m.convert_text.return_value = result
    return m


def _svc(
    *, latex=None, store=None, converter=None, tex_source: str = "\\begin{document}Hello\\end{document}"
) -> ConversionService:
    """Convenience: build a ConversionService with reasonable defaults."""
    return ConversionService(
        latex_tailor=latex or _mock_latex(),
        config_store=store or _mock_store(),
        converter=converter or _mock_converter(tex_source=tex_source),
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    """ConversionService accepts injectable dependencies."""

    def test_minimal_construction(self):
        svc = ConversionService(latex_tailor=MagicMock(), config_store=_mock_store())
        assert svc._latex is not None
        assert svc._config is not None
        # Default converter (ModerncvConverter + ResumeParser) is wired when none given
        assert svc._converter is not None

    def test_custom_converter(self):
        custom = MagicMock()
        svc = ConversionService(
            latex_tailor=MagicMock(),
            config_store=_mock_store(),
            converter=custom,
        )
        assert svc._converter is custom


# ---------------------------------------------------------------------------
# Engine choice
# ---------------------------------------------------------------------------


class TestGetEngine:
    """get_engine — per-campaign engine persistence."""

    def test_default_when_no_config(self):
        svc = _svc()
        assert svc.get_engine("camp-1") == _DEFAULT_ENGINE

    def test_returns_stored_value(self):
        store = _mock_store()
        svc = _svc(store=store)
        svc.accept("camp-1")
        assert svc.get_engine("camp-1") == ENGINE_LATEX

    def test_unknown_campaign_returns_default(self):
        svc = _svc()
        svc.accept("camp-a")
        # camp-b has never been set
        assert svc.get_engine("camp-b") == _DEFAULT_ENGINE


class TestAccept:
    """accept — persist latex engine and return it."""

    def test_returns_latex(self):
        svc = _svc()
        assert svc.accept("camp-1") == ENGINE_LATEX

    def test_persists_latex(self):
        store = _mock_store()
        svc = _svc(store=store)
        svc.accept("camp-1")
        # Key is "resume.engine.camp-1"
        store.set.assert_called_once_with("resume.engine.camp-1", {"engine": "latex"})


class TestReject:
    """reject — persist docx engine and return it."""

    def test_returns_docx(self):
        svc = _svc()
        assert svc.reject("camp-1") == ENGINE_DOCX

    def test_persists_docx(self):
        store = _mock_store()
        svc = _svc(store=store)
        svc.reject("camp-1")
        store.set.assert_called_once_with("resume.engine.camp-1", {"engine": "docx"})


class TestEngineCampaignIsolation:
    """Different campaigns have independent engine settings."""

    def test_accept_and_reject_independent(self):
        svc = _svc()
        svc.accept("camp-a")
        svc.reject("camp-b")
        assert svc.get_engine("camp-a") == ENGINE_LATEX
        assert svc.get_engine("camp-b") == ENGINE_DOCX


# ---------------------------------------------------------------------------
# build_preview
# ---------------------------------------------------------------------------


class TestBuildPreview:
    """build_preview — full docx->moderncv conversion + compile preview."""

    def test_returns_conversion_preview(self):
        latex = _mock_latex(
            storage_path="/tmp/out.pdf",
            page_count=3,
            fidelity_ok=True,
            notes="Pages look right",
            artifact_available=True,
        )
        conv = _mock_converter(tex_source="\\documentclass{moderncv}")
        svc = _svc(latex=latex, converter=conv)

        preview = svc.build_preview("camp-x", "raw resume")

        assert isinstance(preview, ConversionPreview)
        assert preview.campaign_id == "camp-x"
        assert preview.storage_path == "/tmp/out.pdf"
        assert preview.page_count == 3
        assert preview.fidelity_ok is True
        assert preview.notes == "Pages look right"
        assert preview.tex_source == "\\documentclass{moderncv}"
        assert preview.artifact_available is True

    def test_calls_converter_with_given_text(self):
        conv = _mock_converter()
        svc = _svc(converter=conv)
        svc.build_preview("c", "hello world")
        conv.convert_text.assert_called_once_with("hello world")

    def test_passes_converted_source_to_latex_tailor(self):
        conv = _mock_converter(tex_source="TEX_OUTPUT")
        latex = _mock_latex()
        svc = _svc(latex=latex, converter=conv)
        svc.build_preview("c", "input")
        call_args = latex.render_artifact.call_args
        assert call_args is not None
        _vid, tex_source = call_args[0]
        assert tex_source == "TEX_OUTPUT"

    def test_generates_uuid4_variant_id(self):
        """The variant id is a fresh UUID4 hex (32 hex chars) — assert shape, not equality."""
        latex = _mock_latex()
        svc = _svc(latex=latex)
        svc.build_preview("c", "input")
        call_args = latex.render_artifact.call_args
        assert call_args is not None
        vid = call_args[0][0]
        assert isinstance(vid, str)
        assert len(vid) == 32
        # All hex characters
        int(vid, 16)

    def test_copies_all_render_result_fields(self):
        latex = _mock_latex(
            storage_path="/custom/path",
            page_count=7,
            fidelity_ok=False,
            notes="Source estimate",
            artifact_available=False,
        )
        svc = _svc(latex=latex)
        preview = svc.build_preview("c", "text")
        assert preview.storage_path == "/custom/path"
        assert preview.page_count == 7
        assert preview.fidelity_ok is False
        assert preview.notes == "Source estimate"
        assert preview.artifact_available is False

    def test_artifact_not_available_by_default(self):
        """The default mock has artifact_available=False; confirm it flows through."""
        latex = _mock_latex(artifact_available=False)
        svc = _svc(latex=latex)
        preview = svc.build_preview("c", "text")
        assert preview.artifact_available is False
