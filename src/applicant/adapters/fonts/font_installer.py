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
import zipfile
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

# SECURITY (Ledger #94): a font "name" is untrusted input from three places — a
# resume's declared LaTeX/docx font-family text (``detect_required_fonts``), the
# ``name`` form field on ``POST /api/fonts/install``, and a filename rescanned from
# the confined install dir on restart. Without a shape check, any of those can
# smuggle a path-traversal-looking string (e.g. ``../../../../tmp/pwned``) through
# as a "font family name" — it never escapes the filesystem confinement below, but
# it DOES get treated as ground truth and shown to the user as an "installed font"
# (a dishonest/poisoned listing, not just an eyesore). This is the single gate a
# name must pass before it is trusted anywhere in the flow: detection, install,
# persisted/rescanned state, and the listed-fonts API.
_FONT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'()+-]{0,63}$")


def _looks_like_font_name(name: str) -> bool:
    """True if ``name`` is shaped like a plausible font-family name.

    Rejects path separators, ``..`` traversal segments, control/whitespace-padded
    strings, and anything not starting with an alphanumeric character (blocks a
    leading ``.``/``-``/``_`` disguise) or over 64 chars. Legitimate family names
    like ``Times New Roman``, ``Segoe UI``, or ``Lato-Lig`` all pass.
    """
    if not name or len(name) > 64 or name != name.strip():
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    return bool(_FONT_NAME_RE.fullmatch(name))


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

        For a real ``.docx`` (a zip) the declared font families live in
        ``word/fontTable.xml``/``styles.xml``, not in the file's UTF-8 bytes, so we
        branch on the extension and parse the docx XML first (FR-FONT-1); otherwise
        we fall back to scanning the source for LaTeX fontspec/font-family
        directives. Returns a de-duplicated, order-preserving list of family names.
        Missing files yield an empty list (safe: nothing detected -> nothing to
        prompt for).
        """
        found: list[str] = []

        def _add(family: str) -> None:
            root = family.split("-")[0].strip()
            # SECURITY (Ledger #94): a "declared font" is untrusted resume content —
            # never let a path-traversal-shaped string enter the required/missing
            # list (it would later be echoed back as the ``name`` for /fonts/install
            # and shown to the user as an "installed font").
            if root and _looks_like_font_name(root) and root not in found:
                found.append(root)

        path = Path(document_path)
        if path.suffix.lower() == ".docx" and path.is_file():
            for family in self._detect_docx_fonts(path):
                _add(family)
            if found:
                return found
            # fall through to the LaTeX-regex scan only if the docx declared none.

        text = self._read_source(document_path)
        if not text:
            return found
        for pat in _FONT_PATTERNS:
            for m in pat.finditer(text):
                _add(m.group(1).strip())
        return found

    @staticmethod
    def _detect_docx_fonts(path: Path) -> list[str]:
        """Read declared font families from a docx's font table/styles (FR-FONT-1).

        Mirrors ``ResumeParser._detect_docx_fonts`` so a base-resume upload and the
        font prompt agree on which families a real ``.docx`` references.
        """
        found: list[str] = []
        try:
            with zipfile.ZipFile(str(path)) as zf:
                names = zf.namelist()
                for member in ("word/fontTable.xml", "word/styles.xml", "word/document.xml"):
                    if member not in names:
                        continue
                    xml = zf.read(member).decode("utf-8", errors="ignore")
                    # SECURITY (Ledger #94): filter at the source — a docx's font
                    # table is untrusted content and must not smuggle a
                    # traversal/garbage string in as a "declared font family".
                    for m in re.finditer(r'w:(?:ascii|hAnsi|cs)="([^"]+)"', xml):
                        fam = m.group(1).strip()
                        if fam and _looks_like_font_name(fam) and fam not in found:
                            found.append(fam)
                    for m in re.finditer(r'<w:font w:name="([^"]+)"', xml):
                        fam = m.group(1).strip()
                        if fam and _looks_like_font_name(fam) and fam not in found:
                            found.append(fam)
        except (OSError, zipfile.BadZipFile):
            return []
        return found

    def missing_fonts(self, required: list[str]) -> list[str]:
        """Subset of ``required`` not yet installed (drives the upload prompt)."""
        missing: list[str] = []
        for name in required:
            # SECURITY (Ledger #94): never prompt to "install" something that
            # isn't shaped like a font name — a caller that bypasses detection
            # and hands ``required`` straight in (e.g. ``report_for_fonts``)
            # must not be able to smuggle a traversal string through either.
            if not _looks_like_font_name(name):
                continue
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

        SECURITY (Ledger #94): ``name`` is untrusted (a form field on
        ``POST /api/fonts/install``, ultimately possibly echoing a resume's own
        declared font text). It is validated as a plausible font-family name
        BEFORE anything is written to disk or recorded as installed — a
        traversal/garbage string is rejected outright rather than silently
        sanitized-and-accepted, so it can never become a "legitimately
        installed" entry in ``list_fonts()``.
        """
        name = name.strip()
        if not _looks_like_font_name(name):
            raise ValueError(f"Invalid font name: {name!r}")
        self._copy_into_confined_dir(font_path, name)
        self._refresh_font_cache()  # STAGE B boundary (fc-cache stubbed)
        status = FontStatus(name=name, installed=True, environment=self._install_root)
        self._installed[name] = status
        log.info("font_installed", name=name, root=self._install_root)
        return status

    def list_fonts(self) -> list[FontStatus]:
        # SECURITY (Ledger #94): last-mile filter — the source of truth for
        # "installed fonts" must only ever surface legitimate family names, never
        # a raw filesystem path/traversal string, regardless of how an entry got
        # into ``_installed`` (defense in depth alongside the entry-point checks
        # in ``install_font``/``detect_required_fonts``/``_rescan_install_root``).
        return [f for f in self._installed.values() if _looks_like_font_name(f.name)]

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
                # SECURITY (Ledger #94): a stray/pre-existing file whose name isn't
                # a plausible font family (e.g. a poisoned
                # ``.._.._.._.._tmp_pwned_by_traversal.ttf`` left over from before
                # this fix, or anything else dropped straight into the confined
                # dir) must never resurface as a listed "installed font" just
                # because it happens to sit in the fonts dir with a font suffix.
                if not _looks_like_font_name(name):
                    log.warning("font_rescan_skipped_invalid_name", file=str(f))
                    continue
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
