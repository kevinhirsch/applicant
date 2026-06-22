# HARVEST-INVENTORY.md — Evidence Inventory (Harvest & White-Label Audit)

> Living evidence ledger. Every candidate asset from `hermes-agent` and `orwell` considered
> for harvest into `applicant`, with the evidence it's worth taking and its MIT attribution
> obligation. Maintained by the lead; persists through `/compact`. Read-only audit — no code
> moves before the Phase 4 gate.

## Status
- Phase 0 — Ingest & setup: **DONE** (all three repos cloned read-only; licenses confirmed).
- Phase 1 — Parallel deep-dive (5 sub-auditors): **DONE** (all five consolidated below).
- Phase 2 — Comparative fit / keep-vs-replace: **DONE** (verdict synthesis at end of this file).
- Phase 3 — `docs/HARVEST-MAP.md`: **DONE**.
- Phase 4 — `docs/APPLICANT-SURVIVAL-PLAN.md` + verdict (GATE): **DONE — awaiting authorization**.

## Repos & licenses (confirmed on disk)
| Repo | Location | License | Attribution to retain |
|------|----------|---------|-----------------------|
| applicant | `/home/user/applicant` | **MIT** © 2026 kevinhirsch | n/a (target). MIT ⊕ MIT — clean, standard attribution obligations only. |
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

### 2. Hermes platform & agent core — VERDICT: **harvest only the `ProviderProfile` pattern; reject the rest as scope creep** (Confidence H)

**Decisive framing:** hermes ≈ **557k LOC** general LLM-tool-calling agent platform (63 direct deps +
~35 optional extras); applicant ≈ **31k LOC** single-purpose hexagonal engine. Applicant has **no
function-calling agent loop, no MCP, no subagents, no general terminal** (auditor greps → 0 hits) — its
"agent" is a deterministic per-campaign pipeline (`application/services/agent_loop.py`) on a durable
workflow + 24/7 scheduler. **Most hermes platform assets have no socket to plug into**; adopting them
imports the agent paradigm wholesale = the reskin.

**TIER 1 — the one defensible harvest:**
| Asset | Source | Mechanism / evidence | Target | Type | Conf |
|-------|--------|----------------------|--------|------|------|
| **A1 Multi-provider `ProviderProfile`** | `providers/base.py:38-218` + 16 plugins + non-OpenAI adapters (`agent/anthropic_adapter.py` etc.) | one declarative profile (auth/endpoints/vision/temp quirks/max-tokens/live model fetch) replaces "20+ boolean flags"; reaches Anthropic/Bedrock/Gemini **native** APIs applicant can't speak; tested per-provider | behind existing `LLMPort` at `app/container.py:317`; add provider adapters as new **tier backends** (`TierConfig.provider` already namespaces) | **pattern-only** (+ at most ONE concrete adapter, e.g. anthropic) | H abstraction broader / M applicant *wants* it |

**Critical nuance:** applicant's `adapters/llm/openai_compatible.py` has something hermes' transport
**lacks** — a capability-ranked **tier ladder w/ escalation** (climb on low-confidence/context overflow)
+ defensive structured-output parsing. So this is **missing-capability (more reach), NOT worse-arch** —
applicant's port is arguably *cleaner* for its purpose. Harvest the profile *pattern*, **preserve the
ladder**, do NOT lift the plugin/entry-point machinery or 4 heavy adapters wholesale. A1 is a *want*,
not a spec gap (FR-LLM-1 deliberately chose OpenAI-compat + Ollama, can run fully local).

**TIER 2 — REJECT, with differential diagnosis (each has a right-sized applicant equivalent):**
| Asset | Why reject — applicant already has the in-scope slice |
|-------|------|
| **Memory+skills learning loop** (hermes headline: `agent/curator.py`, `background_review.py`, trajectory_compressor) | **Different problem, not better.** Hermes distills reusable *procedures* from varied agent trajectories (needs a tool-calling agent doing varied tasks). Applicant does ONE task; its `learning_service.py` (527 ln) is statistical *yield/taste* learning (conversion-weighted source ranking, role centroid, explore budget) — cheap, no-LLM-hot-path. Not comparable on better/worse. |
| **Multi-platform gateway** (Telegram/Discord/Slack/…; `gateway/run.py` 17.7k ln) | Applicant's outbound need is **notifications**, already better-fit: `ports/driven/notification.py` + Apprise notifier w/ escalation ladder + idempotency. Inbound 18-platform chat = chat-ops product applicant doesn't want (only public surface = `workspace/`). |
| **Cron** (`cron/scheduler.py` 2.5k ln, gateway-coupled) | Applicant has the in-scope slice done durably: `Scheduler.tick()` (injected clock, per-campaign locks, tick isolation) + `DurableOrchestrationPort.schedule(name,cron,fn)` w/ crash recovery. Hermes uses JSON+flock. |
| **MCP (server+client)** | No tool-injection registry to inject into; applicant's `ToolRegistryPort` is a feature on/off toggle, not a dynamic tool catalog. Its one external capability (deep research) is a bounded budget-capped callback. |
| **Subagent spawning** (`tools/delegate_tool.py` 3.2k ln) | No `AIAgent` to fork. Applicant's parallelism is durable queues + per-campaign sandbox slots w/ yield/pivot (`CapacityService`) — multiple *applications*, not multiple *agents*. |
| **6 terminal backends** (local/Docker/SSH/Singularity/Modal/Daytona) | Applicant's only sandbox need is a browser for form-fill, covered by `ports/driven/sandbox.py` (+ Proxmox/local adapters, RemoteViewPort). 5/6 backends = HPC/cloud scope creep (~7.5k LOC + ~12 SDK deps). |

**License hygiene:** every candidate embeds hermes/nous codenames (`~/.hermes`, `HERMES_*` env,
`get_hermes_home`); MIT © Nous Research must travel with any lift, white-label the codenames.

### 3. Orwell architecture & implementation — VERDICT: **harvest 1 strong pattern + 3 minor; not a replacement** (Confidence H)

**Verified RUNS (auditor executed the suites):** `test:arch` (dependency-cruiser) clean — 127
modules / 452 deps, 0 violations; `typecheck` + `build` clean; `test:unit:fast` 1277 pass/1 skip
(incl. fast-check property tests); `test:bdd` 366 scenarios / 1594 steps 100% pass over 63
`.feature` specs. README's "pre-implementation" note is **stale** — mature, test-gated. TS/Node 22
engine + **Python/FastAPI frontend that is a sibling fork of applicant's OWN upstream workspace**.

**Harvest value collapses to essentially ONE asset** (the rest of the engine is ~80% Big-Brother
sim logic that does not transfer):

| # | Asset | Type | Effort/Risk | Conf |
|---|-------|------|-------------|------|
| 1 ★ | **Structural hexagonal-boundary enforcement** — `orwell/.dependency-cruiser.cjs:1-108` + `package.json:29` (`test:arch`), `tsPreCompilationDeps:true` so outward code **cannot even type-only-import** a hidden port; default-deny (`no-engine-layer-on-outward`). | pattern→adapt | Low/Low | H |
| 2 | Type-forbidden capability allowlist — `src/surfaces/tools/registry.ts:8-13,71-73` (`readsVault: false` literal = compile error to register a leaker) + `adapters/mcp/McpServer.ts:171-181` channel gate. | adapt | Med/Low | H pattern / M encoding |
| 3 | Deterministic-core/LLM-narrates as a **structural port type** — `ports/NarrativePort.ts:15-31` (context carries no Vault data by construction) + `adapters/narrative/LlmNarrativePort.ts:145-179` (LLM returns text, never state). | pattern-only | Low | H |
| 4 | Anti-fabrication content-lineage **graded downgrade** — `adapters/inmemory/InMemoryKnowledgeService.ts:23-38,99-120` (claim accepted only if normalized-substring of what happened; else downgraded to capped-0.5 suspicion, not hard-fail). | adapt | Med/Low | M |

**Asset #1 is the standout & directly serves applicant's safety thesis:** applicant IS hexagonal
but enforces layering by **convention + contract tests only** — auditor grep found NO import-linter/
layer contract in `pyproject.toml` or CI. So nothing structurally stops a future `app/router` from
importing a `core/rules` gate and bypassing it. **Diagnosis: worse architecture (missing structural
guarantee), not a missing feature.** Fix: add `[tool.importlinter]` layered contract to applicant
`pyproject.toml`, gate in CI alongside ruff/pytest.

**REJECTED (with reason):** `src/engine/*` (blocs/jury/gossip/evictions… = sim-specific, zero
transfer); the `frontend/` Python app (sibling fork of applicant's own upstream → net-negative,
re-introduces a codename to scrub); LXC+systemd deploy (different-not-better vs applicant's Compose +
`scripts/update.sh`); SQLite persistence (applicant is Postgres+Alembic+chromadb).
**Net:** orwell is NOT a replacement and does not strengthen the kill case — it *confirms* applicant's
architecture is sound but **under-enforced**. **Attribution:** MIT © 2026 kevinhirsch; pattern-only
adoptions copy no file (no notice travels); any verbatim lift (e.g. #4 `contentDerivedFrom`) keeps the
MIT notice in-file; scrub codenames (Orwell/Big Brother/Vault/houseguest/Producer).

### 4. Applicant fit & survival — VERDICT: **KEEP applicant as the spine; harvest FE + provider profiles behind existing seams** (Confidence H)

**The moat is REAL and load-bearing (hermes has literally zero of it):** confirmed by direct read,
six pillars —
- **ATS pre-fill orchestration state machine (deepest moat):** `application/services/prefill_service.py`
  (1218 ln) — sandbox→account gate (login/OAuth/**2FA push-poll** `:315-361`)→page walk→fill→**stop at
  final submit**; 19-state domain machine `core/state_machine.py`; ATS shapes abstracted
  `adapters/browser/ats.py:272` (`Workday/Greenhouse/Lever` registry).
- **Resume tailoring w/ render fidelity:** `adapters/resume_tailoring/latex_tailor.py` — source-diff
  redline `:168`, LaTeX-escape anti-injection `:146`, real xelatex compile + **pypdf font-embedding/
  page-fit inspection** `:356,:418`; docx OOXML fallback.
- **Fabrication guard (densest IP):** `core/rules/truthfulness.py` (566 ln) — whole-token membership
  `:456`, entity-shaped free-prose mode `:501,:523`, numeric value-matching `:443`; scar-tissued.
- **Server-side safety gates a caller can't opt out of:** `core/rules/review_gate.py` (`ensure_submittable`),
  `prefill_boundary.py:73` (CAPTCHA/verify unconditional, opt-in flags server-derived not per-request),
  `sensitive_fields.py` (EEO fills only from stored answers, never AI-guessed).
- **Discovery + source-yield learning:** `adapters/discovery/jobspy_searxng.py` (zero-LLM), conversion-
  weighted source ranking `application/services/learning_service.py:173,:340` (thinner, more re-derivable).
- **Credential vault:** `adapters/credentials/pg_credential_store.py` — libsodium XSalsa20-Poly1305,
  `0600` keyfile. Maturity: **1214 test functions ~1:1 to code.**

**Weaknesses are all at the EDGES, never the moat core (differential diagnosis):**
| | Weakness | Diagnosis | 
|--|----------|-----------|
| W1 | FE polish/cohesion (7 vanilla-JS files ~4.9k LOC vs hermes React/Vite/TS) | **worse UX + missing capability** — *the legitimate reason leadership wants to switch* |
| W2 | Multi-provider breadth (OpenAI-compat+Ollama vs hermes `ProviderProfile`) | **narrower** — but applicant's tier-ladder escalation is *better at its one job*; merge, don't replace |
| W3 | General memory ecosystem | **missing but out of scope** (applicant needs job-conversion learning, which it has) |
| W4 | Live-boundary proof: 1214 tests vs fakes, only 28 integration (skip on absent deps); real-Workday path **wired but never CI-demonstrated** | **unfinished/unproven at edge, not wrong** — residual risk to the "operable" claim |

**Integration seams (the load-bearing fact): `workspace/src/applicant_engine.py` (~130-method bridge)
is the stable API contract.** A React FE harvest plugs into the same `/api/applicant/*` proxy routes +
`applicant_features.py` feature-state — **engine, moat, and safety gates untouched.** Provider profiles
fold behind `ports/driven/llm.py` (`TierLadder`), preserving the ladder.

**Keep-vs-replace, head-on:** REPLACE throws away ~31k LOC of moat (pinned by 1214 tests) to gain a FE
— strictly worse. KEEP-and-harvest cures W1/W2 at the cost of a bounded FE rewrite against a stable API.
**"Still applicant or a reskin?"** Stays applicant **iff** harvest is FE-only + provider profiles behind
the port; becomes a hermes reskin **only if** hermes' agent loop/tool model/gateway replaces
`application/services/agent_loop.py` as the core — **that line must not be crossed** (the tell to watch).
**Confidence:** moat real H; replacement loses H; FE-harvest is right remedy M-H.

### 5. Integration, white-label & licensing — VERDICT: **harvest is mechanically legal but the brand burden is large & asymmetric; prefer pattern-only lifts** (Confidence H)

**License facts (confirmed on disk):** hermes `LICENSE:1-3` = MIT © 2025 Nous Research; orwell
`LICENSE:1-3` = MIT © 2026 kevinhirsch; applicant `LICENSE` = **MIT** © 2026 kevinhirsch.

**License compatibility:** MIT ⊕ MIT — clean, no legal escalation required. Harvested portions
stay under their upstream MIT notices; applicant's own code is MIT. Both in-tree precedents
(`THIRD_PARTY_LICENSES.md`, `frontend/static/LICENSE`, `workspace/licenses/`) already follow this
pattern. Hermes introduces a **genuinely new** third-party holder (Nous Research) not yet anywhere
in applicant; attribution obligations apply (see ledger below).

**Attribution ledger (model both, before importing code):** add BOTH (a) verbatim
`workspace/licenses/<src>-MIT-LICENSE.txt` (model: `workspace/licenses/opencode-MIT-LICENSE.txt` —
"Adapted for:" header + full MIT text incl. upstream copyright) AND (b) an `ACKNOWLEDGMENTS.md` row.

**White-label burden (large, asymmetric — scales super-linearly with lift size for hermes):**
- hermes: ~2,797 brand mentions, **~280 `HERMES_*` env vars**, `~/.hermes` config dir baked into a
  30+-caller import constant (`hermes_constants.py:51,54`), `hermes`/`hermes-agent`/`hermes-acp` CLI
  (`pyproject.toml:296-299`), **Nous first-party provider lock-in** (`NOUS_API_KEY`, Nous Portal OAuth,
  `cli-config.yaml.example:16-18`), `nousresearch.com` domains, caduceus banner, sub-brands
  (Chronos/Hindsight/Caduceus), 7 i18n catalogs.
- orwell: ~5,466 mentions, `ORWELL_*` env prefix (incl. `ORWELL_ADMIN_*`/`ORWELL_ENGINE_*`/
  `ORWELL_CONFIG_DIR` — **conceptually collide with applicant's own `APPLICANT_*`/`ENGINE_URL`**),
  `orwell_*.py`/`orwell*.js` module prefixes, `/etc/orwell/ca/` path, `orwell_memories` Chroma
  collection (**live data key — a rename is a migration, not a sed**), **outbound brand leak**
  `X-OpenRouter-Title: "Orwell"` (`endpoint_resolver.py:190-191`), and "Big Brother"/"Vault Wall"
  themed vocab (load-bearing domain, not chrome → realistic harvest is pattern-only, carries no strings).

**🚨 CI denylist finding (actionable, H):** the white-label denylist is inline at
`.github/workflows/ci.yml:28` (`git grep -iE 'firehouse|orwell|odysseus|smokey'`). **`orwell` is ALREADY
blocked** (an orwell harvest is guarded today). **`hermes`/`nous` are NOT** — and **cannot be naively
added** because applicant legitimately references the **Hermes/Nous model families** (not white-label
violations): `workspace/services/hwfit/data/hf_models.json` (`NousResearch/Hermes-3…`), vLLM
`--tool-call-parser hermes` (`cookbook_routes.py:129`), model context/pricing tables
(`agent_loop.py:1369`, `providers.js`), and an attribution comment crediting "Hermes' skills format"
(`skill_format.py:4-5`). A blanket add red-walls CI → needs **scoped path-excludes** (`':!**/hf_models.json'`,
narrower `nousresearch.com`/`hermes-agent` patterns). Real design task, not a one-liner.

**Sequencing skeleton:** scope-lock lift → license files FIRST → token-rename pass → data-key renames as
migrations → reachability check (front-door) → green-increment gate (incl. denylist). **Top risks:**
env-var rename fan-out (~280 hermes tokens); outbound brand leak; attribution obligations (MIT);
themed-vocab bleed; data-key migration corruption.

---

## PHASE 2 — Comparative fit & the honest keep-vs-replace verdict (synthesis)

**VERDICT: KEEP `applicant`. The "replace with hermes-agent" premise does not survive contact with the
evidence.** Confidence **H**. The four substantive auditors converge independently:

1. **The headline asset evaporates on inspection.** Hermes' "frontend that just works" is React 19 +
   Vite + Tailwind + a private npm design system, with the chat being an xterm.js terminal embed — a
   *management dashboard*, inseparable from its build stack. Adopting it forces a bundler/React/TS onto
   applicant's deliberate no-build front-door and is all-or-nothing ⇒ **a hermes reskin**. Applicant's
   front-door already **equals/exceeds** it on theming, markdown, and feature-state. (SA1)
2. **Hermes' platform is general scope-creep with no socket.** Applicant has no agent loop / MCP /
   subagents / general terminal to attach them to; it has *right-sized domain equivalents* for every
   in-scope sliver (learning, scheduling, notifications, sandbox). Only the `ProviderProfile` *pattern*
   is worth taking — and that's a want, behind a port that's arguably cleaner than hermes'. (SA2)
3. **Orwell is not a replacement and confirms applicant's architecture is sound** (its frontend is a
   sibling fork of applicant's OWN upstream). Net harvest: one strong pattern (structural boundary
   enforcement applicant lacks) + minor refinements. (SA3)
4. **Applicant's moat is real and load-bearing; hermes has ZERO of it.** The ATS state machine,
   fabrication guard, render-fidelity gate, server-side safety boundaries, vault, and conversion
   learning are ~31k LOC pinned by 1,214 tests. **Replace = throw away the moat to gain a FE = strictly
   worse.** (SA4)

**The honest line (the reskin question, answered):** keeping applicant + harvesting *surgically* (FE
patterns, the provider-profile pattern, the import-linter boundary, a couple of safety refinements)
**stays applicant** — the identity is the engine, not the pixels. It becomes a reskin **only if** hermes'
agent-loop/gateway/tool-model replaces `application/services/agent_loop.py` as the core. **That line must
not be crossed; it is the explicit guardrail on the whole plan.**

**What the replace case got right (steelmanned, retained as the real work):** applicant's FE/UX is a
genuine, legitimate weakness (W1) and its multi-provider reach is narrow (W2), and the live-Workday path
is wired-but-CI-unproven (W4). The survival plan's job is to fix those **without** crossing the line.
