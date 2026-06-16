"""FontService — font upload/management flow (FR-FONT-1/2).

On base-resume upload the engine detects required fonts and reports which are
missing; the user uploads any missing ones; they are installed into the (confined)
conversion environment with a runtime cache refresh (no rebuild), and confirmed
installed. This service orchestrates the FontInstaller adapter for the
``/api/fonts`` endpoints (zero-CLI).
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class FontReport:
    """What a base resume requires vs what is installed (drives the prompt)."""

    required: list[str]
    missing: list[str]
    installed: list[str]


class FontService:
    """Implements the font management flow over the FontInstall port."""

    def __init__(self, font_installer) -> None:
        self._fonts = font_installer

    def report_for_document(self, document_path: str) -> FontReport:
        required = self._fonts.detect_required_fonts(document_path)
        missing = self._fonts.missing_fonts(required)
        installed = [f.name for f in self._fonts.list_fonts()]
        return FontReport(required=required, missing=missing, installed=installed)

    def report_for_fonts(self, required: list[str]) -> FontReport:
        missing = self._fonts.missing_fonts(required)
        installed = [f.name for f in self._fonts.list_fonts()]
        return FontReport(required=required, missing=missing, installed=installed)

    def install(self, font_path: str, name: str) -> FontReport:
        self._fonts.install_font(font_path, name)
        installed = [f.name for f in self._fonts.list_fonts()]
        return FontReport(required=[name], missing=[], installed=installed)

    def list_installed(self) -> list[str]:
        return [f.name for f in self._fonts.list_fonts()]
