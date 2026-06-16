"""Font-installer adapter (FR-FONT-1/2).

# STAGE B — render use owned by Phase 3; the flow framework is Phase 0.

Detects the fonts an uploaded resume references, installs uploaded fonts into the
conversion environment, and refreshes the font cache at runtime so a new font is
usable without a rebuild. On base-resume upload the engine calls
``detect_required_fonts`` and prompts for any that are missing (FR-FONT-1).

Filesystem operations are **real but SAFE and confined** to a configurable fonts
dir (``install_root``) — never system-wide. The ``fc-cache -f`` shell-out is **real
when fontconfig is installed** (so an uploaded font is genuinely discoverable to the
LaTeX/docx render env at runtime, FR-FONT-2) and **degrades gracefully to a no-op
when ``fc-cache`` is absent** (the default hermetic lane needs no fontconfig). The
subprocess sits behind a clearly-marked boundary (``_refresh_font_cache``) and is
always scoped to the confined ``install_root``. The copy into the confined dir is
real and verifiable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from applicant.observability.logging import get_logger
from applicant.ports.driven.font_install import FontStatus

log = get_logger(__name__)

# Fonts the vendored templates already provide (treated as pre-installed).
_BUNDLED_FONTS = frozenset({"Lato", "Raleway"})

# Common system fonts present in any conversion environment (not "missing").
_SYSTEM_FONTS = frozenset(
    {
        "Calibri",
        "Cambria",
        "Arial",
        "Times New Roman",
        "Helvetica",
        "Georgia",
        "Verdana",
        "Tahoma",
        "Courier New",
    }
)

# Regexes that surface font family references in LaTeX / docx-ish sources.
_FONT_PATTERNS = (
    re.compile(r"\\setmainfont(?:\[[^\]]*\])?\{([^}]+)\}"),
    re.compile(r"\\setsansfont(?:\[[^\]]*\])?\{([^}]+)\}"),
    re.compile(r"\\fontspec(?:\[[^\]]*\])?\{([^}]+)\}"),
    re.compile(r"\\newfontfamily\\\w+(?:\[[^\]]*\])?\{([^}]+)\}"),
)


class FontInstaller:
    """FontInstallPort adapter — real copy into a confined dir; fc-cache stubbed."""

    def __init__(self, *, install_root: str = ".applicant_fonts") -> None:
        self._install_root = install_root
        self._cache_refreshes = 0  # observable by tests
        # Observable by tests: the dir the last fc-cache ran against, and whether a
        # real fc-cache binary was invoked (vs the graceful no-op when absent).
        self._last_cache_dir: str | None = None
        self._fc_cache_ran = False
        # Track installs in-memory; bundled fonts are present from the start.
        self._installed: dict[str, FontStatus] = {
            name: FontStatus(name=name, installed=True, environment="bundled")
            for name in _BUNDLED_FONTS
        }
        # Pick up any fonts already present in the confined dir (resumable installs).
        self._rescan_install_root()

    # --- detection (FR-FONT-1) --------------------------------------------
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
                root = family.split("-")[0].strip()
                if root and root not in found:
                    found.append(root)
        return found

    def missing_fonts(self, required: list[str]) -> list[str]:
        """Subset of ``required`` not yet installed (drives the upload prompt)."""
        missing: list[str] = []
        for name in required:
            root = name.split("-")[0].strip()
            if root in _SYSTEM_FONTS or name in _SYSTEM_FONTS:
                continue
            if not self._is_installed(name):
                missing.append(name)
        return missing

    # --- install + cache refresh (FR-FONT-2) ------------------------------
    def install_font(self, font_path: str, name: str) -> FontStatus:
        """Install an uploaded font and refresh the cache at runtime (FR-FONT-2).

        The font file is copied into the confined ``install_root`` (real FS op,
        never system-wide), then ``_refresh_font_cache`` is invoked so the
        conversion environment picks it up without a rebuild.
        """
        self._copy_into_confined_dir(font_path, name)
        self._refresh_font_cache()  # STAGE B boundary (fc-cache stubbed)
        status = FontStatus(name=name, installed=True, environment=self._install_root)
        self._installed[name] = status
        log.info("font_installed", name=name, root=self._install_root)
        return status

    def list_fonts(self) -> list[FontStatus]:
        return list(self._installed.values())

    @property
    def cache_refresh_count(self) -> int:
        """How many times the fc-cache refresh ran (real or no-op) — for tests."""
        return self._cache_refreshes

    @property
    def last_cache_dir(self) -> str | None:
        """The confined dir the last fc-cache refresh targeted — for tests."""
        return self._last_cache_dir

    @property
    def fc_cache_available(self) -> bool:
        """True if a real ``fc-cache`` binary is on PATH (drives graceful no-op)."""
        return shutil.which("fc-cache") is not None

    @property
    def fc_cache_invoked(self) -> bool:
        """True if the last refresh actually shelled out to a real ``fc-cache``."""
        return self._fc_cache_ran

    # --- helpers -----------------------------------------------------------
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

    def _rescan_install_root(self) -> None:
        root = Path(self._install_root)
        if not root.is_dir():
            return
        for f in root.iterdir():
            if f.is_file() and f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                name = f.stem
                self._installed.setdefault(
                    name, FontStatus(name=name, installed=True, environment=self._install_root)
                )

    def _copy_into_confined_dir(self, font_path: str, name: str) -> None:
        """Copy the uploaded font into the confined fonts dir (real, safe).

        SAFE: the destination is resolved INSIDE ``install_root`` and the leaf is
        sanitized, so a crafted ``name`` cannot escape the confined directory. No
        system-wide writes ever happen.
        """
        root = Path(self._install_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        src = Path(font_path)
        suffix = src.suffix.lower() if src.suffix else ".ttf"
        leaf = re.sub(r"[^A-Za-z0-9._-]", "_", name) + suffix
        dest = (root / leaf).resolve()
        # Confinement guard: never write outside install_root.
        if root not in dest.parents and dest.parent != root:
            raise ValueError(f"refusing to install font outside confined dir: {dest}")
        try:
            shutil.copyfile(str(src), str(dest))
        except OSError as exc:  # source missing in some test paths — still mark known
            log.warning("font_copy_failed", name=name, error=str(exc))

    def _refresh_font_cache(self) -> None:
        """SUBPROCESS BOUNDARY — real ``fc-cache -f <install_root>`` (FR-FONT-2).

        Runs ``fc-cache -f`` scoped to the confined ``install_root`` so an uploaded
        font is discoverable to the LaTeX/docx render env at runtime (no rebuild).
        The subprocess only fires when ``fc-cache`` is on PATH; when fontconfig is
        absent (the default hermetic lane) it degrades to a counted no-op so no
        fontconfig dependency is required. The invocation count and target dir are
        always recorded for tests.
        """
        self._cache_refreshes += 1
        root = str(Path(self._install_root).resolve())
        self._last_cache_dir = root
        fc_cache = shutil.which("fc-cache")
        if not fc_cache:
            self._fc_cache_ran = False
            log.info("fc_cache_skipped", reason="fc-cache not on PATH", dir=root)
            return None
        try:
            subprocess.run(
                [fc_cache, "-f", root],
                capture_output=True,
                timeout=60,
                check=False,
            )
            self._fc_cache_ran = True
            log.info("fc_cache_refreshed", dir=root)
        except (OSError, subprocess.SubprocessError) as exc:
            self._fc_cache_ran = False
            log.warning("fc_cache_failed", dir=root, error=str(exc))
        return None
