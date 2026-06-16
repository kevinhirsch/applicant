# Third-Party Licenses

Applicant vendors and depends on third-party software. This file records the
notices and obligations that travel with that software.

## Vendored frontend — Odysseus design system (MIT)

The UI shell under `frontend/static/` is vendored from the owner's **MIT-licensed
forks** of the Odysseus design system:

- **orwell** — base of the vendored set (`style.css`, `app.js`, `index.html`,
  `login.html`, `manifest.json`, `sw.js`, the `js/` shell + design-system
  modules, `lib/`, `fonts/` incl. `fonts/custom/GohuFont.ttf`, `css/`, icons).
  Licensed **MIT**, Copyright (c) 2026 kevinhirsch.
- **firehouse** — additional MIT-licensed design-system modules from the same UI
  family, available to draw on where orwell trims something the app shell or our
  surfaces need. Licensed **MIT**, Copyright (c) 2025 Firehouse Contributors.

The MIT `LICENSE` from the orwell fork is preserved verbatim at
`frontend/static/LICENSE`.

> **No network-copyleft obligation.** The vendored UI is MIT-licensed, so there
> is no AGPL §13 source-offer requirement for serving it over HTTP. The only
> obligation is to preserve the MIT copyright notice and permission text, which
> is satisfied by `frontend/static/LICENSE`.
>
> The Applicant Python application (`src/applicant/`) does not import or link the
> vendored code; it only *serves the files*. Our own screens live under
> `frontend/static/applicant/` and reuse the design system's CSS classes.

## Stack libraries

Licenses below are recorded from `docs/spec/master-spec.md` and the upstream
projects. Permissive components carry no copyleft obligation for self-hosted use.

| Component | Role | License |
|---|---|---|
| FastAPI | Web framework / delivery | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| SQLAlchemy | ORM | MIT |
| Alembic | Migrations | MIT |
| psycopg (3) | Postgres driver | LGPL-3.0 |
| Pydantic / pydantic-settings | Validation / config | MIT |
| structlog | Structured logging | MIT / Apache-2.0 (dual) |
| httpx | HTTP client | BSD-3-Clause |
| DBOS Transact | Durable orchestration | MIT |
| LangGraph | In-step reasoning loop | MIT |
| JobSpy | Discovery aggregator (Phase 1) | MIT |
| patchright / Playwright | Browser automation (Phase 2) | Apache-2.0 |
| Neko | Sandbox / remote view (Phase 2) | Apache-2.0 |
| Apprise | Notifications (Phase 1) | BSD-3-Clause |
| SearXNG | Exploratory discovery (Phase 1) | AGPL-3.0 |
| browser-use / Skyvern | AI form fallback (Phase 2) | MIT / AGPL-3.0 |
| Odysseus design system (orwell / firehouse forks) | Vendored UI shell | MIT |

**AGPL deps** (SearXNG and Skyvern) carry distribution/network obligations that
are immaterial for personal self-hosted use, but matter if you publicly
distribute a modified hosted copy. Keep them isolated or swap them if you
distribute. The vendored UI is now MIT (owner's orwell/firehouse forks) and
carries no such obligation.
