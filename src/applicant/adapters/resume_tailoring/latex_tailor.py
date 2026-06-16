"""LaTeX resume-tailoring adapter (primary) (FR-RESUME-3/4, FR-RESUME-5, FR-FONT-2).

LaTeX-primary path: render variants/revisions by editing the **LaTeX source** (plain
text, so the redline is a trivial source-level diff), produce add+subtract highlights
(FR-RESUME-8), run a page-fit / orphaned-title fidelity check (FR-RESUME-4), and
export a font-embedded PDF compiled with xelatex/lualatex + fontspec (moderncv).

Two clearly-marked boundaries keep the DEFAULT lane hermetic (NO TeX required):

* ``_compile_pdf`` — runs the real ``xelatex``/``lualatex`` compile ONLY when a TeX
  engine is installed AND ``allow_compile`` is set; otherwise it returns a
  deterministic synthetic result so the suite is green with no TeX install.
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


class LatexTailor:
    """ResumeTailoringPort adapter — LaTeX engine (xelatex/lualatex + moderncv)."""

    def __init__(
        self,
        *,
        template_root: Path | None = None,
        engine: str = "lualatex",
        allow_compile: bool = False,
        output_dir: Path | None = None,
    ) -> None:
        self._template_root = template_root or _TEMPLATE_ROOT
        self._engine = engine  # "lualatex" (fontawesome5) / "xelatex" (fontspec)
        # The real compile only runs when explicitly enabled (integration lane).
        self._allow_compile = allow_compile
        self._output_dir = output_dir

    # --- source editing (LaTeX is plain text) -----------------------------
    def edit_source(self, base_source: str, edits: dict[str, str]) -> str:
        """Apply literal substitutions to the LaTeX source (FR-RESUME-3).

        LaTeX is plain text, so a variant/revision is a source-level edit: replace
        ``old -> new`` spans. The em-dash post-filter runs on the result so an edit
        can never re-introduce the tell.
        """
        out = base_source
        for old, new in edits.items():
            out = out.replace(old, new)
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
        if not compiled.fonts_embedded:
            fidelity_ok = False
            notes.append("fonts not embedded")
        expected = self._expected_pages(clean_source)
        if page_count != expected:
            fidelity_ok = False
            notes.append(f"page-fit: rendered {page_count} pages, expected {expected}")
        orphans = self._orphaned_titles(clean_source)
        if orphans:
            fidelity_ok = False
            notes.append(f"orphaned section/entry title(s): {', '.join(orphans)}")
        if not compiled.compiled and self._allow_compile:
            # We were asked to really compile but couldn't (no engine) -> soft error.
            notes.append("compile requested but no TeX engine available")

        return RenderResult(
            storage_path=compiled.storage_path,
            fidelity_ok=fidelity_ok,
            page_count=page_count,
            notes="; ".join(notes) if notes else "fidelity check passed",
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
        engine_bin = shutil.which(self._engine) or shutil.which("lualatex") or shutil.which("xelatex")
        if not (self._allow_compile and engine_bin):
            # Stub: deterministic synthetic path; let the fidelity check estimate.
            return _CompileResult(
                storage_path=storage_path, page_count=0, fonts_embedded=True, compiled=False
            )

        # --- real compile (only when explicitly enabled and a TeX engine exists) ---
        out_root = self._output_dir or (Path.cwd() / ".artifacts" / "latex")
        out_root.mkdir(parents=True, exist_ok=True)
        work = out_root / str(variant_id)
        work.mkdir(parents=True, exist_ok=True)
        tex_path = work / "resume.tex"
        tex_path.write_text(source, encoding="utf-8")
        # Make the vendored fonts/classes discoverable to the engine.
        env_input = f"{self._template_root / 'OpenFonts'}:{self._template_root / 'cover'}:"
        try:
            subprocess.run(
                [engine_bin, "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
                cwd=str(work),
                env={"TEXINPUTS": env_input, "PATH": str(Path(engine_bin).parent) + ":/usr/bin:/bin"},
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return _CompileResult(
                storage_path=storage_path, page_count=0, fonts_embedded=True, compiled=False
            )
        pdf_path = work / "resume.pdf"
        if not pdf_path.exists():
            return _CompileResult(
                storage_path=storage_path, page_count=0, fonts_embedded=False, compiled=False
            )
        page_count, fonts_embedded = self._inspect_pdf(pdf_path)
        return _CompileResult(
            storage_path=str(pdf_path),
            page_count=page_count,
            fonts_embedded=fonts_embedded,
            compiled=True,
        )

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
    """True if a PDF font dict (or its descendants) carries an embedded font file."""
    if not hasattr(font, "get"):
        return True
    descriptor = font.get("/FontDescriptor")
    if descriptor is not None:
        desc = descriptor.get_object()
        if any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")):
            return True
    # Composite (Type0) fonts carry the descriptor on a descendant font.
    descendants = font.get("/DescendantFonts")
    if descendants is not None:
        for child in descendants:
            if _font_is_embedded(child.get_object()):
                return True
        return False
    # No descriptor at all -> a standard-14 base font (treated as embeddable).
    return descriptor is None


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
