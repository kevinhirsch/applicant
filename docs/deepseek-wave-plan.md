# DeepSeek wave plan — every open issue, sequenced for 3 parallel tracks

All open issues grouped into **31 groups** across **14 dependency-ordered waves**. Run a
wave's groups in parallel (one per track: Engine / Front-door / Infra-Sec — different parts
of the tree, so isolated/serialized write agents don't collide), let them land, then advance.
Dispatch a wave with `/wave <NN>`. **Always reconcile against `git log origin/main` + open PRs
and drop closed issues before dispatching.**

> Snapshot 2026-06-29. ~~Struck~~ issues were closed after the plan was built (PRs #409–#413).

## Waves at a glance

| Wave | Track A · Engine | Track B · Front-door | Track C · Infra/Sec |
|---|---|---|---|
| W01 | `G20` | `G27` | `G19` |
| W02 | `G04` | `G08` | `G21` |
| W03 | `G14` | `G01` | `G06` |
| W04 | `G11` | `G02` | `G22` |
| W05 | `G13` | `G05` | `G30` |
| W06 | `G12` | `G03` | — |
| W07 | `G17` | `G10` | — |
| W08 | `G07` | `G09` | — |
| W09 | `G16` | `G25` | — |
| W10 | `G18` | `G26` | — |
| W11 | `G15` | `G28` | — |
| W12 | `G31` | `G29` | — |
| W13 | `G23` | — | — |
| W14 | `G24` | — | — |

## Groups and their issues

### Wave 01

**`G20` — Database: SQL models, migrations, JSONB, unique constraints, N+1, in-memory↔SQL divergence, boot fallback**  · _Engine track_
- #244: Alembic 0001_initial uses sa.JSON() not JSONB — schema mismatch with models
- #243: Missing unique constraints on SQL models — InMemory enforces uniqueness but SQL doesn't
- #242: AgentRunRepo N+1 queries: latest(), max_seq(), prune_old() all materialize entire table
- #241: InMemoryStorage commit() and rollback() are no-ops — hides transaction bugs in tests
- #245: Two dead columns in SQL models: JobPostingModel.normalized and GeneratedMaterialModel.redline_state
- #365: Testing: Alembic forward-migration data-integrity on a populated DB is untested
- #312: Engine silently falls back to in-memory storage when the DB is unreachable at boot (no warning)
- #169: Concurrent select-then-insert can raise UniqueViolation (app_config / tool_settings)

**`G27` — Dead code / orphaned files / unused assets cleanup**  · _Front-door track_
- #261: `frontend/` directory is confirmed deprecated but ships 60+ unused JS modules and duplicate fonts
- #262: `workspace/static/fonts/` has 7 font files — only 3 FiraCode are loaded; Inter fonts shipped but never declared
- #263: 5 workspace scripts are one-shot tools with zero cross-references — dead or undocumented maintenance burden
- #264: applicantPortal.js, applicantActivity.js, applicantUpdate.js may be orphaned — not loaded by index.html
- #255: `mcp_servers/_common.py` is orphaned — defines helpers that nothing imports
- #254: `services/faces/` package is entirely dead — zero imports anywhere in the codebase
- #253: `services/search/` is a dead duplicate of `src/search/` — 4 identical files wasting maintenance effort
- #256: 3 Inter font woff2 files (429KB) never loaded — no @font-face declarations in workspace CSS
- #270: _fetchJSON/esc/_toast duplicated identically across all 10 applicant JS modules — ~170 lines of boilerplate
- #265: 1.1MB style.css likely contains substantial dead CSS — needs PurgeCSS audit
- #358: Master tracking: remaining unaudited areas — BDD steps, webtop Dockerfiles, uv.lock, editor JS
- #257: `calendar/reminders.js` is orphaned — zero importers, reminder logic lives in notes.js instead

**`G19` — Config defaults & first-run friction: scheduler/LLM-rate/automated-accounts off, prod preset, env docs, python version pin**  · _Infra/Sec track_
- #185: SCHEDULER_ENABLED defaults to false — engine never auto-ticks out of the box
- #186: LLM rate limiting defaults to disabled (0) — no protection against runaway token spend
- #174: Default lane is entirely hermetic — 5 separate flags needed to make the engine do real work
- #175: ALLOW_AUTOMATED_ACCOUNTS defaults to false — unnecessary manual handoffs for returning users
- #406: 1.0: enable chat-continued onboarding by default — proactive essentials probe ON + document the minimal-wizard model
- #347: `.env.example` missing documentation for SECURE_COOKIES, MIND_BACKEND, SANDBOX_CONCURRENCY, and 3 others
- #349: `alembic.ini` has hardcoded-looking DB credentials as placeholder — misleading
- #348: Python version pinned to `<3.12` — can't run on Python 3.12+ without modifying lock
- #355: Engine and workspace Dockerfiles use different Python versions (3.11 vs 3.12) — mismatch

### Wave 02

**`G04` — Secrets exposure: vault/tokens/TOTP to LLM context, plaintext webhook token, key rotation, sensitive-attr leakage**  · _Engine track_
- #315: `manage_tokens` returns raw API token strings to LLM context
- #314: `vault_get` tool returns plaintext passwords and TOTP secrets to LLM context
- #313: `app_api` tool is a universal loopback with blocklist — any new endpoint is auto-reachable by LLM
- #356: `webhook_token` stored as plain text in DB — all other credentials are Fernet-encrypted or hashed
- #361: Security: credential vault has no key rotation or disaster-recovery path
- #222: _escalate_mapping LLM prompt includes ALL attribute names — sensitive attribute names visible to LLM

**`G08` — Input validation & typing: untyped intake/forms, path params, upload size limits, CORS parsing**  · _Front-door track_
- #318: `onboarding.py` `SaveSectionIn.data: dict` accepts completely untyped intake data
- #319: `model_endpoints.py` `add_endpoint` takes 5 raw `Form(...)` params including `api_key` — no Pydantic model
- #320: All path parameters are bare `str` — no format validation, no length limits, no pattern matching
- #322: No file upload size limits on any upload endpoint — disk exhaustion risk
- #346: CORS `ALLOWED_ORIGINS` env var parsing fragile — no URL validation, trailing whitespace from split

**`G21` — Testing & CI infrastructure: e2e pipeline test, JS harness, tautological/xfail guards, self-hosted runner, skip accounting**  · _Infra/Sec track_
- #364: Testing: no end-to-end test of the discovery→score→digest→prefill→submit pipeline
- #366: Testing: no JS test harness for the front-door (node --check only)
- #373: BDD: `assert True` tautology in `no_cli` step — never verifies zero-CLI requirement
- #276: BDD step `test_p0_steps.py:121` asserts `assert True` — tautological no-op guardrail
- #275: `pytest.xfail()` inside test body hides real failures — ATS dryrun test goes green on browser failure
- #284: `ensure-submittable` POST test only checks status_code==200 — never verifies submittability in response body
- #278: CI uses `runs-on: self-hosted` with no hosted fallback — all PRs blocked if runner goes offline
- #277: CI uses `python` not `uv run python` for compileall — runs against system Python, may miss syntax errors
- #181: 113 integration tests always skip — external boundary code paths never exercised in CI
- #200: docs/delivery-status.md undercounts integration-gated skips — claims 14, actual is ≥15

### Wave 03

**`G14` — Durable orchestration, checkpoints, state machine integrity, graceful shutdown, per-tick state**  · _Engine track_
- #218: Checkpoint shim has no corruption detection — corrupted JSON checkpoint silently returns stale/empty data
- #219: No disk-full handling in checkpoint shim — write fails silently, workflow loses progress
- #220: Two concurrent ticks on the same workflow_id could race on checkpoint writes
- #221: Workflow crash during teardown step leaves sandbox orphaned — no cleanup retry
- #189: Hardcoded 10-year timeout for DBOS approval recv gate — not configurable
- #316: No graceful shutdown — in-flight workflows abandoned, sandboxes leaked, no checkpoint flush
- #180: AgentLoop per-tick rebuild is fragile — per-instance state silently resets
- #198: _force_status bypasses state machine — dataclasses.replace(app, status=to) with zero validation
- #183: Container marked FROZEN — no enforcement mechanism

**`G01` — Front-door XSS & HTML-output escaping (workspace JS innerHTML sinks)**  · _Front-door track_
- #397: [security] Image EXIF GPS coordinates interpolated raw into the gallery detail panel (defense-in-depth escaping)
- #395: [security] Version-history summary/source injected raw into innerHTML (the diff sibling is escaped) — stored XSS
- #391: [security] Document title injected raw into the tab bar (no HTML-escaping) — XSS via email subject / agent / shared title
- ~~#384: [security] Received-email HTML rendered verbatim into innerHTML in the document email composer (XSS)~~ (closed)
- ~~#389: [security] Email reader uses a denylist sanitizer, re-parses sanitized HTML (mXSS), and leaks read-receipt beacons via inline style url()~~ (closed)
- #354: `chatRenderer.js` — 47 innerHTML from LLM output, markdown rendering may pass raw HTML (XSS risk)
- #353: `research/panel.js` (24 catches) + `research/jobs.js` (9 catches) — research failures silently swallowed, scraped HTML rendered unsanitized
- #378: [MEDIUM] layer-panel.js, history-panel.js: Partial HTML escaping — missing quote escaping for attribute safety
- #377: [MEDIUM] build/controls.js: Unescaped values in innerHTML template — fragile XSS risk
- #357: Audit: 34 editor/ JS files — AI image editor, ~18 silent catches, ~31 innerHTML (tracking)

**`G06` — Docker & build supply-chain hardening (non-root, digest pinning, integrity, key fingerprints)**  · _Infra/Sec track_
- #167: Security: actions/checkout persists Git credentials on the runner
- #164: Security: remote binaries/archives fetched without integrity verification
- #161: Security: Docker containers run as the default root user
- #160: Security: base Docker image uses a mutable tag (supply-chain risk from auto-upgrades)
- #375: Docker: CUA driver installer piped from remote URL to bash — no integrity verification
- #374: Docker: all base images use mutable tags — no digest pinning, builds not reproducible

### Wave 04

**`G11` — Engine pre-fill loop robustness: silent failures, crash recovery, health checks, no-error strands**  · _Engine track_
- #335: `_safe_teardown()` silently swallows browser teardown failures — can mask root cause
- #336: No browser crash recovery — TimeoutError/TargetClosedError propagate uncaught from prefill loop
- #207: No browser health check anywhere in the prefill loop — browser crash escapes unhandled
- #205: _fill_field exception handler skips page_log and sensitive audit trail — PrefillResult omits failed field entirely
- #204: _capture_credential fails silently with bare `pass` — freshly created account credentials are lost
- #203: store.retrieve() per-scope exceptions silently skip ALL credential scopes — login fails silently
- #211: LLM escalation failures silently degrade EVERY unmapped field — no 'LLM unavailable' diagnostic event
- #212: _settle() swallows Page.wait_for_load_state timeout — proceeds with empty DOM
- #208: chained attribute access on current_state() → AttributeError if browser returns None
- #223: _try_log_in exception indistinguishable from wrong password — browser crash vs auth failure conflated
- #202: _lookup_credential silently swallows tenant_of() failures — application strands with no error
- #177: No ATS detection on pre-fill failure — silent garbage when ATS can't be filled
- #210: _lookup returns FIRST matching attribute — no priority system, LLM non-determinism amplifies it
- #209: _is_screening_question classifies by word count (≥6) — misclassifies data fields as essay questions
- #206: _lookup matches on label only, not attribute.is_sensitive — false negatives in sensitive field detection

**`G02` — Web hardening: CSRF, CSP, SRI, secure cookies, tabnabbing, headers**  · _Front-door track_
- #383: [security] CDN scripts loaded without Subresource Integrity; CSP style-src still allows 'unsafe-inline'
- #386: [security] target="_blank" anchors missing rel="noopener" (reverse-tabnabbing stragglers)
- ~~#381: [security] No CSRF protection on cookie-authed state-changing /api/* routes (front-door)~~ (closed)
- #268: CSP script-src allows cdn.jsdelivr.net — third-party CDN supply-chain risk
- #269: Session cookie may lack Secure flag — no explicit `secure=True` in auth route

**`G22` — Deploy/ops scripts: install/update/proxmox credential & backup & rollback safety**  · _Infra/Sec track_
- #283: `install.sh` re-generates credentials if .env deleted — incompatible with existing Postgres volume
- #282: `update.sh` has no backup rotation — disk fills indefinitely with daily backups
- #281: `install.sh` `git pull --ff-only || true` swallows ALL pull failures silently
- #280: `proxmox-deploy.sh` leaks DB password on command line — visible in /proc and `ps aux`
- #279: `update.sh --rollback` only restores DB, NOT code/images — rollback incompatible with new code

### Wave 05

**`G13` — Browser / Chrome / stealth: version probe, swiftshader flag, session leak, profile race, fake↔real divergence**  · _Engine track_
- #215: PINNED_CHROME_MAJOR = 124 is stale — probe often fails in containers, causing detectable UA incoherence
- #216: ProfileStore.for_tenant() visit_count increment is a race condition
- #217: PatchrightBrowser._sessions grows unbounded — no close/dispose, memory leak per application
- #337: FakePageSource ≠ PlaywrightPageSource behavioral divergences — real pre-fill paths untestable
- #338: `--enable-unsafe-swiftshader` flag removed in Chrome 125+ — may crash newer Chrome
- #339: `_on_response` status capture has no timestamp — can't correlate response sequence with prefill actions
- #340: Chrome version probe only checks `google-chrome-stable`, `google-chrome`, `chrome` — misses container Chrome paths

**`G05` — Path traversal / file inclusion / SSRF**  · _Front-door track_
- #163: Security: potential file-inclusion / path-traversal via unsanitized file reads
- #251: `_serve_html_with_nonce` has no path containment check — latent path traversal risk
- #310: Security: scraped-URL SSRF guard doesn't cover redirect / subresource hops

**`G30` — Observability & diagnostics: loop metrics/tracing/alerting, startup healthcheck report, generic 500 handler**  · _Infra/Sec track_
- #362: Observability: no metrics/tracing/alerting on the 24/7 loop — silent degradation can run for days
- #188: No startup healthcheck report — silent degradation when binaries are missing
- #252: No generic unhandled exception handler — crashes become opaque 500s with no logging enrichment

### Wave 06

**`G12` — ATS adapters & form-fill correctness: shells, fall-through, dropdown/option matching, SPA hydration**  · _Engine track_
- #171: Greenhouse and Lever ATS adapters are shells — only 3-8 fields modeled vs Workday's full flow
- #173: Unknown ATS falls through to Workday — guaranteed to fail on unsupported ATS forms
- #214: Workday ATS model is exactly 6 fixed pages — real Workday tenant forms vary widely
- #224: PageSource Protocol missing submit_account — FakePageSource and PlaywrightPageSource diverge in behavior
- #225: Dropdown/combobox matching has ZERO fake-model coverage — all real dropdown logic untested in CI
- #226: _pick_visible_option not scoped to opened dropdown — could match options from a DIFFERENT dropdown
- #227: No handling of paginated/async dropdown options — target option may not be in DOM yet
- #341: SPA DOM hydration race in `advance()` end-detection — could skip pages or retry incorrectly
- #342: Dropdown Escape cleanup may operate on detached element after option-selection navigation
- #343: `_filter_query` uses first 2 words only — fails for long option names with shared prefix
- #213: FakePageSource.is_account_gate() ≠ real behavior — fake only checks for account-create, real checks for sign-in too

**`G03` — Access control & auth: privilege checks, impersonation, unattributed engine access, error/state leakage**  · _Front-door track_
- #267: Internal-tool/engine impersonation via X-Applicant-Owner header gated only on user existence, not admin
- #266: INTERNAL_TOOL_TOKEN auto-generates at startup — internal-tool bypass is always active, no disable flag
- #231: Workspace `/api/applicant/features` endpoint is unauthenticated — leaks engine configuration state
- #230: Unattributed engine callback access — 'internal-engine' user can access all owner data
- #228: _require_admin skips loopback check — unauthenticated access to admin/ops routes in unconfigured mode
- #311: Security: require_privilege fails open on unknown privilege keys
- #229: Engine raw error detail exposed to browser — 5xx tracebacks and internal errors leaked in 9 route files
- #317: Engine chat responses forwarded unscrubbed to browser — internal IDs and state may leak

### Wave 07

**`G17` — Discovery & learning flywheel: cross-run dedup, per-board rate limit, feedback loop, scoring defaults, memory backends**  · _Engine track_
- #196: Cross-run deduplication gap — embedding dedup only within a single discovery run
- #195: No per-job-board rate limiting — only campaign-level throughput caps
- #237: `feature_stats` is accumulated but NEVER read — approve/decline feedback loop is open
- #238: `record_converting_role` is dead code — Phase-1 conversion centroid never populated
- #239: `score_for_digest` cache key ignores learning state — scores stale by up to 20% after conversions
- #344: Scoring neutral-positive default 0.75 when no criteria set — viability gate wide open at cold start
- #345: `_parse_json_loose` silently returns dict without `score` key — falls back to embeddings with no log
- #306: Self-improvement learning flywheel: induce workflows (AWM) + curate playbook (ACE) + reflect (Reflexion)
- #307: Evaluate a vendor-able agent-memory backend (mem0 / Letta / Graphiti) behind the memory port

**`G10` — Silent failures — workspace JS (empty .catch / swallowed dynamic imports)**  · _Front-door track_
- #334: Workspace JS: 11 audited modules with 200+ silent catch blocks — systemic silent failure, ~60 modules remain
- #331: `document.js` — 28 TODO/FIXME/HACK markers, 19 empty catches, 6 localStorage without try/catch
- #330: `assistant.js` — `applicantChat.js` dynamic import failure silently swallowed — applicant chat section broken with no feedback
- #329: `emailInbox.js` — 8 dynamic `import('./ui.js')` failures with empty catch — complete loss of error feedback
- #328: `notes.js` — 16 `.catch(() => {})` on note mutations — users think save/delete succeeded when it failed
- #327: `chat.js` — bare `JSON.parse()` on stream chunk data, no try/catch — crashes on malformed JSON
- #352: `cookbookRunning.js` — 10+ `/api/shell/exec` calls, `powershell -Command` via SSH, shell eval, 42 silent catches

### Wave 08

**`G07` — Pre-submit safety: scam/ghost-job detection, duplicate-apply cooldown, per-company cap, eligibility filter, captcha**  · _Engine track_
- #367: Safety: no scam/ghost-job detection before auto-applying — user PII blasted at fake listings
- #368: No duplicate-application / re-apply cooldown guard — agent can apply to the same role twice
- #371: No per-company application volume cap — risk of spamming / getting blacklisted by one employer
- #369: Eligibility: captured work-authorization is never used to filter ineligible (sponsorship/clearance) postings
- #350: CaptchaSolverPort: behavioral-avoidance + solver-service + human-handoff (opt-in), tied to #305
- ~~#360: Security: scoring/tailoring LLM ingests scraped job text with no prompt-injection guard~~ (closed)

**`G09` — Silent failures — workspace Python (bare except sweep)**  · _Front-door track_
- #333: Workspace source: 15 files with 400+ bare `except Exception:` blocks — systemic silent failure
- #332: Workspace routes: 19 files with 400+ bare `except Exception:` blocks — systemic silent error swallowing
- #326: `bg_jobs.py` — corrupted job state file silently resets queue to empty
- #325: `ai_interaction.py` — 15 bare excepts; memory vector add/remove/delete fail silently
- #324: Workspace `agent_loop.py` — 5 silent `except Exception: pass` in main agent loop
- #323: `builtin_actions.py` — 6 `except Exception: pass` + `shell=True` subprocess (26 total bare excepts)
- #246: material_service.py: 29 bare `except Exception:` blocks — entire generation pipeline can silently fail
- #240: `_close_conversion_loop` swallows all exceptions silently — conversions permanently lost

### Wave 09

**`G16` — Post-submission lifecycle: outcomes, rejection/ghost detection, follow-up, snapshot, portfolio attachments**  · _Engine track_
- #190: No post-submission lifecycle — application tracking ends at submit
- #191: No rejection detection — no email scanning or ATS status polling
- #192: No ghosting/silence tracking — no SLA or no-response detection after submission
- #193: No automated follow-up emails — can't send thank-you or check-in messages
- #372: No durable per-application submission snapshot (exact answers + materials sent)
- #197: No portfolio/attachment management beyond resume and cover letter

**`G25` — Reachability gaps: backend-ready endpoints with no proxy/JS/nav consumer**  · _Front-door track_
- #405: Reachability: review-gate ensure-submittable has no front-door proxy/JS (engine enforces server-side)
- #404: Reachability: /criteria/{id}/learned (apply_learned_adjustment) has no front-door proxy/client
- #403: Reachability: chat-proposed criteria refocus can't be committed (no proxy/client for /chat/confirm-criteria)
- #402: Reachability: rendered digest-email HTML preview has no JS consumer
- #401: Reachability: digest "deliver now" endpoint has no JS consumer (backend-ready)
- #201: README claims 9 surfaces are reachable via proxy→JS→nav — only 5 have APPLICANT_SECTIONS wiring
- #199: 4 'live' dormant surfaces have no front-door feature gating — two-layer contract broken
- #287: Workspace email has Applicant digest/feedback routes but zero JS consumers — email surface is dead for Applicant
- #259: Orphan workspace route file: `/api/applicant/research/*` has zero JS consumers
- #258: Orphan workspace route file: `/api/applicant/email/*` has zero JS consumers
- #260: Missing HTML element `tool-email-btn` — email toolbar launcher can never be activated

### Wave 10

**`G18` — Resume/cover rendering & fonts: stubbed TeX/LibreOffice, aggressiveness slider, ATS-parse self-check, phone parse, i18n**  · _Engine track_
- #178: TeX and LibreOffice rendering stubbed — no real PDF output without binaries on PATH
- #187: Resume aggressiveness tuning control is greyed out — slider exists, does nothing
- ~~#400: FR-FONT-1: base-résumé upload doesn't prompt to install missing fonts (detect exists, not wired into the journey)~~ (closed)
- #370: Verify the generated résumé actually parses through an ATS before sending (output self-check)
- #170: Résumé parser drops the leading ( from a parenthesized phone number
- #194: US/English hardcoded — phone parsing, salary, EEO, ATS labels are all US-centric
- #250: Zero i18n infrastructure — all 800+ user-facing strings hardcoded English

**`G26` — Front-door feature integrations & dormant-surface wiring (calendar, email, gallery, tasks, compare, multi-campaign, chat-steering)**  · _Front-door track_
- #290: Feature: Chat-driven campaign control — bidirectional assistant steering
- #291: Feature: Email integration — two-way Applicant email workflow
- #292: Feature: Calendar integration — engine creates events, reads availability
- #293: Feature: Document library integration — Applicant materials as first-class documents
- #294: Feature: Memory/skills/recall — bridge as default, two-way learning loop
- #295: Feature: Tasks integration — pending actions as task system
- #296: Feature: Gallery integration — Applicant screenshots and materials as gallery collections
- #297: Feature: Compare surface — wire up cross-entity comparison
- #298: Feature: Local LLM tier delegation — smart routing between local and cloud endpoints
- #299: Feature: Research integration — company/role deep research before applications
- #301: Feature: Settings surface — unified campaign + engine configuration
- #303: Remove: Notes integration with Applicant — explicitly descoped
- #304: Remove: Cookbook integration with Applicant — explicitly descoped (except local LLM tier)
- #184: Compare surface is present-but-disabled — zero engine backing
- #176: Multi-campaign UI switcher is dormant — backend works but frontend is greyed out
- #273: `applicant-suggested-card` is always hidden — AI-suggested attribute learning surface never shown
- #274: Settings tabs 'notifications', 'fonts', 'sandbox' load renderers from applicantOnboarding.js — but those host divs are hidden inside index.html comments about migrated setup
- #271: OOBE wizard is only 3 steps — README's described notification/fonts/sandbox steps are in Settings, not OOBE
- #289: Document library stores Applicant resumes but resume-variant selection is engine-side only — no cross-surface visibility
- #288: Calendar integration is read-only — engine can detect interviews but can't create calendar events
- #182: Chat-driven steering is incomplete — chatbot reports state but can't control the system
- #286: Memory/skills/recall defaults to `in_memory` — workspace memory UI is invisible to the engine unless `MIND_BACKEND=bridge`

### Wave 11

**`G15` — Notifications: delivery reliability, race/locking, escalation floor, quiet hours, ntfy push**  · _Engine track_
- #233: `send_email` dedup key written BEFORE dispatch — failed SMTP delivery permanently loses digest email
- #234: Single failed Discord/SMTP delivery crashes entire scheduler tick — all ladder escalations lost
- #235: No lock on AppriseNotifier._sent dict — data race between scheduler advance and API expire
- #236: Notification escalation email_timeout floor only applies via configure() — constructor bypass allows 0s instant-email
- #172: Notification quiet hours not implemented — all notifications fire 24/7
- #302: Feature: Notification quiet hours — time-based notification suppression
- #300: Feature: Push notifications via ntfy — urgent action alerts with deep links

**`G28` — Accessibility: focus trap/restore, Escape-to-close, dialog ARIA, labels, button types, reduced-motion**  · _Front-door track_
- #394: [LOW] Status-strip pulse animation ignores prefers-reduced-motion
- #393: [LOW] Glyph-only close buttons rely on title= instead of an accessible aria-label
- #388: [MEDIUM] Visible s in the Applicant forms are orphaned — only a handful associate to their control via for/id
- #385: [MEDIUM] Dialog ARIA missing on 6 of 8 Applicant overlays — no role="dialog" / aria-modal / accessible name
- #382: [HIGH] No Escape-to-close on any dismissible Applicant modal
- #380: [HIGH] No focus trapping in Applicant modals — Tab escapes every overlay, including the blocking OOBE wizard
- ~~#379: [HIGH] Applicant modals don't manage focus — no focus-into-dialog on open, no focus restore on close~~ (closed)
- #249: ~200 `` elements missing `type='button'` — risk accidental form submission
- #247: 800+ inputs use placeholder-as-label — only 5 explicit `` associations in entire app

### Wave 12

**`G31` — Misc correctness & data-governance: context-error false positive, PII retention/erasure, JSON-loose parse**  · _Engine track_
- #285: `_is_context_error` false positives — any response containing the word 'context' triggers context-overflow handling
- #363: Data governance: no PII/résumé/credential erasure or retention policy

**`G29` — Front-door UX/perf bugs: double-submit guards, stale-response/sequence guards, render-blocking CSS, iframe sizing, loader timeout**  · _Front-door track_
- #398: Render-blocking 1.1MB style.css loaded synchronously in <head>
- #396: Mark-submitted action leaves the triggering button enabled (double-submit)
- #392: Digest feedback/survey actions are not re-entry guarded (double-submit)
- #390: Save-run-settings button has no in-flight disable (double-submit)
- #387: Stale-response/sequence guard missing on panel re-renders (fast switches paint the wrong campaign)
- #399: Live-session takeover iframe capped at 480px (letterboxed on mobile)
- #232: `list_campaigns` has no isinstance guard — engine shape change would crash frontend silently
- #248: 5-second loader timeout removes loader regardless of app load state — blank page on failure

### Wave 13

**`G23` — Computer-use (FR-CUA) & agent-intelligence (FR-MIND): self-use desktop, tool registry, context mgmt, integration legs**  · _Engine track_
- #179: Desktop assist (FR-CUA) is fully built but inoperable — locked behind sandbox image bake
- #141: FR-CUA: autonomous loop should self-use desktop assist for off-page steps (file-upload dialogs)
- #142: FR-CUA: reconcile cua-driver MCP tool names/arg schemas against the real binary (integration leg)
- #144: FR-MIND-6 / FR-CUA-2: expose memory/skills/recall + desktop as agent-callable tools in the loop
- #145: Integration verification: MIND_BACKEND=bridge end-to-end + real cua-driver smoke
- #143: FR-MIND-8: engine context management — turn compression + provider prefix-cache

### Wave 14

**`G24` — Autonomy epics & research spikes: plan-as-data, Skyvern parity, MCP server, eval harness**  · _Engine track_
- #305: Epic: plan-as-data execution — typed-DSL planner over a semantic DOM (camoufox), all surfaces
- #351: Epic: Skyvern parity — close every autonomous form-filling capability gap
- #308: Expose the engine as an MCP server (fastapi_mcp) + adopt MCP reference tools
- #309: Browser-agent eval harness (AgentLab + BrowserGym) for the pre-fill planner
