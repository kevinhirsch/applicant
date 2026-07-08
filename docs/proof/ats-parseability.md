# ATS-parseability proof (P2-10)

**Claim:** generated résumés — both the LaTeX/moderncv primary render
(`templates/latex/`) and the docx-XML in-place fallback (`templates/docx/`) —
produce a real PDF whose text layer is machine-readable: the contact block,
section headers, work history, and skills all round-trip cleanly through an
ATS-style parser. A render that does NOT round-trip cleanly is never
submitted (Issue #370, `core/rules/ats_parseability.check_render_parseability`,
wired pre-submit in `application/services/submission_service._verify_ats_parse`).

## What "an ATS-style parser" means here

The repo does not vendor a third-party commercial ATS's own résumé-parsing
service (Workday/Greenhouse/Lever's parsers are not open-source and are not
reachable outside a live application). The citable evidence instead round-trips
each rendered PDF through the **same open-source, deterministic parser the
engine itself uses to ingest an uploaded résumé**
(`adapters/resume_parser/resume_parser.py`, built on `pypdf`'s PDF text-layer
extraction — the same text-extraction approach real ATS ingestion pipelines
use) — i.e. the identical machinery a real ATS would need: pull the PDF's text
layer, then recover the contact block / section headers / work history /
skills from it. This is stronger than asserting against source text handed
directly to the check: every existing `check_render_parseability`/`ResumeParser`
test (`tests/bdd/steps/test_enh_spirit_steps.py`,
`tests/unit/test_cov_backlog_resumehealth.py`) stubs the compile/convert
boundary and hands the check a plain string. (`tests/unit/test_ats.py` covers
a different, unrelated "ATS" concern — the browser-automation adapters that
drive Workday/Greenhouse/Lever's live application forms, not résumé parsing.)
Here the parser is instead handed the **actual rendered PDF FILE**, produced by
the real xelatex/lualatex compile or the real LibreOffice headless convert.

## Evidence

**Test:** `tests/integration/test_ats_parseability_proof.py`

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -v -m integration tests/integration/test_ats_parseability_proof.py
```

Two tests, one per render path, each `@pytest.mark.integration` (never runs in
the default `-m "not integration"` gate) and self-skipping when its system
binary is absent — mirroring `tests/integration/test_resume_render_real.py`'s
existing pattern:

- `test_docx_rendered_pdf_round_trips_through_the_deterministic_parser` — builds
  a base `.docx`, applies the SAME `DocxTailor.edit_document_xml` in-place OOXML
  edit production uses for a tailoring pass, converts it to a real PDF with
  LibreOffice headless (`soffice --convert-to pdf`), and feeds the resulting PDF
  to `ResumeParser`. Asserts name / email / skills / work-history all recover,
  that the tailored edit (a company-name substitution) survived the render, and
  that `check_render_parseability` independently agrees the text is machine-readable.
- `test_latex_rendered_pdf_round_trips_through_the_deterministic_parser` — the
  same shape over the LaTeX/moderncv path: `ModerncvConverter` templates the
  sample résumé into a real moderncv `.tex` source, `LatexTailor(allow_compile=True)`
  compiles it with the real xelatex/lualatex engine, and the resulting PDF is
  fed to the same `ResumeParser`.

Companion pure-rule/BDD coverage that was already green before this story and
is unchanged by it (the render-side self-check on source text, and its
negative/"unparseable render" branch): `tests/bdd/features/enhancements/
enh_370_ats_parseability_selfcheck.feature`, `tests/bdd/steps/
test_enh_spirit_steps.py`, `tests/unit/test_cov_backlog_resumehealth.py`.

## Which lane actually ran where (honest split — H-series: a skip is not a pass)

Both render paths gate on a real system dependency that `shutil.which()` may
not find — or, as discovered while building this proof, may find a BINARY for
without the capability actually working. In the sandboxed dev container this
story was built in:

- **TeX (xelatex/lualatex): absent entirely.** `shutil.which` finds neither
  binary, so the LaTeX test self-skips honestly with that reason. Not
  exercised in this container.
- **LibreOffice: binary present, but non-functional for document conversion.**
  `soffice --version` succeeds (`LibreOffice 24.2.7.2`), so the naive
  `shutil.which("soffice")` gate is satisfied — but this container ships only
  the `libreoffice-core`/`libreoffice-common` packages, NOT
  `libreoffice-writer` (confirmed via `dpkg -l | grep libreoffice`), so
  headless convert fails to load ANY input document (`.docx`, `.txt`, `.odt`
  all failed identically with `Error: source file could not be loaded`,
  verified by direct `soffice --headless --convert-to pdf ...` invocation and
  `strace`, and independent of a fresh `-env:UserInstallation` profile or
  fontconfig cache rebuild). `DocxTailor` reports this honestly as
  `convert_failed=True` (never a silent false pass), so the proof test's
  `artifact_available` check catches it and self-skips with the real reason
  instead of asserting against a PDF that was never produced.
- **The deploy image is not the dev container.** `docker/Dockerfile` installs
  the full `libreoffice-writer` package plus TeX (`xelatex`/`lualatex` +
  moderncv/fontspec/fontawesome5), so both real-render lanes are expected to
  run for real there; the self-hosted `.github/workflows/ci-integration.yml`
  runner also pre-bakes TeX and verifies it explicitly before the suite runs.
  **Neither real-render lane executed in this session** — both are deferred to
  the Integration Lane / a real deploy image. What DID run here and is
  asserted as passing: the pure/hermetic pieces of the same pipeline —
  `ModerncvConverter.convert_text` producing a real moderncv `.tex` source
  (`tests/unit/test_moderncv_conversion.py`), `DocxTailor.edit_document_xml`'s
  in-place OOXML edit, and `ResumeParser`/`check_render_parseability` recovering
  every expected field from the sample résumé's plain text (manually verified
  against the identical sample content used by the proof test) — plus the full
  hermetic suite (`-m "not integration"`).

## Honest boundaries

- This is NOT a live round-trip through any specific commercial ATS's own
  ingestion (Workday/Greenhouse/Lever's parsers are closed and unreachable
  outside a real application) — it is a round-trip through the repo's own
  open-source deterministic parser, built on the same PDF-text-layer
  extraction approach real ATS ingestion pipelines use. That is the strongest
  claim citable without a live employer-facing proof run (tracked separately
  as P1-2).
- The claim covers the two shipped render paths only (LaTeX primary, docx
  fallback); it says nothing about a résumé rendered by some other tool the
  user might upload instead of using either shipped path.
- A negative case (an unparseable render — e.g. text-as-image — must be
  flagged, not submitted) is pinned at the pure-rule level
  (`check_render_parseability`'s "no recoverable text layer" branch,
  `enh_370` scenario 3) rather than by rendering an actual broken PDF here;
  the pure rule is the same one the real render-side self-check calls.
