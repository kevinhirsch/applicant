"""Regression coverage for exhaustive-audit-pass-2 lens 12 (help &
self-explainability) finding #48, confined to
``static/js/applicantGallery.js``.

Follows the convention of ``test_applicant_debug_help_lens12.py``: every fact
is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket. Each assertion was hand-verified to go red
when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Finding covered (see ``docs/design/audits/exhaustive2/12_help_selfexplain.md``):
  * #48 — Compare's modal has an explainer intro line at the top of its
    modal body ("Put two or more applications or postings side-by-side to
    see exactly where they differ."), but Gallery's modal body had no intro
    explaining what the Gallery shows or why. Gallery's modal scaffold now
    renders a plain-language intro ``<p>`` right after the header and before
    the job-search picker, matching Compare's placement and style.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
GALLERY_JS = JS_DIR / "applicantGallery.js"
COMPARE_JS = JS_DIR / "applicantCompare.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_gallery_modal_has_an_intro_paragraph_before_the_campaign_picker():
    """The Gallery modal scaffold must render an intro <p> before the
    job-search <select>, mirroring Compare's explainer line placed at the
    top of its modal body."""
    js = _read(GALLERY_JS)
    header_idx = js.index("Application Gallery")
    picker_idx = js.index('id="applicant-gallery-campaign"')
    assert header_idx < picker_idx, "sanity: header must precede the picker"
    window = js[header_idx:picker_idx]
    m = re.search(r"<p[^>]*>(.*?)</p>", window, re.DOTALL)
    assert m, "expected an intro <p> between the modal header and the job-search picker"


def test_gallery_intro_copy_explains_what_it_shows():
    """The intro copy must actually describe what the Gallery is/does —
    screenshots and generated materials — not just be a placeholder tag."""
    js = _read(GALLERY_JS)
    header_idx = js.index("Application Gallery")
    picker_idx = js.index('id="applicant-gallery-campaign"')
    window = js[header_idx:picker_idx]
    m = re.search(r"<p[^>]*>(.*?)</p>", window, re.DOTALL)
    assert m
    copy = re.sub(r"\s+", " ", m.group(1)).strip()
    assert len(copy) > 20, "intro copy should be a real explanatory sentence, not empty/trivial"
    lowered = copy.lower()
    assert "capture" in lowered or "screenshot" in lowered, (
        "intro should mention what's captured (screenshots)"
    )
    assert "resume" in lowered or "cover letter" in lowered or "material" in lowered, (
        "intro should mention the generated materials (resumes/cover letters/answers)"
    )


def test_gallery_intro_style_matches_compares_explainer_line():
    """Reuse the same subdued explainer-line styling Compare already uses
    (opacity + small font-size), rather than inventing new ad-hoc CSS."""
    compare_js = _read(COMPARE_JS)
    compare_p = re.search(r'<p style="([^"]*)">\s*Put two or more', compare_js)
    assert compare_p, "expected to find Compare's own intro <p> style for reference"

    gallery_js = _read(GALLERY_JS)
    header_idx = gallery_js.index("Application Gallery")
    picker_idx = gallery_js.index('id="applicant-gallery-campaign"')
    window = gallery_js[header_idx:picker_idx]
    m = re.search(r'<p style="([^"]*)">', window)
    assert m, "expected the Gallery intro <p> to carry an inline style"
    gallery_style = m.group(1)
    assert "opacity:0.75" in gallery_style, "expected the same subdued opacity Compare uses"
    assert "font-size:12px" in gallery_style, "expected the same small font-size Compare uses"


def test_gallery_intro_has_no_jargon_or_codenames():
    """White-label: no FR-/NFR- requirement IDs and no vendor/persona
    codenames leak into the new intro copy."""
    js = _read(GALLERY_JS)
    header_idx = js.index("Application Gallery")
    picker_idx = js.index('id="applicant-gallery-campaign"')
    window = js[header_idx:picker_idx]
    assert not re.search(r"\bFR-[A-Z]", window)
    assert not re.search(r"\bNFR-[A-Z]", window)
    assert not re.search(r"firehouse|orwell|odysseus|smokey|hermes-agent", window, re.IGNORECASE)
