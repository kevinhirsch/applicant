# HARVEST-INVENTORY.md — Evidence Inventory (Harvest & White-Label Audit)

> Living evidence ledger. Every candidate asset from `hermes-agent` and `orwell` considered
> for harvest into `applicant`, with the evidence it's worth taking and its MIT attribution
> obligation. Maintained by the lead; persists through `/compact`. Read-only audit — no code
> moves before the Phase 4 gate.

## Status
- Phase 0 — Ingest & setup: **DONE** (all three repos cloned read-only; licenses confirmed).
- Phase 1 — Parallel deep-dive (5 sub-auditors): **IN PROGRESS**.
- Phase 2 — Comparative fit / keep-vs-replace: pending.
- Phase 3 — `docs/HARVEST-MAP.md`: pending.
- Phase 4 — `docs/APPLICANT-SURVIVAL-PLAN.md` + verdict (GATE): pending.

## Repos & licenses (confirmed on disk)
| Repo | Location | License | Attribution to retain |
|------|----------|---------|-----------------------|
| applicant | `/home/user/applicant` | **Unlicense (public domain)** | n/a (target). NB asymmetry: ingesting MIT into a public-domain repo — flag for legal. |
| hermes-agent | `/tmp/harvest-scratch/hermes-agent` | **MIT** | `Copyright (c) 2025 Nous Research` — upstream `NousResearch/Hermes-Agent`. |
| orwell | `/tmp/harvest-scratch/orwell` | **MIT** | `Copyright (c) 2026 kevinhirsch`. |

Precedent in-tree: `THIRD_PARTY_LICENSES.md`, `frontend/static/LICENSE`, `workspace/licenses/`,
`workspace/ACKNOWLEDGMENTS.md`, and the CI white-label codename denylist already establish how
this repo vendors + white-labels MIT code. New harvests follow that same pattern.

## Baseline snapshot
- **applicant** — hexagonal FastAPI engine (`src/applicant/`, 186 py) + vendored white-labeled
  vanilla-JS front-door (`workspace/`, 281 py / 149 js). Single-purpose: autonomous job
  application (discovery, pre-fill/Workday, resume tailoring, review-before-submit safety).
- **hermes-agent** — general self-improving agent platform. MIT © Nous Research. TS frontend
  (`web` 125, `website` 732, `ui-tui` 364, `apps` 599) + Python platform (`agent`, `providers`,
  `gateway` 64, `skills` 452, `optional-skills` 442, `cron`, `optional-mcps`). 1678 test files.
- **orwell** — Big-Brother SIM, "built and playable, features 0001–0041 green." MIT © kevinhirsch.
  TS/Node engine (`src/` hexagonal: domain/engine/ports/adapters/surfaces) + Python/FastAPI
  frontend (`frontend` 609) over a permissioned MCP boundary. 51 BDD `features/`, 36 `deploy/`.

---

## Consolidated inventory (filled from sub-auditor reports)

_Sub-auditor reports are being consolidated here, de-duplicated, in the shared entry format:
Asset (repo+path) · What · Evidence · Maturity/tests · Deps · Attribution · Fit vs applicant ·
Integration type · Effort/risk · Confidence._

### 1. Hermes frontend & UX
_pending sub-auditor 1_

### 2. Hermes platform & agent core
_pending sub-auditor 2_

### 3. Orwell architecture & implementation
_pending sub-auditor 3_

### 4. Applicant fit & survival
_pending sub-auditor 4_

### 5. Integration, white-label & licensing
_pending sub-auditor 5_
