"""Font-installer adapter (FR-FONT-1/2).

# STAGE B — owned by Phase 3 (render use; flow framework Phase 0); flesh out here.

Installs uploaded fonts into the conversion environment and refreshes the font
cache at runtime (fc-cache), and detects fonts required by an uploaded resume.
"""

from __future__ import annotations

from applicant.ports.driven.font_install import FontStatus


class FontInstaller:
    """FontInstallPort adapter (stub until Phase 3)."""

    def detect_required_fonts(self, document_path: str) -> list[str]:
        # STAGE B: parse document for referenced font families.
        return []

    def install_font(self, font_path: str, name: str) -> FontStatus:
        raise NotImplementedError("STAGE B — Phase 3: install font + fc-cache refresh.")

    def list_fonts(self) -> list[FontStatus]:
        return []
