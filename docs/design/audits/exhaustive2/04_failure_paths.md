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
