# Design Spec — Plan-as-Data execution + system-wide autonomy upgrade

Status: **proposal** (forward-looking; not yet implemented). Author target: the
engine maintainers. White-labeled throughout (Applicant domain terms only).

## 0. Why

Generic browser agents run a vision loop: `screenshot → LLM → click → screenshot →
…`, one model call per step. The "code-as-plan" idea (rtrvr.ai / Retriever, and the
broader plan-and-execute literature) replaces that with **one model call that emits a
whole plan over a semantic DOM**, executed by a local harness — cutting model
round-trips ~N→1 per page and the per-step latency/cost.

Applicant is *already* past the screenshot loop (it does DOM field-detection, not
vision), but it still reasons step-by-step. This spec adopts the plan-once idea **as
the system's general intelligence substrate**, not just for pre-fill — while keeping
Applicant's safety guarantees intact.

**The safe re-write of "code-as-plan" for Applicant is _plan-as-data_:** the model
emits a **typed operation list** (validated against a schema), and the trusted
camoufox/Playwright harness executes each op through the *existing* guarded actions.
No model-authored code runs on the consequential path. This is the **Hybrid** posture
chosen for this work:

- **Typed-DSL plan** on the safety-critical fill/submit path (executed by the harness).
- **Read-only sandboxed JS** for discovery/extraction (no side effects, nothing to submit).

It implements directly on **camoufox** because camoufox is Firefox-driven-by-Playwright
and the engine's `PageSource` (`adapters/browser/page_source.py`) already *is* that
harness.

## 1. Core concept — the Plan-as-Data DSL

A **Plan** is an ordered list of typed **Ops** the model emits in one shot. Each Op is
data, validated against a JSON Schema before anything executes. The op set is small and
closed (no escape hatch into arbitrary code):

| Op | Args | Notes |
|---|---|---|
| `goto` | `url` | Untrusted URLs pass `assert_navigable_url` (the SSRF guard shipped in #168). |
| `find` | `ref`, `role`, `name?`, `near?` | Resolve a stable element handle from the semantic snapshot (§2). |
| `fill` | `ref`, `attribute_id` | Fill an element with a value **from the attribute cloud by id** — never a literal the model invented (fabrication guard). |
| `select` | `ref`, `attribute_id` | Same, for dropdowns/radios. |
| `click` | `ref` | Routed through `ensure_action_allowed` (stop-boundary). |
| `upload` | `ref`, `document_id` | An allowed pre-fill step (`UPLOAD_DOCUMENT`); the doc is a real generated/approved artifact id. |
| `extract` | `ref?`, `shape` | Read-only structured read of the DOM (discovery/scrape lane, §7). |
| `assert` | `ref`, `predicate` | Verification (value present, URL host unchanged). |
| `wait` | `for`, `timeout` | Settle / element-visible. |
| `stop` | `reason` | Explicit hand to a human (`account_create`/`captcha`/`final_submit`). |

**Key safety property:** `fill`/`select`/`upload` reference the **attribute cloud /
document library by id**, not by literal value. The model decides *which fact goes in
which field*; it cannot inject a *fabricated value* — the executor resolves the id to the
user's real, stored, fabrication-guarded fact. This is the single most important design
choice: it preserves NFR-TRUTH-1 by construction.

The DSL lives in **core** as pure entities + a pure validator (`core/rules/plan.py`):
schema-validate, bound the op count, and reject any `fill` whose `attribute_id` is
unknown or any `click`/`stop` that would cross the boundary without authorization.
Because it is pure, it is hermetically testable (the executor is the only IO part).

## 2. The semantic DOM snapshot (DOM-as-text)

The planner sees the page as **text**, not pixels. Reuse `detect_fields()` and add a
compact **accessibility-tree serializer**: interactive elements (inputs, selects,
buttons, links) with their role, accessible name, nearby label text, current value, and
a **stable `ref`**. Each element gets a `data-applicant-ref` attribute injected by the
harness so the plan addresses elements by ref, not brittle CSS/XPath that breaks on ATS
variation.

Optimized defaults:
- **Budget:** ~8k tokens of snapshot; if larger, section the page and plan per-section.
- **Include:** interactive + labeled elements + headings; **drop** decorative nodes,
  scripts, hidden elements.
- **Stable refs:** `data-applicant-ref="r{n}"` assigned in document order per snapshot.
- **No raw secrets in the snapshot** (the form is the user's own, but never serialize
  values of password/OTP fields — those are human-step anyway).

## 3. The camoufox harness (the executor)

`PageSource` (camoufox = Playwright-over-Firefox) gains an `execute(plan) -> PlanResult`
that runs ops sequentially:

- Resolve `ref` → Playwright `Locator` (via the injected `data-applicant-ref`).
- `fill`/`select`/`upload`/`click` reuse the **existing** `type_value`/`click`/upload
  methods, which already route through `ensure_action_allowed` + the human-cadence
  typing — so the stop-boundary, sensitive-field rules, and stealth all still apply
  unchanged.
- `extract` runs the read-only JS lane (§7).
- Returns per-op status + the post-state for the self-correction loop (§5).

Camoufox specifics: it injects its own coherent fingerprint, so nothing about
plan-as-data changes the stealth posture; the harness is the same browser, just driven
by a plan instead of step-by-step calls. On the `chromium`/patchright fallback the same
executor works (Playwright API is shared).

## 4. The planner (the intelligence layer)

A new **driving port** `PlannerPort.plan(goal, observation, facts, constraints) -> Plan`.
Default adapter `LLMPlanner` uses the **existing L1/L2 tier ladder**:

- **L1 (cheap, coding-capable)** emits the plan — planning is a structured, code-shaped
  task a cheap model does well. **Structured output / JSON-schema mode ON** so the plan
  parses deterministically (the transport-conformance §8b lesson).
- **L2 (pro)** is reserved for hard *writing* (cover letters, screening prose) —
  unchanged. Planning ≠ writing.
- Prompt = role + the DSL schema + the semantic snapshot (§2) + the **attribute-cloud
  manifest** (ids + labels the plan may reference, never raw secrets) + constraints (the
  stop-boundary, the closed op set).

Default paradigm: **Plan-and-Execute with a self-correction loop** (§5), not per-step
ReAct — that's the whole point (fewer round-trips). ReAct-style single steps remain the
fallback when a plan repeatedly fails.

## 5. Self-correction loop (autonomy)

Execute the plan; after each consequential op **verify** (read back the filled value;
assert the URL host is unchanged — doubles as an anomaly/SSRF check). On a failed op or
a verification miss:

1. Capture the **new** semantic snapshot + the failure reason.
2. Re-plan from the new state (the planner sees what went wrong).
3. Bounded retries, then **give up to a human** via the existing pending-action /
   live-takeover path — never loop forever.

Optimized defaults: **max 3 re-plans per page**, exponential settle backoff, and the
give-up reuses the resume-failure-cap ledger pattern (process-lived, per CLAUDE.md). A
re-plan budget keeps token cost bounded.

## 6. Whole-application planning

A higher-level **flow planner** plans the multi-page journey once — `enter application →
navigate → fill page(s) → stop at the first irreducible human step` — and delegates each
page to the page-level planner (§4). The **stop-boundary is still the hard gate**: the
flow planner may *propose* reaching the submit page, but `FINAL_SUBMIT` /
`ACCOUNT_CREATE_SUBMIT` / CAPTCHA always emit `stop` and hand to the human
(`engine_submit_authorized` stays false unless the user clicks authorize). Plan-once
here means the engine isn't re-reasoning the whole flow every tick.

## 7. Discovery & scraping — the read-only JS lane (Hybrid)

Where there is **nothing to submit** (job-board listing pages, posting detail
extraction), flexibility pays and risk is low, so the Hybrid posture allows a
**sandboxed read-only JS extractor**:

- The model emits a small **read-only** extractor (or a typed `extract` op with a target
  shape); the harness runs it in an **isolated world** with **no network, no cookie/
  storage writes, output size-capped**, returning structured rows.
- Lets the engine `regex/dedup/batch` thousands of infinite-scroll rows **without a
  model call per row** — the discovery efficiency win.
- The scraped `source_url` still passes the SSRF guard before any later navigation;
  extraction has **no side effects** and cannot click/submit.

Defaults: isolated world, **2s** execution cap, **256KB** output cap, no `fetch`/network,
JSON-only return. If the extractor errors, fall back to the engine's existing parser.

## 8. Safety & guards (non-negotiable, unchanged guarantees)

- **Plan is data, validated in pure core** — no arbitrary code on the fill/submit path.
- **Values come from ids**, so the fabrication guard holds by construction (§1).
- **Every consequential op** still passes `ensure_action_allowed` (stop-boundary),
  sensitive-field rules, and review-before-submit — the executor calls the same guarded
  methods, it just calls them from a plan.
- **The engine cannot self-authorize a submit** — `stop` is the only thing the planner
  can emit at the boundary; `FINAL_SUBMIT` requires the human's explicit authorize.
- **Read-only JS lane** is isolated, side-effect-free, network-less, output-capped — and
  can never reach the consequential ops.
- **Prompt-injection from the DOM** (a poisoned posting/form trying to steer the plan) is
  contained: the worst a malicious page can do is produce a plan whose consequential ops
  are *still* gated by the guards and whose values are *still* id-resolved facts — it
  cannot fabricate, cannot submit, cannot exfiltrate (read-only lane is network-less).

## 9. System-wide intelligence upgrade (Applicant as a whole)

Plan-as-data is the substrate; the larger goal is **a more intelligent, autonomous
system end to end**. Apply the same patterns across the hexagon:

- **Discovery:** plan-based multi-source query expansion + the read-only scrape lane.
- **Scoring/match:** keep structured-output scoring; add a reflection pass (LLM-as-judge
  on borderline matches) gated by cost.
- **Materials:** plan the tailoring (which attributes → which résumé sections) as data;
  the fabrication guard + non-AI-voice post-filter stay on every path.
- **The agent loop:** plan-and-execute over the daily cycle; **memory/skills feed the
  planner** as context (the learned playbooks become planning priors); the self-
  correction loop applies; **LLM-as-judge evals** score outputs and feed learning.
- **Unified `PlannerPort`** (one driving port) with executor adapters (camoufox browser,
  and later the desktop/computer-use sandbox) — so the same planning intelligence drives
  every actuator. This is the hexagonal home for "higher autonomy."

## 10. Architecture fit (hexagonal)

- **core/** — `core/rules/plan.py`: the Plan/Op entities + the pure validator + the guard
  predicates. Pure, hermetically tested.
- **ports/driving/** — `PlannerPort` (emit a Plan from goal+observation+facts).
- **adapters/** — `LLMPlanner` (tier ladder, structured output); the camoufox `PageSource`
  gains `execute(plan)`; a read-only-JS extractor sub-adapter.
- **application/services/** — `prefill_service` / `agent_loop` call `PlannerPort` then
  `browser.execute(plan)` instead of orchestrating field-by-field.
- Import-linter contract preserved (core pure; adapters → core; the planner is a port).

## 11. Optimized defaults (summary)

| Knob | Default | Rationale |
|---|---|---|
| Planner model | the configured **L1** (cheap, coding-capable), JSON-schema output ON | planning is structured/code-shaped; cheap is enough |
| Writing model | **L2** (unchanged) | prose quality |
| Max ops / page | 40 | bounds a runaway plan |
| Max re-plans / page | 3 → human handoff | autonomy without infinite loops |
| DOM snapshot budget | ~8k tokens, a11y-compact | cost + signal |
| Element refs | `data-applicant-ref` | stable across ATS variation |
| Read-only JS | isolated world, 2s, 256KB, no network | flexible scrape, zero risk |
| Verification | read-back after fill; assert URL host unchanged | correctness + anomaly/SSRF |
| Fallback | per-field ReAct + existing parser | resilience when planning fails |

## 12. Rollout (green increments, flag-gated, A/B against today)

1. **DSL + pure validator + planner port** (core + port + L1 adapter) — no behavior
   change; unit-tested.
2. **Pre-fill via plan-as-data** behind `PREFILL_PLANNER` flag; A/B vs the current
   per-field path on the dry-run ATS fixture; integration-gated.
3. **Self-correction loop** + verification.
4. **Discovery read-only JS lane.**
5. **Whole-application flow planner.**
6. **System-wide `PlannerPort`** across the loop + **LLM-as-judge eval harness** feeding
   learning.

Each phase keeps every CI gate green and the safety guards intact; the planner is OFF by
default until a phase proves out on the integration fixtures.

## 13. Reuse candidates (to be populated from the domain deep-research)

Lift-and-shift (principle #1): adapt proven, **license-clean** code over writing fresh.
From `docs/design/competitive-research.md` (MIT/Apache-2.0 only — Skyvern is AGPL, idea-only):

- **DOM/a11y serializer (§2)** ← **browser-use** (MIT) — lift the DOM-snapshot-as-text serializer.
- **The DSL shape (§1)** ← **Stagehand** (MIT) `act`/`extract`/`observe` — our typed-op surface, proven on Playwright.
- **Planner/LLM adapter (§4)** ← **litellm** (MIT) — back the L1/L2 ladder with retries/fallbacks/cost-tracking + structured output.
- **Self-correction (§5)** ← **Reflexion** (verbal reflection in episodic memory) pattern.
- **Skills/learning feeding the planner (§9)** ← **AWM** (Apache-2.0: induce reusable per-ATS workflows from successful runs) + **ACE** (generation→reflection→curation playbook) + **Voyager/SkillWeaver** (skills-as-code). The "smarter every application" flywheel.
- **Memory backend (§9)** ← **mem0 / Letta / Graphiti** (Apache-2.0) behind the memory port.
- **Eval / A-B gate (§12)** ← **AgentLab + BrowserGym** (Apache-2.0).
- **Integration surface** ← **fastapi_mcp** (MIT) to expose the engine as an MCP server; the MCP reference Memory / Sequential-Thinking / Fetch servers as drop-in tools.

Competitive reference (study; verify license before any code reuse): **ApplyPilot**
(near-twin pipeline; Workday-portal registry pattern).

## 14. Risks & open questions

- **Planning quality on messy ATS** → mitigated by self-correction + per-field fallback;
  prove on the dry-run fixture before enabling.
- **DOM-snapshot token cost** → compact a11y + per-section planning + prefix-cache the
  stable DSL/instructions.
- **Read-only-JS sandbox escape** → isolated world + no network + output cap; never on the
  consequential path (open question: enforce via CSP in the isolated context).
- **Model/provider for L1 planning** → defer the concrete pick to the deep-research
  findings + the operator's configured provider; structured-output support is the gate.
