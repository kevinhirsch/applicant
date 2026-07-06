# Exhaustive-audit closure status (12-lens backlog)

Single tracker for the 12-lens `exhaustive2/` UX-hardening backlog: what each lens
contains, how much is closed, and what remains. Raw finding **totals badly overstate
remaining work** — most front-door items were applied by earlier passes and the closure
sweeps below; whole lenses are closed; and several later-built surfaces carry zero findings
(they postdate the audit).

Update this file when a lens materially advances. Companion logs:
[`discovered-issues.md`](../discovered-issues.md) (incidental bugs found while sweeping) and
[`../../../known-issues.md`](../../../known-issues.md) (engine/deploy defects).

_Last synced: after PRs #626–#630 merged to `main`._

## Per-lens status

| Lens | Findings | Status | Notes |
|---|---|---|---|
| 01 · micro-interactions | 97 | **essentially closed** | All high-traffic front-door surfaces swept (portal, doclib, model-ladder, vault, remote, onboarding, chat, tracker, mind, results). The 5 unswept `applicant*.js` surfaces (automation-settings, capabilities, reachability, shortcuts, trust) carry **0** lens-01 findings — built after the audit. Only scattered items remain. |
| 02 · copy & voice | 281 | **essentially closed (front-door)** | Every front-door speaking surface rewritten to the house voice (first-person-singular, `errText` toasts, curly apostrophes, "search"/"documents" terminology). Remaining: engine-emitted message templates + the engine's internal `frontend/static/applicant/` UI (lower priority — not the public surface). |
| 03 · performance | 72 | **hot-path done** | Workspace request hot-path trimmed (#46–50: CSP-nonce skip on `/static/`, single-lookup cookie auth, image-owner cache, one keepalive client). Remaining: `applicant_engine.py` #25 (3 serial sync HTTP calls on `/features`) + a handful of smaller items. |
| 04 · failure paths | 77 | **CLOSED** | Driven to zero across prior waves + this session (crash→FAILED boundaries, idempotency, honest degraded-mode surfacing, retry/dead-letter). |
| 05 · a11y deep | 70 | **partial** | `index.html` done (echoing aria-labels removed, live-region relocated, rail nav role). Other surfaces remain. |
| 06 · mobile responsive | 60 | **partial** | PWA (manifest + SW) and Vault done. Other surfaces remain. |
| 07 · power users | 59 | **not started — ask first** | Mostly **net-new features**: MCP surface, scoped API tokens, CLI, keyboard-shortcut system. Product decisions, not mechanical closure. |
| 08 · engine dark matrix | 108 | **largest open mechanical lens** | Partially addressed (the Tracker board closed several engine-behavioral gaps). Not yet systematically driven — the biggest remaining **fix** (not feature) chunk. |
| 09 · activation funnel | 87 | **barely touched** | Mix of mechanical onboarding/activation copy+flow fixes and some feature slices. |
| 10 · notifications | 58 | **partial tail** | Notifier dedup/re-fire + ntfy correctness shipped (#9/#19/#20/#35/#36) and inbox owner-scope (#28, security). Remaining: config/UX tail. |
| 11 · settings & config | 60 | **partial tail** | Vault backup note, saved-secret placeholders, model-ladder key handling shipped. Remaining: settings copy/config tail. |
| 12 · help & self-explain | 50 | **partial — part feature** | Some tooltip/copy items done; a full in-app help/docs system is a **feature** (ask first). |

## Security thread (cross-user isolation — CLOSED)

The engine is single-tenant, so `require_user` alone was only IDOR protection, not
cross-account isolation. Closed in two PRs:
- **#626** — notification inbox owner-scope (`_require_notification_owner`).
- **#629 / #630** — factored the shared `require_engine_owner` gate and applied it to **all**
  read **and** write endpoints on the `pending / campaigns / tracker / activity` proxies. A
  second workspace account can no longer read or mutate the owner's data; single-user mode
  is preserved. (DISC-15 + DISC-15b.)

## Session PR map (this closure cycle)

| PR | Lenses / items |
|---|---|
| #626 | 10 (#9/#19/#20/#35/#36 notifier, #28 inbox owner-scope security), 01 (doclib, model-ladder) |
| #627 | 06 (vault, PWA), 05 (index.html a11y), 03 (perf hot-path #46–50) |
| #628 | 02 (copy ×4 surfaces), DISC-10 (bulk-decline reason), DISC-12 (redrive visibility) |
| #629 | DISC-15 read isolation (security), 01/02 (chat, tracker) |
| #630 | DISC-15b write isolation (security), 01/02 (mind, results) |

## Recommended resume order

1. **DISC-2** — restart-durable ledgers (highest-value open engine bug; see `discovered-issues.md`).
2. **Lens 08** — engine dark matrix (biggest mechanical win still open).
3. **Lens 03 / 05 / 06 / 10 / 11 tails** — mechanical, safe to batch.
4. **Lens 09 mechanical half** — activation copy/flow fixes.
5. **STOP and ask** before the feature-heavy set: lens 07, the lens-12 help/docs system, and
   the lens-09 feature slices (MCP surface, scoped tokens, CLI, rules engine, web-push).
