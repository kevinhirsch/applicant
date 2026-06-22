# HARVEST-WAVE-FEATURES.md — Feature drafts for the survival-plan waves

> **Status:** Planning artifact (Phase 4+). **No code is implemented here** — these are drafted feature
> specs, one per action item in `docs/APPLICANT-SURVIVAL-PLAN.md`, written in applicant's house style
> (requirement + scope + acceptance criteria + reachability + test plan + white-label/attribution + DoD).
> Each traces to a `docs/HARVEST-MAP.md` entry (A#). Authored for review **before** any wave is authorized
> to implement.
>
> **Binding constraints carried into every feature (CLAUDE.md principles):** #1 lift-and-shift before
> rebuild; #2 reachability is the definition of done (verify the white-labeled front-door chain, not just
> the engine); #3 white-label always (CI denylist clean); #4 front-door proxies, engine owns logic;
> #5 green increments (engine pytest + front-door `test_applicant_*` + ruff + boot smoke + single Alembic
> head + `docker compose config` + denylist all pass).
>
> **The guardrail (applies to all):** no feature may displace `application/services/agent_loop.py` with a
> general agent loop. Each lands behind an existing applicant seam.

---

## Proposed requirement IDs

These features introduce a `FR-HARVEST-*` group (and one `NFR-ARCH-*`). They are drafts pending the
owner folding accepted ones into `docs/spec/master-spec.md` and `docs/work-packages.md`.

| Feature | Wave | Harvest-map | Integration type | Brand exposure |
|---------|------|-------------|------------------|----------------|
| NFR-ARCH-1 — Structural layer boundary | 1 | A1 | pattern-only | none |
| FR-HARVEST-DENYLIST — White-label denylist hardening | 1 (doc) → 3 (impl) | A6 | adapt (CI) | n/a (is the guard) |
| FR-HARVEST-CARET — Streaming caret | 2 | A3 | pattern-only | none |
| FR-HARVEST-FEPOLISH — Front-door cohesion pass | 2 | (in-house) | n/a | none |
| FR-HARVEST-CAPREG — Typed capability allowlist | 2 | A4 | adapt | none |
| FR-HARVEST-PROVIDER — Provider-profile abstraction | 3 | A2 | pattern + behind-port | **hermes/nous** |
| FR-HARVEST-TRUTHTIER — Graded fabrication downgrade | 3 | A5 | adapt | none |
| NFR-OPS-1 — Integration lane proof | 4 | (in-house) | n/a | none |

---

# WAVE 1 — Cheap, high-leverage hardening

## NFR-ARCH-1 — Structurally enforced hexagonal layer boundary
- **Trace:** `HARVEST-MAP.md` A1 (source pattern: `orwell/.dependency-cruiser.cjs:1-108`).
- **Problem (evidence):** applicant is hexagonal but enforces layering by convention + contract tests
  only — no import-linter/layer contract exists in `pyproject.toml` or `.github/workflows/ci.yml`. Nothing
  structurally prevents a future `app/router` or adapter from importing a `core/rules/*` safety gate and
  bypassing it, which directly undercuts the "engine cannot self-authorize a final submit" guarantee.
- **Requirement:** the build MUST fail when a module imports across a forbidden layer edge. Specifically:
  `app/` and `adapters/` MUST NOT import `application/services` internals out of declared order; no module
  except `app/container.py` (the composition root) MAY import the safety-gate internals
  `core/rules/{review_gate,prefill_boundary,sensitive_fields,truthfulness}`.
- **Scope:** add `import-linter` (dev dep) + a `[tool.importlinter]` layered contract to `pyproject.toml`;
  add a CI step beside ruff/pytest. **No application code changes** beyond fixing any existing violation
  the linter surfaces (each such fix is itself a finding to report, not a silent edit).
- **Acceptance criteria:**
  1. `lint-imports` (or equivalent) runs green locally and in CI on a clean tree.
  2. A deliberately-introduced illegal import (e.g. `app/routers/x.py` importing `core/rules/review_gate`)
     fails the check with a clear message. (Proven via a throwaway branch, not committed.)
  3. The contract documents each layer and the one sanctioned edge (composition root).
- **Reachability:** N/A (build-time guarantee) — but it *protects* a front-door-reachable safety property.
- **Test plan:** the CI step itself is the test; add a short `tests/architecture/test_layering_contract`
  doc/marker if a runtime assertion is wanted. Existing 1,214 tests must stay green.
- **White-label / attribution:** none — pattern-only, no source copied. Optional courtesy comment noting
  the dependency-cruiser origin of the idea.
- **Dependencies / sequencing:** none. First item; unblocks confidence for later waves.
- **Effort / risk:** Low / Low.

## FR-HARVEST-DENYLIST — White-label codename denylist hardening (Wave 1 = document; Wave 3 = implement)
- **Trace:** `HARVEST-MAP.md` A6 (finding at `.github/workflows/ci.yml:28`).
- **Problem (evidence):** the denylist (`firehouse|orwell|odysseus|smokey`) already blocks `orwell` but NOT
  `hermes`/`nous`. A hermes harvest would not be caught. **But** applicant legitimately references the
  Hermes/Nous *model families* (`workspace/services/hwfit/data/hf_models.json`; vLLM
  `--tool-call-parser hermes` at `cookbook_routes.py:129`; model context/pricing tables; the attribution
  comment at `workspace/services/memory/skill_format.py:4-5`), so a blanket add red-walls CI.
- **Requirement:** before any hermes string-bearing code lands, the denylist MUST block product/brand
  codenames (`hermes`, `nous`, harvested sub-brands) while NOT matching legitimate model-family references.
- **Scope (Wave 1):** documentation only — this spec + the precondition note in the survival plan.
  **Scope (Wave 3):** modify `ci.yml:28` to add `hermes`/`nous` with scoped path-excludes
  (`':!**/hf_models.json'`, narrower `nousresearch.com`/`hermes-agent` patterns, or path-excludes for the
  model-catalog/pricing files).
- **Acceptance criteria:** (Wave 3) the denylist fails on an injected `Hermes`/`Nous` product/brand string
  in a harvested module, and passes on the current tree (no false positives on the known legitimate refs,
  enumerated above).
- **Reachability:** N/A (CI guard).
- **Test plan:** run the grep against the current tree (must pass) and against a seeded violation (must fail).
- **White-label / attribution:** n/a (this is the white-label guard).
- **Dependencies / sequencing:** **MUST land before FR-HARVEST-PROVIDER code** (the only hermes string-bearer).
- **Effort / risk:** Med / Med (false-positive risk — real regex design task).

---

# WAVE 2 — Front-door polish (the visible W1 weakness)

## FR-HARVEST-CARET — Streaming "hugging caret" in the chat renderer
- **Trace:** `HARVEST-MAP.md` A3 (idea: `hermes-agent/web/src/components/Markdown.tsx:24-48`).
- **Problem:** during token streaming, applicant's renderer has no caret affordance that hugs the last
  character; the cursor/indicator orphans, which reads as less "finished."
- **Requirement:** while a message is streaming, a caret indicator MUST render as the final inline element
  of the last rendered block and disappear on completion; it MUST be `aria-hidden` and not affect copied text.
- **Scope:** ~10 lines of vanilla JS in `workspace/static/js/markdown.js`
  (`renderContent`/`processWithThinking` tail) + a CSS rule reusing the workspace design system. **Do not**
  import any React component.
- **Acceptance criteria:**
  1. Caret appears at the tail of streamed content and is removed when the stream ends.
  2. Selecting/copying the message does not include the caret glyph.
  3. No regression in existing markdown rendering (thinking blocks, mermaid, sanitization).
- **Reachability:** chat surface in the front-door (`applicantChat.js` / chat stream) — verify visually via
  `docs/playtest-protocol.md`.
- **Test plan:** front-door `test_applicant_*` smoke for the chat route still passes; manual/Playwright
  visual check of the caret per playtest §6a.
- **White-label / attribution:** none (no brand strings in the idea). If transcribed closely, a courtesy
  comment citing MIT © 2025 Nous Research; flag to legal if any concern about idea-level copying.
- **Dependencies / sequencing:** none; bundle with FE polish pass.
- **Effort / risk:** XS / negligible.

## FR-HARVEST-FEPOLISH — Front-door cohesion pass (in-house, on the existing stack)
- **Trace:** `APPLICANT-SURVIVAL-PLAN.md` Wave 2 (in-house; addresses weakness W1). **Not a hermes harvest.**
- **Problem (evidence):** the auditors found applicant's FE weakness is **cohesion/polish on a sound base**,
  not a missing capability — 7 hand-rolled `applicant*.js` modules (~4.9k LOC) with uneven empty/loading/
  error states and OOBE→Settings flow seams. The honest answer to "their frontend just works" is to finish
  ours on the stack we already have — NOT to adopt React/Vite (rejected, `HARVEST-MAP.md` §B).
- **Requirement:** every front-door surface MUST present consistent loading, empty, and error states using
  the workspace design system (`.cal-btn`, `.admin-card`, `.settings-*`, `.memory-*`); the OOBE wizard →
  Settings re-entry MUST be coherent; no dead/locked UI without explanation (reuse `applicant_features.py`
  state + tooltips).
- **Scope:** audit-driven refinements to existing `workspace/static/js/applicant*.js` + CSS only. No build
  step introduced. No new framework. No hermes code.
- **Acceptance criteria:**
  1. The Playwright monkey/crawl (`docs/playtest-protocol.md` §6a) opens every surface, clicks every
     control, and reports zero unhandled error/empty states.
  2. Each section's active/locked/disabled state matches `applicant_features.py`, with a tooltip explaining
     any locked/disabled state.
  3. `node --check` passes on all changed JS; front-door `test_applicant_*` green.
- **Reachability:** the whole front-door — this feature *is* a reachability/UX pass.
- **Test plan:** playtest protocol §6a automated crawl + the contract sweep; front-door proxy tests.
- **White-label / attribution:** none (in-house).
- **Dependencies / sequencing:** can run parallel to FR-HARVEST-CARET; benefits from NFR-ARCH-1 being in.
- **Effort / risk:** Med / Low (bounded, no framework change).

## FR-HARVEST-CAPREG — Typed capability allowlist for engine-exposed operations
- **Trace:** `HARVEST-MAP.md` A4 (pattern: `orwell/src/surfaces/tools/registry.ts:8-13,71-73` +
  `McpServer.ts:171-181`).
- **Problem (evidence):** applicant's `workspace/routes/applicant_*_routes.py` proxies enforce owner-scope
  at runtime but cannot *declare* "this operation is structurally incapable of returning sensitive engine
  state / mutating an application without review."
- **Requirement:** each engine operation exposed through the front-door MUST be registered in a frozen,
  typed registry carrying explicit flags (e.g. `mutates_application: bool`, `needs_human_review: bool`,
  `exposes_sensitive: bool`); a drift test MUST fail if any registered entry violates the declared
  invariants (mirroring orwell's `registry.ts:121` drift test).
- **Scope:** engine-side registration where `require_automated_work`/review gates live + a unit test. Adapt
  to Python (frozen dataclass/enum registry; Python lacks literal-`false` field discipline).
- **Acceptance criteria:**
  1. Every `/api/applicant/*`-exposed engine op has a registry entry.
  2. The drift test fails when a sensitive op is registered without `needs_human_review`/with
     `exposes_sensitive` mismatched.
  3. Existing gates (`review_gate`, `prefill_boundary`) remain the runtime enforcers — the registry
     *declares*, it does not replace them.
- **Reachability:** the proxy boundary — verify a sensitive op is declared and gated end-to-end.
- **Test plan:** new unit + the existing safety-gate tests stay green.
- **White-label / attribution:** drop orwell "Vault"/"God Mode"/channel vocabulary; MIT © 2026 kevinhirsch
  only if any orwell source is transcribed (and `orwell` is already denylisted, guarding leaks).
- **Dependencies / sequencing:** complements NFR-ARCH-1.
- **Effort / risk:** Med / Low.

---

# WAVE 3 — Provider reach + safety refinement (Med risk · demand-gated)

## FR-HARVEST-PROVIDER — Declarative multi-provider profile abstraction
- **Trace:** `HARVEST-MAP.md` A2 (source: `hermes-agent/providers/base.py:38-218`).
- **Problem (evidence):** applicant's `adapters/llm/openai_compatible.py` covers OpenAI-compatible + Ollama;
  it cannot speak non-OpenAI native APIs (Anthropic Messages, Bedrock, Gemini). This is *missing reach*, not
  worse architecture — applicant's `LLMPort` has a tier-ladder + defensive JSON parsing hermes lacks.
- **Requirement:** provider-specific quirks (auth, endpoints, vision, temperature handling, kwarg splits,
  per-model max-tokens, live model fetch) MUST be expressible as a declarative profile behind the existing
  `ports/driven/llm.py` `LLMPort`, **without** removing the capability-ranked tier ladder or the defensive
  structured-output parsing. Adding a new provider MUST NOT require touching the transport branch logic.
- **Scope:** pattern-only for the profile concept (replace the `_ollama_provider`/`_call_openai`/
  `_call_ollama` branch with a profile table); wired at `app/container.py:317`; add **at most one** concrete
  non-OpenAI adapter (Anthropic) as a new tier backend (`TierConfig.provider` already namespaces) **only if**
  a real user requirement appears. Do NOT lift hermes' plugin/entry-point machinery or its 4 heavy adapters.
- **Acceptance criteria:**
  1. Existing OpenAI-compatible + Ollama behavior unchanged (regression-tested), tier ladder intact.
  2. A new provider can be added by declaring a profile only.
  3. (If Anthropic adapter built) it slots behind `LLMPort` as a tier backend with no transport-branch edits;
     OAuth/credential reading reviewed as a security surface.
- **Reachability:** model selection in the front-door (model-endpoint manager / `applicantModelLadder.js`) —
  a newly-declared provider must be selectable through the white-labeled UI.
- **Test plan:** port-contract tests for `LLMPort`; profile-table unit tests; front-door `test_applicant_*`
  for model selection; boot smoke.
- **White-label / attribution:** **license files land first** —
  `workspace/licenses/hermes-agent-MIT-LICENSE.txt` (verbatim MIT © 2025 Nous Research) +
  `ACKNOWLEDGMENTS.md` row. Rename any `HERMES_*`/`NOUS_*` env reads → `APPLICANT_*`; **strip the Nous
  first-party provider** (`nous`/`nous-api`, `NOUS_API_KEY`, Nous Portal OAuth); remove `nousresearch.com`
  endpoints.
- **Dependencies / sequencing:** **BLOCKED until FR-HARVEST-DENYLIST (Wave 3 impl) lands** (introduces
  hermes/nous tokens) **and** legal sign-off on the mixed-license question.
- **Effort / risk:** profile pattern Med / Low; Anthropic adapter Med-High / Med.

## FR-HARVEST-TRUTHTIER — Graded "downgrade to review" tier in the fabrication guard
- **Trace:** `HARVEST-MAP.md` A5 (technique: `orwell/src/adapters/inmemory/InMemoryKnowledgeService.ts:23-38`).
- **Problem (evidence):** `core/rules/truthfulness.py` hard-raises on unsupported claims — strong but binary.
  An unsupported-but-plausible cover-letter embellishment is either hard-failed or (in prose mode) passes.
- **Requirement:** the fabrication guard SHOULD support a graded outcome: a claim whose content is not
  derivable (normalized-substring) from the candidate's true attribute set MAY be **downgraded to a
  capped-confidence review-flag** (surfaced as a suggestion for human review) rather than only hard-failing
  — never silently promoted to ground truth. The existing hard-raise path for clear fabrications MUST remain.
- **Scope:** add the `normalizeContent`/derivation-check + cap-confidence technique as a new tier in
  `truthfulness.py`; surface flags through the existing review UI (redline). Adapt to Python.
- **Acceptance criteria:**
  1. A clearly-invented credential (e.g. unearned "Stanford"/"PhD") still hard-raises.
  2. A borderline unsupported phrase becomes a review-flagged suggestion, not a silent pass.
  3. Numeric/whole-token matching behavior (`:443`,`:456`) preserved; existing truthfulness tests green.
- **Reachability:** the review/redline surface (`documentLibrary.js`) — flags must appear for the user.
- **Test plan:** extend `truthfulness` unit tests with graded-downgrade cases; front-door review proxy test.
- **White-label / attribution:** drop orwell "Vault"/"suspicion"/"houseguest" framing; MIT © 2026
  kevinhirsch if any helper lifted verbatim.
- **Dependencies / sequencing:** independent; optional polish.
- **Effort / risk:** Med / Low · Confidence M (refinement, not a gap).

---

# WAVE 4 — Prove the moat is operable

## NFR-OPS-1 — Integration lane demonstrating the live ATS/render path
- **Trace:** `APPLICANT-SURVIVAL-PLAN.md` Wave 4 (addresses weakness W4; in-house).
- **Problem (evidence):** 1,214 tests prove logic against fakes; only 28 `@pytest.mark.integration` tests
  exercise the real browser/TeX/boards and they skip on absent deps. The real-Workday/real-render path is
  *wired* (`container.py`) but never CI-demonstrated — the keep decision rests on the moat being operable.
- **Requirement:** at least once, in a CI or staging lane, the system MUST exercise the real browser
  (Camoufox/Chromium) + real TeX render + a live ATS dry-run end-to-end (stopping at the review/pre-fill
  boundary — never an actual final submit), producing an artifact (rendered PDF + state-machine trace) as
  evidence.
- **Scope:** a separate, initially non-blocking CI lane (or documented staging run) that builds the engine
  image with the browser/TeX deps and runs the integration-marked tests against a sandbox target. No product
  code change required if the paths already work; any gap found is a finding.
- **Acceptance criteria:**
  1. The lane renders a font-embedded PDF and passes the pypdf inspection (`latex_tailor.py:356,418`).
  2. The ATS dry-run reaches `MATERIAL_REVIEW`/`AWAITING_FINAL_APPROVAL` without crossing the submit
     boundary (`prefill_boundary.py` honored).
  3. The lane is reproducible and its artifacts are retained.
- **Reachability:** demonstrates the front-door → engine → real-world chain end-to-end (the strongest
  reachability proof in the audit).
- **Test plan:** the integration-marked suite itself, run with deps present; stabilize before any gating.
- **White-label / attribution:** none (in-house).
- **Dependencies / sequencing:** last; highest setup cost. Start as non-blocking to avoid CI flakiness (risk R6).
- **Effort / risk:** Med-High value / Med (environment/flakiness).

---

## Open decisions for the owner (before implementing any wave)
1. Confirm the `FR-HARVEST-*` / `NFR-ARCH-1` IDs and fold accepted ones into `docs/spec/master-spec.md` +
   `docs/work-packages.md`.
2. Legal sign-off on the mixed-license (Unlicense ⊕ MIT) question — gates Wave 3 code (FR-HARVEST-PROVIDER,
   FR-HARVEST-TRUTHTIER if verbatim).
3. Whether FR-HARVEST-PROVIDER's concrete Anthropic adapter is in scope now or deferred until user-demand.
4. Whether NFR-OPS-1 runs in CI or as a documented staging procedure first.
