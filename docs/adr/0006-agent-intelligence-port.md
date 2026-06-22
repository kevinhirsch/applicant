# ADR-0006: Port Hermes Agent's learning/looping/intelligence substrate as `FR-MIND`

**Status:** Proposed (extends master spec §3.4 `FR-LEARN` / §3.17 `FR-AGENT`; new `FR-MIND`
group specced in [`docs/spec/agent-intelligence.md`](../spec/agent-intelligence.md)).

## Context

Applicant's 24/7 engine already learns **quantitatively** — `FR-LEARN` real-conversion
learning per campaign, self-learning criteria (`FR-CRIT`), the attribute cloud (`FR-ATTR`).
What it lacks is a **general self-improving substrate**: durable **curated memory**
(environment facts/lessons + user style), **procedural skills the agent writes from
experience and improves on reuse**, and **cross-session recall** of its own past runs. These
are exactly the "guts" of **Hermes Agent** (MIT, `kevinhirsch/hermes-agent`): a closed
learning loop (agent-curated memory + periodic nudges + autonomous skill creation + skill
self-improvement), a clean agent loop (`AIAgent`/`run_agent.py` → tiered `prompt_builder`,
central `tools/registry` dispatch, `context_compressor` + `prompt_caching`), and FTS5
session recall. Per working principle #1, porting this proven substrate beats inventing one.

The catch: Hermes is a **single-session, SQLite-backed CLI/gateway agent** that builds one
frozen prompt per session. Applicant is a **multi-campaign, Postgres + chromadb + DBOS**
engine whose **scheduler rebuilds a fresh `AgentLoop` every tick**. A naïve file-for-file
port would either reintroduce SQLite (violating `NFR-LOCAL-1`'s Postgres/chromadb stack) or
store learning state on the per-tick loop instance — where it would **silently reset every
tick**, the exact failure the project already warns about for the resume-backoff ledger.

## Decision

Port the **learning + looping + intelligence core** of Hermes as a new `FR-MIND` group,
**re-homed** onto Applicant's hexagonal ports and durable stores:

- **Curated memory**, **procedural skills**, and **recall** become **driven ports**
  (`MemoryStore`, `SkillStore`, `RecallIndex`) with **Postgres + chromadb** adapters — *not*
  SQLite, *not* files. Memory is a **snapshot read per tick**; writes go to the durable
  store + a curation queue.
- The **closed learning loop** becomes a **DBOS scheduled workflow** (`curation_service`) —
  the same durable-orchestration mechanism that already drives digests/discovery — running a
  periodic curation nudge on a **cheaper auxiliary model**, proposing memory/skill updates
  that **stage for human approval** (upstream `write_approval` → pending-actions Portal).
- We adopt upstream's **tiered prompt assembly**, **central tool registry/dispatch**, and
  **context compression + (provider-gated) prefix caching** into `AgentLoop`/services.
- **Cross-tick state lives in Postgres or a process-lived injected object** (like the
  resume ledger), **never on the loop instance** (`FR-MIND-10`).
- **Memory/skills/recall are advisory context, never authorization** (`FR-MIND-11`): the
  core safety guards derive their own ground truth, so a self-written skill cannot grant
  account-creation/CAPTCHA/final-submit authority or weaken the truthfulness guardrail. All
  ingested content is prompt-injection-scanned and treated as untrusted.
- `FR-MIND` **complements, does not replace** `FR-LEARN`/`FR-CRIT`/`FR-ATTR` — qualitative/
  procedural memory underneath the existing quantitative conversion learning.
- User-facing surfacing is **white-labeled** ("what the assistant remembers", "saved
  playbooks"; no MEMORY.md/SOUL.md/Hermes/Nous strings — CI denylist gates it), reuses the
  existing **memory/profile** + **Portal** + **Activity/Debug** surfaces (principle #1/#2),
  and ships **dormant** until wired.

Scope is deliberately the *learning/looping core only* — **not** Hermes' messaging gateways,
its 28 toolsets wholesale, its provider-OAuth pool, or its CLI; Applicant keeps its own front
door, `FR-LLM` model access, tools, and channels.

MIT attribution is recorded in the repo-root `NOTICE`.

Alternatives considered: **build a bespoke memory/skill system** — rejected (principle #1;
reinvents a working closed loop and its safety/curation discipline). **Adopt Hermes
file-for-file with SQLite** — rejected (`NFR-LOCAL-1` Postgres/chromadb; per-tick model
mismatch). **Extend `FR-LEARN` only** — rejected (`FR-LEARN` is statistical/conversion;
procedural memory + recall + curated facts are a different, complementary capability).

## Consequences

- **Positive:** the agent accumulates reusable procedural know-how and curated context
  across its 24/7 operation, recalls prior similar runs, and self-improves — behind
  review-before-write and the existing stop-boundary. Clean hexagonal placement (NFR-EXT-1);
  hermetic CI via in-memory adapters; no new external service (lands on existing Postgres +
  chromadb + DBOS).
- **Negative / cost:** real implementation surface (three new ports + adapters, a scheduled
  curation workflow, prompt-builder/context-manager work) — staged behind dormant flags.
  Curation adds (cheap, scheduled) LLM cost; the context-management + progressive-disclosure
  layers are what keep the 24/7 loop from becoming a token furnace (`FR-MIND-13`). The
  advisory-not-authorization invariant must be enforced in the core and unit-tested, or a
  self-improving loop is a path around safety.
- **License diligence:** transcribe the upstream `LICENSE` verbatim into `NOTICE` when code
  is vendored.
