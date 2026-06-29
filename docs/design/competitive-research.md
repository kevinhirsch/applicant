# Competitive & Capability Research — autonomous web-agent + AI-job-application domain

Purpose: find reusable code and novel ideas to raise Applicant's intelligence,
autonomy, capability, and integration. Companion to `docs/design/plan-as-data.md`.

**Method & honesty note.** Produced by the deep-research harness: 6 angles → parallel
web search → 29 sources fetched → 143 claims extracted → **25 top claims
adversarially verified (3-vote): 24 confirmed, 1 killed.** The harness's auto-synthesis
field returned a stub, so the synthesis below was written from the **verified run-log
claims + the 28-source map** (each finding carries its source). One claim was
**refuted** and is reported as such.

License is the gate for *code* reuse in a self-hosted product: **MIT / Apache-2.0 =
vendor-able; AGPL-3.0 = idea-only** (copyleft would infect the product). Tagged per item.

---

## Axis 1 — Intelligence & autonomy (weighted highest)

- **Agent Workflow Memory (AWM)** — arXiv 2409.07429 (ICML 2025); code `github.com/
  zorazrw/agent-workflow-memory`, **Apache-2.0**. Induces reusable *workflows* (routines
  abstracted from past trajectories, variables parameterized) and injects them into agent
  memory to guide future tasks. **Online, no extra training.** **WebArena +51.1% relative**
  (35.5 vs 23.5), **Mind2Web +24.6%**. *This is the single highest-leverage idea for
  Applicant's learning layer.* (verified 3-0, multiple times)
- **Reflexion** — arXiv 2303.11366 (NeurIPS 2023), 2,300+ citations. Reinforces agents via
  **verbal self-reflection stored in episodic memory, no weight updates**; modular 3-model
  (actor / evaluator / self-reflection) architecture; large gains over baselines. (3-0)
- **ACE — Agentic Context Engineering** — arXiv 2510.04618 (ICLR 2026). Treats context as
  an **evolving "playbook"** refined by a **generation → reflection → curation** pipeline
  with structured incremental delta updates; **+10.6% on agent benchmarks, no labeled
  supervision.** (3-0)
- **Voyager** — `voyager.minedojo.org`. **Skills stored as executable code**, each indexed
  by the embedding of its NL description, retrieved top-5 for similar situations, complex
  skills composed from simpler ones. (3-0)
- **Plan-and-Execute vs ReAct** — Plan-and-Execute is **cheaper than ReAct for >3-step
  tasks** (cost ≈ `1·strong_model + N·cheap_model`). The **Reflection** pattern
  (draft → critic → regenerate) is the third core pattern. *Directly validates the
  plan-as-data spec's plan-once default + the L1-plans/L2-writes tier split.* (verified)

## Axis 2 — Agent memory & skill libraries (vendor-able)

- **mem0** — `github.com/mem0ai/mem0`, **Apache-2.0**. Multi-level memory (User/Session/
  Agent) with add/search; 3-stage extract→consolidate→retrieve; **LOCOMO SOTA**; **p95
  latency −91% vs full-context.** ⚠️ The "**>90% token-cost savings**" claim was
  **REFUTED (1-2)** — cite the latency win, not a 90% token figure.
- **Letta** (ex-MemGPT) — `github.com/letta-ai/letta`, **Apache-2.0**. Stateful agents with
  persistent **memory blocks** that learn/self-improve over time. (3-0)
- **Graphiti / Zep** — `github.com/getzep/graphiti`, **Apache-2.0**. **Temporal (bi-temporal)
  knowledge-graph** memory — facts have validity windows; supersession tracked. (3-0)
- **SkillWeaver** — `github.com/OSU-NLP-Group/SkillWeaver`. Web agent **autonomously
  discovers skills, practices them, distills experience into reusable parameterized APIs**,
  growing a plug-and-play skill library. (verified)

## Axis 3 — Browser-agent frameworks (vendor-able code)

- **browser-use** — `github.com/browser-use/browser-use`, **MIT**, ~101k stars. DOM-first
  (page state as **DOM-snapshot text**), ReAct loop, **89.1% on WebVoyager.** The mature
  **a11y/DOM serializer** is the most directly reusable piece for our semantic snapshot.
- **Stagehand** — `github.com/browserbase/stagehand`, **MIT**. Built **on Playwright**,
  exposes **`act` / `extract` / `observe`** AI primitives over it. *This is essentially the
  plan-as-data DSL shape, already proven — borrow the surface.*
- **Skyvern** — `github.com/Skyvern-AI/skyvern`, **AGPL-3.0** ⚠️ (anti-bot/CAPTCHA reserved
  to their cloud). Strong ideas (vision+DOM, Workday/ATS focus) but **idea-only** — do not
  vendor AGPL code into the product.
- **WebVoyager** (arXiv 2405.20309) — multimodal web agent; mainly a benchmark/reference.

## Axis 4 — Benchmarks & evaluation

- **AgentLab + BrowserGym** — `github.com/ServiceNow/AgentLab`, **Apache-2.0**. Develop +
  evaluate web agents across **13+ benchmarks**. *The eval harness for our pre-fill
  planner's A/B gate.*
- **WebArena / Mind2Web** — the standard task suites the above results are measured on;
  techniques (not the sites) transfer.

## Axis 5 — Integrations (MCP / computer-use / model routing)

- **litellm** — `github.com/BerriAI/litellm`, **MIT**. Provider-agnostic gateway (100+ LLMs,
  OpenAI format) with retries/fallbacks/cost-tracking — **exactly Applicant's L1/L2 tier
  ladder, hardened.** SDK or self-hosted proxy.
- **fastapi_mcp** — `github.com/tadata-org/fastapi_mcp`, MIT. Expose a **FastAPI app as an
  MCP server** with near-zero glue. *Applicant IS FastAPI → instant MCP integration surface.*
- **modelcontextprotocol/servers** — MIT. 7 reference servers incl. **Memory
  (knowledge-graph)**, **Sequential Thinking** (reflective problem-solving), **Fetch**,
  Filesystem, Git, Time. Drop-in tools.
- **trycua/cua** — the computer-use driver Applicant already references (cua-driver).
- **bytebot** — `github.com/bytebot-ai/bytebot`, **Apache-2.0**. Self-hosted AI **desktop
  agent** (containerized Ubuntu via NL) — a license-clean reference for the desktop/
  computer-use sandbox beyond browser-only.

## Axis 6 — Stealth / anti-detection + ATS auto-apply

- **nodriver** — `github.com/ultrafunkamsterdam/nodriver` (undetected-chromedriver
  successor); and **patchright** — benchmarked anti-detect options. Applicant already uses
  camoufox (default) + patchright; nodriver is a fallback to keep on the radar.
- **ApplyPilot** — `github.com/Pickle-Pixel/ApplyPilot`. **Near-twin pipeline**: JobSpy (5
  boards) + custom scrapers for **48 Workday portals + 30 career sites** + AI 1-10 scoring +
  AI tailoring + **CapSolver** CAPTCHA. *Best competitive reference; study the Workday-portal
  registry pattern.* (⚠️ verify license before any code reuse.)
- **ats-screener** — `github.com/sunnypatell/ats-screener`. Résumé↔JD ATS scoring — idea
  reference for a match/score explainer.
- *Caveat:* CAPTCHA-solving + aggressive evasion carry ToS/legal risk; Applicant's
  stop-at-human-step posture is the safer default. Keep CAPTCHA a human step.

---

## TOP RECOMMENDATIONS TO ADOPT (ranked by competitive-edge impact)

| # | What | Tag | License | Effort | Lift |
|---|---|---|---|---|---|
| 1 | **AWM workflow-induction** — induce per-ATS form-fill "workflows" from successful pre-fill runs; inject as planner priors | adopt-idea+code | Apache-2.0 | M | **High** — the "smarter every application" flywheel; fewer re-plans, higher repeat-ATS success |
| 2 | **ACE playbook loop** — restructure the curation/learning layer as generation→reflection→curation with delta updates | adopt-idea | — | M | **High** — compounding self-improvement, no labels |
| 3 | **Stagehand act/extract/observe DSL** — adopt its primitive shape for the plan-as-data DSL | adopt-idea | MIT | L | **High** — de-risks the spec; proven surface |
| 4 | **browser-use DOM/a11y serializer** — lift-and-shift the semantic-DOM snapshot (spec §2) | adopt-code | MIT | L-M | **High** — the planner's "eyes," already mature |
| 5 | **litellm** — back the LLM adapter / tier ladder | adopt-code | MIT | L-M | **High** — robust fallbacks, cost-tracking, 100+ providers, transport-conformance for free |
| 6 | **Reflexion self-reflection** — the self-correction loop (spec §5) + post-run learning | adopt-idea | — | L | M-H |
| 7 | **mem0 / Letta / Graphiti** — a real memory backend behind the memory port | adopt-code | Apache-2.0 | M | M-H (cite latency win, not the refuted token claim) |
| 8 | **fastapi_mcp** — expose the engine as an MCP server | adopt-code | MIT | L | M — instant integration surface |
| 9 | **AgentLab / BrowserGym** — eval harness for the planner A/B gate | adopt-code | Apache-2.0 | M | M — rigorous planner regression |
| 10 | **Voyager / SkillWeaver skills-as-code** — executable, composable, embedding-retrieved skills | adopt-idea | MIT/—  | M-H | M-H |
| 11 | **bytebot** — desktop/computer-use sandbox reference | adopt-idea | Apache-2.0 | H | M — off-page steps |
| 12 | **ApplyPilot Workday registry** — competitive reference; Workday-portal coverage pattern | adopt-idea | verify | study | M |

**Headline:** the biggest intelligence lift is **#1 + #2 + #6 together** — an
induce-workflows → reflect → curate-playbook learning loop that makes the agent measurably
better at each ATS the more it applies, with **no training**. The biggest *capability/
reuse* wins are **#3–#5** (DSL + DOM serializer + litellm), which de-risk and accelerate the
plan-as-data spec directly. **License watch-outs:** Skyvern is AGPL (idea-only); verify
ApplyPilot's license before reusing any code.

**Refuted (do not repeat):** mem0 does *not* demonstrably save ">90% token cost" (killed
1-2); its verified win is **p95 latency −91%** vs full-context.
