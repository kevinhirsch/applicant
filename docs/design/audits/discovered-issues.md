# Discovered issues — incidental findings ledger

Bugs and genuinely-broken behavior noticed **while working other tasks**, that are
not (or not cleanly) captured by the numbered exhaustive-audit lenses. Captured here
so they are not lost, then scheduled and driven to zero like any other backlog item.

Format: `id | severity | what | where | status`. Severity: **high** (data loss /
safety / a promised feature that silently never runs), **med**, **low**.

Status: `open`, `in-progress`, `fixed (PR #…)`, `wontfix (reason)`.

---

## Open

- **DISC-1 · high · Approved follow-ups never actually send.**
  `send_scheduled_follow_ups()` is now correct (lens 10 #1 / #53 fixed), but **nothing
  calls it** — no scheduler tick hook, no router wires the send-queue into the running
  loop. So a user who approves a follow-up draft never has it sent. Needs a scheduler
  hook (`scheduler.py`) that drains due follow-ups each tick.
  Where: `application/services/post_submission_service.py::send_scheduled_follow_ups`
  (definition-only; grep finds no caller) + `application/services/scheduler.py`.
  Status: open.

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

- **DISC-0 · high · `detect_outcome` returned an object that *looked* rejected without
  persisting.** The REJECTED-transition swallow (lens 04 #42) masked a second bug: the
  outer `app` variable was reassigned to the rejected-status object *before* the
  transaction was confirmed, so on a persistence failure the function returned an object
  that appeared rejected in memory though nothing was saved. Fixed alongside #42 by
  transitioning on a local and returning the untouched original on failure.
  Status: fixed (PR #619-batch, `post_submission_service.py`).
