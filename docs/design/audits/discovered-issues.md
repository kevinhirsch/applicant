# Discovered issues — incidental findings ledger

Bugs and genuinely-broken behavior noticed **while working other tasks**, that are
not (or not cleanly) captured by the numbered exhaustive-audit lenses. Captured here
so they are not lost, then scheduled and driven to zero like any other backlog item.

Format: `id | severity | what | where | status`. Severity: **high** (data loss /
safety / a promised feature that silently never runs), **med**, **low**.

Status: `open`, `in-progress`, `fixed (PR #…)`, `wontfix (reason)`.

**Snapshot (after the DISC-2/3/12 restart-durability + boot-visibility batch):** fixed —
DISC-0/2/3/4/5/6/7/8/9/10/11/12/13/14/15/15b/17/18;
1 open — DISC-16 (reverse-direction `owner` kwargs never populated). Per-lens backlog
status lives in [`exhaustive2/CLOSURE-STATUS.md`](exhaustive2/CLOSURE-STATUS.md).

---

## Open

- **DISC-18 · high · Model-picker auto-heal rewrote the Job Assistant's engine sentinel.**
  `updateModelPicker`'s "model no longer available → PATCH first available model onto the
  session" auto-heal only recognized the engine-backed chat via the lazily-loaded
  `applicantChatModule`, which loses the boot race — so every reload with a configured
  model endpoint PATCHed `endpoint_url` from `applicant://engine` to that endpoint,
  silently reconnecting the assistant's conversation to a raw LLM (split-brain: each
  reload then minted a fresh "Job assistant" session). Live-caught during the chat-
  unification verification (two corrupted sessions observed in the demo DB). Fixed
  two-layer: a direct sentinel check in `modelPicker.js` before the heal, and a
  server-side 400 in `session_routes.py` refusing any model/endpoint rewrite on a
  sentinel-flagged session (covers the model-cycling shortcut, presets, and group
  conversion too). Guard-tested in `test_applicant_chat_unification.py`.
  Status: **fixed** (chat-unification PR).

- **DISC-17 · low · Stale lifted-from path comment in workspace middleware.**
  `workspace/core/middleware.py`'s header comment reads `# src/middleware.py` — a leftover
  path from wherever the file was lifted, now wrong. Cosmetic; fix on next touch of that file.
  Where: `workspace/core/middleware.py` (top-of-file comment). Status: fixed (PR pending) —
  comment corrected to `# workspace/core/middleware.py`.


- **DISC-14 · low · Notifier reads the clock independently in three places.**
  `notify()`, `advance()`, `deliver_now()` each take/compute a timestamp, and `_build_rungs`
  takes its OWN later clock read for `due_at` — so a stale timestamp reused across them can make
  every rung's `due_at` look microseconds in the future and skip firing (a real footgun hit and
  fixed while doing lens 10 #9). Thread one `now` value through `notify()`→`_build_rungs()`→`_fire_due()`.
  Where: `src/applicant/adapters/notification/apprise_notifier.py`. Status: **fixed** —
  `notify()` now takes a single clock read and threads it through `_build_rungs(notification, now)`
  and `_fire_due(delivery, now)`; regression test in
  `tests/unit/test_notifier_disc14_single_clock_read.py`.

- **DISC-16 · low · Reverse-direction `owner` kwargs are never populated.**
  `workspace/src/applicant_engine.py`'s `owner=` kwargs (engine→workspace calendar/email/research/
  memory callbacks) are passed by no caller, so that channel is unattributed. Status: open.

- **DISC-5 · med · Deep-research inner-hop transport timeout may still be short.**
  Lens 04 #10 gave the front-door research *route* a long read timeout, but the
  engine→workspace research *callback* hop (the workspace-callback discovery adapter on
  the engine side) may still carry a short default transport timeout — so a long manual
  run could 502 at that inner hop even after the route fix. Verify and, if short, lengthen.
  Where: `src/applicant/adapters/.../research` workspace-callback adapter vs
  `workspace/routes/applicant_internal_routes.py` (`_RESEARCH_*` request-budget clamp).
  Status: fixed (PR pending) — the engine-side `HttpWorkspaceClient` research
  transport ceiling was still the snappy 30s default while the workspace research
  budget clamps up to 600s, so a long manual run 502'd at this inner hop. Raised the
  default to 630s (600s budget ceiling + buffer, matching the front-door route's
  `_RESEARCH_RUN_MAX_TIMEOUT`), resolved config-local from `WORKSPACE_RESEARCH_TIMEOUT`
  with that sane default, and pinned it with hermetic tests.

- **DISC-6 · low · Already-resolved pending action isn't surfaced to the UI.**
  The service `resolve()` now returns a distinguishable already-resolved signal (lens 04
  #27), but the `pending_actions` router still returns a bare `204` regardless, so the
  front-door proxy/UI can't tell the user "this was already handled." Wire the signal
  through (response body or distinct status) → proxy → JS.
  Where: `app/routers/pending_actions.py` (~206-237) + workspace proxy + Portal JS.
  Status: **fixed (PR pending)** — the router keeps returning the original bare `204`
  for a genuine open→resolved transition, but a repeat resolve now gets a `200` with
  `{"status": "already_resolved"}`; the workspace proxy (`applicant_portal_routes.py::
  resolve_action`) forwards it as an `already_resolved` flag; `applicantPortal.js::
  _doResolve` now honors that real server signal via the SAME honest "already handled"
  path the client-side guard (Portal #50) already used for a same-tab double-click —
  closing the gap for a cross-tab/cross-device already-resolved case the client-only
  guard couldn't see.

- **DISC-7 · high · Follow-up can resend — "sent at most once" is violated.**
  In `send_scheduled_follow_ups`, if `notify_decision` sends the email but the subsequent
  `follow_ups.update(sent_fup)` (flip to SENT) raises, the exception is swallowed and the
  row stays `SCHEDULED`, so `list_due()` resends the same follow-up next tick — contradicting
  the "sent AT MOST ONCE" docstring. Flip to SENT before/atomically-with the send, or record
  a sent-marker that survives the flip failure.
  Where: `application/services/post_submission_service.py::send_scheduled_follow_ups`.
  Status: **fixed** (this batch — the row is durably flipped to SENT *before* the send, so
  a crash/flip-failure after a successful send can no longer resend).

- **DISC-8 · med · Ghosting can double-signal.**
  In `check_ghosting`, the `GhostingSignal` row is added BEFORE the status flip to GHOSTED;
  if the flip silently fails, the application stays re-matchable and gets a duplicate
  ghosting signal on the next day's sweep. Order the flip before the signal, or make them
  atomic.
  Where: `application/services/post_submission_service.py::check_ghosting`.
  Status: **fixed** (this batch — a signal is recorded only if one doesn't already exist for
  the application, so a re-sweep after a failed flip can't create a duplicate).

- **DISC-12 · low · Redrive failures are invisible.**
  `lifespan._redrive_pending`'s per-workflow `except Exception: log.info("redrive_skipped", …)`
  swallows individual durable-workflow redrive failures at `log.info` (not even a warning) with
  no counter — a batch of failed redrives is invisible in logs and on `/healthz`. Same
  "no aggregate signal" class as 04-#48, scoped inside one boot step.
  Where: `app/lifespan.py::_redrive_pending`.
  Status: **fixed** — each per-workflow redrive failure is logged at `warning` (a genuine
  anomaly, not routine info) and counted into a `failed` tally; a non-zero tally emits one
  batch-level `redrive_failed_batch` warning AND records a `durable_recovery_redrives`
  failed step onto the process's `BootHealth` snapshot (04-#48's existing aggregate signal)
  so a batch of failed redrives is visible on `/healthz`, not just buried in logs. Regression
  test: `tests/unit/test_lifespan_redrive_visibility.py`.

- **DISC-13 · high (security) · Loopback trust was bypassable behind a proxy/tunnel.**
  The first-run/unconfigured loopback bypass in `applicant_ops_routes._require_admin`,
  `applicant_admin_routes._require_admin`, and `auth_helpers.require_user` trusted any request
  whose peer host was loopback — but a cloudflared/reverse-proxy tunnel connects FROM loopback,
  so a remote unauthenticated caller routed through such a tunnel inherited local-operator trust
  and could reach admin/update/run-control endpoints before auth was configured.
  Status: **fixed** (this batch — all three call sites now fail closed when any proxy/tunnel
  forwarding header is present, matching the already-hardened `app.py` pattern).

- **DISC-9 · med · Pre-submit override is lost when the pipeline can't start.**
  In `agent_loop._process_approvals`, the presubmit-safety override is cleared as soon as
  it's seen, before `_start_pipeline` confirms the pipeline actually started. If
  `_start_pipeline` returns `False` for a NORMAL reason (e.g. capacity full — not an
  exception), the override bookkeeping is already gone, so the next tick re-blocks the item
  and it looks brand-new to the operator even though they already overrode it once. Clear
  the override only after a confirmed start.
  Where: `application/services/agent_loop.py::_process_approvals`.
  Status: **fixed** (this batch — the override clears only after `_start_pipeline` confirms a
  start; a capacity-full or exception failed-start preserves it for the next tick).

- **DISC-10 · med · Bulk decline loses the shared reason on failure.**
  The digest single-row decline now preserves the typed reason on a failed POST (04-#53),
  but `_onBulkDecline` has the same unfixed pattern — a failed bulk decline forces retyping
  the shared reason for the whole batch.
  Where: `workspace/static/js/emailLibrary/applicantDigest.js::_onBulkDecline`.
  Status: **fixed** (landed in a prior batch, commit `12922fb`, before this ledger entry
  was flipped — a module-level `_lastBulkDeclineReason` mirrors the single-row
  `_lastDeclineReasonByRow` pattern: preserved when at least one row in the batch fails,
  prefilled into the next prompt's `defaultValue`, cleared only once the whole batch
  clears cleanly. Covered by `workspace/tests/test_applicant_copy_digest_lens02.py`.
  This ledger entry was stale — no code change was needed this batch, only this status
  correction.).

- **DISC-11 · low · Approval-start give-ups are invisible to the operator surface.**
  The new `ApprovalStartLedger` (04-#32) gives up on a repeatedly-failing pipeline start,
  but `list_given_up()` / `retry_given_up()` (the operator visibility + retry surface for
  resume give-ups) don't include approval-start give-ups — a given-up app is invisible there.
  Where: `application/services/agent_loop.py` give-up surface.
  Status: **fixed** (this batch — `list_given_up`/`retry_given_up` now merge both ledgers,
  tagging each row with a `give_up_reason`). Front-door copy to distinguish the reason in the
  UI is a small workspace follow-up.

- **DISC-2 · high · In-memory ledgers lost on restart → retry storm.**
  `ResumeLedger` and `CurationLedger`/`InMemoryRoutineStore` are now process-lived
  (tick-safe), but a genuine process restart (deploy via update.sh, OOM, crash) wipes
  them, so the resume-backoff and routine state reset and the loop can re-attempt
  everything at once. Needs a storage-backed ledger (persist + reload on boot).
  Where: `app/container.py` (ledger construction) + `application/services/agent_loop.py`.
  Status: **fixed** — the retry-storm source is the **`ResumeLedger`** (the backoff
  window `last_resume` + the failure/give-up cap, exactly the "where" scoped above), so
  it is now storage-backed: a new `ConfigLedgerStore`
  (`adapters/storage/ledger_persistence.py`) persists a JSON snapshot to the SAME
  durable `app_config` table the OOBE ladder/wizard state already uses — **no new table
  or migration**. The container injects it and calls `restore()` at boot (before any
  loop binds the ledger's dicts); `AgentLoop` re-persists after every mutation
  (`_mark_resumed`, `_record_resume_failure`, `retry_given_up`), so on the next boot the
  backoff/give-up state is reloaded and the loop no longer treats every parked
  application as immediately "due". On the real-DB lane the store opens a **fresh session
  per write** via `session_factory` (scheduler-thread-safe — it never touches the boot
  Session, CONC-2), mirroring `AuditLogService`'s per-event isolation; with no DB it
  round-trips through the in-memory config store (nothing survives a restart there
  anyway). Regression tests:
  `tests/unit/test_resume_ledger_durable_disc2.py` (snapshot/restore across a simulated
  restart incl. datetimes; in-place `_load_snapshot`; every mutation site persists; a
  SQLite `app_config` round-trip; end-to-end container rebuild). **Out of scope
  (honest):** `CurationLedger` (curation dedupe — a restart just re-dedupes, no storm)
  and `InMemoryRoutineStore` (planning priors only; the store's own docstring defers
  durability to a future DB-backed adapter implementing its Protocol) are intentionally
  left in-memory — neither is the retry-storm source and both are outside this "where".
  (Audit 04-#30/#41 touch this; capturing the restart-durability half.)

- **DISC-3 · med · Prefill diagnostics ring resets every tick.**
  Unlike the routine store, the prefill diagnostics ring has no injectable process-lived
  option, so it resets on every per-tick service rebuild — diagnostics for a stuck
  prefill vanish between ticks.
  Where: `application/services/prefill_service.py` (diagnostics ring) + `container.py`.
  Status: **fixed** — lift-and-shift of the exact process-lived pattern the routine
  store / resume ledger already use: `PrefillService` takes an injectable
  `diagnostics_ring`, the container builds ONE process-lived `PrefillDiagnosticsRing`
  (`container.py`) and injects it into the shared singleton AND every per-tick/per-
  request `PrefillService` rebuild, so a diagnostic recorded on any tick is visible
  through the never-rebuilt `container.prefill_service` the admin
  `/api/admin/prefill-diagnostics` route reads. Regression test:
  `tests/unit/test_prefill_diagnostics_durable_lens04.py`. (Audit 04-#39.)

- **DISC-4 · med · Saved model-connection keys can't be reused in a tier.**
  Picking a saved connection into a model-ladder tier (lens 11 #9) cannot auto-fill its
  API key — keys stay sealed server-side (`list_endpoints` returns `has_key: bool`, never
  the ref), so the user must re-enter the key. A backend route to bind a tier to a saved
  connection's key *by reference* (never exposing plaintext) would close it.
  Where: engine model-endpoint service + a new bind-by-ref route; `applicantModelLadder.js`.
  Status: fixed (PR pending). A tier now carries a `connection_id` reference (never a key):
  the ladder save route (`PUT /api/setup/llm/tiers`, `TierSettings.connection_id`) accepts
  the saved connection's id, and `SetupService.build_ladder` resolves that connection's
  sealed key server-side AT USE TIME (`_resolve_connection_key`, reading the shared vault via
  the connection's own `model.endpoint.{id}` ref) — so rotating the connection's key flows to
  every bound tier and the plaintext is never copied into the tier, never returned to the
  client, never logged. `applicantModelLadder.js` binds the tier on pick (no re-prompt when
  the connection has a key) and re-sends the id on save; `get_tiers` surfaces `connection_id`
  (non-secret) but never the key. Precedence: a freshly typed key wins, then `connection_id`,
  then the tier's own `api_key_ref`.

---

## Resolved

- **DISC-15b · high (security) · Cross-account WRITE on campaigns/tracker proxies.**
  The write endpoints (`applicant_campaigns_routes.py`: update/clone/delete/toggle-source;
  `applicant_tracker_routes.py`: the 7 POST mutators) still gated only on `require_user` after
  DISC-15 closed the reads — so a second workspace account could still MUTATE the owner's
  campaigns/applications (single-tenant engine ⇒ the id-validation check is trivially satisfied).
  Fixed by applying the shared `require_engine_owner` gate to every write endpoint on both files
  (lone owner in single-user mode still passes; a second account gets 403 and the engine mutation
  is never invoked). Status: **fixed** (batch-5 PR — `4f3b17a`, +8 write-isolation tests).

- **DISC-15 · high (security) · Cross-account READ on pending/campaigns/tracker/activity proxies.**
  The sibling `applicant_*_routes.py` read proxies gated only on `require_user`; since the engine is
  single-tenant, that let a second workspace account read the owner's pending actions / campaigns /
  tracker board / activity feed. Fixed by factoring the `_require_notification_owner` gate into the
  shared `require_engine_owner` (`workspace/src/auth_helpers.py`) and applying it to every read
  endpoint on those four proxies (lone owner in single-user mode still passes; a second account gets
  403). The WRITE-endpoint half is tracked separately as **DISC-15b** (still open).
  Status: **fixed** (batch-4 PR — `2684ac0`, +16 cross-user isolation tests).

- **DISC-1 · NOT A BUG (was mis-captured) · Approved follow-ups DO send.**
  Originally captured as "nothing calls `send_scheduled_follow_ups()`" — that was wrong,
  propagated from an earlier agent working off stale `main`. Verified: the scheduler tick
  already drains due follow-ups (`scheduler.py` calls
  `post_submission.send_scheduled_follow_ups(now=now)`), wired by prior merged commit
  `65b0ab5` ("Wire dark-engine audit items 7/10 … follow-up send queue"). No action needed.
  Status: wontfix (already wired; false finding — kept for the audit trail).

- **DISC-0 · high · `detect_outcome` returned an object that *looked* rejected without
  persisting.** The REJECTED-transition swallow (lens 04 #42) masked a second bug: the
  outer `app` variable was reassigned to the rejected-status object *before* the
  transaction was confirmed, so on a persistence failure the function returned an object
  that appeared rejected in memory though nothing was saved. Fixed alongside #42 by
  transitioning on a local and returning the untouched original on failure.
  Status: fixed (PR #619-batch, `post_submission_service.py`).
