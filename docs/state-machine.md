# Application Lifecycle State Machine

Source: master spec §7. This is the per-application lifecycle. Covers **FR-DUR-1/3** (every step a small idempotent DBOS step; approval waits via DBOS `recv`), **FR-PREFILL-2/4/5/6/7**, **FR-ATTR-5/6**, **FR-AGENT-4/5/6**, **FR-RESUME-8**, **FR-NOTIF-2**, **FR-LOG-4**, **FR-UI-3**, **FR-SANDBOX**.

## ASCII diagram (verbatim from §7)

```
DISCOVERED -> SCORED -> DIGESTED
  -> DECLINED (terminal; feedback -> FR-LEARN + criteria delta)
  -> APPROVED -> SANDBOX_PROVISIONING -> ACCOUNT_PREFILL --(form filled)--> AWAITING_ACCOUNT_HUMAN_STEP <-> (user: button/CAPTCHA/email-verify)
  -> PREFILLING
       <-> BLOCKED_DETECTION        (cautious-mode pause; notify + VNC)
       <-> BLOCKED_MISSING_ATTR     (soft error; attribute reused after resolve)
       <-> BLOCKED_QUESTION         (uncertainty; hold)
  -> MATERIAL_PREP                  (resume variant pick/generate; cover letter; screening answers; page-fit + fidelity check)
       <-> MATERIAL_REVIEW          (redline w/ add+subtract highlights; interactive add/subtract/free-text revision loop; approve/decline/revise)
  -> AWAITING_FINAL_APPROVAL        (bundled material approval + final-submit gate; notify + VNC)
  -> SUBMITTED_BY_USER (terminal)   -> log + OutcomeEvent(submitted)
  -> FINISHED_BY_ENGINE (terminal)  -> log + OutcomeEvent(submitted)   [friction-free, user-authorized]
  -> EMERGENCY_DATA_HANDOFF         (only when agent reports fill failed; user pastes into own browser; then mark-submitted)
  -> FAILED (terminal)              (unrecoverable; error surfaced)
```

## Invariants (§7)

> Every `BLOCKED_*`/`AWAITING_*`/`MATERIAL_REVIEW` emits a notification, lands in the pending-actions portal, and yields capacity (pivot). The engine never clicks an account-creating submit, never solves a CAPTCHA, never auto-fills sensitive EEO fields, and never submits generated material without approval. Every step is a small idempotent DBOS step (mid-step resumption); approval waits use DBOS `recv`.

## State list

| State | Kind | Description |
|---|---|---|
| DISCOVERED | transient | Posting gathered by discovery (FR-DISC). |
| SCORED | transient | Viability score + rationale computed (FR-AGENT-3). |
| DIGESTED | wait (user) | Placed in the daily digest awaiting approve/decline (FR-DIG-3). |
| DECLINED | terminal | User declined; feedback → FR-LEARN + criteria delta (FR-DIG-5, FR-FB-1). |
| APPROVED | transient | User approved; queued for processing (FR-DIG-3). |
| SANDBOX_PROVISIONING | transient | Isolated browser sandbox spinning up (FR-SANDBOX-1, FR-PREFILL-1). |
| ACCOUNT_PREFILL | transient | Account-creation form being pre-filled (FR-PREFILL-2). |
| AWAITING_ACCOUNT_HUMAN_STEP | wait (user) | Account form filled; user does button/CAPTCHA/email-verify via VNC (FR-PREFILL-4). |
| PREFILLING | transient | Application pages being pre-filled field by field (FR-PREFILL-2/3). |
| BLOCKED_DETECTION | wait (user) | Cautious-mode pause on a detection signal; notify + VNC (FR-PREFILL-6, FR-STEALTH). |
| BLOCKED_MISSING_ATTR | wait (user) | Soft error for a missing attribute; value reused after resolve (FR-ATTR-5). |
| BLOCKED_QUESTION | wait (user) | Agent uncertainty; hold for input (FR-AGENT-4/5). |
| MATERIAL_PREP | transient | Resume variant pick/generate, cover letter, screening answers; page-fit + fidelity check (FR-RESUME-3/4/7, FR-ANSWER-1). |
| MATERIAL_REVIEW | wait (user) | Redline review with add/subtract/free-text revision loop; approve/decline/revise (FR-RESUME-8). |
| AWAITING_FINAL_APPROVAL | wait (user) | Bundled material approval + final-submit gate; notify + VNC (FR-PREFILL-5, FR-NOTIF-2). |
| SUBMITTED_BY_USER | terminal | User submitted in the live session; log + OutcomeEvent(submitted) (FR-LOG-1, FR-LEARN-2). |
| FINISHED_BY_ENGINE | terminal | Engine clicked final submit (friction-free, user-authorized); log + OutcomeEvent(submitted). |
| EMERGENCY_DATA_HANDOFF | wait (user) | Only when the agent reports fill failed; user pastes into own browser, then mark-submitted (FR-PREFILL-7, FR-LOG-4). |
| FAILED | terminal | Unrecoverable; error surfaced (FR-NOTIF-5). |

## Transition table

| From | Event / condition | To |
|---|---|---|
| DISCOVERED | viability scored | SCORED |
| SCORED | added to digest | DIGESTED |
| DIGESTED | user declines (+ feedback) | DECLINED |
| DIGESTED | user approves | APPROVED |
| APPROVED | provision sandbox | SANDBOX_PROVISIONING |
| SANDBOX_PROVISIONING | account required | ACCOUNT_PREFILL |
| SANDBOX_PROVISIONING | no account needed | PREFILLING |
| ACCOUNT_PREFILL | form filled (no submit click) | AWAITING_ACCOUNT_HUMAN_STEP |
| AWAITING_ACCOUNT_HUMAN_STEP | user completes button/CAPTCHA/email-verify | PREFILLING |
| PREFILLING | detection signal | BLOCKED_DETECTION |
| PREFILLING | missing attribute | BLOCKED_MISSING_ATTR |
| PREFILLING | agent uncertainty | BLOCKED_QUESTION |
| BLOCKED_DETECTION | user resolves in live session | PREFILLING |
| BLOCKED_MISSING_ATTR | user supplies value (stored + reused) | PREFILLING |
| BLOCKED_QUESTION | user answers | PREFILLING |
| PREFILLING | pages filled, material needed | MATERIAL_PREP |
| PREFILLING | fill failed (agent reports) | EMERGENCY_DATA_HANDOFF |
| MATERIAL_PREP | material ready | MATERIAL_REVIEW |
| MATERIAL_REVIEW | user sends back with revisions | MATERIAL_PREP |
| MATERIAL_REVIEW | user approves material | AWAITING_FINAL_APPROVAL |
| MATERIAL_REVIEW | user declines application | DECLINED |
| AWAITING_FINAL_APPROVAL | user submits in live session | SUBMITTED_BY_USER |
| AWAITING_FINAL_APPROVAL | user authorizes engine (friction-free) | FINISHED_BY_ENGINE |
| AWAITING_FINAL_APPROVAL | CAPTCHA/verify intervenes | (user completes, then SUBMITTED_BY_USER) |
| EMERGENCY_DATA_HANDOFF | user pastes + marks submitted | SUBMITTED_BY_USER |
| any | unrecoverable error | FAILED |

## What each BLOCKED_* / AWAITING_* state emits

Each waiting state performs the same three actions, then **pivots** (yields capacity so other applications proceed — FR-AGENT-6, FR-DUR-4). The wait itself is a DBOS `recv` so a crash resumes the wait.

| State | Notification | Pending-action entry (FR-UI-3) | Pivot |
|---|---|---|---|
| DIGESTED | Discord/email/web "digest ready" (FR-DIG-2, FR-NOTIF-2) | Digest approval row | Yes |
| AWAITING_ACCOUNT_HUMAN_STEP | Notify + one-click VNC link (FR-PREFILL-4) | "Complete account creation" action | Yes |
| BLOCKED_DETECTION | Notify + VNC, cautious-mode handoff (FR-PREFILL-6) | "Detection blocker — take over" action | Yes |
| BLOCKED_MISSING_ATTR | Soft-error notification (FR-ATTR-5) | "Provide missing detail" action | Yes |
| BLOCKED_QUESTION | Pause-and-notify, hold for input (FR-AGENT-4) | "Agent question" action | Yes |
| MATERIAL_REVIEW | Review notification linking to redline surface; approve only after viewing (FR-NOTIF-4) | "Review document/answer" action | Yes |
| AWAITING_FINAL_APPROVAL | Notify + VNC; escalation ladder (FR-NOTIF-2) | "Final approval / submit" action | Yes |
| EMERGENCY_DATA_HANDOFF | Notify with pre-filled values to paste (FR-PREFILL-7) | "Emergency handoff + mark submitted" action | Yes |

Notifications follow the FR-NOTIF-2 escalation ladder (Discord push held 30s; in-app if user verifiably present; email after the configurable 15-minute timeout) and are idempotent across channels (FR-NOTIF-3). Errors (→ FAILED, or any error) surface immediately at any hour (FR-NOTIF-5).
