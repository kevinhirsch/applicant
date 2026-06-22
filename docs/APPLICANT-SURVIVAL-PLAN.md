# APPLICANT-SURVIVAL-PLAN.md — Keep-applicant-alive plan + viability verdict

> **Status:** Phase 4 deliverable of the Harvest & White-Label Migration Audit. This is a **document, not
> code** — no harvest has been executed. It synthesizes `HARVEST-INVENTORY.md` (five read-only
> sub-auditor deep-dives) and `docs/HARVEST-MAP.md` into a prioritized, wave-sequenced action list and an
> honest viability verdict. Closes at a **review gate**: no code moves before authorization.

---

## 0. The question we were asked

Leadership is weighing **killing `applicant` and adopting `hermes-agent`** instead, "because hermes'
frontend just works." The mandate was to determine — with evidence — what to harvest from hermes-agent
and orwell, where it lands, how to white-label it, and from that, whether `applicant` has a real reason
to live or replacement wins.

---

## 1. VIABILITY VERDICT — **KEEP `applicant`** (Confidence: High)

**The replace-with-hermes premise does not survive contact with the code.** Three findings, each
independently sufficient, jointly decisive:

1. **The headline asset isn't transferable.** Hermes' "frontend that just works" is a React 19 + Vite +
   Tailwind + private-npm-design-system app whose chat is an xterm.js *terminal embed* — a management
   dashboard inseparable from its build stack. Adopting it forces a bundler/React/TS onto applicant's
   deliberate no-build front-door, all-or-nothing, which **is** the reskin. And applicant's existing
   front-door already **equals or exceeds** it on the axes that transfer to a browser product: runtime
   theming (`theme.js`, 3,790 CSS-var refs), markdown (`markdown.js`, 803 ln with thinking blocks /
   mermaid / sanitization vs hermes' self-described "NOT CommonMark" 383-line renderer), and a real
   server-side feature-state machine (`applicant_features.py`, 253 ln vs a 24-line stub). *The thing we
   were told to switch for, we substantially already have.*

2. **Hermes' platform has no socket in applicant.** Applicant is not an LLM-tool-calling agent — it has
   no agent loop, MCP, subagents, or general terminal to attach hermes' platform to. For every in-scope
   sliver it already has a **right-sized domain equivalent** (statistical learning, durable scheduler,
   Apprise notification escalation ladder, browser-only sandbox). Only the `ProviderProfile` *pattern* is
   worth taking, and even that is a *want*, behind an `LLMPort` that is arguably cleaner than hermes'
   (it has a tier-ladder + defensive JSON parsing hermes lacks).

3. **Applicant's moat is real, load-bearing, and exclusive.** ~31k LOC of job-application domain logic,
   pinned by **1,214 tests**, that hermes has **zero** of: the 19-state ATS pre-fill orchestration
   machine (account gate / 2FA push-poll / detection pause / stop-at-final-submit;
   `prefill_service.py`, `core/state_machine.py`), the scar-tissued deterministic **fabrication guard**
   (`truthfulness.py`, 566 ln), the **render-fidelity** LaTeX/docx tailor with pypdf font-embedding
   inspection, the **server-side safety gates** a caller cannot opt out of (`review_gate.py`,
   `prefill_boundary.py`, `sensitive_fields.py`), the libsodium credential vault, and the conversion-yield
   learning loop. **Replacing applicant means rebuilding all of this on a foreign architecture and
   re-earning every bug fix and safety proof — to gain a frontend we can more cheaply improve in place.
   That trade is strictly worse.**

**The reskin question, answered head-on:** harvesting *surgically* (FE polish patterns, the provider
profile pattern, a structural import boundary, a couple of safety refinements) **keeps it applicant** —
the product's identity is the engine and its safety posture, not the pixels. It becomes a hermes reskin
**only if** hermes' agent-loop / gateway / tool-model replaces `application/services/agent_loop.py` as
the core. **That line is the single explicit guardrail of this plan and must not be crossed.**

**What the replace case got right (and this plan delivers):** applicant's **front-end polish/cohesion
(W1)** is a legitimate weakness, its **multi-provider reach (W2)** is narrow, and its **live-Workday
path (W4)** is wired but never demonstrated in CI. Keeping applicant is the right call *because* these
are fixable in place without touching the moat — which is exactly what the waves below do.

> **Timeline/effort to "competitive":** Wave 1 (days) removes the architectural-rigor gap leadership can
> see. Wave 2 (1–2 weeks) closes the visible FE-polish gap that drove the replace conversation. Waves 3–4
> (2–4 weeks, demand-gated) add provider reach and convert "wired" to "proven." None requires a
> re-platform. **The honest headline: applicant is not behind on substance — it is behind on a frontend
> coat of paint and one CI lane, both cheaply fixable.**

---

## 2. Prioritized action list — sequenced into waves

Each item traces to a `docs/HARVEST-MAP.md` entry (A#) or is enabling work. Ordered highest-leverage /
lowest-risk first. **Wave 1 is the leadership-facing, lowest-risk credibility win** — note it is NOT the
FE harvest, because the FE harvest was rejected; the highest-leverage cheap win is hardening the moat's
structural guarantee.

### Wave 1 — Cheap, high-leverage hardening (Low risk · ~days · no white-label exposure)
- **[A1] Add a structural import-linter boundary contract** to `pyproject.toml` + a CI step. Forbid
  `app/`/`adapters/` from reaching `application/services` internals out of order and from importing the
  `core/rules/*` safety gates outside `container.py`. *Why first:* it converts applicant's central safety
  thesis ("the engine cannot self-authorize a submit") from convention into a CI-enforced invariant — the
  one place orwell was genuinely cleaner — at near-zero cost and zero brand surface.
- **[A6, part 1] Document the white-label denylist gap.** No code; record that `hermes`/`nous` need scoped
  path-excludes before any hermes harvest (precondition for Wave 3).

### Wave 2 — Front-door polish (the visible W1 gap) (Low-Med risk · ~1–2 weeks · no framework change)
- **[A3] Streaming "hugging caret"** in `markdown.js` (pattern-only, vanilla JS + CSS).
- **FE cohesion pass on the existing stack** (not a harvest — in-house): audit `applicant*.js` against the
  workspace design system (`.cal-btn`, `.admin-card`, `.settings-*`) for consistency, empty/loading/error
  states, and the OOBE→Settings flow, using the playtest protocol (`docs/playtest-protocol.md` §6a monkey
  crawl). *Rationale:* the auditors found applicant's FE weakness is **cohesion/polish on a sound base**,
  not a missing capability — so the remedy is finishing it, not replacing it. This is the direct,
  honest answer to "their frontend just works": make ours just work, on the stack we already have.
- **[A4] Typed capability allowlist** for engine-exposed operations (`mutates_application`/
  `needs_human_review` flags + a drift test). Hardens the proxy boundary; complements A1.

### Wave 3 — Provider reach + safety refinement (Med risk · demand-gated · ~1–2 weeks)
- **[A6, part 2] Implement the scoped CI denylist** (`hermes`/`nous` with path-excludes for
  `hf_models.json`, model-catalog/pricing files). **Must land before A2 code.**
- **[A2] `ProviderProfile` pattern** behind `LLMPort` (preserve the tier ladder). Add **one** concrete
  non-OpenAI adapter (Anthropic) *only if* a real user requirement appears. License files + attribution
  land first.
- **[A5] Graded-downgrade refinement** to the fabrication guard (`truthfulness.py`) — unsupported
  embellishments become review-flagged suggestions, not silent passes or hard fails.

### Wave 4 — Prove the moat is operable (Med-High value · addresses W4)
- **Stand up the integration lane at least once in CI/staging:** real browser (Camoufox/Chromium) + TeX +
  a live ATS dry-run, converting the 28 skip-on-absent-dep integration tests from "wired" to
  "demonstrated." *Why last but important:* the keep decision rests on the moat being **operable**, not
  just tested against fakes. This is the highest-credibility evidence that applicant does the hard thing
  hermes cannot.

### Explicitly NOT doing (and why) — see `docs/HARVEST-MAP.md` §B
Hermes web FE / design system, theme model, WS gateway client, Ink utils, the memory+skills loop,
multi-platform gateway, cron, MCP, subagents, 5/6 terminal backends; orwell's game engine, Python
frontend, LXC deploy, SQLite persistence, and cucumber harness. Each rejected with a cited mechanism.
**Above all: do not replace `agent_loop.py` with hermes' agent loop** — that is the reskin line.

---

## 3. Attribution & legal obligations (carry into every executed wave)

- **Before any code copy:** `workspace/licenses/<src>-MIT-LICENSE.txt` (verbatim) + `ACKNOWLEDGMENTS.md`
  row. hermes → MIT © 2025 Nous Research (**new** holder for this repo); orwell → MIT © 2026 kevinhirsch
  (already present in `THIRD_PARTY_LICENSES.md`).
- **⚠️ Mixed-license question for human/legal review (NOT resolved here):** applicant is Unlicense (public
  domain); harvested portions remain MIT. The repo's licensing story must explicitly state "portions are
  MIT — see `THIRD_PARTY_LICENSES.md`/`licenses/`" and must not over-claim public domain over harvested
  files. **Sign-off required before merge of any string/code harvest.**
- Most of Wave 1–2 is **pattern-only** (A1, A3) — nothing copied, so no notice travels; the legal item
  binds mainly on Wave 3 (A2 concrete adapter, A5 verbatim helper).

---

## 4. Risk register

| ID | Risk | Mitigation |
|----|------|------------|
| R1 | Hermes env-var rename fan-out (~280 `HERMES_*`) misses a token | Scope to pattern-only/single-module lifts; A6 denylist catches leaks |
| R2 | Outbound brand leak (`X-OpenRouter-Title`, User-Agent) escapes post-harvest | Rename pass step 4; grep outbound headers in review |
| R3 | Mixed-license over-claim (Unlicense vs MIT) | §3 legal sign-off gate before merge |
| R4 | "Reskin creep" — a harvest grows toward replacing the agent loop | §1 guardrail; A1 import-linter makes core displacement visible in CI |
| R5 | Scoped denylist still red-walls legitimate Hermes/Nous model references | A6 is a real design task with path-excludes, tested before A2 |
| R6 | Wave 4 integration lane flakiness in CI | Run as a separate non-blocking lane first; stabilize before gating |

---

## 5. Bottom line for the gate

`applicant` should **live**. It is not losing on substance — it owns a deep, test-pinned, safety-first
job-application moat that the proposed replacement has none of. It is losing on **frontend polish and one
unproven CI lane**, both fixable in place in weeks without a re-platform. The harvest that helps is
**small and surgical** (one strong orwell architecture pattern, a provider abstraction pattern, a FE
micro-polish, two safety refinements) and lands entirely behind existing seams. Adopting hermes wholesale
would throw away the moat to buy a frontend we can more cheaply finish ourselves — and would make
applicant a hermes reskin. **Recommendation: approve Wave 1 now; sequence Waves 2–4 as scoped above;
obtain legal sign-off on the mixed-license question before any Wave 3 code harvest.**
