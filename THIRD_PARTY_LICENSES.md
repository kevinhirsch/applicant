# Third-Party Licenses

Applicant vendors and depends on third-party software. This file records the
notices and obligations that travel with that software.

## Vendored frontend — Odysseus (AGPL-3.0)

The entire UI shell under `frontend/static/` is vendored **verbatim** from the
Odysseus project, which is licensed under the **GNU Affero General Public License
v3.0 (AGPL-3.0)**. The original `LICENSE` file is preserved at
`frontend/static/LICENSE`.

> **Network copyleft obligation.** AGPL-3.0 §13 requires that if you run a
> modified version of an AGPL work and let users interact with it **over a
> network**, you must offer those users the corresponding source code. Because
> Applicant serves this vendored UI over HTTP, this obligation applies to the
> vendored portion if you distribute or publicly host a modified copy.
>
> **Containment.** To keep this obligation isolated, the AGPL material is
> confined to `frontend/static/` (static assets served as-is). The Applicant
> Python application (`src/applicant/`) does not import or link Odysseus code; it
> only *serves the files*. Our own screens live under
> `frontend/static/applicant/` and reuse Odysseus's CSS classes, which is
> permitted use of the vendored stylesheet.

If you distribute Applicant publicly and wish to avoid the AGPL obligation, swap
the vendored UI for a permissively licensed shell.

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

**AGPL deps** (SearXNG, Skyvern, and the vendored Odysseus UI) carry
distribution/network obligations that are immaterial for personal self-hosted
use, but matter if you publicly distribute a modified hosted copy. Keep them
isolated or swap them if you distribute.
