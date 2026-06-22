# Agent intelligence — learning, looping & memory port — `FR-MIND`

Integration spec for porting the **"guts" of Hermes Agent** — its general-purpose
self-improving agent substrate (the **closed learning loop**, the **agent/reasoning loop**,
**curated memory**, **procedural skills**, and **cross-session recall**) — into Applicant's
24/7 engine. This is a **lift-and-shift** (working principle #1) of Hermes' learning +
looping + intelligence machinery, re-homed onto Applicant's hexagonal ports, Postgres +
chromadb storage, DBOS durable orchestration, per-tick `AgentLoop`, safety gates, and
white-labeled front door.

- **Source we lift from (MIT):** `kevinhirsch/hermes-agent`.
  <https://github.com/kevinhirsch/hermes-agent> — "a self-improving AI agent … built-in
  learning loop … creates skills from experience, improves them during use … searches its
  own past conversations."
- **Companion spec:** [`docs/spec/computer-use.md`](computer-use.md) (`FR-CUA`) ports the
  desktop-control feature; this doc ports the brain behind the loop.
- **Attribution:** [§9](#9-attribution-mit) and the repo-root [`NOTICE`](../../NOTICE).

> **Authority & relationship to existing learning.** This doc *extends* the master spec.
> Applicant **already has** a domain-specific learning subsystem — `FR-LEARN`
> (real-conversion learning per campaign), the self-learning **criteria** (`FR-CRIT-1`),
> the **attribute cloud** (`FR-ATTR`), and the agent loop (`FR-AGENT`). `FR-MIND` does **not
> replace** them — it adds the *general* self-improving substrate **underneath** them:
> Hermes contributes the **qualitative / procedural** learning (curated memory + skills the
> agent writes for itself + session recall) that complements Applicant's **quantitative**
> conversion learning. Where this doc and the master spec disagree, the master spec wins.

---

## 0. What already exists — the lift-and-shift base (read first)

Per working principle #1 (**never rebuild what exists**), note that a **Hermes-derived
memory + skills substrate already ships in the white-labeled front door**, under
`workspace/services/memory/` (chat-scoped today). This port **lifts and extends that**, it
does not start from scratch:

| Already in-tree (workspace) | What it is |
|---|---|
| `workspace/services/memory/memory.py` + `service.py` | `MemoryManager` / memory service (persistent storage, similarity) |
| `workspace/services/memory/memory_vector.py` | **ChromaDB** vector store (`applicant_memories` collection), shares the RAG embedding client — local recall (`NFR-LOCAL-1`) |
| `workspace/services/memory/memory_extractor.py` | **background auto-extraction** of facts from chat + **periodic LLM audit** that consolidates duplicates / rewrites vague / removes junk (≈ upstream curation nudge) |
| `workspace/services/memory/skills.py` + `skill_format.py` | skills on disk as `SKILL.md` (YAML frontmatter + When-to-Use/Procedure/Pitfalls/Verification), usage sidecar, ownership — the upstream skills format, already white-labeled |
| `workspace/services/memory/skill_extractor.py` | **background auto-extraction of skills** from complex runs (≥2 rounds / ≥2 tool calls) — upstream "create a skill after a complex task" |
| `workspace/routes/{memory_routes,applicant_memory_routes,skills_routes}.py` | front-door routes (incl. an `/api/applicant/*` owner-scoped proxy already present) |
| `workspace/mcp_servers/memory_server.py` | memory exposed over MCP |

**So the gap this spec closes is not "build memory/skills" — it is "wire that existing
substrate into the engine's autonomous 24/7 loop and close the learning loop around the
engine's own work" (applications, pre-fill, discovery), not just workspace chat.** The
`FR-MIND` requirements below should be read as: **reuse the workspace modules' formats,
extractors, and ChromaDB store**, and add (a) engine-side reachability via a port, (b) the
scheduled curation loop around engine runs, and (c) the safety invariants. The **placement**
of the store (keep in workspace + engine reads via the bridge, vs. move into the engine, vs.
a shared Postgres/chromadb both read) is the **first open question** — see §10; recommended
direction there.

---

## 1. What "the guts" are (upstream → what we take)

Hermes' learning/looping/intelligence stack, from its docs and source layout:

| Upstream component (Hermes) | What it does | We port it as |
|---|---|---|
| **Agent loop** — `AIAgent` (`run_agent.py`) | conversation lifecycle: prompt build → provider resolve → API call → tool dispatch → loop → persist | maps onto Applicant's `AgentLoop` (`FR-AGENT`); we adopt its **tiered prompt assembly**, **tool-dispatch loop**, and **persist-every-turn** discipline |
| **Tiered prompt builder** — `prompt_builder.py` | ordered system-prompt tiers: identity → tool guidance → context files → memory/profile | `FR-MIND-5` tiered prompt assembly |
| **Tool registry** — `tools/registry.py`, `model_tools.py` | central registry, auto-registration, schema collection, `handle_function_call()` dispatch | `FR-MIND-6` tool registry/dispatch (Applicant already has tools; we adopt the registry discipline) |
| **Curated memory** — `MEMORY.md` + `USER.md`, `memory_manager.py` | bounded, curated facts/lessons + user prefs; frozen-snapshot injection; add/replace/remove | `FR-MIND-1` curated memory |
| **Procedural skills** — `SKILL.md`, `skill_manage`, progressive disclosure | the agent **writes reusable playbooks from experience** and improves them; L0/L1/L2 loading | `FR-MIND-2` procedural skills |
| **Session recall** — SQLite **FTS5** over past sessions | full-text recall of prior conversations without token overhead | `FR-MIND-3` recall (re-homed to **Postgres FTS + chromadb**, already deployed) |
| **Identity** — `SOUL.md` (slot #1) | agent identity/voice at prompt position #1 | `FR-MIND-4` identity tier (white-labeled; reuses Applicant's voice spec) |
| **Closed loop** — periodic curation **nudges** + autonomous skill creation + self-improvement | the loop that ties memory+skills+recall together over time | `FR-MIND-7` closed learning loop (driven by DBOS scheduling) |
| **Context mgmt** — `context_compressor.py`, `prompt_caching.py` | summarize middle turns over threshold; provider prefix-cache breakpoints | `FR-MIND-8` context management |
| **Write-approval gates** — `write_approval`, `pending/` staging | self-writes are staged for human approve/deny | `FR-MIND-9` review-before-write (→ pending-actions Portal) |

**The one decisive re-homing:** Hermes is a single-session CLI/gateway agent backed by
**SQLite**, building one frozen prompt per session. Applicant is a **24/7 multi-campaign
engine** backed by **Postgres + chromadb + DBOS**, whose **scheduler rebuilds a fresh
`AgentLoop` per tick**. So the port is not file-for-file: memory/skills/recall become
**durable stores** loaded per tick, and the curation loop becomes **scheduled DBOS work**,
not an in-process background thread.

---

## 2. Scope & non-goals

**In scope** — a general self-improving substrate the autonomous agent uses while it works
applications 24/7:
- **Curated memory** the agent maintains about its environment and the user (bounded,
  human-readable, editable in the existing memory/profile surface).
- **Procedural skills** the agent writes for itself after solving something non-trivial
  ("how to clear Greenhouse's react-select for *location*", "Acme's Workday tenant account
  flow"), reused on later applications, improved on re-encounter.
- **Cross-session recall** over the engine's own run/conversation history (Postgres FTS +
  chromadb), so the agent can pull up what happened on a prior, similar application.
- The **tiered prompt assembly**, **tool-dispatch loop**, **context management**, and
  **persist-every-turn** discipline adopted into `AgentLoop`.
- All of it behind **review-before-write** and the existing safety boundary.

**Non-goals**
- **Not** replacing `FR-LEARN`/`FR-CRIT`/`FR-ATTR` quantitative learning — `FR-MIND` sits
  under and beside them.
- **Not** Hermes' multi-platform messaging gateways (Telegram/Discord/Slack), its 28
  toolsets wholesale, its provider-OAuth pool, or its CLI — Applicant has its own front
  door, LLM port (`FR-LLM`), tools, and channels. We take the *learning/looping core*, not
  the surrounding product.
- **Not** SQLite — Applicant's stores are Postgres + chromadb (`NFR-LOCAL-1`).
- **Not** a way around the stop-boundary. Memory and skills are **advisory context, never
  authorization** (see §6).

---

## 3. Requirements — `FR-MIND`

- **FR-MIND-1 (MUST — curated memory).** The agent maintains a **bounded, curated** memory
  of (a) **environment facts & lessons** (analogue of Hermes `MEMORY.md`) and (b) **user
  preferences & communication style** (analogue of `USER.md`), stored durably in Postgres
  (not a file), per campaign where campaign-scoped. Operations are **add / replace / remove**
  (substring match), with enforced size bounds; when near capacity the agent consolidates
  before adding. Memory is a **frozen snapshot loaded at the start of each loop tick** and
  is **editable in the existing memory/profile front-door surface** (`FR-UI`, the
  `memory-*` design system). It captures preferences, corrections, project/campaign
  conventions, and completed work; it **skips** trivia, easily re-derivable facts, large
  dumps, and one-off session details (the upstream save policy).

- **FR-MIND-2 (MUST — procedural skills the agent writes & improves).** After completing a
  **non-trivial** task (heuristic: a successful application run, or a workflow of ≥5 tool
  calls, or clearing a blocker via pivot `FR-AGENT-6`), the agent MAY **author a reusable
  skill** — a structured playbook (`when to use / procedure / pitfalls / verification`,
  the upstream `SKILL.md` body) — and on re-encountering the situation **improve** it
  (`patch` for targeted updates, `edit` for rewrites). Skills use **progressive disclosure**
  (L0 metadata list → L1 full body → L2 reference files) to keep token cost bounded, lifted
  from upstream. Skills are stored durably (Postgres + chromadb for retrieval) and are
  **campaign-scoped or global** as authored. This is Applicant's **procedural memory**,
  complementing `FR-LEARN`'s statistical conversion memory.

- **FR-MIND-3 (MUST — cross-session recall, Postgres/chromadb).** The agent can **recall
  its own past runs/conversations** by full-text and semantic search over the engine's
  durable history — **Postgres FTS** (the re-home of upstream's SQLite **FTS5**) plus the
  already-deployed **chromadb** for embedding recall (`NFR-LOCAL-1`, embeddings local).
  Recall is **on-demand** (a tool the loop calls), so it costs tokens only when used, and is
  scoped to the owner/campaign. No SQLite is introduced.

- **FR-MIND-4 (MUST — identity tier, white-labeled).** The system prompt's **slot #1** is
  an **identity/voice tier** (the re-home of upstream `SOUL.md`), sourced from Applicant's
  existing voice spec (`docs/voice-and-truthfulness.md`), **not** an upstream persona. It
  is white-labeled (no Hermes/Nous/SOUL naming, no codenames) and MAY be user-tunable in
  Settings. Any user-supplied identity text is **prompt-injection-scanned** before
  inclusion (upstream does this) and never auto-overwritten.

- **FR-MIND-5 (MUST — tiered prompt assembly).** `AgentLoop` assembles the system prompt in
  **ordered tiers** (upstream `prompt_builder.py`): identity (`FR-MIND-4`) → tool guidance
  → context/criteria/attributes → curated memory/profile (`FR-MIND-1`). Tiering keeps the
  cacheable prefix stable (see `FR-MIND-8`).

- **FR-MIND-6 (MUST — tool registry & dispatch).** Tools the loop exposes are collected via
  a **central registry** with schema collection and a single `handle_function_call()`-style
  dispatch (upstream `tools/registry.py` / `model_tools.py`). The memory, skill, and recall
  capabilities above are themselves **registered tools** (`memory.*`, `skill_manage`,
  `recall`), gated like any other tool. Applicant's existing tools (pre-fill, discovery,
  document generation, `FR-CUA` desktop) register the same way (`FR-UI-4` tool toggles).

- **FR-MIND-7 (MUST — closed learning loop on a schedule).** A **periodic curation loop**
  ties it together: on a schedule (DBOS scheduling — the same mechanism that drives digests
  and discovery, `FR-DUR`), the engine runs a **curation nudge** that reviews recent runs,
  proposes memory updates and new/improved skills, prunes stale entries, and feeds anything
  campaign-relevant into `FR-LEARN-4`'s attribute cross-referencing. The nudge MAY run on a
  **cheaper auxiliary model** for cost (upstream "background review on cheaper models",
  consistent with `FR-LEARN-7` "keep learning cheap"). Proposed self-writes go through
  `FR-MIND-9`.

- **FR-MIND-8 (MUST — context management).** The loop applies **context compression**
  (summarize middle turns once context crosses a threshold, with parent/child **lineage**
  tracking — upstream `context_compressor.py`) and, **where the provider supports it**,
  **prefix-cache breakpoints** (upstream `prompt_caching.py` / Anthropic cache control) to
  cut token cost. Because Applicant's model is cloud-or-local (`FR-LLM`), prefix caching is
  applied **only when the configured provider supports it** and is a no-op otherwise.

- **FR-MIND-9 (MUST — review-before-write; self-writes are gated).** Every **agent
  self-write** to memory or skills is **staged for human review** (upstream
  `write_approval` + `pending/` staging) → surfaced as a **pending action in the Portal**
  (`FR-NOTIF`/`FR-UI`), approve/deny. The default posture is **review-on**, matching
  Applicant's review-before-act invariant. The user MAY relax curation of **non-sensitive,
  non-integral** memory to auto-apply (mirroring `FR-LEARN-4` / `FR-FB-3`: integral changes
  always require confirmation), but skills and identity edits always require approval.

- **FR-MIND-10 (MUST — per-tick safety: state lives in process/Postgres, never the loop
  instance).** Because the scheduler **rebuilds a fresh `AgentLoop` per tick**
  (`container._build_tick_services`), all learning state that must persist across ticks
  lives in **Postgres** (durable) or in a **process-lived object injected into every loop**
  (like the existing resume backoff/failure ledger) — **never on the loop instance**, or it
  silently resets each tick. The memory snapshot is **read** per tick; writes go to the
  durable store + the curation queue, not to in-loop fields.

- **FR-MIND-11 (MUST — memory/skills are advisory, never authorization).** Curated memory,
  skills, and recalled content are **context only**. They **cannot** opt the agent past any
  safety boundary: not the pre-fill stop-boundary (`FR-PREFILL-4`), not review-before-submit,
  not the truthfulness guardrail (`FR-RESUME-2`), not `FR-CUA`'s desktop limits. A skill
  that *says* "submit automatically" confers no authority; the core guards derive their own
  ground truth (the project's "never rely on a caller-supplied input to opt a safety check
  in" rule). All ingested skill/memory/recall content is **prompt-injection-scanned**
  (upstream does this on skills/identity) and treated as untrusted.

- **FR-MIND-12 (MUST — reachability & white-label).** The substrate is operable through the
  white-labeled front door (principle #2): curated memory + saved skills are **viewable and
  editable in the memory/profile section**; the curation queue surfaces in the
  **pending-actions Portal**; recall/skill activity shows in **Activity/Debug** (`FR-OBS`).
  All copy is plain-language **Applicant** ("what the assistant remembers", "saved
  playbooks") — no `MEMORY.md`/`SOUL.md`/`skill_manage`/Hermes/Nous strings (the CI
  white-label denylist gates it). Surfaces ship **dormant** (`FR-UI-2`) until their backend
  is live.

- **FR-MIND-13 (SHOULD — keep it cheap & local).** Consistent with `FR-LEARN-7` and
  `NFR-LOCAL-1`: recall/embeddings run **locally** (chromadb); curation prefers the cheaper
  model; the LLM is reserved for human-readable summaries and genuinely hard mappings. The
  substrate must not turn the 24/7 loop into a token furnace (the context-management and
  progressive-disclosure layers above are how).

---

## 4. Architecture (hexagonal placement)

```
core/ (pure rules — no IO)
  ├── memory policy: bounds, add/replace/remove, save-worthiness filter   (FR-MIND-1)
  ├── skill policy: when-to-author, progressive-disclosure levels          (FR-MIND-2)
  ├── advisory-not-authorization invariant (guards derive own ground truth) (FR-MIND-11)
  └── prompt-tier ordering rules                                            (FR-MIND-5)

ports/driven/
  ├── MemoryStore        # add/replace/remove/snapshot, bounded, owner/campaign-scoped
  ├── SkillStore         # create/patch/edit/delete + progressive-disclosure read
  ├── RecallIndex        # full-text (Postgres FTS) + semantic (chromadb) search
  └── (existing) LlmPort, NotificationPort, OrchestrationPort, …

adapters/
  ├── memory/postgres_memory.py        # MemoryStore on Postgres
  ├── skills/postgres_skill_store.py   # SkillStore on Postgres (+ chromadb for retrieval)
  ├── recall/pg_fts_chroma_recall.py   # RecallIndex: Postgres FTS5-analogue + chromadb
  └── (test) in-memory adapters for the hermetic lane

application/services/
  ├── prompt_builder        # tiered assembly (FR-MIND-5), adopted from upstream pattern
  ├── tool_registry         # registry + dispatch (FR-MIND-6)
  ├── context_manager       # compression + lineage + (provider-gated) prefix cache (FR-MIND-8)
  ├── curation_service      # the scheduled closed loop (FR-MIND-7) → DBOS scheduled workflow
  └── AgentLoop (FR-AGENT)  # rebuilt per tick; READS memory snapshot, WRITES via stores/queue

app/
  ├── routers: extend memory/profile + admin routers to expose memory/skills/curation queue
  └── container.py: inject process-lived curation ledger into every per-tick loop (FR-MIND-10)
```

**Durable orchestration.** The curation loop is a **DBOS scheduled workflow** co-resident in
the same Postgres (`FR-DUR`); each curation step is idempotent and checkpointed, so a crash
resumes mid-curation. The approval hand-off uses the existing `send`/`recv` gate machinery.

**Storage map (Hermes SQLite → Applicant).**

| Hermes | Applicant |
|---|---|
| `MEMORY.md` / `USER.md` files | `MemoryStore` rows in Postgres (bounded, versioned) |
| `~/.hermes/skills/*/SKILL.md` | `SkillStore` rows in Postgres + chromadb vectors for retrieval |
| `~/.hermes/pending/skills/` staging | curation queue → pending-actions Portal (`FR-MIND-9`) |
| SQLite sessions + **FTS5** | engine run/conversation history in Postgres + **Postgres FTS** + chromadb |
| `SOUL.md` | identity tier from `docs/voice-and-truthfulness.md` (`FR-MIND-4`) |

---

## 5. Reachability (definition of done — principle #2)

```
spec (FR-MIND)
  → engine ports + adapters (MemoryStore / SkillStore / RecallIndex)
  → engine services (prompt_builder / tool_registry / context_manager / curation_service)
  → engine routers (extend the memory/profile + admin/ops + pending-actions routers)
  → workspace proxies (workspace/routes/applicant_*_routes.py — thin, owner-scoped)
  → JS (reuse the memory/profile section + applicantPortal.js + applicantDebug.js)
  → nav/section (Profile → "What the assistant remembers" + "Saved playbooks";
                 Portal → curation approvals; Activity/Debug → recall/skill activity)
```

- The memory/profile section **already exists** (`memory-*` classes, profile editors) — per
  principle #1 we **lift those surfaces** and add memory + saved-skills panels, not new UI.
- Curation proposals reuse the **pending-actions Portal** (the in-app notification center)
  and its existing approve/deny + toast machinery — not a new approval UI.
- Until the stores are wired, panels render **dormant/locked** via the dormant registry +
  `applicant_features.py` (`FR-MIND-12`), so there is no dead UI.

---

## 6. Safety (the load-bearing constraints)

1. **Advisory, never authorization (`FR-MIND-11`).** A learned skill or memory entry cannot
   grant the agent permission to create an account, solve a CAPTCHA, final-submit, fabricate
   resume content, or exceed `FR-CUA` desktop limits. Safety guards in the **core** derive
   their own ground truth; they never read a flag the agent could have written into its own
   memory/skill. This is the single most important rule — it is what keeps a self-improving
   loop from improving its way around the stop-boundary.
2. **Untrusted-content handling.** Memory, skills, and recalled conversation text are
   **prompt-injection-scanned** and treated as untrusted input to the model, exactly as
   upstream scans `SOUL.md`/skills and forbids following screenshot-embedded instructions.
3. **Review-before-write (`FR-MIND-9`).** Self-writes stage for approval by default; the
   user owns the relax/auto-apply policy and integral changes always require confirmation
   (`FR-FB-3`).
4. **Per-tick discipline (`FR-MIND-10`).** No cross-tick state on the loop instance, or the
   "memory" silently resets every tick and the learning loop quietly does nothing — the
   subtle failure mode the project already warns about for the resume ledger.
5. **White-label & truthfulness.** Curation never weakens `FR-RESUME-2` (no fabrication);
   learned playbooks describe *procedure*, not invented facts about the user.

---

## 7. Configuration

| Setting | Default | Purpose | Upstream analogue |
|---|---|---|---|
| `MEMORY_WRITE_APPROVAL` | `true` | stage memory writes for review | `memory write_approval` |
| `SKILLS_WRITE_APPROVAL` | `true` | stage skill writes for review (always on for skills/identity) | `skills.write_approval` |
| `MEMORY_MAX_CHARS` / `USER_MAX_CHARS` | bounded | size caps to keep prompt bounded | `MEMORY.md`/`USER.md` limits |
| `CURATION_SCHEDULE` | periodic | cadence of the closed-loop nudge | periodic nudges |
| `CURATION_MODEL` | cheaper aux | model for background curation | "background review on cheaper models" |
| `RECALL_BACKEND` | `pg_fts+chroma` | recall index backends (local) | SQLite FTS5 |
| `CONTEXT_COMPRESS_THRESHOLD` | provider-aware | when to summarize middle turns | `context_compressor` |
| `PREFIX_CACHE` | `auto` | provider prefix caching when supported | `prompt_caching` |

No SQLite, no new external service: everything lands on the **Postgres + chromadb** the
stack already deploys (`NFR-LOCAL-1`).

---

## 8. Testing

- **Hermetic (CI default, green-increment command):** in-memory adapters for
  Memory/Skill/Recall; unit-test the core policies — bounds, add/replace/remove,
  save-worthiness filter, **advisory-not-authorization** (assert a skill claiming submit
  authority is denied by the core guard), per-tick state isolation (assert curation state
  survives an `AgentLoop` rebuild because it lives in the injected process-lived ledger /
  Postgres, not the instance).
- **Front-door:** extend `workspace/tests/test_applicant_*` for the memory/skills proxy
  routes and the curation-approval pending-action (owner-scoped, auth-gated, degrades when
  dormant).
- **Integration (`@pytest.mark.integration`):** Postgres FTS + chromadb recall round-trip;
  a full curation tick proposing a memory update + a skill, staged to the queue, approved,
  and reflected on the next loop's snapshot.
- **Determinism:** curation runs on the cheaper model and must be idempotent (DBOS step
  checkpointing) — re-running a curation tick must not duplicate skills/memory.

---

## 9. Attribution (MIT)

This port **lifts and adapts** the learning-loop, agent-loop, curated-memory, skills, and
session-recall design from **Hermes Agent** (`kevinhirsch/hermes-agent`), MIT-licensed. MIT
requires preserving the upstream copyright and permission notice; it is recorded in the
repo-root **[`NOTICE`](../../NOTICE)** and MUST be carried in any distribution that includes
this code. Replace the transcribed notice in `NOTICE` with the **verbatim** upstream
`LICENSE` text when code is actually vendored.

- Hermes Agent — © the Hermes Agent / Nous Research authors — MIT.
  <https://github.com/kevinhirsch/hermes-agent> (`LICENSE`).

Applicant remains MIT (`LICENSE`, © 2026 kevinhirsch). White-label (principle #3) applies to
**user-facing** strings and shipped artifacts; attribution lives in `NOTICE`/spec/source
headers, not product UI.

---

## 10. Open questions

- **Store placement (decide first).** The Hermes-derived memory/skills substrate already
  lives in `workspace/services/memory/` (ChromaDB `applicant_memories` + on-disk `SKILL.md`).
  Engine vs. workspace ownership must be settled: **(recommended)** keep the **store in the
  workspace** (it already has the extractors, vector store, and routes) and have the **engine
  agent reach it via the existing engine↔workspace callback bridge** (`APPLICANT_INTERNAL_TOKEN`,
  `WORKSPACE_URL`) — the `RecallIndex`/`MemoryStore`/`SkillStore` ports become thin clients
  over that bridge, no data migration, and the engine owns only the *loop* logic. Alternatives:
  move the substrate into the engine (more churn, breaks lift-and-shift), or a shared Postgres/
  chromadb both apps read (coupling). Resolve before un-dormanting.
- **Memory scope: per-campaign vs. global.** Some lessons are campaign-specific (a tenant's
  account flow), some global (the user's communication style). Decide the default split and
  whether the UI exposes both scopes. → before un-dormanting.
- **Skill ↔ FR-LEARN overlap.** Where a procedural skill encodes the same signal as the
  conversion learner (`FR-LEARN-5`), define which is authoritative to avoid double-counting
  in discovery/scoring bias.
- **Auto-apply boundary.** Exactly which memory classes may auto-apply (`FR-MIND-9`) without
  approval — reuse `FR-FB-3`'s integral/non-integral test verbatim, or define a narrower
  memory-specific list?
- **Identity tunability.** Does the user-tunable identity tier (`FR-MIND-4`) risk diluting
  the truthfulness/voice guardrails? Consider locking the guardrail clauses and letting the
  user tune only tone.
- **Prefix-cache portability.** Prefix caching is provider-specific; confirm the no-op path
  for local Ollama and the OpenAI-compatible lane is clean (`FR-MIND-8`).
