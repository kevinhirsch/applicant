# HARVEST-MAP.md — What to harvest, where it lands, how to white-label

> **Status:** Phase 3 deliverable of the Harvest & White-Label Migration Audit (read-and-plan;
> **no code moved**). Evidence base: `HARVEST-INVENTORY.md` (five sub-auditor deep-dives, read-only).
> Companion: `docs/APPLICANT-SURVIVAL-PLAN.md` (the wave plan + viability verdict).
>
> **One structured entry per candidate asset.** Each carries: Source · Why · Target · Integration type ·
> White-label actions · Attribution · Effort/Risk/Deps/Sequencing. Sources: `hermes-agent` (MIT © 2025
> Nous Research, `NousResearch/Hermes-Agent`) and `orwell` (MIT © 2026 kevinhirsch).

## Headline result

The audit was commissioned on the premise that hermes-agent's polished frontend should *replace*
`applicant`. **That premise fails the evidence** (see `docs/APPLICANT-SURVIVAL-PLAN.md` §Verdict). The
defensible harvest is **small, surgical, and pattern-dominant** — it lands behind `applicant`'s existing
seams and **never** displaces its domain core. Anything larger crosses into "applicant becomes a hermes
reskin," which loses applicant's only moat. Every entry below is sized to that constraint.

**Legend — Integration type:** `lift-as-is` (copy verbatim, white-label strings) · `adapt` (copy then
modify) · `behind-a-port` (new adapter behind an existing/!new port) · `pattern-only` (rebuild from the
idea; no source file copied, so no notice travels).

---

## A. ACCEPTED HARVESTS (recommended, in priority order)

### A1 — Structural hexagonal-boundary enforcement (import-linter)
- **Source:** `orwell/.dependency-cruiser.cjs:1-108` + `orwell/package.json:29` (`test:arch`), proven by
  orwell `tests/architecture/*` (auditor ran it: 127 modules, 0 violations).
- **Why (evidence/mechanism):** orwell forbids outward modules from *even type-only-importing* a hidden
  port (`tsPreCompilationDeps:true`), default-deny (`no-engine-layer-on-outward`). **Applicant is
  hexagonal but enforces layering by convention + contract tests only** — auditor grep found NO
  import-linter/layer contract in `pyproject.toml` or CI. Nothing structurally stops a future `app/router`
  from importing a `core/rules` safety gate and bypassing it — exactly the invariant applicant's whole
  "engine cannot self-authorize a submit" thesis depends on. **Diagnosis: missing structural guarantee
  (worse architecture), not a missing feature.**
- **Target:** new `[tool.importlinter]` layered contract in `/home/user/applicant/pyproject.toml`; new CI
  step in `.github/workflows/ci.yml` beside ruff/pytest. Forbid `app/`, `adapters/` from reaching
  `application/services` internals out of order; forbid any non-`container.py` module from importing the
  safety-gate internals (`core/rules/{review_gate,prefill_boundary,sensitive_fields,truthfulness}`).
- **Integration type:** **pattern-only** (the `.cjs` is TS-specific; the *discipline* maps 1:1 to
  Python's `import-linter`).
- **White-label actions:** none (no source copied; it's a pattern). The contract is authored fresh.
- **Attribution:** none required (pattern-only, nothing copied). Optional courtesy mention of the idea's
  origin in a code comment — not a legal obligation.
- **Effort / Risk / Deps / Sequencing:** **Low / Low** · dep: `import-linter` (dev). **Wave 1** — cheapest,
  highest-leverage hardening; directly strengthens the safety posture that is applicant's moat.

### A2 — `ProviderProfile` declarative multi-provider pattern
- **Source:** `hermes-agent/providers/base.py:38-218` (the `ProviderProfile` dataclass) + the 16
  `plugins/model-providers/*` profiles as reference shapes. (NOT the 4 heavy adapters wholesale.)
- **Why (evidence/mechanism):** one declarative profile (auth, endpoints, vision, temperature quirks,
  `extra_body`/kwarg splits, per-model max-tokens, live model fetch) replaces the "20+ boolean flags"
  branching. It cleanly reaches **non-OpenAI native APIs** (Anthropic Messages, Bedrock, Gemini) applicant
  cannot currently speak. Tested per-provider in hermes. **Differential:** this is *more reach*
  (missing-capability), NOT better architecture — applicant's `LLMPort` has a capability-ranked **tier
  ladder w/ escalation** + defensive JSON parsing that hermes' transport lacks and that must be preserved.
- **Target:** behind the existing `ports/driven/llm.py` `LLMPort`, implemented in
  `adapters/llm/openai_compatible.py`; wired at `app/container.py:317`. Replace the
  `_ollama_provider`/`_call_openai`/`_call_ollama` branch with a profile table; add concrete providers as
  new **tier backends** (`TierConfig.provider` already namespaces by provider).
- **Integration type:** **pattern-only** for the profile concept; **behind-a-port / adapt** for *at most one*
  concrete adapter (e.g. Anthropic) **only if** a real user requirement for Claude-direct appears.
- **White-label actions (if any concrete code is copied):** rename `HERMES_*`/`NOUS_*` env reads →
  `APPLICANT_*`; **strip the Nous first-party provider** (`nous`/`nous-api`, `NOUS_API_KEY`, Nous Portal
  OAuth — `cli-config.yaml.example:16-18`); remove `nousresearch.com` endpoints; do NOT lift the
  plugin/entry-point machinery.
- **Attribution:** if any `providers/base.py` code is copied → `workspace/licenses/hermes-agent-MIT-LICENSE.txt`
  (verbatim MIT © 2025 Nous Research) + `ACKNOWLEDGMENTS.md` row. Pattern-only ⇒ none, but an
  attribution comment is courteous (applicant already credits "Hermes' skills format" at
  `workspace/services/memory/skill_format.py:4-5`).
- **Effort / Risk / Deps / Sequencing:** profile pattern **Med / Low**; one concrete adapter **Med-High /
  Med** (OAuth/credential reading is a security surface). **Wave 3**, and only if user-demand-gated. Depends
  on the CI denylist work (A6) because it introduces "hermes"/"nous" tokens.

### A3 — Streaming "hugging caret" (front-end polish)
- **Source:** `hermes-agent/web/src/components/Markdown.tsx:24-48` (`StreamingCaret`).
- **Why (evidence/mechanism):** an `aria-hidden` span rendered as the final inline child of the last block
  so the streaming caret hugs the last character instead of orphaning to a new line — a small but real
  "feels finished" affordance applicant's `markdown.js`/`chatStream.js` lack.
- **Target:** `workspace/static/js/markdown.js` (`renderContent`/`processWithThinking` tail) + a CSS rule.
- **Integration type:** **pattern-only** (~10 lines vanilla JS + CSS; do **not** import the React component).
- **White-label actions:** none (no brand strings in the idea).
- **Attribution:** trivial idea; if the snippet is transcribed closely, cite MIT © 2025 Nous Research in a
  comment. No license file needed for ~10 lines of idea-level code (flag to legal if uncomfortable).
- **Effort / Risk / Deps / Sequencing:** **XS / negligible**. **Wave 2** (bundled with the FE-polish pass).

### A4 — Capability allowlist where the type system forbids a sensitive-data tool
- **Source:** `orwell/src/surfaces/tools/registry.ts:8-13,71-73` (`readsVault: false` as a literal, so
  registering a leaker is a compile error) + `orwell/src/adapters/mcp/McpServer.ts:171-181` (channel gate
  refuses off-list tools before dispatch).
- **Why (evidence/mechanism):** turns "this surface must not expose sensitive engine state" from a runtime
  auth check into a *declared, test-pinned* invariant. Applicant's `workspace/routes/applicant_*_routes.py`
  proxies are owner-scoped runtime checks; they cannot today *declare* "this route is structurally
  incapable of returning sensitive state."
- **Target:** applicant's engine-side router/tool registration where `require_automated_work`/review gates
  live; encode each exposed engine operation in a frozen typed registry with `mutates_application` /
  `needs_human_review` flags + a unit test asserting no entry violates the invariant (mirroring orwell's
  drift test `registry.ts:121`).
- **Integration type:** **adapt** (Python lacks literal-`false` field discipline → frozen registry + guard
  test).
- **White-label actions:** drop orwell's "Vault"/"God Mode"/"player/admin channel" vocabulary; use
  applicant's own domain terms.
- **Attribution:** pattern/adapt; if any orwell source is transcribed, MIT © 2026 kevinhirsch travels.
  (`orwell` is already in the CI denylist, so leaked strings fail CI — a built-in guard.)
- **Effort / Risk / Deps / Sequencing:** **Med / Low**. **Wave 2-3** (hardening; complements A1).

### A5 — Anti-fabrication content-lineage "graded downgrade" refinement
- **Source:** `orwell/src/adapters/inmemory/InMemoryKnowledgeService.ts:23-38,99-120`
  (`contentDerivedFrom`: a claim is accepted as ground truth only if its content is a normalized substring
  of something that actually happened; otherwise downgraded to a capped-0.5 *suspicion*, never promoted).
- **Why (evidence/mechanism):** applicant's `core/rules/truthfulness.py` already hard-*raises* on
  unsupported claims — strong, but binary. Orwell's technique adds a **graded** tier: an unsupported
  résumé/cover-letter embellishment becomes a flagged low-confidence *suggestion for human review* rather
  than a hard fail or a silent pass — aligning with applicant's review-before-submit ethos.
- **Target:** `core/rules/truthfulness.py` fabrication path (add a "downgrade to review-flag" tier beside
  the existing raise) + surfacing through the review UI.
- **Integration type:** **adapt** (port the `normalizeContent`/cap-confidence technique into Python).
- **White-label actions:** drop orwell's "Vault"/"suspicion"/"houseguest" framing.
- **Attribution:** MIT © 2026 kevinhirsch if any helper is lifted verbatim.
- **Effort / Risk / Deps / Sequencing:** **Med / Low** · **Confidence M** (refinement, not a gap — applicant's
  guard already covers the core need). **Wave 3** (optional polish).

### A6 — CI white-label denylist hardening (enabling work, not a code asset)
- **Source:** finding from `.github/workflows/ci.yml:28` (current denylist:
  `firehouse|orwell|odysseus|smokey`).
- **Why (evidence/mechanism):** `orwell` is **already** denylisted (an orwell harvest is guarded today).
  `hermes`/`nous` are **not** — so a hermes harvest would not be caught. **But they cannot be naively
  added:** applicant legitimately references the **Hermes/Nous model families** (`hf_models.json`
  `NousResearch/Hermes-3…`; vLLM `--tool-call-parser hermes` at `cookbook_routes.py:129`; pricing/context
  tables; the `skill_format.py:4-5` attribution comment). A blanket add red-walls CI on legitimate strings.
- **Target:** `.github/workflows/ci.yml:28` — add `hermes`/`nous` (and harvested sub-brands) **with scoped
  path-excludes** (`':!**/hf_models.json'`, narrower `nousresearch.com`/`hermes-agent` patterns, or path
  excludes for model-catalog/pricing files).
- **Integration type:** **adapt** (real design task on the denylist regex; not a one-liner).
- **White-label actions:** n/a (this *is* the white-label guard).
- **Attribution:** n/a.
- **Effort / Risk / Deps / Sequencing:** **Med / Med** (false-positive risk). **Must precede any hermes
  string-bearing harvest** (gates A2 and any FE transcription that names hermes).

---

## B. REJECTED HARVESTS (explicit, with reason — so the decision is auditable)

| Asset | Source | Reject reason (mechanism) |
|-------|--------|---------------------------|
| **Hermes web frontend / `@nous-research/ui` design system** | `web/`, `apps/` | Inseparable from React 19 + Vite + Tailwind + private npm DS; chat is an xterm.js terminal embed. Adopting any real component drags the whole stack ⇒ deletes applicant's no-build front-door = **the reskin**. Applicant already equals/exceeds on theming, markdown, feature-state. |
| **Hermes theme model / `Markdown.tsx` renderer / `dashboard-flags.ts`** | `web/src/themes`, `Markdown.tsx`, `lib/dashboard-flags.ts` | Applicant's `theme.js`/`markdown.js`/`applicant_features.py` are **superior or equal** (runtime theming, fuller markdown, real server feature-state vs a 24-line stub). Harvest would be a downgrade. |
| **`JsonRpcGatewayClient` (WS RPC)** | `apps/shared/src/json-rpc-gateway.ts` | Clean code, **wrong transport** — applicant streams over SSE/HTTP, zero WebSocket consumers. Adoption = a transport rewrite for no gain. |
| **Ink terminal utils** (`stringWidth`, `sliceAnsi`, `parse-keypress`, `optimizer`) | `ui-tui/packages/hermes-ink/*` | Excellent terminal primitives; applicant's front-door is a browser DOM app — **no terminal surface to consume them**. |
| **Memory + skills learning loop** | `agent/curator.py`, `background_review.py`, `trajectory_compressor.py` | **Different problem, not better.** Hermes distills reusable *procedures* from varied agent trajectories (needs a tool-calling agent doing varied tasks). Applicant does ONE task; its `learning_service.py` is statistical *yield/taste* learning. No common better/worse axis; harvest = paradigm import. |
| **Multi-platform gateway** | `gateway/` (`run.py` ~17.7k ln) | Applicant's need is *notifications*, already better-fit (`notification.py` + Apprise escalation ladder). Inbound 18-platform chat = chat-ops product applicant doesn't want. |
| **Cron system** | `cron/` (`scheduler.py` ~2.5k ln) | Applicant has the in-scope slice done more durably: `Scheduler.tick()` + `DurableOrchestrationPort.schedule()` w/ crash recovery. Hermes cron is JSON+flock, gateway-coupled. |
| **MCP server+client** | `mcp_serve.py`, `tools/mcp_tool.py` | No tool-injection registry to inject into; applicant's `ToolRegistryPort` is a feature on/off toggle. Its one external capability (deep research) is a bounded budget-capped callback. |
| **Subagent spawning** | `tools/delegate_tool.py` | No `AIAgent` to fork. Applicant's parallelism is durable queues + per-campaign sandbox slots w/ yield/pivot — multiple *applications*, not multiple *agents*. |
| **5/6 terminal backends** (SSH/Singularity/Modal/ManagedModal/Daytona) | `tools/environments/*` | HPC/cloud scope creep (~7.5k LOC + ~12 SDK deps). Applicant's only sandbox need (browser for form-fill) is covered by `ports/driven/sandbox.py` + Proxmox/local adapters. |
| **Orwell `src/engine/*`** (blocs/jury/gossip/evictions…) | `orwell/src/engine` | Big-Brother-SIM-specific game logic; zero transfer to a job-application engine. |
| **Orwell Python `frontend/`** | `orwell/frontend` | Sibling fork of applicant's OWN upstream workspace — net-negative (duplicates what applicant has, re-introduces a codename to scrub). |
| **Orwell LXC/systemd deploy & SQLite persistence** | `orwell/deploy`, `src/adapters/sqlite` | Different-not-better than applicant's Docker Compose + `scripts/update.sh` and Postgres+Alembic+chromadb. |
| **BDD/cucumber harness** | `orwell/features` | "Executable spec per requirement" is a nice discipline, but retrofitting Gherkin onto applicant's well-named pytest is a large lift for marginal gain (philosophy-only). |

---

## C. Cross-cutting white-label & licensing rules (apply to every accepted harvest)

1. **License files land before code.** Add `workspace/licenses/<src>-MIT-LICENSE.txt` (verbatim, modeled on
   `workspace/licenses/opencode-MIT-LICENSE.txt`) + an `ACKNOWLEDGMENTS.md` row **in the same or a prior
   commit** as the harvested code — never strip attribution to "clean up."
2. **Attribution that must travel:** hermes → `MIT © 2025 Nous Research`; orwell → `MIT © 2026 kevinhirsch`.
   Hermes is a **new** third-party holder for this repo (Nous Research appears nowhere yet); orwell's
   holder (`kevinhirsch`) already appears in `THIRD_PARTY_LICENSES.md`.
3. **Attribution (carry with every harvest):** applicant is MIT © 2026 kevinhirsch; harvested portions
   stay under their upstream MIT notices (Nous Research / kevinhirsch). MIT ⊕ MIT — clean, no legal
   escalation. Add `workspace/licenses/<src>-MIT-LICENSE.txt` + `ACKNOWLEDGMENTS.md` row per harvest.
4. **Brand-rename pass per harvest:** module/file names → env vars (`HERMES_*`/`ORWELL_*`/`NOUS_*` →
   `APPLICANT_*`) → config dirs/paths → URLs/outbound headers (`X-OpenRouter-Title`, User-Agent) →
   user-facing copy → assets. **Data keys (`orwell_memories` Chroma collection, `HERMES_HOME`-pathed state)
   are migrations, not seds.**
5. **CI denylist (A6) gates string-bearing hermes harvests.** Add `hermes`/`nous` with scoped excludes
   *before* importing any hermes code that could leak the tokens.
6. **Reachability + green-increment gate** (binding principles #2/#5): every harvest must light up through
   the white-labeled front-door, and pass engine pytest + front-door `test_applicant_*` + ruff + boot smoke
   + single Alembic head + `docker compose config` + the denylist.

---

## D. The guardrail (the line that keeps "applicant" applicant)

Every entry above lands **behind an existing applicant seam** (`ports/driven/llm.py`,
`workspace/src/applicant_engine.py`, `core/rules/*`, `pyproject.toml` contracts) and **none** displaces
`application/services/agent_loop.py`. The moment a harvest proposes replacing the domain agent loop,
gateway, or tool model with hermes' general equivalents, it has crossed from "harvest into applicant" to
"applicant becomes a hermes reskin" — and by the moat analysis (`APPLICANT-SURVIVAL-PLAN.md` §1) that
trade loses applicant's only defensible advantage. **Do not cross it.**
