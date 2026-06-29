"""LaTeX resume-tailoring adapter (primary) (FR-RESUME-3/4, FR-RESUME-5, FR-FONT-2).

LaTeX-primary path: render variants/revisions by editing the **LaTeX source** (plain
text, so the redline is a trivial source-level diff), produce add+subtract highlights
(FR-RESUME-8), run a page-fit / orphaned-title fidelity check (FR-RESUME-4), and
export a font-embedded PDF compiled with xelatex/lualatex + fontspec (moderncv).

Two clearly-marked boundaries keep the DEFAULT lane hermetic (NO TeX required):

* ``_compile_pdf`` — runs the real ``xelatex``/``lualatex`` compile when the render
  mode permits it AND a TeX engine is installed. In the default ``render_mode="auto"``
  the real compile auto-enables whenever a TeX engine is on PATH at runtime (so prod
  uses the real compile-and-inspect fidelity check, FR-RESUME-4), and degrades to a
  deterministic synthetic result when no engine is present so the suite is green with
  no TeX install.
* ``_inspect_pdf`` — when a real PDF exists it is inspected with ``pypdf`` (exact
  page count + font-embedding); otherwise the fidelity check models the inspection
  deterministically on the source so "looks fine in source is not acceptable" still
  has something concrete to assert against.

The em-dash deterministic post-filter and the truthfulness guardrail run on every
pass (``core.rules.truthfulness``), so no adapter can emit an em-dash tell.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from applicant.core.ids import ResumeVariantId
from applicant.core.rules.truthfulness import contains_emdash, normalize_emdashes
from applicant.ports.driven.resume_tailoring import RedlineResult, RenderResult

# Repo-root-relative location of the vendored LaTeX assets (templates/latex/...).
_TEMPLATE_ROOT = Path(__file__).resolve().parents[4] / "templates" / "latex"

# Heuristic line budgets for the page-fit check (FR-RESUME-4). A moderncv page fits
# roughly this many source body lines; a cover letter is exactly one page.
_LINES_PER_PAGE = 55


@dataclass(frozen=True)
class _CompileResult:
    """Output of the TeX compile boundary."""

    storage_path: str
    page_count: int  # 0 means "compile stubbed; estimate from source"
    fonts_embedded: bool
    compiled: bool  # True if a real PDF was produced
    # True when the real compile was attempted (engine present + enabled) but no PDF
    # came out — distinguishes "no engine installed" from "engine ran but failed", so
    # the user-facing note can be honest and actionable instead of misleading.
    compile_failed: bool = False


class LatexTailor:
    """ResumeTailoringPort adapter — LaTeX engine (xelatex/lualatex + moderncv)."""

    def __init__(
        self,
        *,
        template_root: Path | None = None,
        engine: str = "lualatex",
        allow_compile: bool | None = None,
        render_mode: str = "auto",
        output_dir: Path | None = None,
    ) -> None:
        self._template_root = template_root or _TEMPLATE_ROOT
        self._engine = engine  # "lualatex" (fontawesome5) / "xelatex" (fontspec)
        # Render mode (FR-RESUME-4): "auto" auto-enables the real compile when a TeX
        # engine is on PATH at runtime, else falls back to the deterministic stub;
        # "on" forces compile (and soft-errors if no engine); "off" forces the stub.
        # ``allow_compile`` is kept for back-compat: True == "on", False == "off".
        if allow_compile is not None:
            render_mode = "on" if allow_compile else "off"
        self._render_mode = render_mode
        self._output_dir = output_dir

    @property
    def _allow_compile(self) -> bool:
        """Whether the real compile should run, given the render mode + engine."""
        if self._render_mode == "off":
            return False
        if self._render_mode == "on":
            return True
        # "auto": enable the real compile only when a TeX engine is actually present.
        return self._tex_engine() is not None

    def _tex_engine(self) -> str | None:
        """The TeX engine binary to use, preferring the configured one."""
        return (
            shutil.which(self._engine)
            or shutil.which("lualatex")
            or shutil.which("xelatex")
        )

    def _compile_env(self, engine_bin: str, work: Path) -> dict[str, str]:
        """Build the subprocess env for the TeX compile.

        Starts from a copy of ``os.environ`` so HOME/TEXMFVAR/etc. survive — the
        old code replaced the entire env with only TEXINPUTS+PATH, which broke the
        xelatex/lualatex first-run cache build (it needs HOME/TEXMFVAR to write the
        font cache). The vendored asset dirs are PREPENDED to any existing
        TEXINPUTS, keeping the trailing ``:`` so the engine still searches the
        default tree. PATH keeps the engine's own bin dir plus the inherited PATH.

        Crucially, xelatex/lualatex build a font/format cache on first run and abort
        (producing NO PDF) when they cannot write it. In the engine container the
        service user often has no writable HOME and TEXMFVAR/TEXMFCACHE are unset, so
        we point HOME + the TeX cache vars at a writable scratch dir under the compile
        work tree. That makes the real compile reliable on the deploy image instead of
        silently degrading to the source-estimate stub.
        """
        import os

        env = os.environ.copy()
        vendored = f"{self._template_root / 'OpenFonts'}:{self._template_root / 'cover'}:"
        existing_texinputs = env.get("TEXINPUTS", "")
        # Prepend vendored dirs; trailing ':' (in ``vendored``) preserves the
        # default search tree even when there is no pre-existing TEXINPUTS.
        env["TEXINPUTS"] = vendored + existing_texinputs
        engine_dir = str(Path(engine_bin).parent)
        inherited_path = env.get("PATH", "")
        env["PATH"] = (
            f"{engine_dir}:{inherited_path}" if inherited_path else f"{engine_dir}:/usr/bin:/bin"
        )
        # Guarantee a writable cache so the first-run font/format cache build does not
        # abort the compile when the container HOME is unset/read-only.
        cache = work / ".texcache"
        cache.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(cache)
        env["TEXMFVAR"] = str(cache)
        env["TEXMFCACHE"] = str(cache)
        env["FONTCONFIG_PATH"] = env.get("FONTCONFIG_PATH", "/etc/fonts")
        return env

    def _link_vendored_fonts(self, work: Path) -> None:
        """Make the vendored ``OpenFonts/`` tree reachable from the compile cwd.

        cover.cls loads fonts via a path relative to the working directory; the
        compile happens in a temp dir, so we expose OpenFonts there. Prefer a
        symlink (cheap); fall back to a copy when symlinks are unavailable (e.g.
        some container filesystems). Best-effort: a failure here just means the
        cover compile degrades to the stub, never a crash.
        """
        src = self._template_root / "OpenFonts"
        dst = work / "OpenFonts"
        if not src.is_dir() or dst.exists():
            return
        try:
            dst.symlink_to(src, target_is_directory=True)
        except (OSError, NotImplementedError):
            try:
                import shutil as _shutil

                _shutil.copytree(src, dst)
            except OSError:  # pragma: no cover - never let asset wiring break render
                pass

    # --- source editing (LaTeX is plain text) -----------------------------
    def edit_source(self, base_source: str, edits: dict[str, str]) -> str:
        """Apply literal substitutions to the LaTeX source (FR-RESUME-3).

        LaTeX is plain text, so a variant/revision is a source-level edit: replace
        ``old -> new`` spans. The em-dash post-filter runs on the result so an edit
        can never re-introduce the tell.

        SECURITY: the *substituted CONTENT* (``new``) is generated/edited resume
        text, not template control sequences, so it is LaTeX-escaped before being
        written into the source. This stops content like ``\\input{...}``/``%``/
        ``&`` from being interpreted as TeX (content injection into the compiled
        .tex — note ``-shell-escape`` stays OFF). Only the values are escaped; the
        ``old`` anchors (template control sequences) are matched verbatim.
        """
        from applicant.adapters.resume_tailoring.moderncv_converter import latex_escape

        out = base_source
        for old, new in edits.items():
            out = out.replace(old, latex_escape(new))
        return normalize_emdashes(out)

    # --- redline (FR-RESUME-8) --------------------------------------------
    def render_redline(
        self, variant_id: ResumeVariantId, base_source: str, new_source: str
    ) -> RedlineResult:
        """Deterministic source-level redline of ``new_source`` vs ``base_source``.

        Both sides are em-dash-normalized first (FR-RESUME-5) so the diff never
        flags a stripped dash as a content change. Additions/subtractions are
        per-line; ``rendered_html`` highlights them (consumed by review.js).
        """
        base = normalize_emdashes(base_source)
        new = normalize_emdashes(new_source)
        base_lines = base.splitlines()
        new_lines = new.splitlines()

        additions: list[str] = []
        subtractions: list[str] = []
        html_parts: list[str] = []
        sm = difflib.SequenceMatcher(a=base_lines, b=new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for line in new_lines[j1:j2]:
                    html_parts.append(f'<span class="redline-eq">{_esc(line)}</span>')
            elif tag == "delete":
                for line in base_lines[i1:i2]:
                    subtractions.append(line)
                    html_parts.append(f'<del class="redline-sub">{_esc(line)}</del>')
            elif tag == "insert":
                for line in new_lines[j1:j2]:
                    additions.append(line)
                    html_parts.append(f'<ins class="redline-add">{_esc(line)}</ins>')
            elif tag == "replace":
                for line in base_lines[i1:i2]:
                    subtractions.append(line)
                    html_parts.append(f'<del class="redline-sub">{_esc(line)}</del>')
                for line in new_lines[j1:j2]:
                    additions.append(line)
                    html_parts.append(f'<ins class="redline-add">{_esc(line)}</ins>')

        return RedlineResult(
            variant_id=variant_id,
            additions=tuple(additions),
            subtractions=tuple(subtractions),
            rendered_html="\n".join(html_parts),
        )

    # --- cover letter (FR-RESUME-10) --------------------------------------
    def build_cover_source(
        self,
        *,
        first_name: str = "",
        last_name: str = "",
        contact_line: str = "",
        date: str = "",
        company: str = "",
        company_address: str = "",
        body_paragraphs: list[str] | None = None,
        closing: str = "Sincerely,",
        signature: str = "",
    ) -> str:
        """Build a one-page cover-letter LaTeX source from cover.cls (FR-RESUME-10).

        Renders the vendored ``cover.cls`` commands deterministically (no template
        engine dependency) from TRUTHFUL, voice-matched body text. The em-dash
        post-filter runs on every field so the cover letter carries no tell, and the
        ``\\documentclass[]{cover}`` marker makes the fidelity check enforce exactly
        one page (FR-RESUME-4).
        """
        paras = [normalize_emdashes(p) for p in (body_paragraphs or []) if p.strip()]
        lines = [
            "\\documentclass[]{cover}",
            "\\begin{document}",
            f"\\namesection{{{normalize_emdashes(first_name)}}}"
            f"{{{normalize_emdashes(last_name)}}}{{{normalize_emdashes(contact_line)}}}",
            f"\\currentdate{{{normalize_emdashes(date)}}}",
            f"\\companyname{{{normalize_emdashes(company)}}}",
            f"\\companyaddress{{{normalize_emdashes(company_address)}}}",
        ]
        lines += [f"\\lettercontent{{{p}}}" for p in paras]
        lines += [
            f"\\closing{{{normalize_emdashes(closing)}}}",
            f"\\signature{{{normalize_emdashes(signature)}}}",
            "\\end{document}",
        ]
        return "\n".join(lines)

    # --- render + fidelity (FR-RESUME-4) ----------------------------------
    def render_artifact(self, variant_id: ResumeVariantId, source: str) -> RenderResult:
        """Compile a font-embedded PDF and run the compile-and-inspect fidelity check.

        "Looks fine in source is not acceptable" (voice-and-truthfulness §5): the
        check verifies the artifact compiles, fits its exact page budget, embeds
        fonts, carries no orphaned section/entry title, and is em-dash-free.
        """
        # Em-dash post-filter runs on every render pass (FR-RESUME-5).
        clean_source = normalize_emdashes(source)

        compiled = self._compile_pdf(variant_id, clean_source)

        notes: list[str] = []
        # Prefer the real compiled page count; otherwise model it on the source.
        page_count = compiled.page_count if compiled.page_count else self._estimate_pages(clean_source)

        fidelity_ok = True
        if contains_emdash(clean_source):  # defensive: post-filter must have run
            fidelity_ok = False
            notes.append("em-dash survived the post-filter")
        # Only judge font embedding against a PDF we actually produced. When the
        # compile was stubbed or failed there is no PDF to inspect, so reporting
        # "fonts not embedded" would be misleading — the real story is told below.
        if compiled.compiled and not compiled.fonts_embedded:
            fidelity_ok = False
            notes.append("Some fonts in the rendered PDF are not embedded.")
        expected = self._expected_pages(clean_source)
        if page_count != expected:
            fidelity_ok = False
            notes.append(f"Layout check: rendered {page_count} page(s), expected {expected}.")
        orphans = self._orphaned_titles(clean_source)
        if orphans:
            fidelity_ok = False
            notes.append(f"A section heading may be stranded at a page break: {', '.join(orphans)}.")
        if compiled.compile_failed:
            # The render tools ARE installed but the compile produced no PDF (template
            # or environment problem). This is a real fidelity miss — flag it honestly
            # and point at the fix (white-labeled, no TeX/FR jargon).
            fidelity_ok = False
            notes.append(
                "We couldn't produce the polished PDF, so this is an approximate preview. "
                "If this keeps happening, rebuild the engine so the document tools are up to date."
            )
        elif not compiled.compiled and self._allow_compile:
            # Engine was requested but no render tools were found at runtime.
            fidelity_ok = False
            notes.append(
                "The document tools needed to build the polished PDF aren't available, so this is "
                "an approximate preview. Rebuild the engine to enable high-fidelity rendering."
            )

        return RenderResult(
            storage_path=compiled.storage_path,
            fidelity_ok=fidelity_ok,
            page_count=page_count,
            notes="; ".join(notes) if notes else "Looks like a faithful match.",
        )

    # --- COMPILE BOUNDARY -------------------------------------------------
    def _compile_pdf(self, variant_id: ResumeVariantId, source: str) -> _CompileResult:
        """Real xelatex/lualatex compile when enabled + available; else stub.

        Real path (integration lane): write ``source`` to a temp dir alongside the
        vendored ``OpenFonts/`` + ``cover.cls``, invoke ``self._engine`` with
        fontspec, then inspect the produced PDF (page count + font embedding) via
        ``_inspect_pdf``. The DEFAULT lane keeps ``allow_compile=False`` so NO TeX
        is required and the suite stays hermetic.
        """
        storage_path = f"artifacts/{variant_id}.pdf"
        engine_bin = self._tex_engine()
        if not (self._allow_compile and engine_bin):
            # No engine on PATH (or render disabled): deterministic synthetic path;
            # let the fidelity check estimate. NOT a failure — nothing was attempted.
            return _CompileResult(
                storage_path=storage_path, page_count=0, fonts_embedded=True, compiled=False
            )

        # --- real compile (only when explicitly enabled and a TeX engine exists) ---
        out_root = self._output_dir or (Path.cwd() / ".artifacts" / "latex")
        out_root.mkdir(parents=True, exist_ok=True)
        # ``variant_id`` is an opaque id, but treat it as untrusted: a value carrying
        # path separators / ``..`` could otherwise make ``work`` (and the resume.tex
        # written into it below) escape ``out_root`` and clobber an arbitrary file
        # (path traversal / file inclusion). Contain it to a per-variant subdir.
        out_root_real = out_root.resolve()
        work = (out_root_real / str(variant_id)).resolve()
        try:
            work.relative_to(out_root_real)
        except ValueError as exc:
            raise ValueError(
                f"refusing résumé artifact path outside {out_root_real}: "
                f"variant_id {variant_id!r} escapes the output dir"
            ) from exc
        work.mkdir(parents=True, exist_ok=True)
        # The cover-letter class loads its bundled fonts via a path RELATIVE to the
        # compile cwd (``\setmainfont[Path = OpenFonts/fonts/...]``). The compile runs
        # in this temp work dir, so make the vendored OpenFonts tree reachable here
        # (symlink, copy fallback) — otherwise fontspec aborts with "font cannot be
        # found" and no PDF is produced. Harmless for the résumé path, which uses
        # system fonts. (TEXINPUTS already exposes cover.cls; only files loaded by an
        # explicit relative Path need to sit next to the cwd.)
        self._link_vendored_fonts(work)
        tex_path = work / "resume.tex"
        tex_path.write_text(source, encoding="utf-8")

        # Try the preferred engine, then the other one — moderncv/fontspec quirks make
        # one of xelatex/lualatex succeed where the other aborts, and falling back is
        # far better than degrading to the no-real-PDF estimate.
        pdf_path = work / "resume.pdf"
        for engine_bin in self._engine_candidates():
            try:
                subprocess.run(
                    [engine_bin, "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
                    cwd=str(work),
                    env=self._compile_env(engine_bin, work),
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if pdf_path.exists():
                page_count, fonts_embedded = self._inspect_pdf(pdf_path)
                return _CompileResult(
                    storage_path=str(pdf_path),
                    page_count=page_count,
                    fonts_embedded=fonts_embedded,
                    compiled=True,
                )

        # Engine(s) ran but produced no PDF — a real compile FAILURE (template/asset
        # issue or unwritable cache), not "no engine installed". Surface the captured
        # log so the deploy operator can diagnose it from the engine output.
        self._log_compile_failure(work, source)
        return _CompileResult(
            storage_path=storage_path,
            page_count=0,
            fonts_embedded=False,
            compiled=False,
            compile_failed=True,
        )

    def _engine_candidates(self) -> list[str]:
        """Resolved engine binaries to try, preferred first, de-duplicated."""
        import shutil as _shutil

        seen: set[str] = set()
        ordered: list[str] = []
        for name in (self._engine, "lualatex", "xelatex"):
            resolved = _shutil.which(name)
            if resolved and resolved not in seen:
                seen.add(resolved)
                ordered.append(resolved)
        return ordered

    def _log_compile_failure(self, work: Path, source: str) -> None:
        """Emit the tail of the TeX log when a real compile produced no PDF.

        Silent degradation hides WHY the deploy image fell back to the estimate; the
        log tail (or its absence) is the single most useful diagnostic for an operator
        triaging a missing-PDF report.
        """
        try:
            from applicant.observability.logging import get_logger

            log = get_logger(__name__)
            tex_log = work / "resume.log"
            tail = ""
            if tex_log.exists():
                tail = "\n".join(tex_log.read_text(errors="replace").splitlines()[-25:])
            log.warning(
                "resume_compile_failed",
                work_dir=str(work),
                log_tail=tail or "(no resume.log produced — engine never started)",
                source_head=source[:200],
            )
        except Exception:  # pragma: no cover - diagnostics must never break render
            pass

    @staticmethod
    def _inspect_pdf(pdf_path: Path) -> tuple[int, bool]:
        """Inspect a real PDF: exact page count + whether fonts are embedded.

        Uses pypdf (already a dependency). A font is "embedded" when its descriptor
        carries a FontFile/FontFile2/FontFile3 stream — exactly the fidelity-check
        guarantee (FR-RESUME-4, FR-FONT-2).
        """
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        fonts_embedded = True
        for page in reader.pages:
            resources = page.get("/Resources")
            if not resources:
                continue
            fonts = resources.get("/Font") if hasattr(resources, "get") else None
            if not fonts:
                continue
            for font_ref in fonts.values():
                font = font_ref.get_object()
                if not _font_is_embedded(font):
                    fonts_embedded = False
        return page_count, fonts_embedded

    # --- page-fit + orphan heuristics -------------------------------------
    def _estimate_pages(self, source: str) -> int:
        body = self._body_lines(source)
        if not body:
            return 1
        return max(1, -(-len(body) // _LINES_PER_PAGE))  # ceil division

    def _expected_pages(self, source: str) -> int:
        """Expected exact page count: cover letters are 1 page, resumes 1-2."""
        if "\\documentclass[]{cover}" in source or "\\namesection" in source:
            return 1
        return self._estimate_pages(source)

    def _orphaned_titles(self, source: str) -> list[str]:
        """Flag a \\section whose body would spill to the next page (no \\needspace).

        Heuristic: a ``\\section`` landing in the last two source lines of a page
        with no ``\\needspace`` guard preceding it risks an orphaned title.
        """
        lines = self._body_lines(source)
        orphans: list[str] = []
        for idx, line in enumerate(lines):
            m = re.search(r"\\section\{([^}]*)\}", line)
            if not m:
                continue
            pos_in_page = idx % _LINES_PER_PAGE
            near_bottom = pos_in_page >= _LINES_PER_PAGE - 2
            guarded = idx > 0 and "\\needspace" in lines[idx - 1]
            if near_bottom and not guarded:
                orphans.append(m.group(1))
        return orphans

    @staticmethod
    def _body_lines(source: str) -> list[str]:
        return [ln for ln in source.splitlines() if ln.strip() and not ln.lstrip().startswith("%")]


def _font_is_embedded(font: object) -> bool:
    """True ONLY if a PDF font dict (or its descendants) carries an embedded file.

    Conservative (FR-RESUME-4, FR-FONT-2): the fidelity guarantee is that EVERY
    font ships its own file. The old check returned True when a font carried no
    descriptor ("standard-14 base font") and when a descriptor existed but had no
    ``/FontFile*`` stream — both are NON-embedded fonts and were false positives.
    We now require an actual ``/FontFile``/``/FontFile2``/``/FontFile3`` stream.
    """
    if not hasattr(font, "get"):
        # Unknown shape: cannot prove embedding -> treat as NOT embedded.
        return False
    descriptor = font.get("/FontDescriptor")
    if descriptor is not None:
        desc = descriptor.get_object()
        if any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")):
            return True
        # Descriptor present but no font file stream -> NOT embedded.
        return False
    # Composite (Type0) fonts carry the descriptor on a descendant font.
    descendants = font.get("/DescendantFonts")
    if descendants is not None:
        # Every descendant must be embedded for the composite font to count.
        children = list(descendants)
        return bool(children) and all(
            _font_is_embedded(child.get_object()) for child in children
        )
    # No descriptor and no descendants -> a standard-14 base font referenced by
    # name, which is NOT embedded.
    return False


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
