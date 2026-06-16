"""Font-installer adapter (FR-FONT-1/2).

# STAGE B — owned by Phase 3 (render use; flow framework Phase 0).

Detects the fonts an uploaded resume references, installs uploaded fonts into the
conversion environment, and refreshes the font cache at runtime (``fc-cache -f``)
so a new font is usable without a rebuild. On base-resume upload the engine calls
``detect_required_fonts`` and prompts for any that are missing.

The actual filesystem copy + ``fc-cache`` invocation is **stubbed behind a clearly
marked boundary** so the suite never touches the real font dirs or shells out.
"""

from __future__ import annotations

import re
from pathlib import Path

from applicant.ports.driven.font_install import FontStatus

# Fonts the vendored templates already provide (treated as pre-installed).
_BUNDLED_FONTS = frozenset({"Lato", "Raleway"})

# Regexes that surface font family references in LaTeX / docx-ish sources.
_FONT_PATTERNS = (
    re.compile(r"\\setmainfont(?:\[[^\]]*\])?\{([^}]+)\}"),
    re.compile(r"\\setsansfont(?:\[[^\]]*\])?\{([^}]+)\}"),
    re.compile(r"\\fontspec(?:\[[^\]]*\])?\{([^}]+)\}"),
    re.compile(r"\\newfontfamily\\\w+(?:\[[^\]]*\])?\{([^}]+)\}"),
)


class FontInstaller:
    """FontInstallPort adapter (filesystem ops stubbed safely)."""

    def __init__(self, *, install_root: str = "/usr/share/fonts/applicant") -> None:
        self._install_root = install_root
        # Track installs in-memory; bundled fonts are present from the start.
        self._installed: dict[str, FontStatus] = {
            name: FontStatus(name=name, installed=True, environment="bundled")
            for name in _BUNDLED_FONTS
        }

    def detect_required_fonts(self, document_path: str) -> list[str]:
        """Detect font families referenced by a document (FR-FONT-1).

        Parses the source for fontspec/font-family directives. Returns a
        de-duplicated, order-preserving list of family names. Missing files yield
        an empty list (safe: nothing detected -> nothing to prompt for).
        """
        text = self._read_source(document_path)
        if not text:
            return []
        found: list[str] = []
        for pat in _FONT_PATTERNS:
            for m in pat.finditer(text):
                family = m.group(1).strip()
                # Strip a leading "Lato-Lig" weight suffix down to the family root.
                root = family.split("-")[0].strip()
                if root and root not in found:
                    found.append(root)
        return found

    def missing_fonts(self, required: list[str]) -> list[str]:
        """Subset of ``required`` not yet installed (drives the upload prompt)."""
        return [name for name in required if not self._is_installed(name)]

    def install_font(self, font_path: str, name: str) -> FontStatus:
        """Install an uploaded font and refresh the cache at runtime (FR-FONT-2)."""
        self._copy_and_refresh(font_path, name)  # STAGE B boundary
        status = FontStatus(name=name, installed=True, environment=self._install_root)
        self._installed[name] = status
        return status

    def list_fonts(self) -> list[FontStatus]:
        return list(self._installed.values())

    # --- helpers / boundary ------------------------------------------------
    def _is_installed(self, name: str) -> bool:
        root = name.split("-")[0].strip()
        return root in self._installed or name in self._installed

    def _read_source(self, document_path: str) -> str:
        try:
            p = Path(document_path)
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        return ""

    def _copy_and_refresh(self, font_path: str, name: str) -> None:
        """STAGE B BOUNDARY — real copy into the font dir + ``fc-cache -f``.

        A real install would copy ``font_path`` into ``self._install_root`` and run
        ``fc-cache -f`` so the conversion environment picks the font up at runtime
        (no rebuild). Stubbed: no filesystem writes, no subprocess.
        """
        return None
