# Applicant — Deep Audit Round 3 (1,080 findings, twelve lenses)

> **The brief.** One more completely exhaustive pass, deeper and finer than the two before it,
> "until there are no more ideas." Twelve parallel auditors, each on a lens the prior rounds
> covered only at headline level (or not at all), each **deduped** against the 157 pixel-parity
> items (`APPLE_GENIUS_IMPROVEMENTS.md`), the 358 product items (`PRODUCT_EXHAUSTIVE_AUDIT.md` +
> `exhaustive/`), and everything Waves 1–2 already shipped. Every item is ranked
> `[VALUE · EFFORT]` with a verified `file:line` anchor. Full lists live in
> [`exhaustive2/`](./exhaustive2/); this is the overseer synthesis.
>
> **Cumulative corpus: 1,595 ranked suggestions** (157 + 358 + 1,080) across three rounds.

## Scoreboard

| # | Lens | Items | File |
|---|---|---|---|
| 1 | Micro-interactions & input mechanics | 97 | [`01_micro_interactions.md`](./exhaustive2/01_micro_interactions.md) |
| 2 | Copy & voice (line-by-line, before→after) | 281 | [`02_copy_voice.md`](./exhaustive2/02_copy_voice.md) |
| 3 | Performance & perceived speed | 72 | [`03_performance.md`](./exhaustive2/03_performance.md) |
| 4 | Failure paths & resilience | 78 | [`04_failure_paths.md`](./exhaustive2/04_failure_paths.md) |
| 5 | Accessibility deep pass | 70 | [`05_a11y_deep.md`](./exhaustive2/05_a11y_deep.md) |
| 6 | Mobile & responsive | 60 | [`06_mobile_responsive.md`](./exhaustive2/06_mobile_responsive.md) |
| 7 | Power users & extensibility | 59 | [`07_power_users.md`](./exhaustive2/07_power_users.md) |
| 8 | Dark engine capability matrix | 108 | [`08_engine_dark_matrix.md`](./exhaustive2/08_engine_dark_matrix.md) |
| 9 | Activation & the first 24 hours | 87 | [`09_activation_funnel.md`](./exhaustive2/09_activation_funnel.md) |
| 10 | Notifications & channels end-to-end | 58 | [`10_notifications.md`](./exhaustive2/10_notifications.md) |
| 11 | Settings & configuration | 60 | [`11_settings_config.md`](./exhaustive2/11_settings_config.md) |
| 12 | Help & self-explainability | 50 | [`12_help_selfexplain.md`](./exhaustive2/12_help_selfexplain.md) |
| | **Total** | **1,080** | |

---

## 1. The bug ledger — real breakage the audit caught (fix before features)

This round didn't just produce suggestions; it caught **functional and safety bugs**. Ranked by
gravity (anchors in the lens files):

**Safety / irreversibility**
1. A double-clicked "Authorize the assistant to finish" can physically click the employer's
   submit button **twice** — no busy/terminal state on the irreversible action (04, 01).
2. The chat agent's `app_api` loopback allowlists **all** of `/api/applicant/` — including the
   final-authorization remote paths — with no method fence; a stop-boundary soft spot (07).
3. The engine's MCP tool surface is mounted **unauthenticated** (read-only today, but ungated) (07).

**Silently broken features (wired-looking but dead)**
4. Follow-up + cautious-mode-pause notifications call notifier methods that **don't exist** —
   they have silently never been delivered (10).
5. Ghosting detection can never fire: `_submission_age` returns 0 — and `PostSubmissionService`
   has **zero call sites** anyway (triple-dark: migrated, built, never invoked) (08).
6. `applicantReachability.js` loads on every page; all three exports hit **404 proxy paths** (08).
7. The prod compose never feeds `.env` into the engine container — **~50 documented env vars are
   dead in production** (egress, sandbox backend, takeover desktop, log level…) (11).
8. `Campaign.schedule` is accepted, stored, and **never read** by the scheduler (07, 08).
9. Default quiet-hours settings suppress Discord/email **24/7** (time-independent evaluation) (10).
10. The CRITICAL notification urgency (built for overnight CAPTCHA waits) is **never emitted** (10).

**Hard funnel blockers**
11. **Non-admin users cannot complete OOBE step 1** — `/api/model-endpoints` is admin-gated (09).
12. The onboarding work-history/education `repeat:true` sections render **only one entry** —
    users cannot enter a second job (01, 09).
13. A failed LaTeX preview **permanently disables** the resume step's Continue (09).
14. The landing page never mentions job applications and offers **no path to `/login`** (09).
15. The redline diff renders as a collapsed, colorless blob — the workspace never defines the
    `.redline-add`/`.redline-sub` classes the engine's HTML depends on (06).

**Data loss & state races**
16. Portal refresh (`_load(true)`) wipes half-typed answers — including on an automatic 2FA-poll
    timeout mid-typing (01, 04).
17. Chat clears the composer before the request resolves; its Retry duplicates the user bubble (01).
18. Escape tears down the blocking OOBE overlay mid-form; on mobile the wizard is
    swipe-dismissible (01, 06).
19. A dead `DATABASE_URL` boots into non-persistent in-memory storage that `/healthz` reports
    as **ok** — the user is never told their data isn't persisting (04).
20. The timeout ladder is contradictory (30s proxy < 45s middleware < 600s handler): long research
    is structurally unable to succeed (04).
21. Notification delivery state is process memory — a restart drops every held push and re-sends
    the same-day digest (10).

**Smaller but real**
22. Compare's campaign picker duplicates its options on every reopen (01).
23. Per-channel quiet-hours choices are dropped by the proxy's body model; a configured channel
    can never be removed (11).
24. The Automation pane's Windows-VM picker can't actually switch sandbox backends (11).
25. Two contradictory hardcoded ghosting SLAs (14 vs 30 days) (11).
26. `new Notification()` throws on Android; a service worker is registered but web-push is absent (06).
27. Bearer API tokens pass applicant-route auth as a phantom, un-attributed user (07).
28. FR-requirement codes leak verbatim into a user-visible 409 error — a shipping white-label
    violation (12).
29. Keybind defaults disagree between runtime and the Settings panel (`ctrl+alt+b` vs `ctrl+b`) (07).
30. The expanded-sidebar Portal launcher is a click-only `<div>` — the home base is
    keyboard-unreachable in that mode; the final-submit confirm has no dialog role (05).

## 2. The nine systemic themes of round 3

1. **The last-mile pattern.** Engine read-models (detections, stealth posture, loop health, run
   stats, diagnostics) reach the workspace proxy and die for want of ~20 lines of JS each (08).
2. **Wired-looking but dead.** Compose not passing `.env`, no-op schedule fields, notifier calls
   to nonexistent methods, dead safety features — configuration and plumbing that *looks* alive
   and silently isn't (11, 10, 08, 07).
3. **No single narrator.** The agent speaks as "I", "we", "the assistant", and "Applicant" —
   sometimes in one sentence, worst at the highest-gravity moments. Five cross-cutting fixes
   (one pronoun, one error-text path, campaign→search, materials→documents, typography) resolve
   ~⅓ of 281 copy items (02).
4. **Data loss at the consent points.** Refresh races, composer clears, dismissible blocking
   overlays — typed input is destroyed exactly where trust is decided (01, 04).
5. **Boot & poll economics.** ~7.5 MB uncompressed text per boot, no gzip, blanket `no-cache`
   (~165 revalidations), fresh `httpx.AsyncClient` per proxy call, a badge that downloads the
   full payload for a count, unbounded digest re-scoring (03).
6. **The hollow alert last-mile.** No outbound message contains a usable link; Android
   notifications throw; no web-push; the badge lives on a rail mobile hides (10, 06).
7. **Assistive hollowness.** Zero live regions outside `#toast`; focus traps decay after first
   reopen; forced-colors has one rule in 36k lines (05).
8. **The help vacuum.** No help entry point, no user docs, no first-use education — and the chat
   assistant is explicitly forbidden by its own prompt from explaining the product (12).
9. **Power-user substrate exists, unconnected.** Scoped tokens, a 57-tool agent, HMAC webhooks,
   task scheduler, MCP — all shipped in the vendored workspace, almost none attributed, fenced,
   documented, or bridged to the engine (07).

## 3. Sequencing (how to eat 1,080 items)

- **First: the bug ledger** (§1) — ~30 items, mostly S/M effort, several safety-relevant.
  Nothing else in the corpus matters if the funnel blocks non-admins and ghosting can't fire.
- **Then: five keystone unlocks** that each convert dozens of items into small wiring tasks —
  (a) gzip + cache headers + eager-module diet (03); (b) one narrator + one error-text path (02);
  (c) the engine-preferences Settings pane over the existing zero-restart `app_config` pattern
  (11); (d) token owner-attribution + loopback method fence + MCP auth (07); (e) a
  `notify()` contract test that fails on nonexistent-method emits (10).
- **Then: the last-mile sweeps** — finish proxied-but-unrendered read-models (08), live regions +
  focus-trap repair (05), mobile redline/web-push (06), help scaffolding (12).
- **Per-item detail lives in the lens files**, each already ranked best-ROI-first.

---

*Round 3 of the exhaustive audit series. Prior: `APPLE_GENIUS_IMPROVEMENTS.md` (157, pixel
parity/HIG), `PRODUCT_EXHAUSTIVE_AUDIT.md` + `exhaustive/` (358, product). Cumulative: 1,595.*
