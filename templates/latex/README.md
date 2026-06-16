# LaTeX templates and vendored assets

These assets back the **LaTeX-primary** resume/cover-letter path (FR-RESUME-3/4,
FR-RESUME-10, FR-FONT-2). The Phase 3 `LatexTailor` adapter renders the `*.tex.j2`
Jinja2 templates and (in a real install) compiles them with `lualatex`/`xelatex`
with fonts embedded. The actual TeX compile is stubbed behind a clearly-marked
boundary so the test suite passes **without a TeX distribution installed**.

## Contents

| Path | Origin | Purpose |
|---|---|---|
| `moderncv/main.tex.j2` | adapted from `cv/main_example.tex` | resume (moderncv `banking`) |
| `cover/cover.cls` | copied verbatim | cover-letter document class |
| `cover/cover.tex.j2` | new, uses `cover.cls` | cover-letter template (FR-RESUME-10) |
| `OpenFonts/fonts/lato/*` | copied verbatim | Lato font family (embedded at compile) |
| `OpenFonts/fonts/raleway/*` | copied verbatim | Raleway font family (embedded at compile) |

## Upstream license / attribution

The LaTeX class and fonts originate from **`kevinhirsch/ai-job-search`**
(`cover_letters/cover.cls`, `cover_letters/OpenFonts/`, `cv/main_example.tex`),
itself derived from the **deedy-resume-openfont** CV class
(`\ProvidesClass{deedy-resume-openfont}[2014/04/30 CV class]`). The upstream
project license is preserved at `/tmp/ai-job-search/LICENSE` in the source
environment; downstream redistribution must keep that attribution.

Bundled fonts and their own licenses:

- **Lato** — Łukasz Dziedzic, released under the **SIL Open Font License 1.1**.
- **Raleway** — Matt McInerney / Pablo Impallari / Rodrigo Fuenzalida, **SIL Open
  Font License 1.1**.
- **moderncv** — Xavier Danaux, distributed under the **LaTeX Project Public
  License (LPPL)**.

The SIL OFL and LPPL both permit redistribution with attribution; this notice
satisfies that requirement. Replace these with the user's own uploaded fonts via
the FontInstall subsystem (FR-FONT-1/2) when the resume design requires them.
