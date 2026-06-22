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

### 1. Hermes frontend & UX  — VERDICT: **REJECT the FE harvest** (Confidence H)

**Headline finding (overturns the replace premise):** hermes' "frontend that just works" is
**React 19 + TS + Vite 8 + Tailwind v4 + a private npm design system `@nous-research/ui@0.18.2`**
(imported by 46/54 web components), and the chat itself is an **xterm.js terminal embedding the
Ink TUI over WebSocket** — a management dashboard, not a consumer web surface. Its polish is
**inseparable from its build stack**; there is no vanilla subset. Adopting any real component
drags in React+Tailwind+the npm pkg ⇒ **a full re-platform = a hermes reskin.**

**Applicant already matches/exceeds on every axis that transfers to a browser product:**
- Theming: `workspace/static/js/theme.js` (presets + custom colors + fonts + density + radius +
  bg-effects + frosted glass + runtime local-font injection; 3,790 CSS-var refs) **> hermes'**
  build-time `color-mix()` cascade (`web/src/themes/`).
- Markdown: `workspace/static/js/markdown.js` (803 ln: thinking/reasoning blocks, emoji-SVG,
  mermaid, sanitization) **> hermes'** self-described "NOT CommonMark" 383-ln `Markdown.tsx`.
- Feature-state: `workspace/src/applicant_features.py` (253 ln real active/locked/disabled
  server state machine) **> hermes'** 24-ln `dashboard-flags.ts` stub that returns `true`.

**Framework verdict (the headline question):** YES — adopting hermes' FE forces React/TS/Vite/
Tailwind + private DS onto applicant's deliberate **no-build** front-door (CI gates `node --check`
only). It deletes the no-build model. All-or-nothing; violates working-principle #1.

**Only harvestable items — PATTERN-ONLY (no framework):**
| # | Asset | Type | Effort | Note |
|---|-------|------|--------|------|
| 1 | Streaming "hugging caret" — `web/src/components/Markdown.tsx:24-48` (`StreamingCaret`) | pattern-only | XS | ~10 ln CSS+DOM into `markdown.js`; caret hugs last char. Best (only clear) FE harvest. |
| 2 | Human-readable cron picker — `web/src/lib/schedule.ts:1-382` (`buildScheduleString`) | pattern-only | S | **No consumer today** (applicant scheduling is engine-side 24/7 loop, not user cron). Defer. |

**Explicit REJECTs (with reason):** `@nous-research/ui` DS (= the reskin); theme model (applicant
superior); `Markdown.tsx` (downgrade); `dashboard-flags.ts` (applicant superior);
`JsonRpcGatewayClient` WS RPC (applicant uses SSE/HTTP, zero WebSocket consumers — wrong transport);
Ink terminal utils `stringWidth`/`sliceAnsi`/`parse-keypress`/`optimizer` (no terminal surface in a
browser app). 
**Attribution:** any verbatim copy (even the caret) carries MIT © 2025 Nous Research; white-label
brand strings ("Hermes Teal", "Nous Blue", `__HERMES_*__`) only, never the copyright.

### 2. Hermes platform & agent core
_pending sub-auditor 2_

### 3. Orwell architecture & implementation
_pending sub-auditor 3_

### 4. Applicant fit & survival
_pending sub-auditor 4_

### 5. Integration, white-label & licensing
_pending sub-auditor 5_
