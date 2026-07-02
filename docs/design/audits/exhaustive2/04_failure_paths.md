# Failure Paths & Resilience — Applicant error-taxonomy audit (lens 04, exhaustive2)

> **Lens.** Every failure path, end to end: engine down mid-action, session expiry mid-flow,
> restart-lost state, double-submit/idempotency, poll-vs-action races, partial payloads,
> abandoned long ops, dropped live views, stale caches, two-tab duplication, storage corruption,
> clock skew, honest surfacing of the engine's own degraded modes, mid-tick DB loss, sandbox
> launch failures, notification delivery failures, and the install/update recovery story —
> plus the engine-side swallowed-exception inventory, retry policies, and dead-letter handling.
>
> **Dedup.** Excludes what `PRODUCT_EXHAUSTIVE_AUDIT.md` + `exhaustive/quick-wins-cross-cutting.md`
> already shipped or listed: `_fetchJSON` now has a 15s AbortController timeout + `errText` 401-vs-
> down taxonomy + `errorHTML`/`wireRetry` retry buttons + `pollVisible` hidden-tab pause
> (`applicantCore.js:31-158`). Findings below are new failure paths on top of that baseline.
>
> Format: `N. **Title** — [VALUE: high|med|low · EFFORT: S|M|L] — failure scenario + file:line.`

---

## Tier 1 — Degraded modes the user is never told about (honesty failures)

1. **In-memory storage fallback passes the health probe as "ok"** — [VALUE: high · EFFORT: S] — When the DB is unreachable at boot the container silently degrades to `InMemoryStorage(is_fallback=True)` (`src/applicant/app/container.py:210-243`), but `/healthz` treats `engine is None` as a *satisfied* check (`checks["database"] = "in-memory"`, `ok` stays `True` — `src/applicant/app/main.py:140-150`). A prod box with a typo'd `DATABASE_URL` reports 200-healthy, the install/update heartbeat goes green, and every application, approval, and credential the user creates evaporates on the next restart. The fallback marks itself unhealthy via `storage.healthcheck()` (#312, `lifespan.py:273-280`) — but only into a log line, and `/healthz` never consults it on the no-engine path.

2. **Non-persistent fallback is surfaced only as a server log — never to the user** — [VALUE: high · EFFORT: M] — The one place the "running on non-persistent in-memory storage; data will NOT survive restart" truth exists is a `log.warning` at boot (`src/applicant/app/lifespan.py:273-280`). No engine endpoint, no workspace proxy, no Portal banner, no Settings health row carries it. The owner types their profile, vault secrets, and campaign config into a box that will forget everything, with zero in-product signal. Surface `storage.healthcheck()`/`is_fallback` through setup-status → `applicant_features.py` → a persistent front-door banner.

3. **Boot-time capability report (stub résumé renderer / stub browser) is unreachable from the front-door** — [VALUE: high · EFFORT: M] — `build_capability_report()` (`src/applicant/app/capability_report.py:49-99`) knows when TeX+LibreOffice are absent ("renders a stub") or the automation browser is missing, but no workspace route or JS ever reads it (zero references under `workspace/`; `workspace/ROADMAP.md:19` admits degraded-state reporting is a TODO). A deployed image missing a layer looks fully healthy in the UI until a résumé renders blank or pre-fill silently does nothing — exactly the deploy hazard the report was built to name.

4. **Total discovery outage is indistinguishable from a quiet job market** — [VALUE: high · EFFORT: M] — Every discovery source catches *all* exceptions, logs `discovery_source_failed`, and returns `[]` (`src/applicant/adapters/discovery/jobspy_searxng.py:262-264`, `:292-296`, `:345-347`). If the bundled search service container is down or every board blocks the box, a run "succeeds" with 0 postings; the digest says nothing was found and the user concludes the market is dead. Per-run, count sources-failed vs sources-ok and surface "3 of 4 job sources couldn't be reached" in the digest/Activity instead of a silent empty.

5. **LaTeX path silently degrades to a source-estimate stub PDF** — [VALUE: high · EFFORT: M] — In `render_mode="auto"`, a missing TeX engine (or an aborted first-run font-cache build) makes the compile silently fall back to the approximate preview (`src/applicant/adapters/resume_tailoring/latex_tailor.py:84-99`, degradation described at `:111-116`); the Dockerfile's TeX cache warm-up is best-effort `|| true` (`docker/Dockerfile:136-137`). The user reviews and approves a document believing it is the real render. Flag stub-rendered artifacts on the review surface.

6. **Engine blip ⇒ every nav section falsely reads LOCKED** — [VALUE: high · EFFORT: S] — When `engine_available_sync` returns `False`, `compute_features` leaves `status=None` and `_section_state` returns `STATE_LOCKED` for *every* section (`workspace/src/applicant_features.py:291-292`, `:330-334`) — a 5-second engine restart makes the whole product look un-set-up (locked = "finish setup"), not offline. The docstring even promises a degrade-to-`configured` state (`:19-22`) that is unreachable because `STATE_CONFIGURED` requires a non-None status (`:300-303`). Distinguish "engine unreachable" from "not configured" in section state.

7. **Interview-calendar callback failure silently empties the assistant's context** — [VALUE: med · EFFORT: S] — Any failure of the workspace `calendar_interviews` callback degrades to `""` (`src/applicant/application/services/chat_service.py:891-896`), so with the workspace down (or token mismatched) the chat assistant simply doesn't know about scheduled interviews and answers as if there are none — a silent wrong-answer mode, not an error.

8. **Research callback lost outright on one failed HTTP attempt** — [VALUE: med · EFFORT: M] — `run_research` catches `WorkspaceError` and returns `None` with only a warning (`src/applicant/application/services/research_service.py:170-176`), and the engine→workspace client has no retry/backoff — one `httpx.Client` attempt per call (`src/applicant/adapters/workspace/http_workspace_client.py:105-117`). A momentary workspace restart permanently loses the deep-research enrichment for that posting with no re-queue and no user-visible trace.

---

## Tier 2 — The proxy/transport layer (engine down mid-action)

9. **`ApplicantEngineClient` has zero retry policy — one dropped packet fails a user action** — [VALUE: high · EFFORT: M] — `_request` issues exactly one attempt and converts any `httpx` error to `EngineError` (`workspace/src/applicant_engine.py:185-198`). For idempotent GETs (portal list, status, features) a single transient reset surfaces as "engine offline" to the user. Add a 1-retry-with-jitter for safe GETs (never for consequential POSTs — see #12).

10. **Deep-research run is cut off by the generic 30s read timeout** — [VALUE: high · EFFORT: S] — `research_run` uses the client-wide `httpx.Timeout(read=30.0)` default (`workspace/src/applicant_engine.py:46`, `:824-826`) while the workspace's own internal handler accepts a 30–600s budget (`workspace/routes/applicant_internal_routes.py:849`); the documents route already models the fix with a per-call 120s override (`workspace/routes/applicant_documents_routes.py:53`). A legitimate multi-minute research run reliably surfaces as a timeout error after 30s — long-op abandonment by design.

11. **Engine's own research callback is killed at 45s by the workspace request-timeout middleware** — [VALUE: med · EFFORT: S] — The 45s `_RequestTimeoutMiddleware` exempts `/api/applicant/research` but not `/api/applicant/internal/research` (`workspace/app.py:133-158`, exempt list `:137`; handler `applicant_internal_routes.py:806`), and the engine's HTTP read cap is 30s anyway (`http_workspace_client.py:44`, `:178-180`). Three different timeouts (30s client, 45s middleware, 600s handler budget) guarantee the longest-running feature dies at the shortest one.

12. **Consequential POSTs are pass-through with no idempotency key** — [VALUE: high · EFFORT: M] — `authorize-engine-finish`, `submit-self`, `pause`, approve/resolve all forward verbatim (`workspace/routes/applicant_remote_routes.py:194-211`, `applicant_ops_routes.py:234-254`). If the *response* is lost (proxy timeout after the engine committed), the UI shows an error, the user retries, and the engine receives the terminal action twice. An `Idempotency-Key` header minted client-side (or engine-side already-in-state guards, see Tier 4) is the fix for the one action that "cannot be undone."

13. **Engine-down maps to 503 on some proxies and 502 on others** — [VALUE: low · EFFORT: S] — The identical transport failure returns 503 from ops/portal/research/control (`applicant_ops_routes.py:101-105`, `applicant_portal_routes.py:108-112`) but 502 from documents/remote (`applicant_documents_routes.py:117-127`, `applicant_remote_routes.py:79-88`). Client code (and any future retry logic) can't branch reliably on status; pick one and standardize.

14. **Raw engine error bodies are forwarded verbatim to the browser** — [VALUE: med · EFFORT: S] — `_safe_detail` returns up to 500 chars of the engine's error body (`workspace/src/applicant_engine.py:114-117`) and `soft_degrade`/`_engine_http_error` expose it as the user-facing `message` (`:947-955`; `applicant_ops_routes.py:109`). An engine 422 with a validation traceback fragment or internal field names leaks straight into product copy. Map known statuses to plain language; log the raw detail server-side only.

15. **`/api/applicant/features` does 3 uncached blocking engine calls per nav render** — [VALUE: med · EFFORT: M] — `compute_features` re-probes health + two GETs on every call with no memoization (`workspace/src/applicant_features.py:330-348`), each with a 30s read budget (`applicant_engine.py:895-944`). A slow (not down) engine makes the *nav-gating* endpoint the slowest thing on every page load, and a hung engine stalls section rendering. Cache for 15–30s with a stale-while-revalidate.

16. **First-run ops controls are reachable unauthenticated from loopback** — [VALUE: med · EFFORT: S] — When auth is unconfigured, `_require_admin` returns `""` for any 127.0.0.1 caller (`workspace/routes/applicant_ops_routes.py:73-82`), opening update-trigger / run-config / pause-all to any local process during the setup window. Failure mode: a co-resident container or script triggers a self-update mid-OOBE.

17. **Static files are served non-atomically — a mid-write module is served truncated** — [VALUE: low · EFFORT: S] — `_RevalidatingStatic` re-reads `.js/.css` bytes per request with no size/atomic-swap guard (`workspace/app.py:415-431`). Anyone editing in place on a live box (the documented no-restart dev flow) can serve a half-written ES module, which fails import and takes the whole SPA surface down until reload. Mitigated in prod by container recreation; unmitigated in the documented dev loop.

---

## Tier 3 — Install / update / stack failure recovery

18. **Update: migrate succeeds, restart or heartbeat fails ⇒ half-updated stack with manual-only rollback** — [VALUE: high · EFFORT: M] — Auto-rollback fires *only* when `alembic upgrade head` itself fails (`scripts/update.sh:333-341`). If migration succeeds but `docker compose up -d` (`:354`) or the post-update heartbeat (`:363-366`) fails, the new schema is live under old/mixed containers and the script just prints "run --rollback" and exits 1. The window where the DB is ahead of the code has no automated recovery.

19. **Update smart-skip can deploy new code onto an old schema** — [VALUE: high · EFFORT: S] — `RUN_MIGRATE` is set only when the git diff touches the hardcoded `src/applicant/adapters/storage/alembic/versions/` path (`scripts/update.sh:250`). A migration created anywhere else (path rename, a vendored workspace migration, a data-fix in `env.py`) is skipped while the new code that needs it deploys — the exact skew the migrate step exists to prevent. Fall back to `alembic heads` vs `alembic current` comparison instead of path-matching.

20. **Heartbeat failure never triggers the rollback it recommends** — [VALUE: med · EFFORT: M] — The update's own final health verification failing only prints guidance (`scripts/update.sh:363-366`), while `--rollback` itself refuses to run without a matching snapshot (`:179`). So the one moment the script *knows* the stack is unhealthy post-update, it takes no restorative action. (Backup ordering itself is correct: dump-then-migrate with an empty-dump guard, `:283-305`.)

21. **Fresh install runs migrations with no backup and no recovery path** — [VALUE: low · EFFORT: S] — `install.sh --apply` migrates with no dump (backup only exists on the update path, `scripts/install.sh:836-844`). Acceptable for an empty DB, but a re-run of install against an existing volume (a common operator mistake) has nothing to restore if a migration half-applies.

22. **The in-app updater monitors the update through the container the update restarts** — [VALUE: med · EFFORT: M] — `applicantUpdate.js` polls `/api/applicant/ops/update` every 3s through `applicant-ui` (`workspace/static/js/applicantUpdate.js:26-28`, `:142-146`), but the update recreates `applicant-ui` itself (`docker/docker-compose.prod.yml:370`), so mid-update the poll throws, `_stopPolling()` + error render fire, and the user watching their update sees "offline" at the exact moment reassurance matters. The sidecar updater + log volume survive (`:378-395`) — the front-end just doesn't auto-resume: polling restarts only if the user manually reopens the modal (`applicantUpdate.js:189-198`). Keep polling through the outage with a "restarting — this is expected" state.

23. **chromadb/ntfy have no healthcheck; UI waits only for `service_started`** — [VALUE: low · EFFORT: S] — `applicant-ui` depends on chromadb with `condition: service_started` (`docker/docker-compose.prod.yml:73`) and ntfy has no healthcheck at all, so the UI can boot before vectors/notifications are actually ready; RAG init returns `None` and lazily retries (`:339-347`, `:354-363`) — a degrade, but an unannounced one. (Postgres also lacks `start_period`, so slow-disk first-boot `pg_isready` failures burn the 10 retries — `:253-257`.)

24. **No engine-side caller (with retry) exists for the internal calendar-event write** — [VALUE: med · EFFORT: M] — The workspace exposes `POST /internal/calendar/events` returning 502 on DB failure (`workspace/routes/applicant_internal_routes.py:744-804`), but `HttpWorkspaceClient` has no `create_event` method and no retry wrapper — any engine attempt to record an interview on the user's calendar that fails once is lost silently (interview detected, calendar never updated, user misses it).

---

## Tier 4 — Double-submit & resolve races (idempotency of the consequential POSTs)

25. **Double-clicking "authorize the assistant to finish" can double-click the real employer submit** — [VALUE: high · EFFORT: M] — The engine's authorize endpoint calls `container.browser.click_final_submit(...)` *before* delivering the decision (`src/applicant/app/routers/remote.py:342-357`); only the resulting OutcomeEvent is deduped (`record_submission` returns the pre-existing "submitted" event, `src/applicant/application/services/submission_service.py:194-197`, `:334-343`) — the *physical click* is not. Two rapid POSTs (double-click, or the same row open in two tabs) fire two real final-submit clicks against the live application form. The one irreversible action in the product needs a state-guard before the click, not after.

26. **Integral-change resolve has no already-resolved guard — the attribute change applies twice** — [VALUE: high · EFFORT: S] — The pending-actions resolve router applies a held profile change whenever `kind==INTEGRAL_CHANGE and body.apply` without checking `action.resolved` (`src/applicant/app/routers/pending_actions.py:168-183`); a second POST from a duplicated tab re-runs `attribute_cloud.upsert(..., confirm=True)`. (Plain resolve, by contrast, is a silent idempotent no-op — `pending_actions_service.py:202-204` — and bulk resolve correctly skips already-resolved ids, `:216-230`.)

27. **Resolving an already-resolved row returns 204 with no "someone beat you to it" signal** — [VALUE: med · EFFORT: S] — `resolve()` just calls `storage.resolve()+commit` and succeeds for unknown/already-resolved ids (`src/applicant/application/services/pending_actions_service.py:202-204`). Benign server-side, but it means the front-door can never tell the user "this was already handled (by the engine / your other tab)" — the row simply vanishes and any answer they typed into it is discarded as if accepted.

28. **Final-approval mailbox accumulates duplicate decisions forever** — [VALUE: med · EFFORT: S] — Each `submit_decision` `send`s a new payload onto the durable topic (`src/applicant/application/services/final_approval_service.py:72-86`); `recv` pops one (`checkpoint_shim.py:353-366`), so a double-POST leaves a stale second decision persisted in the checkpoint mailbox indefinitely — a latent poison message for any future recv on that topic.

29. **Remote's consequential buttons rely on one coarse module `_busy` flag and are never visually disabled** — [VALUE: med · EFFORT: S] — Takeover / resume / submit-self / authorize / desktop-assist all gate on a shared `_busy` boolean but the DOM buttons stay enabled (`workspace/static/js/applicantRemote.js:35`, `:367-379`, `:484-519`) — a fast double-click silently no-ops with no feedback, and any handler that throws before its `finally` strands `_busy=true`, dead-locking every remote action until the modal is reopened. (Contrast: Portal disables each button before its POST — `applicantPortal.js:950-1214` — and redline/digest/debug/vault have per-action guards — `documentLibrary.js:2188/2387/2405`, `applicantDigest.js:341/561`, `applicantVault.js:192`.)

29a. **Onboarding conflict-apply and preview accept/reject have no in-flight guard** — [VALUE: med · EFFORT: S] — `#ao-conf-apply` loops one `confirm-conflict` POST per conflict and is never disabled — a double-click replays the whole batch (`workspace/static/js/applicantOnboarding.js:1462-1478`); the résumé-conversion `#ao-prev-accept`/`#ao-prev-reject` likewise double-POST accept/reject (`:1505-1514`).

---

## Tier 5 — Engine restart & the 24/7 loop (what in-memory state forgets)

30. **Resume/backoff ledger is in-memory only — every restart triggers a retry storm of given-up applications** — [VALUE: high · EFFORT: M] — `ResumeLedger` (`last_resume`/`failures`/`giveup`) is a plain process-lived dataclass (`src/applicant/application/services/agent_loop.py:65-97`, `:274-277`; created at `container.py:968-972`). After any restart (including every `update.sh` run), an application that permanently failed 5 times and was "given up" becomes eligible again with backoff reset to 0 — immediate re-drive on the first tick, and it must re-fail 5 more times to re-give-up. The give-up decision the user may have been notified about silently un-happens.

31. **No dead-letter for the pipeline START path — a poison APPROVED application retries forever** — [VALUE: high · EFFORT: M] — The `_RESUME_FAILURE_CAP=5` give-up guards only the RESUME path (`src/applicant/application/services/agent_loop.py:695-727`); a fresh `APPROVED` application whose pipeline always crashes re-raises out of `_start_pipeline` every tick and stays `APPROVED` (`:629-656`, `:553-627`) — retried forever, with no cap, no dead-letter state, and no pending action telling the user this role is stuck.

32. **One poison approved posting aborts the rest of the campaign's tick** — [VALUE: high · EFFORT: S] — `_process_approvals` iterates approved postings and the first `_start_pipeline` exception propagates, skipping every later approved posting that tick (`src/applicant/application/services/agent_loop.py:553-627`). Combined with #31, one bad posting starves all its siblings every tick, indefinitely.

33. **Total DB outage bypasses the "your agent is stuck" alert entirely** — [VALUE: high · EFFORT: M] — `services = self._tick_services_factory()` runs *before* the tick's `try:` (`src/applicant/application/services/scheduler.py:176-182`, `:202`); if the session factory can't connect, the exception escapes `tick()`, `_tick_running` is never reset, and `_record_tick_metrics` (`:267`) never runs — so the consecutive-failure counter behind `_raise_failure_alert` (`:304-349`) never advances. The alert covers per-campaign failures but not the most likely systemic one: Postgres down. (The outer loop then swallows the escape and retries at a fixed interval with no backoff — `src/applicant/app/lifespan.py:205-211`.)

34. **Stale workflow lease after a hard kill is never reclaimed — the workflow is permanently unclaimable** — [VALUE: high · EFFORT: M] — `claim_workflow` creates an `O_CREAT|O_EXCL` `.lease` file removed only in the clean-exit `finally` (`src/applicant/adapters/orchestration/checkpoint_shim.py:137-179`). A process killed mid-advance (OOM, docker kill during update) leaves the lease on the shared checkpoint volume; every future tick's claim yields `False` with no TTL or steal — that application halts silently forever.

35. **Hard-kill orphans the live sandbox/browser of an in-flight prefill** — [VALUE: med · EFFORT: M] — Sandbox/browser cleanup runs only on the graceful lifespan shutdown path (`src/applicant/app/lifespan.py:88-105`, `:128-155`); a SIGKILL/crash skips it. Re-drive rebuilds workflow context from checkpoints (`agent_loop.py:757-783`) but cannot reclaim the orphaned VM/container/browser session — leaked capacity and a possibly half-filled live form under the user's identity.

36. **No step-level retry policy in the orchestrator** — [VALUE: med · EFFORT: M] — `run_step` runs `fn()` exactly once; on raise, no checkpoint is written and the exception propagates (`src/applicant/adapters/orchestration/checkpoint_shim.py:338-347`). All retry cadence is the tick loop, which conflates "transient network blip" with "permanent failure" — no max-attempts, no backoff, no error classification. (Contrast: checkpoint files themselves are versioned/checksummed with truncation treated as no-checkpoint — `:201-313` — that part is sound.)

37. **Prefill launch failures crash the pipeline with no FAILED state and no pending action** — [VALUE: high · EFFORT: M] — The `try/except → _failed_prefill` recovery boundary wraps only the page walk (`src/applicant/application/services/prefill_service.py:563-579`); `sandbox.provision`, `browser.open`, and the whole account-gate/login block run outside it (`:285`, `:312-314`, `:331-390`). A browser-launch failure (missing binary, sandbox capacity) propagates as an uncaught pipeline crash — the app never reaches FAILED, no operator pending action is created, and it silently retries every tick (feeding #31). Inside the walk, by contrast, a crash lands a structured FAILED + error action (`:581-606`).

38. **Missing browser binary passes `/healthz` and only manifests as the runtime crash above** — [VALUE: med · EFFORT: S] — Capability probes are logged and added to the healthz `capabilities` block but explicitly "do not affect ok/degraded" (`src/applicant/app/main.py:166-174`; `src/applicant/observability/capabilities.py:1-13`). A deploy without the browser layer is green at deploy time and fails only when the first prefill crashes uncaught (#37).

39. **Prefill diagnostics ring resets every tick — the 24/7 loop retains no login/credential degradation history** — [VALUE: med · EFFORT: S] — Credential/login degradations are recorded on `self._diagnostics` of a `PrefillService` instance that the scheduler rebuilds every tick (`src/applicant/application/services/prefill_service.py:231-238`, `:1056-1068`, `:1092-1100`, `:1112-1127`; rebuild at `container.py:1123-1250`) — the exact per-tick-reset trap CLAUDE.md warns about. Diagnostics are only ever populated for request-scoped instances, so the autonomous loop's failures leave no trace here.

40. **Ladder-advance and tick metrics run outside the tick's try/finally** — [VALUE: low · EFFORT: S] — `_advance_ladders` (`scheduler.py:262`) and `_record_tick_metrics` (`:267`) sit after the `finally`; an exception there escapes `tick()` uncounted, skewing the stall detector and skipping metrics for an otherwise-successful tick.

41. **Routine/curation stores are in-memory — induced ATS routines and dedupe counters reset on restart** — [VALUE: low · EFFORT: M] — `InMemoryRoutineStore` + curation ledger are process-lived only (`src/applicant/app/container.py:893-894`, `:1012`); every restart forgets learned form-fill routines (re-derived at cost) and resets curation dedupe, allowing duplicate curation work after each update.

---

## Tier 6 — Swallowed exceptions with real consequences (engine)

42. **A detected rejection can be silently lost** — [VALUE: high · EFFORT: S] — `detect_outcome` commits the rejection *signals*, then wraps the `REJECTED` state transition + OutcomeEvent + commit in `try/except: pass` (`src/applicant/application/services/post_submission_service.py:66-73`). If that block fails, the app stays un-rejected, the user's tracker lies, and the learning loop never sees the negative outcome — with zero log.

43. **Ghosting detection has the same silent-loss pattern** — [VALUE: med · EFFORT: S] — The ghosting signal is stored but the `GHOSTED` transition + outcome emission are `try/except: pass` (`src/applicant/application/services/post_submission_service.py:133-138`) — the terminal state can silently vanish while the signal persists, leaving the app in limbo.

44. **Follow-up send failures are fully swallowed — no log, no retry, state advance also passed** — [VALUE: med · EFFORT: S] — A notifier error during follow-up dispatch hits `except Exception: continue` with no log, and the `FOLLOWING_UP` state advance is separately `try/except: pass` (`src/applicant/application/services/post_submission_service.py:174-188`). A timed follow-up the user is counting on can silently never send and never retry.

45. **External notification channel failure is dropped AND falsely recorded as delivered** — [VALUE: high · EFFORT: M] — `_fire_due` catches `NotificationDeliveryError`, logs it, then unconditionally sets `rung.fired=True` and appends the channel to `sent_channels` (`src/applicant/adapters/notification/apprise_notifier.py:523-559`, `:749-760`). A Discord/push outage means an IMMEDIATE "agent stuck" alert is lost (beyond the in-app inbox, which is written first — `:478-502`) with no retry, and introspection reports the dead channel as having delivered. (Digest email is the exception: its dedup key is only added after confirmed dispatch, so it can retry — `:606-629`.)

46. **User's aggressiveness setting silently fails to persist** — [VALUE: med · EFFORT: S] — `_persist_aggressiveness` writes to the config store under `try/except: pass` (`src/applicant/application/services/material_service.py:320-331`); a store failure means the user's explicitly-chosen tailoring aggressiveness resets on restart with no trace, and the UI keeps showing the value they picked.

47. **Audit-trail writes can drop an ActionEvent (logged, but the FR-LOG trail has a hole)** — [VALUE: med · EFFORT: M] — `_persist_isolated` logs the failure but the event is still lost (`src/applicant/application/services/audit_log_service.py:112-127`); for a product whose trust story is "every action, in order," a failed audit write should at least be counted/surfaced, ideally buffered and retried.

48. **Boot continues past every startup-step failure** — [VALUE: med · EFFORT: S] — Durable-recovery re-drive, DB healthcheck, dormant-surface seeding, audit-log start, and system-campaign seed are each individually `except Exception: log.warning` (`src/applicant/app/lifespan.py:259-328`). Any one failing (e.g. audit-log service never starts) yields a healthy-looking engine missing a core subsystem — no aggregate "boot degraded" flag reaches `/healthz` or the front-door.

---

## Tier 7 — Poll-vs-action races & re-render input loss (front-door)

49. **Portal refresh rebuilds the list mid-typing — every draft answer in every row is wiped** — [VALUE: high · EFFORT: M] — `_load(true)` re-renders via `body.innerHTML = …` (`workspace/static/js/applicantPortal.js:859-881`); the header "Refresh" button (`:338`) and — worse — the *automatic* Google-2FA timeout handler (`:1127`) both call it. A user typing an answer into one row while a 2FA wait in another row times out loses everything they typed, with no warning. Preserve draft values across re-render (read textareas before rebuild, restore after) or re-render per-row.

50. **Resolving a row the engine already resolved shows a raw error and strands a dead row** — [VALUE: med · EFFORT: S] — If another tab/the engine resolved the action first, `_doResolve`'s catch just re-enables the button and toasts `e.message` verbatim (`workspace/static/js/applicantPortal.js:944-946`, `:960-964`); the defunct row stays until manual refresh. Treat already-resolved as success: fade the row with "already handled." (Pairs with engine-side #27: today the engine returns 204 for a duplicate resolve, so this path only triggers on other errors — but neither layer tells the user the truth.)

51. **The 60s badge poll correctly leaves the open list DOM alone (anti-finding)** — [VALUE: low · EFFORT: S] — `refreshBadge` only refetches counts/notifications (`workspace/static/js/applicantPortal.js:1275-1290`) — background polling alone does not destroy typed input. Documenting so nobody "fixes" it into a re-render; the destruction paths are the explicit `_load(true)` callers in #49.

---

## Tier 8 — Session expiry & draft loss mid-flow (front-door)

52. **The onboarding wizard has zero draft persistence — a 401/reload mid-section loses typed profile data** — [VALUE: high · EFFORT: M] — No localStorage/sessionStorage/beforeunload anywhere in the wizard; state is `_intakeIndex` plus per-section POSTs on advance (`workspace/static/js/applicantOnboarding.js:1520-1539` and throughout). A session expiring mid-section (the longest typing surface in the product) throws away the current section's fields; the user re-logs-in to a wizard that forgot where they were. Persist a per-step draft (sessionStorage) and restore on relaunch.

53. **Digest decline reason is destroyed if the POST fails** — [VALUE: med · EFFORT: S] — The mandatory "why are you passing" reason is captured via `styledPrompt`, whose modal is gone by the time `decline` fails; the catch only re-enables buttons (`workspace/static/js/emailLibrary/applicantDigest.js:373-383`, `:397-400`), so the typed reason must be re-typed from memory. Retry with the captured value, or re-open the prompt pre-filled.

54. **Redline "ask for a change" instruction lives only in the DOM** — [VALUE: med · EFFORT: S] — The free-text change request survives a failed turn POST but not a re-render (`_loadApplicantMaterials`/`_renderApplicantReview`) or reload (`workspace/static/js/documentLibrary.js:2324-2331`, `:2368`). Mid-review refreshes (or a second surface triggering a reload of materials) silently discard the user's editorial instruction.

55. **Chat composer clears before the send succeeds** — [VALUE: med · EFFORT: S] — `input.value=''` runs before the POST resolves (`workspace/static/js/applicantChat.js:395`, `:421-424`); on failure the text is recoverable only via the verbatim Retry button (not editable) and is gone entirely on reload. Clear on success, or restore into the composer on failure.

56. **Vault secret survives a failed save but not the 401 that likely caused it** — [VALUE: low · EFFORT: M] — On save error the password input is left intact (good — `workspace/static/js/applicantVault.js:204-209`, `:221`), but a session-expiry-forced reload loses the typed secret. Deliberately do NOT draft-persist secrets; instead detect `kind==='auth'` and offer an in-place re-auth so the modal (and the typed secret) survives.

---

## Tier 9 — Live view, long ops & abandonment (front-door)

57. **The live-session iframe has no error/health detection — a dead sandbox renders a browser error page forever** — [VALUE: high · EFFORT: M] — `_setActiveSession` just sets `frame.src` with no `onload`/`onerror` and no session-status poll (`workspace/static/js/applicantRemote.js:203-213`, `:91`); nothing re-validates `_activeSession` over time (`:316-336`). If the engine restarts or the sandbox dies while the user watches (the highest-tension moment in the product), the frame silently dies until they think to click "Refresh sessions." Poll session liveness and overlay a "session ended — reconnecting/reload" state.

58. **"Waiting for your phone…" can stick disabled forever** — [VALUE: med · EFFORT: S] — `continueTwoFactor` is awaited with no cancel or client-side deadline (`workspace/static/js/applicantPortal.js:1114-1116`); if the engine hangs past the proxy timeout the button stays disabled with the waiting label and no way out short of a full refresh (which then triggers #49's input wipe via `:1127`).

59. **Résumé-conversion preview hangs with no cancel, and closing the wizard orphans it** — [VALUE: med · EFFORT: M] — `_buildPreview` awaits `conversion/preview` with no client deadline (`workspace/static/js/applicantOnboarding.js:1481-1518`); a stalled build leaves "Building a polished version…" forever, closing the overlay abandons the op invisibly, and reopening re-fires a fresh build rather than attaching to the in-progress one — double work on the engine, no progress truth for the user.

60. **Chat "Thinking…" and digest deep-research have no timeout/cancel/abandon UX** — [VALUE: med · EFFORT: M] — `_send` awaits a single buffered `/message` POST (`workspace/static/js/applicantChat.js:399-401`) and `_onResearch` awaits `research/run` with the button stuck on "Researching…" (`workspace/static/js/emailLibrary/applicantDigest.js:412-439`); closing the panel mid-run orphans the operation (the report only opens on success). Combined with the 30s proxy read cap (#10), long research *cannot* succeed — the user gets a spinner, then an error, and the engine work is discarded.

61. **Run-now offers no progress and no cancel** — [VALUE: low · EFFORT: S] — Debug run-now awaits its POST showing only "Running…" (`workspace/static/js/applicantDebug.js:620-642`); a stalled engine leaves the admin surface stuck with no way to abandon or observe the run's actual state.

---

## Tier 10 — Two tabs, storage corruption & clock skew (front-door)

62. **Two tabs double-toast every notification and race the seen-marker** — [VALUE: med · EFFORT: M] — Each tab polls independently and runs `_toastNew` (`workspace/static/js/applicantPortal.js:135-156`), so both pop the same toasts; both write `NOTIF_SEEN_KEY` last-writer-wins (`:111-120`), so one tab can advance the marker past notifications the other never displayed — permanently un-seen items. Use a `storage` event or BroadcastChannel to elect one toasting tab.

63. **"While you were away" recap window is clobbered by a second tab** — [VALUE: med · EFFORT: S] — `_captureRecapSince` reads `RECAP_SEEN_KEY` then immediately overwrites it with `Date.now()` (`workspace/static/js/applicantPortal.js:415-423`); a second tab opened moments later computes a near-empty recap window. The overnight-recap feature degrades to noise for anyone who opens two tabs.

64. **One background tab's blur marks the user absent for the engine** — [VALUE: med · EFFORT: S] — The digest presence heartbeat sends `present:false` on `blur`/`visibilitychange` (`workspace/static/js/emailLibrary/applicantDigest.js:893-916`, `:902`) even while another tab is focused — the engine then re-enables push/chat fan-out duplicates for a user who is actually looking at the app.

65. **Seen-marker corruption silently re-toasts the entire backlog** — [VALUE: low · EFFORT: S] — Marker writes are wrapped in empty `catch` (quota errors mean it never persists — `workspace/static/js/applicantPortal.js:119`, `:422`) and a corrupt value goes through `Number()` → `0`/`NaN` (`:113-115`), which re-classifies every historical notification as new on next load. Validate the parsed marker and re-seed to newest on nonsense.

66. **All "new/since" math trusts the client clock against engine timestamps** — [VALUE: med · EFFORT: M] — Recap totals include runs with `_runTs > _recapSince` where `_recapSince` is client `Date.now()` (`workspace/static/js/applicantPortal.js:437-451`, `:415-423`); notification newness compares engine `created_at` to the client-stored marker (`:122-125`, `:145-148`); relative ages use `Date.now() - engineTs` with negatives collapsing to "just now" (`workspace/static/js/applicantActivity.js:57-67`). A self-hosted box with drift (common on home servers without NTP) over/under-counts the recap and mis-toasts. Anchor markers to engine-supplied `server_now` instead.

67. **Digest feature-gate memoized for the whole page session** — [VALUE: med · EFFORT: S] — `_featurePromise` caches whether the digest section is active (`workspace/static/js/emailLibrary/applicantDigest.js:30`, `:79-93`); after the user finishes setup (or the engine restarts into a different state) the panel stays stale until a full page reload — the classic "it says locked but I just configured it" support ticket.

---

## Tier 11 — Payload robustness & remaining edges

68. **Onboarding conflict-apply throws on an unanswered conflict radio** — [VALUE: med · EFFORT: S] — `wrap.querySelector('input[name="ao-conf-…"]:checked').value` null-derefs when the user leaves a conflict unanswered (`workspace/static/js/applicantOnboarding.js:1468`), surfacing as the generic "Could not apply choices" toast instead of "please pick an option for each conflict" — a validation gap masquerading as an engine failure.

69. **Redline injects engine `rendered_html` unsanitized** — [VALUE: med · EFFORT: M] — `redline.innerHTML = rl.rendered_html` (`workspace/static/js/documentLibrary.js:2274-2281`) trusts the engine's HTML wholesale (there is a fallback when the field is absent, so no blank surface). Any upstream content that survives engine templating (posting text, LLM output) renders live in the front-door — sanitize or render into a shadow root with a strict allowlist. *(Trust-lens #12 flagged the annotation-layer angle; this is the injection/robustness angle.)*

70. **`ui_control` highlight trusts an engine-supplied CSS selector** — [VALUE: low · EFFORT: S] — `document.querySelector(uiData.selector)` throws on malformed selectors and is swallowed by the outer catch (`workspace/static/js/chatStream.js:111`, `:193-195`) — a silent no-op that makes assistant-driven UI guidance flaky with no trace.

71. **Most renderers degrade gracefully on partial payloads (anti-finding)** — [VALUE: low · EFFORT: S] — Portal rows coalesce missing `payload` fields (`applicantPortal.js:669`, `:726`, `:1421`), digest rows fall back on `row.title||row.summary` (`emailLibrary/applicantDigest.js:250-252`), remote snapshot type-checks answers/materials (`applicantRemote.js:614-618`), results/activity numeric-guard (`applicantResults.js:43-53`, `applicantActivity.js:362-380`). Keep this bar: the two regressions to fix are #68 and #69.

72. **Optimistic pause toggle correctly rolls back (anti-finding)** — [VALUE: low · EFFORT: S] — `_applyPauseOptimistic` paints the new state, reverts on error, then reconciles via `refreshStatus` (`workspace/static/js/applicantActivity.js:104-113`, `:129-135`); Portal/digest/documents all remove rows only *after* the awaited POST resolves (`applicantPortal.js:957-959`, `emailLibrary/applicantDigest.js:357-360`, `documentLibrary.js:2390-2393`). This is the pattern to standardize on, not a gap.

---

## The shape of the fix (read this before picking items)

Five systemic moves close most of the list:

1. **Make degraded modes first-class data.** One engine "health & capabilities" payload (persistence fallback #1–2, capability stubs #3/#5/#38, boot-step failures #48, per-source discovery health #4) surfaced through setup-status → `applicant_features.py` → a persistent front-door banner. Everything in Tier 1 collapses into this.
2. **Guard the irreversible click server-side.** A submitted/submitting state-check *before* `click_final_submit` (#25) plus an already-resolved guard on integral-change (#26) and an honest "already handled" contract (#27/#50). Client disables (#29/#29a) are defense-in-depth, not the fix.
3. **Persist the loop's memory.** Move the resume/give-up ledger (#30), add a start-path failure cap + per-app isolation (#31/#32), lease TTL (#34), and widen the prefill recovery boundary (#37). These five turn "restart = retry storm + stuck workflows" into "restart = resume."
4. **One timeout ladder.** Client draft-preserving re-render (#49) + per-operation timeouts that are *longer at each outer layer* (engine op < proxy read < middleware < UI), fixing #10/#11/#59/#60 in one policy.
5. **Retry-or-record for outbound side effects.** Notifications (#45), workspace callbacks (#8/#24), follow-ups (#44), outcome transitions (#42/#43): either retry with backoff or write a durable "failed, will retry / needs attention" record. Never log-and-forget an action the user is counting on.
