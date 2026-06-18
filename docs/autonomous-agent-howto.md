# The Autonomous Agent — How It Works, How to Run It, and What's Missing

**Audience:** the operator/owner. **Scope:** the "agent that scrapes job sources,
pre-populates the digest, and works applications autonomously" — how to start it,
how to see what it's doing while you chat with it, and an honest gap list with a
build plan to make it a usable tool.

**Requirements source:** `docs/spec/jobagentmasterspec.md` (the uploaded master
build spec) and `docs/spec/master-spec.md`. These two share the **exact same
requirement set** (identical FR-/NFR- IDs and section structure); `master-spec.md`
carries ~40 lines more prose elaboration. Either is authoritative for the IDs cited
below.

> Status legend: **✅ built + reachable** · **🟡 built but not reachable / partial in
> the front-door** · **❌ not built**. All claims are cited to `file:line`.

---

## 1. What the agent is supposed to do (spec intent)

Per §1 Vision + the lifecycle (§7) and FR-DISC / FR-AGENT / FR-DIG / FR-DUR:

> A self-hosted engine that runs **24/7**, **agentically discovers postings** on a
> schedule matching self-learning criteria, delivers a **daily digest** you
> approve/decline, and for approved roles **pre-fills the application** up to the
> irreducible human steps — all observable, with a **pending-actions portal** as
> your home base and a **chatbot** that helps and learns.

End-to-end autonomous loop (FR-DISC-1, FR-AGENT-3, FR-DIG-1, FR-PREFILL, FR-LEARN-2):
```
discover (scrape boards, 0 tokens) → score viability → daily digest →
  you approve/decline (+feedback) → pre-fill in sandbox → material review →
  final-approval gate → submit (you or authorized engine) → log + learn conversion
```

---

## 2. Is the scraping/discovery actually built? — Yes.

- **Discovery adapters:** `src/applicant/adapters/discovery/factory.py`
  `build_default_discovery(live, searxng_url, proxies, …)` wires
  `LiveJobSpyClient` (LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter via
  python-jobspy), `LiveSearxngClient`, `LiveRssClient` (e.g. HN "who's hiring"),
  plus a `SampleSource` (clients.py:58/89/165). ✅
- **Config-driven:** `DISCOVERY_LIVE` (default False → offline fakes; prod sets
  `true`), `SEARXNG_URL`, `DISCOVERY_PROXIES` (`config.py`; `docker-compose.prod.yml`
  sets `DISCOVERY_LIVE=true`, `SEARXNG_URL=http://searxng:8080`, + a `searxng`
  service). ✅
- **Proven live:** with `live=True` it returns **real postings** from Indeed +
  LinkedIn (Glassdoor/ZipRecruiter 403 as expected — they block scrapers); zero LLM
  tokens (FR-DISC-4). The integration test `tests/integration/test_discovery_live.py`
  exercises it (gated by `DISCOVERY_LIVE_TEST=1`). ✅

**So the scraping integration exists and works.** What's thin is the *operability*
(starting it, seeing it run) — §4–§6.

---

## 3. How discovery is triggered (the crux)

Discovery is **not** event- or button-driven; it runs inside the **scheduler tick**:

`app/lifespan.py:_scheduler_loop` (ticks every `SCHEDULER_INTERVAL_SECONDS`, default
60s) → `scheduler.tick(now)` (`application/services/scheduler.py`) → per active
campaign `agent_loop.tick(campaign_id, now)`
(`application/services/agent_loop.py`) → `_discover_and_digest` (runs discovery →
scoring → at-most-once-daily digest) → `_process_approvals` (approved digest rows →
create Application → run the durable pipeline).

Two hard gates before any *new* automated work runs (FR-ONBOARD-2, FR-OOBE-3,
FR-UI-5):
1. `SCHEDULER_ENABLED` must be true (default **false** in dev/test, **true** in prod
   compose) — else the loop never runs (`lifespan.py`).
2. `is_automated_work_allowed()` must be true: **onboarding complete + channels
   configured + LLM configured** (`agent_loop.py`/`scheduler.py`). Until then the
   loop only re-drives in-flight work; **no discovery/digest**.

---

## 4. How to START it (production checklist)

1. **Deploy** the stack (`scripts/install.sh --apply`, or `docker compose -f
   docker/docker-compose.prod.yml up -d --build`).
2. In `.env`: `SCHEDULER_ENABLED=true`, `DISCOVERY_LIVE=true`,
   `SEARXNG_URL=http://searxng:8080`, and your `APPLICANT_INTERNAL_TOKEN`.
3. In the UI: **connect a model** (Settings → Add Models / OOBE), **configure a
   notification channel** (Discord/email), and **complete the Workday-ready
   onboarding** — these three open the automated-work gate (FR-UI-5/OOBE-3/ONBOARD-2).
4. **Pick a run mode + throughput** — `PUT /api/applicant/ops/runs/{campaign_id}/config`
   (`run_mode` ∈ continuous / fixed_duration / until_n_viable; `throughput_target`
   ≤ 30/day) (FR-AGENT-1/2). ✅ reachable.
5. **Enable discovery sources** — `GET/PUT /api/applicant/ops/discovery/{campaign_id}[/{source_key}]`
   (FR-DISC-2). ✅ endpoint reachable (the in-UI toggle surface is thin — §6 gap).
6. Then wait for the next scheduler tick (≤ ~60s); the digest materializes once/day
   and lands in the **Portal** + your channel.

There is currently **no UI button to "run discovery now" or to start/stop the
scheduler** — it's env-gated at boot (§6 gaps).

---

## 5. How to SEE what it's doing (today) + chat with it

What exists in the front-door right now:
- **Pending-Actions Portal** (home base, FR-UI-3) — every item awaiting you
  (digest reviews, material reviews, soft errors, final-approval). ✅
- **Activity / Debug surface** (`window.applicantDebugModule.openApplicantDebug()`,
  FR-OBS-2) — tabs **Activity / Logs / Variants / Run controls / Sources / Tools /
  Update**: per-application history, durable-workflow state, screenshots, run
  controls. ✅ reachable.
- **Agent intent sentence** (FR-AGENT-7) — `GET /api/applicant/ops/runs/{cid}/intent`
  ("what it intends to do next"); run list + stats `GET /ops/runs/{cid}`. ✅
- **Job Assistant chat** (FR-CHAT-1) — `openApplicantChat()`; helps, identifies
  profile gaps, updates attributes/criteria (confirmation-gated). ✅

The Activity → **Run controls** tab now also shows a **live status chip** (Working
now / Idle / Paused, with last-run, next-run and today's count) plus **Run now** and
**Pause/Resume**, and the **Insights** tab shows what it has learned. So you *can*
see live status + intent + activity + learning (one set of surfaces) and chat
(another) — the only remaining nicety is putting them **side by side** in one
window (§7).

---

## 6. GAPS — what an end-to-end audit + remediation found (most now CLOSED)

A focused audit (engine + workspace proxy + JS, cited to `file:line`) re-checked
each suspected gap. **Several were already fully built** — the original gap list
above overstated them — and the genuine operate/observe gaps were then **shipped**.
Current state:

| # | Item | Status | Notes |
|---|---|---|---|
| G1 | **"Run now"** — run one tick on demand instead of waiting ~60s | ✅ shipped | `POST /api/.../ops/runs/{cid}/run` → `Scheduler.run_now` (single-flight per campaign); button in Activity → Run controls |
| G2 | **Pause / resume** automated work at runtime (no restart) | ✅ shipped | `POST /ops/runs/{cid}/pause`·`/resume` → `AgentRunService.set_active` (persisted `active` flag); button in Run controls (NFR-ZEROCLI-1) |
| G3 | **Live "is it running / last-tick / next-tick / today's count"** | ✅ shipped | `GET /ops/runs/{cid}/status` (`Scheduler.state()` heartbeat); status chip (Working now / Idle / Paused) in Run controls |
| G4 | **Discovery-source on/off + yield** in the UI (FR-DISC-2) | ✅ already built | Activity → **Sources** tab: per-source toggles, funnel stats, exploration-budget slider |
| G5 | **Empty-day note** "nothing today, here's what I searched" (FR-DIG-6) | ✅ already built | `digest_service.EMPTY_DAY_NOTE` + `_searched_summary`, rendered in email/web |
| G6 | **Source-yield learning reweighting** (FR-DISC-5) | ✅ already built + wired | `LearningService` decayed conversion weights → `source_ranking`/`exploration_split` reorder discovery; **now also visible** in the Insights tab |
| G7 | **Dual-pane** (live status + activity on one side, chat on the other) | 🟡 partial | All constituents are reachable — live status + intent + activity + **Insights** (learned conversion) in the Activity surface; the Job Assistant chat is a separate window. A single side-by-side surface is the remaining polish (§7) |

Adjacent spec gaps closed in the same pass:
- **FR-LLM-3 tier-ladder editor** — Settings → "Set up Applicant" now has a full
  ordered/reorderable/add-remove model-ladder editor (was API-only); keys are
  preserved across edit/reorder.
- **FR-LEARN visibility** — new **Insights** tab surfaces real per-source conversion,
  converting roles, and the exploration budget (was engine-internal only).
- **FR-NOTIF-5 quiet hours** — engine had dead quiet-hours math; now persisted,
  gated (errors always immediate), and configurable in Settings → Notifications.

**Bottom line:** the *scraping + applying* integrations were built and proven; the
**operate + observe** layer (run-now, pause/resume, a live running indicator) and
the **learning/model-ladder/quiet-hours reachability** gaps are now closed. The one
remaining nicety is the unified side-by-side watch-and-chat surface (§7).

---

## 7. The dual-pane "watch it work while you talk to it" (recommended build)

Your ask — *"know whether the agent is running, see what it's been doing
autonomously on one side, chat with it on the other, concurrently"* — is the
natural union of FR-OBS-2 (debug/activity), FR-AGENT-7 (intent), FR-UI-3 (pending),
and FR-CHAT-1 (chat). It is **not** yet a single surface. Recommended:

**A split "Agent" surface** (reuse the existing tool-window + design-system classes,
no new framework):
- **Left pane — Live agent status + activity feed:**
  - A header status chip: **Running / Idle / Paused / Blocked**, last-tick time,
    next-tick countdown, today's throughput vs cap (needs G3 endpoint).
  - The **intent sentence** (FR-AGENT-7), updating per run.
  - A reverse-chronological **activity feed** (discovered N, scored, digest
    delivered, application X → state) sourced from `agent_runs` + `admin/history` +
    `detection_events` — the data already exists (`agent_loop` records intent/stats;
    `application_screenshots`, `decisions`, `outcome_events`).
  - **Start / Pause** + **Run now** controls (needs G1/G2).
- **Right pane — Chat (FR-CHAT-1):** the existing Job Assistant, so you can ask
  "what are you doing / why did you skip X / add this criterion" while watching the
  left pane react.

**Build order (smallest → most valuable) — most now done:**
1. ~~**G3 status endpoint**~~ ✅ shipped — `GET /ops/runs/{cid}/status` returns
   last_tick / next_tick / running / today's-count; the status chip renders it.
2. ~~**G1 "Run now"**~~ ✅ shipped — `POST /ops/runs/{cid}/run` → `Scheduler.run_now`.
3. ~~**G4 Sources panel**~~ ✅ already built (Activity → Sources).
4. **Split Agent surface** (remaining) — compose the left feed (status + intent +
   activity + Insights, all already built) beside the chat in one window; reuse
   `.admin-card`/`.cal-btn`/modal classes. This is the only outstanding piece.
5. ~~**G2 start/stop**~~ ✅ shipped (pause/resume); **G5/G6** ✅ already built.

Each step is a normal green-increment PR (ruff + engine pytest + front-door
`test_applicant_*` + `node --check` + single Alembic head + compose config +
white-label denylist), front-door-reachable per the CLAUDE.md reachability rule.

---

## 8. Reconciling the two spec files

`jobagentmasterspec.md` (uploaded) and `docs/spec/master-spec.md` (in-repo) have an
**identical requirement set** — same FR-/NFR- IDs, same §1–§13 structure. The
in-repo file has more elaboration prose (~40 extra lines). For any future audit,
cite the **requirement IDs** (stable across both). If the two ever diverge on an ID,
treat that as a spec gap to flag (§13 Traceability), not silently pick one. Both are
now version-controlled under `docs/spec/`.
