# Plan — Real-browser Workday pre-fill + credential-store login/account-creation

Status: **proposed** (for review). Author: playtest hardening. Scope owner: Applicant engine.

## 1. Goal

Make the autonomous loop actually **pre-fill a real Workday application end-to-end**, and add a
**credential-store-driven login / account-creation** flow so the engine can get *past* the account
gate on its own where the user has authorized it — while preserving the safety guarantees
(review-before-submit, never solve CAPTCHA/email-verify, never final-submit without explicit
authorization) and **multi-tasking** so one blocked application never stalls the others.

This is one body of work because the credential flow is meaningless until the engine can actually
drive a live Workday account/login page, and the live-navigation work is incomplete without
handling the account gate.

## 2. What the live playtest proved (2026-06-18)

Driving the loop at a live NVIDIA Workday posting (`nvidia.wd5.myworkdayjobs.com`) with the new
`BROWSER_REAL=true` toggle showed:

- **Real Chrome launches and reaches the live posting** — stealth-coherent (`webdriver=false`,
  WebGL present after the SwiftShader fix), TLS resolved once the sandbox egress CA was trusted.
- **But the captured page was blank** and no fields were detected: the engine completed to
  `AWAITING_FINAL_APPROVAL` having filled nothing. Root causes (grounded in the code, below):
  `open()` doesn't wait for the SPA to hydrate; nothing clicks **"Apply"** to enter the application
  flow; and `WorkdayAts` carries **no real Workday selectors**.

So the real-browser path *loads a URL* but does not yet *drive a Workday application*.

## 3. Current state (file:line)

What already works — do **not** rebuild:

- `PlaywrightPageSource` (`src/applicant/adapters/browser/page_source.py`): `detect_fields()`
  (~528) reads real `input/select/textarea`, preferring `[name]`, `#id`, then `[data-automation-id]`;
  `advance()` (~592) clicks a Next/Continue selector list and waits `networkidle`; `current_state()`
  (~490) returns url/fields/status/body/signals; `is_account_create_page()` (~628) and
  `is_final_submit_page()` (~644) are heuristic (URL + visible text); `type_value()` (~569) types
  with human cadence; `screenshot()` (~584) writes a real PNG.
- **Credential vault** is production-ready: `ports/driven/credential_store.py` (`Credential{tenant_key,
  username, secret, source}`, `store/capture/retrieve/list_tenants`), `adapters/credentials/
  pg_credential_store.py` (libsodium `SecretBox`, file master key 0600, durable, unique on
  `(campaign_id, tenant_key)`), wired in `container.py` (~253) into `PrefillService`. Today it only
  banks SYSTEM-campaign secrets (LLM/Proxmox), never ATS-site credentials.
- **Multi-tasking** exists: `CapacityService` (`admit_sandbox`/`yield_for_block`/`release_sandbox`,
  `SANDBOX_CONCURRENCY` cap), `AgentLoop._start_pipeline` admission gate (~423), the scheduler's
  per-campaign non-reentrant lock + per-tick session isolation.
- **Hand-off plumbing** exists: `PrefillService.resume_after_account/_detection/_missing_attr`,
  `_account_handoff` (lands `AWAITING_ACCOUNT_HUMAN_STEP`), `PendingActionsService.materialize`,
  `NotificationService` escalation, `remote.py` resume endpoints.

The narrow gaps:

- `open()` (~486) does `goto(url)` with default `wait_until="load"` — **no SPA-hydration wait**.
- **No "Apply" entry click** — the loop inspects the landing posting page, not the application form.
- `WorkdayAts` (`adapters/browser/ats.py`) only models a *fake* page sequence with mock selectors
  (`#email`); the real driver gets **no Workday selector/step knowledge**.
- **No ATS-site credential use**: nothing calls `credentials.retrieve(campaign_id, tenant_key)` to
  fill a login/account page; no predefined-credential setting; `submit_account()` only raises.

## 4. The safety-boundary change (read first)

The requested credential flow **changes a core safety invariant**. Today
`core/rules/prefill_boundary.py` lists `ACCOUNT_CREATE_SUBMIT` as **irreducible** — the engine never
creates accounts. The new behavior lets the engine **create an account from a user-defined
predefined credential set** and **log in** on its own. We will make this an *explicitly gated*
capability, never a silent default:

- New setting (default **OFF**): `ALLOW_AUTOMATED_ACCOUNTS` (env, surfaced in Settings). The engine
  may log in / create an account **only when** the user has (a) enabled this and (b) configured a
  predefined credential set.
- Still **never** solved by the engine, unconditionally: CAPTCHA, email-verify, SMS-verify
  (`_IRREDUCIBLE` keeps these). Still **never** final-submit without `engine_submit_authorized`.
- The guard moves from "always refuse account-create" to a derived-ground-truth check
  `ensure_account_action_allowed(*, automated_accounts_enabled, has_predefined_credentials)` — the
  engine derives the decision; a caller flag can never opt the safety in (per CLAUDE.md).
- This warrants a dedicated **security review** (its own ADR under `docs/adr/`).

## 5. Credential-store login / account-creation flow (RESOLVED — automate the login)

**Hard requirement (non-negotiable):** the vault stores the user's logins like a password
manager and the engine **drives the login automatically** — the user must NOT sign in per
application. This holds for direct email/password ATS logins **and** for "Sign in with Google".

On reaching an **account gate** (`is_account_gate`) for `tenant_key = workday:<host>`:

1. **Already authenticated?** A persistent per-tenant/Google browser profile (FR-STEALTH-3,
   `ProfileStore` → `launch_persistent_context(user_data_dir=…)`) may already carry a live session
   cookie → the gate is skipped and the engine proceeds straight into the form. This is what makes
   "sign in once every few days" real: the session is reused across applications.
2. **Direct email/password gate** → retrieve `credentials.retrieve(campaign_id, tenant_key)`; if
   present, click "Sign in with email", fill username/secret, submit, detect success. Fully
   automated.
3. **"Sign in with Google" gate** (chosen approach = *all of the above*): the engine maintains a
   persistent Google session and **also** stores the Google credential. It clicks "Sign in with
   Google"; if the Google session is live → OAuth consent clicks through (no password). If Google
   demands re-auth, the engine types the stored Google email/password.
   - **2FA flow (as specified):** when the persisted Google session has expired AND 2FA is required,
     the engine (a) sends a notification via `NotificationService` that Google needs a 2FA re-login,
     **including a link that continues the workflow** (the user clicks it to have the engine trigger
     the 2FA push); (b) the user approves the 2FA on their device; (c) the engine waits up to **60s**
     for a successful 2FA (login-success signal); (d) if not successful within 60s, it sends **another
     notification prompting a retry**. The successful session is then cached in the profile for days.
4. **No credential + account creation allowed** (`ALLOW_AUTOMATED_ACCOUNTS` on + predefined set) →
   create an account from the predefined credential set, then `credentials.capture(...)`.
5. **Any impediment** (login fails, lockout, CAPTCHA, account-create blocked, Google bot-check) →
   **hold the sandbox as-is**, emit a descriptive pending action + notification with a **one-tap
   resume** link, and **pivot to the next application** (multi-task; never idle-wait). When the user
   fixes it in the held session, capture the working credential/session and **resume that thread**.

**Caveats (engineering reality, acknowledged):** 2FA itself cannot be auto-completed — it is the
60s notify→approve→retry hand-off above. Auto-typing a primary Google password with an automation
browser carries a real **account-flag/lockout risk**; the persistent-session reuse minimizes how
often a password is typed. The Google credential is a high-value secret (vault is libsodium-sealed).
Live Google-login automation can only be exercised in a real deploy (the sandbox MITMs TLS and Google
blocks datacenter automation), so this layer is built + unit/fixture-tested for logic; live
validation is the operator's, done carefully.

Open sub-decisions remaining: held-sandbox vs. concurrency-cap interaction (hold the slot for instant
resume vs. yield + re-provision), and the exact per-ATS "login success" signal.

## 6. Real-Workday navigation increments

- **Hydration**: `open()` waits for `networkidle` (and/or a Workday root selector like
  `[data-automation-id]`) before inspecting, with a bounded timeout + graceful fallback.
- **Apply entry**: detect + click the Workday "Apply" / "Apply Manually" / "Autofill with Resume"
  entry, landing on the sign-in/create-account modal. Add to a Workday step model.
- **Real selectors**: a Workday selector/step map keyed on `[data-automation-id]` for the canonical
  steps (Sign In / Create Account, My Information, My Experience, Application Questions, Voluntary
  Disclosures, Self Identify, Review → Submit). Thread ATS step knowledge into the *real* driver
  (today only the fake source consumes `ats.pages()`).
- **Step walking**: reuse `advance()` (Next/Continue + networkidle) plus per-step field detection +
  the existing fill/sensitive/essay/missing-attr policies, which already work once real fields are
  detected.

## 7. Phased delivery (each phase ships green + reviewed)

- **Phase 0 — local ATS fidelity fixtures.** DEFERRED (low priority, for later testing): a locally
  served HTML app approximating Workday/iCIMS for deterministic real-browser tests. Until then,
  hermetic `data:`-URL integration tests cover the real-DOM behaviors.
- **Phase 1 — live-DOM walking. DONE (PR #95, #96).** Hydration wait + "Apply" entry
  (`enter_application`) + account-gate recognition (`is_account_gate`, incl. sign-in/Google). Verified
  live: the engine drives the real NVIDIA Workday from posting → Apply → the Create-Account/Sign-In
  gate. Remaining: per-step field detection + step-walk refinement on the post-login form.
- **Phase 2 — credential auto-login (in progress).** Settings for the credential set (per-tenant ATS
  + Google) + `PrefillService` auto-login: direct email/password (fill+submit+detect), "Sign in with
  Google" via persistent session + stored creds, and the **2FA notify→continue→60s-wait→retry** flow
  (§5). Failure/any-impediment → hold+notify+pivot.
- **Phase 3 — account creation (gated).** The `ALLOW_AUTOMATED_ACCOUNTS` guard + `submit_account()`
  implementation + `capture()` into the vault + the `ACCOUNT_PREFILL → PREFILLING` conditional
  transition. Security-review ADR. CAPTCHA/verify still hand off.
- **Phase 4 — impediment handling + resume.** Hold-sandbox semantics, the one-click resume pending
  action/notification, `resume_after_login` that updates the credential store and continues the
  thread, and the multi-task pivot (reconcile with the concurrency cap).
- **Phase 5 — live validation.** End-to-end against a real Workday tenant in a real deploy (no TLS
  interception), with the review-before-submit gate intact.

## 8. Files in scope

`adapters/browser/page_source.py` (hydration, Apply, submit_account, Workday selectors) ·
`adapters/browser/ats.py` (real Workday step/selector map; share with the real driver) ·
`application/services/prefill_service.py` (credential retrieve/fill/login/create, impediment
hold+notify+pivot, resume_after_login) · `core/rules/prefill_boundary.py` +
`core/state_machine.py` (gated account-create transition + guard) · `app/config.py`
(`ALLOW_AUTOMATED_ACCOUNTS`, predefined-credential settings) · `app/routers/*` +
`workspace/routes/applicant_*` + `workspace/static/js/*` (Settings UI for the credential set;
resume endpoints) · `docs/adr/` (account-creation security ADR) · tests across unit/contract/
integration + the Phase-0 fixtures.

## 9. Open decisions for the user

1. **Predefined credential set** shape: one fixed email + generated per-tenant passwords? an email
   alias per tenant (`you+acme@…`)? where stored (vault under SYSTEM campaign)?
2. **Held-sandbox vs concurrency cap**: hold the slot for instant resume (cap counts held sessions)
   or yield + re-provision on resume (frees capacity, slower resume)? The requested "hold as-is for
   quick resumption" favors holding — confirm cap sizing.
3. **`ALLOW_AUTOMATED_ACCOUNTS` default** and whether account-creation needs per-run confirmation vs
   a one-time settings opt-in.
4. **"Login success" signal** definition (post-login URL/automation-id, absence of error) per ATS.
5. Scope of **non-Workday ATSes** for the first cut (Workday only, or iCIMS/Greenhouse fixtures too).
