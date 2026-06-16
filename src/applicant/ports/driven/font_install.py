"""FontInstall port (FR-FONT-1/2).

Install uploaded fonts into the conversion environment and refresh the font cache
at runtime (no rebuild). On base-resume upload, detect required fonts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FontStatus:
    name: str
    installed: bool
    environment: str


@runtime_checkable
class FontInstallPort(Protocol):
    """Outbound port for font installation and cache refresh."""

    def detect_required_fonts(self, document_path: str) -> list[str]:
        """Detect fonts a document requires (FR-FONT-1)."""
        ...

    def install_font(self, font_path: str, name: str) -> FontStatus:
        """Install an uploaded font and refresh the cache at runtime (FR-FONT-2)."""
        ...

    def list_fonts(self) -> list[FontStatus]:
        """Return install status of known fonts."""
        ...
