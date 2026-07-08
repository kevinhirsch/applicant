# H1 — Receipts, not narration: the claim-path audit

**Story:** Phase 1.5 · H1 (`docs/backlog/road-to-market.md`). **DoD:** every
number/claim the owner reads (Today "what I did", Activity feed, Tracker
counts, digest/recap) is a projection of **recorded actions**, never an LLM
describing what it thinks it did; an audit confirms no claim-path narrates and
a test pins it.

This file is the audit record. It is machine-checked: every callable named
here is enumerated in `tests/unit/test_h1_receipts_not_narration.py`
(`CLAIM_PATH_CALLABLES`) and source-scanned for model-invocation tokens on
every run of the hermetic suite (`test_no_claim_path_narrates`, with
`test_claim_path_list_matches_the_audit_doc` keeping this doc and the test
list in sync, and a canary proving the scanner catches a real LLM path).

## The claim paths, and where each number comes from

| Surface (front-door) | Claim the owner reads | Recorded source (engine) | Claim-path callables (audited) |
|---|---|---|---|
| **Today** — guardrails line (`applicantToday.js` → `/api/applicant/campaigns/{id}/guardrails`) | "Today: N applications · ~$X · target T/day" | Persisted `agent_runs` rows: `count_pipelines_started_on` + `sum_stats_between` over the usage counters `AgentLoop` durably folds into `agent_runs.stats`. Dollar figures are labeled estimates; `usage_reported=False` says so instead of implying "free". | `today_summary`, `monthly_projection` (CostService) |
| **Activity** — status strip + "Recently I…" rows (`applicantActivity.js` → `/api/applicant/activity/*`) | The per-run sentence + "discovered 5 · pre-filled 3 · submitted 1" | Each row is one persisted `agent_runs` record. Its sentence is a deterministic template over that tick's own counters (`TickResult`) — including the "why nothing happened" skip-reason rows; the stat summary and the per-run **receipt** render only counters the record carries. | `_intent_sentence`, `_record_intent`, `_record_skip_reason` (AgentLoop); `status`, `latest_intent` (AgentRunService) |
| **Activity** — "Right now / Up next" snapshot (`/api/agent/status/{id}`) | "Right now I'm working… I've started A of today's B applications." | Scheduler heartbeat + the persisted run status; every block omits what its source can't answer (FR-AGENT-5). | `_now_sentence`, `_next_sentence`, `agent_status` (agent_status router) |
| **Daily status push** (notification inbox) | "Since yesterday I started N applications…" | The same persisted run status + application history + pending count; no source ⇒ no message at all. | `build_message`, `_past_lines`, `_present_lines`, `_future_lines` (StatusUpdateService) |
| **Tracker** counts (`applicantTracker.js`) | Bucket headers "(N)" | N is literally `rows.length` of the application rows rendered directly beneath the header — the receipt is inline. No engine claim path involved beyond the row list itself. | — (render-side projection; see `_renderBucket`) |
| **Digest** — "what I searched" + empty-day note | "Searched: titles=…; sources=…" | The campaign's stored criteria + enabled discovery sources. | `_searched_summary` (DigestService) |
| **Weekly recap** | "This week I sent N applications…" | Count of submission snapshots captured in the 7-day window — the durable stop-boundary evidence of each real send. Interviews/offers are **omitted** (not zero-padded) because no recorded source exists yet. Best source names only a source with recorded yield. | `build_weekly_recap`, `_applications_sent_between`, `_best_source_for_recap`, `render_weekly_recap_message` (DigestService) |

## Receipts in the UI (the links from claim to record)

* **Activity rows** now carry an expandable per-run **Receipt** (`_receiptHTML`,
  `applicantActivity.js`): the recorded run's own counters (roles found,
  shortlisted, applications started, handed to you, submitted, budget left,
  model calls, estimated cost, skip reason, recorded-at). A counter the record
  doesn't carry contributes no line; a run with no recorded numbers renders no
  receipt. Pinned in `workspace/tests/test_applicant_h1_receipts.py`.
* **Today's count** links to its receipt: the guardrails line opens Activity
  (the recorded-run trail the number is computed from), announced via
  tooltip/aria and keyboard-operable. Same test file.
* **Weekly recap / daily push** notifications already deep-link to the digest
  and Activity surfaces they summarize.
* **Tracker** counts sit directly above the rows they count.

## Boundary notes

* **Chat is narration-capable by design** (`ChatService._reply_text` builds a
  prompt and calls the model) but its "what have you been doing" answers are
  grounded in the same read-only status context, and any LLM failure degrades
  to a deterministic reply. Chat is a conversation, not one of the H1 claim
  surfaces; it is used as the scanner's **canary** to prove the audit's token
  list catches real model paths.
* Digest **row scores** use the scoring model — that is a judgment about a
  posting, not a claim about work done, so scoring is deliberately outside
  this audit. The digest's *claims* (row counts, searched line, empty-day
  note) are projections and are audited.
* The weekly recap's deeper projection properties (window edges, zero-count
  honesty, never fabricating interview/offer numbers) are pinned in
  `tests/unit/test_cov_round2_weeklyrecap.py`.
