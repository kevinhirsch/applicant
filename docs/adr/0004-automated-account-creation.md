# ADR-0004: Gated automated account creation (and the pre-fill-stop boundary change)

**Status:** Accepted (product direction: automate-by-default; supersedes the unconditional
"engine never creates accounts" stance for the account-create step only).

## Context

The original pre-fill-stop boundary (ADR-0001, FR-PREFILL-4) made the account-creation submit
an **irreducible human step** — the engine pre-filled fields but never created an account or
signed in. Operating the product as an autonomous job-application engine surfaced a hard
requirement: the user cannot sign in (or create an account) for **every** application. The
binding product principle is now **automate-by-default**: if a step *can* be driven
automatically, the engine MUST attempt it, and the human is escalated to **only** for genuinely
high-stakes or non-automatable steps.

For the account step that means: the engine logs in from a stored credential (already shipped),
and — where the user has opted in — **creates an account** from a user-defined predefined
credential set, banking the result in the vault for reuse. The steps that remain irreducible are
the ones the engine *cannot* safely produce: CAPTCHA/bot-challenges, and email/SMS verification.
Final-submit remains a deliberate review-before-submit trust gate.

## Decision

1. **`ACCOUNT_CREATE_SUBMIT` becomes conditionally allowed**, not unconditionally irreducible. It
   is permitted **only** when automated account creation is enabled, exactly as `FINAL_SUBMIT` is
   permitted only when the user has authorized engine submission. `CAPTCHA`, `EMAIL_VERIFY`,
   `SMS_VERIFY` stay unconditionally irreducible.
2. **The gate is server-derived, default OFF.** A new setting `ALLOW_AUTOMATED_ACCOUNTS`
   (env, default `false`) is wired into the browser adapter at construction; `submit_account()`
   passes it to `ensure_action_allowed(...)`. The decision is derived from server configuration —
   **never** from a caller/request input opting the safety check in (per CLAUDE.md). With the
   gate off, behavior is exactly as before (hand off at the account create step).
3. **Credentials are banked.** A created account's username/password is generated from the
   predefined set (a fixed email + a strong per-tenant generated password) and stored via the
   credential vault (`capture`, libsodium-sealed) so subsequent applications at that tenant log in
   automatically.
4. **Email/SMS verification still hands off.** If account creation triggers a verification step,
   the engine holds the sandbox and escalates (those remain irreducible).

## Consequences

- **Positive:** the engine can clear the account gate end-to-end where the user opted in, fulfilling
  "don't make me sign in for every application"; the boundary stays enforced in the core (no adapter
  can bypass it); off-by-default keeps the conservative behavior for anyone who hasn't opted in.
- **Risk / cost:** creating accounts (and, separately, auto-typing a Google password) on third-party
  ATSes carries account-flag/lockout and ToS risk; this is the user's explicit, opt-in choice. The
  predefined Google/account credentials are high-value secrets (vault-sealed). Live account creation
  cannot be exercised from CI (real ATS + bot defenses), so the flow is built + unit/fixture-tested
  for logic; live validation is the operator's, done carefully.
- **Unchanged guarantees:** review-before-submit (final submit needs explicit authorization),
  truthfulness, sensitive-field policy, and the CAPTCHA/email/SMS-verify hand-offs all stand.
