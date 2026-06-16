# Phase 3 — requests to frozen owners

Phase 3 must not edit frozen files (core, ports, container/main/config/lifespan/
deps/static, `pyproject.toml`, conftests, Phase 1/2 files). The following items
were needed but are out of Phase 3's edit scope; they are recorded here for the
owning phase/maintainer rather than actioned.

## 1. New runtime dependencies (pyproject.toml — FROZEN)

The LaTeX-primary and docx-XML fallback paths are scaffolded with their real
compile/convert steps **stubbed behind clearly-marked boundaries** so the suite
runs with no external toolchain. A production implementation needs:

- **Jinja2** — render `templates/latex/moderncv/main.tex.j2` and
  `templates/latex/cover/cover.tex.j2`. (The adapter currently does not import
  jinja2; the boundary that would render the template is stubbed.)
- **python-docx** (or `lxml` + `zipfile`) — in-place OOXML text-run editing for
  the docx-XML fallback (`DocxTailor`).
- A **docx -> PDF** converter (LibreOffice headless `soffice --convert-to pdf`)
  for the docx fidelity check.
- A **TeX distribution** (TeX Live with `lualatex`/`xelatex`, `fontspec`,
  `moderncv`, `fontawesome5`) on the conversion host for the LaTeX fidelity check.

Requested change: add `jinja2` and `python-docx` to the project dependencies in
`pyproject.toml`. TeX Live + LibreOffice are system packages for the install
image (Phase 4 packaging, FR-INSTALL-1).

## 2. Container wiring for the Phase 3 service (container.py — FROZEN)

`MaterialService` is not constructed in `app/container.py` (frozen). The
`documents` router composes it on demand from the frozen container's adapters
(`storage`, `llm`, `latex_tailor`) — the same pattern the Phase 1 `digest` router
uses for `DigestService`. If a singleton is preferred, add
`material_service = MaterialService(storage, llm, latex_tailor)` to the container
and expose it via `deps.py`.

## 3. RevisionSession persistence (storage — FROZEN)

There is no `revision_sessions` repository on the storage port. `MaterialService`
keeps revision sessions **in-memory** for the Phase 3 scaffold. A durable
implementation should add a `revision_sessions` repo (or persist the session into
the `GeneratedDocument`/DBOS workflow state) so a revision loop survives a restart
(FR-DUR-1). Requested for the storage owner.

## 4. Fit score units (informational)

`ResumeFitScoring.coverage` is a 0.0..1.0 float (frozen entity). The FR-RESUME-7
selection threshold is expressed as a 0-100 percentage (`FIT_THRESHOLD = 70`);
`MaterialService.select_or_generate` compares `coverage * 100 >= threshold`. No
change requested; noted for consistency.
