# docx-XML fallback templates

The **docx-XML / OOXML fallback** path (FR-RESUME-3/4, §11) is the load-bearing
fallback used when the LaTeX conversion does not faithfully reproduce the user's
hand-tuned design. Instead of re-typesetting from scratch, the `DocxTailor`
adapter edits the **OOXML of the user's own uploaded `.docx` in place** so the
exact layout, fonts, and spacing survive.

## Why a fallback at all

LaTeX gives the cleanest typographic result, but a candidate's existing resume is
often a carefully tuned Word document. Re-rendering it in LaTeX can shift spacing,
fonts, or page breaks. The docx-XML path keeps the original design and only swaps
the **text runs** (`<w:t>` elements inside `<w:p>` paragraphs), so adaptation
reframes content (FR-RESUME-2) without disturbing the design.

## Shape (Phase 3 thin scaffold)

- No template files ship here yet: the "template" for the docx path is the user's
  uploaded `.docx`, supplied at runtime.
- `DocxTailor.render_redline` diffs the old vs new text runs and reports
  additions/subtractions (same `RedlineResult` contract as the LaTeX path).
- `DocxTailor.render_artifact` would, in a real install, write the edited OOXML
  and run a `docx -> PDF` conversion (LibreOffice headless) with embedded fonts
  for the fidelity check (FR-RESUME-4). That conversion is **stubbed behind a
  clearly-marked boundary** so tests pass without LibreOffice/Word installed.
- The em-dash post-filter + truthfulness rules run on the text runs **before** the
  OOXML is written, exactly as on the LaTeX path (voice-and-truthfulness §6).

## Dependencies (not yet added)

A real implementation would add `python-docx` (or direct `zipfile` + `lxml` OOXML
editing) and a `docx -> PDF` converter. Adding those deps is out of scope for the
Phase 3 scaffold; see `docs/notes/phase3-requests.md`.
