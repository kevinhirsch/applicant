# Discovered issues — incidental findings ledger

Bugs and genuinely-broken behavior noticed **while working other tasks**, that are
not (or not cleanly) captured by the numbered exhaustive-audit lenses. Captured here
so they are not lost, then scheduled and driven to zero like any other backlog item.

Format: `id | severity | what | where | status`. Severity: **high** (data loss /
safety / a promised feature that silently never runs), **med**, **low**.

Status: `open`, `in-progress`, `fixed (PR #…)`, `wontfix (reason)`.

**Snapshot (after PRs #626–#630 + chat unification):** 13 fixed —
DISC-0/3/7/8/9/10/11/12/13/15/15b/17/18;
6 open — DISC-2 (restart-durable ledgers, highest value), DISC-4, DISC-5, DISC-6, DISC-14,
DISC-16. Per-lens backlog status lives in
[`exhaustive2/CLOSURE-STATUS.md`](exhaustive2/CLOSURE-STATUS.md).

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
  Where: `src/applicant/adapters/notification/apprise_notifier.py`. Status: fixed (PR pending) —
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
  Status: open (surfaced fixing 04-#10).

- **DISC-6 · low · Already-resolved pending action isn't surfaced to the UI.**
  The service `resolve()` now returns a distinguishable already-resolved signal (lens 04
  #27), but the `pending_actions` router still returns a bare `204` regardless, so the
  front-door proxy/UI can't tell the user "this was already handled." Wire the signal
  through (response body or distinct status) → proxy → JS.
  Where: `app/routers/pending_actions.py` (~206-237) + workspace proxy + Portal JS.
  Status: open (surfaced fixing 04-#27; the Portal #50 lane addresses the UX shell).

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
  Status: open (surfaced fixing 04-#48).

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
  Status: open (surfaced fixing 04-#53).

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
  Status: open. (Audit 04-#30/#41 touch this; capturing the restart-durability half.)

- **DISC-3 · med · Prefill diagnostics ring resets every tick.**
  Unlike the routine store, the prefill diagnostics ring has no injectable process-lived
  option, so it resets on every per-tick service rebuild — diagnostics for a stuck
  prefill vanish between ticks.
  Where: `application/services/prefill_service.py` (diagnostics ring) + `container.py`.
  Status: open. (Audit 04-#39.)

- **DISC-4 · med · Saved model-connection keys can't be reused in a tier.**
  Picking a saved connection into a model-ladder tier (lens 11 #9) cannot auto-fill its
  API key — keys stay sealed server-side (`list_endpoints` returns `has_key: bool`, never
  the ref), so the user must re-enter the key. A backend route to bind a tier to a saved
  connection's key *by reference* (never exposing plaintext) would close it.
  Where: engine model-endpoint service + a new bind-by-ref route; `applicantModelLadder.js`.
  Status: open (surfaced fixing 11-#9; the front-end already prompts for the key once).

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
