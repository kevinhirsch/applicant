# ADR-0010: Durable curated-agent-memory — a Postgres-backed `sql` backend

**Status:** Accepted (grounds `docs/APPLICANT-BACKLOG.md` § EPIC MIND-DURABLE).
**Numbering:** next free slot after `docs/adr/0009-self-improving-agents.md` in the existing
`docs/adr/0001`–`0009` sequence.
**Relates to:** `docs/adr/0006-agent-intelligence-port.md` (the FR-MIND driven ports this
adds a durable adapter behind). Issue #286. Spec anchors: FR-MIND-1/2/3, FR-MIND-11,
FR-MIND-13, FR-DUR-3.

## Context

The FR-MIND curated agent-memory trio (`MemoryStore` / `SkillStore` / `RecallIndex`, built by
`src/applicant/adapters/memory/factory.py::build_agent_memory`) is read fresh per call as
advisory context by the scorer (`scoring_service._learned_context`), the chat agent
(`chat_service._memory_context`), and material generation. The deployed engine ran
`MIND_BACKEND=in_memory` (`src/applicant/app/config.py::mind_backend`), so the trio was
in-process and **ephemeral** — every engine restart/rebuild wiped it. A product whose promise is
"it remembers you" cannot lose that on a restart.

The other durable option already in the tree, `bridge` (→ the front-door companion memory store
over the engine→workspace callback channel), was disabled because it **stalled the digest build
~45s in the hot read path**. So the durability fix has a hard constraint: **it must not add a
network / companion dependency to the read path.**

`temporal_backend.py` (`TemporalMemoryStore`, #307) was evaluated: it is a bi-temporal
in-process fact log (`self._facts: list[...]`) — it adds validity-window *history*, but it is
**still in-memory and NOT durable**. It solves a different problem (retain superseded facts), not
persistence. It is therefore **neither superseded nor built upon** here — it stays an orthogonal,
selectable in-memory backend; `sql` is the durability backend.

## Decision

Add a new `MIND_BACKEND=sql` backend: a durable trio persisted to the **existing** SQLAlchemy
storage stack (models / session / alembic), reused rather than a new framework.

1. **Three tables** (`adapters/storage/models.py`, registered with the same `Base.metadata`, so
   `create_all` and `alembic upgrade head` both build them; migration `0015_agent_memory`):
   - `memory_entries` — `id` (**INTEGER autoincrement PK**, deliberately, not the String(64) UUID
     the other tables use: insertion order is load-bearing here — `replace` targets the FIRST
     matching line and `snapshot` keeps lines in order until the char budget is spent — and an
     autoincrement PK gives a monotonic order identical on SQLite and Postgres), `campaign_id`
     (NULLABLE), `kind`, `scope`, `text`, `created_at`, `updated_at`. Index
     `ix_memory_entries_scope_campaign_kind (scope, campaign_id, kind)` so `snapshot()` is a
     single indexed query.
   - `skills` — PK `name` (the port is keyed by name); the ordered playbook sections
     (`procedure`/`pitfalls`/`verification`) and `tags` are portable JSON arrays (JSONB on
     Postgres, JSON on SQLite); index `ix_skills_scope_campaign (scope, campaign_id)`.
   - `recall_entries` — PK `run_id`; `text`, `campaign_id` (NULLABLE), timestamps; index on
     `campaign_id`. (Beyond the two tables the issue named, because a *durable* recall index needs
     its own persisted rows — recall is over past runs, not curated memory.)

2. **Adapter** `adapters/memory/sql_backend.py` — `SqlMemoryStore` / `SqlSkillStore` /
   `SqlRecallIndex`. Every operation opens a **short-lived session from the injected
   `session_factory`** and closes it (the `pg_credential_store` idiom), never holding the
   per-tick/per-request isolated Session — required for concurrency safety under 24/7 + DBOS
   queues + the container's per-tick Session isolation. `snapshot()` enforces the SAME char
   bounds as `InMemoryMemoryStore` via the pure `core/rules/agent_memory.enforce_bounds`, so the
   two adapters are behaviorally identical. `recall.search()` is a bounded (`LIMIT`),
   dependency-free keyword rank reusing `in_memory._tokenize` — **local, no network**.

3. **Bounded growth.** `add()` prunes the oldest rows beyond a per-(scope, campaign) cap
   (default 500), the same "cap it so a rewritten blob can't grow unbounded" rule as
   `learning_service.cap_feature_stats`, keeping the table — and the snapshot query — bounded
   over a 24/7 lifetime.

4. **Wiring.** `build_agent_memory` gains a keyword-only `session_factory` (backward-compatible;
   existing `build_agent_memory(settings, workspace)` callers unchanged). The container threads
   in the `session_factory` it already builds. `sql` with **no reachable DB falls back to
   `in_memory`**, so boot and the hermetic test lane are always safe. Config keeps the
   `in_memory` default (fast, isolated test lane); the **production default is `sql`**, set in
   `docker/docker-compose.prod.yml`. The memory tables are created by `alembic upgrade head`,
   which `scripts/install.sh` and `scripts/update.sh` already run before the api serves.

## Consequences

- **Positive:** curated memory / skills / recall now survive restarts and rebuilds (proved by a
  dispose-and-reconstruct-on-the-same-DB test and an end-to-end `create_app` restart smoke); the
  read path stays local + single-query + <50ms (no re-introduction of the bridge stall); no new
  runtime dependency (reuses the storage stack already in every deploy); safety semantics are
  unchanged — the write-approval gate (MEMORY_WRITE_APPROVAL) and advisory-only `claims_authority`
  filtering live ABOVE the store; the store persists, it grants nothing.
- **Negative / trade-offs:** `memory_entries` uses an integer PK, a deliberate deviation from the
  UUID convention (justified above); `replace`/`remove` fetch the (bounded) rows and match the
  substring in Python to preserve exact in-memory semantics rather than rely on dialect-specific
  `LIKE` — cheap because the table is capped; a per-scope row cap means the very oldest lessons
  are pruned once the cap is exceeded (acceptable — curated memory is meant to be bounded, and the
  snapshot was already char-capped).
- **Deferred to the parent/overseer:** production deploy, the server-side `alembic upgrade head`
  DB migration, restart-verification on 10.0.1.11, and seeding data. This ADR + branch deliver
  build + tests + commits only.
