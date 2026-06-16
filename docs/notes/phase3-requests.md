# Phase 3 — requests to frozen owners (RESOLVED status log)

> **Status (2026-06): all items below are RESOLVED.** This file originally captured
> follow-ups that Phase 3 could not action because it must not edit frozen files (core,
> ports, container/main/config/lifespan/deps/static, `pyproject.toml`, conftests, Phase
> 1/2 files). During the deepening phases the owning maintainers actioned each request.
> Each item now carries a **Resolution** line. No residual work remains.

## 1. New runtime dependencies (pyproject.toml)

The LaTeX-primary and docx-XML fallback paths were originally scaffolded with their real
compile/convert steps **stubbed behind clearly-marked boundaries** so the suite ran with no
external toolchain. The production implementation needed:

- **Jinja2** — render `templates/latex/moderncv/main.tex.j2` and
  `templates/latex/cover/cover.tex.j2`.
- **python-docx** (or `lxml` + `zipfile`) — in-place OOXML text-run editing for the
  docx-XML fallback (`DocxTailor`).
- A **docx → PDF** converter (LibreOffice headless `soffice --convert-to pdf`) for the docx
  fidelity check.
- A **TeX distribution** (TeX Live with `lualatex`/`xelatex`, `fontspec`, `moderncv`,
  `fontawesome5`) on the conversion host for the LaTeX fidelity check.

**Resolution — RESOLVED.** `jinja2`, `python-docx`, and `pypdf` were added to `pyproject.toml`
(along with `apprise`, `python-jobspy`, `pynacl`, `python-multipart`, and `pytest-cov` for
the other phases). The LaTeX/docx render boundaries are wired through Jinja2 + python-docx.
TeX Live + LibreOffice remain **system packages** baked into the Phase 4 install image
(FR-INSTALL); the real-toolchain fidelity tests
(`test_latex_conversion_real.py`, `test_resume_render_real.py`) are integration-gated and
skip when no TeX/LibreOffice binary is present, while the hermetic default lane covers the
logic with fakes.

## 2. Container wiring for the Phase 3 service (container.py)

`MaterialService` was not constructed in `app/container.py`. The `documents` router composed
it on demand from the frozen container's adapters (`storage`, `llm`, `latex_tailor`) — the
same pattern the Phase 1 `digest` router uses for `DigestService`.

**Resolution — RESOLVED (by design).** `MaterialService` is intentionally composed
per-request in the `documents` router from the container's frozen adapters; `DigestService`
follows the same per-request composition in the `digest` router. The newer Phase 4 services
(`AdvancedLearningService`, `ChatService`) are held as frozen singletons in
`app/container.py` and exposed via `deps.py`. Both patterns are accepted; no change needed.

## 3. RevisionSession persistence (storage)

There was no `revision_sessions` repository on the storage port. `MaterialService` kept
revision sessions **in-memory** for the Phase 3 scaffold. A durable implementation needed a
`revision_sessions` repo (or session persisted into `GeneratedDocument`/workflow state) so a
revision loop survives a restart (FR-DUR-1).

**Resolution — RESOLVED (Phase 3b).** A durable `revision_sessions` table and
`RevisionSessionRepo` (`add`/`get`/`get_for_material`) were added to the storage adapter
(`adapters/storage/models.py`, `repositories.py`) and exposed as `SqlAlchemyStorage.revisions`,
with an Alembic migration. The revision loop now survives a restart, satisfying FR-RESUME-8 +
FR-DUR-1.

## 4. Fit score units (informational)

`ResumeFitScoring.coverage` is a 0.0..1.0 float (entity). The FR-RESUME-7 selection threshold
is expressed as a 0–100 percentage (`FIT_THRESHOLD = 70`); `MaterialService.select_or_generate`
compares `coverage * 100 >= threshold`.

**Resolution — RESOLVED (no change needed).** The units are consistent: `coverage` stays a
0.0..1.0 float on the entity and is scaled to a percentage at the single comparison site
against `FIT_THRESHOLD`. Verified consistent; nothing to change.
