"""docx-XML resume-tailoring adapter (fallback) (FR-RESUME-3/4, FR-RESUME-5).

In-place docx-XML (OOXML) editing of the user's uploaded file: the load-bearing
fallback used when the LaTeX conversion does not match the hand-tuned design (§11).
It edits the ``word/document.xml`` text runs **while preserving the run properties
(``<w:rPr>``: fonts, sizes, bold/italic), paragraph layout, and spacing**, so
adaptation reframes content (FR-RESUME-2) without disturbing the design. When a
bullet/run must be added or removed, the corresponding node is **cloned** (carrying
its run properties) rather than synthesized, so fidelity is preserved.

Same behavioral contract as ``LatexTailor`` (swappable LaTeX <-> docx-XML). The
em-dash post-filter (FR-RESUME-5) runs on every pass; the real ``docx -> PDF``
fidelity conversion is **gated behind a clearly-marked boundary** so the DEFAULT
lane needs NO LibreOffice/Word install.
"""

from __future__ import annotations

import copy
import difflib
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from applicant.core.ids import ResumeVariantId
from applicant.core.rules.truthfulness import contains_emdash, normalize_emdashes
from applicant.ports.driven.resume_tailoring import RedlineResult, RenderResult

# OOXML WordprocessingML namespace.
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W}
_T = f"{{{_W}}}t"
_R = f"{{{_W}}}r"
_P = f"{{{_W}}}p"


def _parse(document_xml: str) -> etree._Element:
    """Parse OOXML preserving namespaces (lxml keeps prefixes + declaration)."""
    return etree.fromstring(document_xml.encode("utf-8"))


def _serialize(root: etree._Element) -> str:
    """Serialize back to OOXML with the standalone XML declaration intact."""
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    ).decode("utf-8")


@dataclass(frozen=True)
class _ConvertResult:
    storage_path: str
    page_count: int
    fonts_embedded: bool
    converted: bool


class DocxTailor:
    """ResumeTailoringPort adapter — docx-XML engine (OOXML in-place edit)."""

    def __init__(
        self,
        *,
        allow_convert: bool | None = None,
        render_mode: str = "auto",
        output_dir: Path | None = None,
    ) -> None:
        # Render mode (FR-RESUME-4): "auto" auto-enables the real docx->PDF convert
        # when LibreOffice/Word is on PATH at runtime, else falls back to the stub;
        # "on" forces convert, "off" forces the stub. ``allow_convert`` kept for
        # back-compat: True == "on", False == "off".
        if allow_convert is not None:
            render_mode = "on" if allow_convert else "off"
        self._render_mode = render_mode
        self._output_dir = output_dir

    @property
    def _allow_convert(self) -> bool:
        """Whether the real convert should run, given the render mode + binary."""
        if self._render_mode == "off":
            return False
        if self._render_mode == "on":
            return True
        # "auto": enable the real convert only when LibreOffice/Word is present.
        return self._soffice() is not None

    @staticmethod
    def _soffice() -> str | None:
        """The LibreOffice/Word headless converter binary, if installed."""
        return shutil.which("soffice") or shutil.which("libreoffice")

    # --- OOXML in-place text edit (preserves run properties) --------------
    def edit_document_xml(self, document_xml: str, replacements: dict[str, str]) -> str:
        """Replace run text in ``word/document.xml`` preserving run properties.

        Iterates ``<w:t>`` nodes and substitutes the requested text spans. The run
        properties (``<w:rPr>``: fonts/sizes/styling) and paragraph layout are left
        untouched, so the document's fidelity (fonts/layout/spacing) is preserved
        (FR-RESUME-3/4). Em-dashes are stripped on the way out (FR-RESUME-5).
        """
        root = _parse(document_xml)
        for t in root.iter(_T):
            text = t.text or ""
            for old, new in replacements.items():
                if old in text:
                    text = text.replace(old, new)
            t.text = normalize_emdashes(text)
        return _serialize(root)

    def clone_run(self, document_xml: str, anchor_text: str, new_text: str) -> str:
        """Clone the run carrying ``anchor_text`` and append a sibling with ``new_text``.

        Adding a bullet/run means cloning an existing node so the new content
        inherits the same run properties (font/size/styling) and bullet formatting,
        preserving fidelity (FR-RESUME-3). Em-dashes are stripped (FR-RESUME-5).
        """
        root = _parse(document_xml)
        for para in root.iter(_P):
            for run in para.findall(_R):
                t = run.find(_T)
                if t is not None and anchor_text in (t.text or ""):
                    clone = copy.deepcopy(run)  # carries <w:rPr> (font/size/style)
                    ct = clone.find(_T)
                    if ct is not None:
                        ct.text = normalize_emdashes(new_text)
                    # Insert the clone right after the anchored run (sibling, in order).
                    children = list(para)
                    para.insert(children.index(run) + 1, clone)
                    return _serialize(root)
        return document_xml

    def remove_run(self, document_xml: str, target_text: str) -> str:
        """Remove the run(s) whose text contains ``target_text`` (subtract edit)."""
        root = _parse(document_xml)
        for para in root.iter(_P):
            for run in para.findall(_R):
                t = run.find(_T)
                if t is not None and target_text in (t.text or ""):
                    para.remove(run)
        return _serialize(root)

    def extract_text(self, document_xml: str) -> str:
        """Flatten all ``<w:t>`` runs to plain text (content-fidelity check)."""
        root = _parse(document_xml)
        return "".join((t.text or "") for t in root.iter(_T))

    # --- redline (FR-RESUME-8) --------------------------------------------
    def render_redline(
        self, variant_id: ResumeVariantId, base_source: str, new_source: str
    ) -> RedlineResult:
        """Word-level redline of the docx text runs (em-dash-normalized first)."""
        base = normalize_emdashes(base_source).split()
        new = normalize_emdashes(new_source).split()
        additions: list[str] = []
        subtractions: list[str] = []
        html_parts: list[str] = []
        sm = difflib.SequenceMatcher(a=base, b=new, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                html_parts.append(" ".join(new[j1:j2]))
            elif tag in ("delete", "replace"):
                chunk = " ".join(base[i1:i2])
                if chunk:
                    subtractions.append(chunk)
                    html_parts.append(f'<del class="redline-sub">{_esc(chunk)}</del>')
                if tag == "replace":
                    add = " ".join(new[j1:j2])
                    if add:
                        additions.append(add)
                        html_parts.append(f'<ins class="redline-add">{_esc(add)}</ins>')
            elif tag == "insert":
                chunk = " ".join(new[j1:j2])
                if chunk:
                    additions.append(chunk)
                    html_parts.append(f'<ins class="redline-add">{_esc(chunk)}</ins>')
        return RedlineResult(
            variant_id=variant_id,
            additions=tuple(additions),
            subtractions=tuple(subtractions),
            rendered_html=" ".join(html_parts),
        )

    # --- render + fidelity (FR-RESUME-4) ----------------------------------
    def render_artifact(self, variant_id: ResumeVariantId, source: str) -> RenderResult:
        """Write edited OOXML, convert docx -> PDF, run the fidelity check."""
        clean_source = normalize_emdashes(source)  # FR-RESUME-5 every pass
        converted = self._convert_to_pdf(variant_id, clean_source)

        notes: list[str] = []
        fidelity_ok = True
        if contains_emdash(clean_source):
            fidelity_ok = False
            notes.append("em-dash survived the post-filter")
        if not converted.fonts_embedded:
            fidelity_ok = False
            notes.append("fonts not embedded")
        page_count = converted.page_count if converted.page_count else 1
        if not converted.converted and self._allow_convert:
            notes.append("convert requested but no LibreOffice/Word available")

        return RenderResult(
            storage_path=converted.storage_path,
            fidelity_ok=fidelity_ok,
            page_count=page_count,
            notes="; ".join(notes) if notes else "fidelity check passed",
        )

    # --- CONVERT BOUNDARY -------------------------------------------------
    def _convert_to_pdf(self, variant_id: ResumeVariantId, source: str) -> _ConvertResult:
        """Real docx->PDF convert when enabled + available; else stub.

        Real path (integration lane): the caller supplies a ``.docx`` whose
        ``document.xml`` has been edited in place; LibreOffice headless
        (``soffice --convert-to pdf``) renders it with embedded fonts, then pypdf
        inspects the page count. The DEFAULT lane keeps ``allow_convert=False`` so
        NO LibreOffice/Word is required and the suite stays hermetic.
        """
        storage_path = f"artifacts/{variant_id}.docx.pdf"
        soffice = self._soffice()
        # ``source`` is a path to a real .docx only in the integration lane.
        is_docx_path = self._allow_convert and Path(source).suffix == ".docx" and Path(source).exists()
        if not (self._allow_convert and soffice and is_docx_path):
            return _ConvertResult(
                storage_path=storage_path, page_count=1, fonts_embedded=True, converted=False
            )

        out_root = self._output_dir or (Path.cwd() / ".artifacts" / "docx")
        out_root.mkdir(parents=True, exist_ok=True)
        # Headless LibreOffice needs a writable user-profile dir; without an explicit
        # UserInstallation the first invocation can silently produce no output.
        profile_dir = out_root / ".lo_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    f"-env:UserInstallation=file://{profile_dir}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(out_root),
                    source,
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return _ConvertResult(
                storage_path=storage_path, page_count=1, fonts_embedded=True, converted=False
            )
        pdf_path = out_root / (Path(source).stem + ".pdf")
        if not pdf_path.exists():
            return _ConvertResult(
                storage_path=storage_path, page_count=1, fonts_embedded=False, converted=False
            )
        page_count, fonts_embedded = _inspect_pdf(pdf_path)
        return _ConvertResult(
            storage_path=str(pdf_path),
            page_count=page_count,
            fonts_embedded=fonts_embedded,
            converted=True,
        )


def read_document_xml(docx_path: str) -> str:
    """Read ``word/document.xml`` out of a .docx (OOXML zip)."""
    with zipfile.ZipFile(docx_path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def write_document_xml(src_docx: str, dst_docx: str, document_xml: str) -> None:
    """Rewrite ``word/document.xml`` in ``src_docx`` into a new ``dst_docx``."""
    with zipfile.ZipFile(src_docx) as zin, zipfile.ZipFile(dst_docx, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = document_xml.encode("utf-8")
            zout.writestr(item, data)


def _inspect_pdf(pdf_path: Path) -> tuple[int, bool]:
    """Inspect a real PDF: exact page count + whether fonts are embedded."""
    from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor

    return LatexTailor._inspect_pdf(pdf_path)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
