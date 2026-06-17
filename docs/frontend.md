# Front door: the white-labeled workspace UI

Applicant's user interface is **not** served by the engine. It is a separate,
white-labeled **workspace** web app (`workspace/`) that runs as the public
`applicant-ui` service on `${APP_PORT}` (→ container `7000`) and talks to the engine
(internal `api:8000`) across the bridge. This doc covers how the front door is wired
and how to add or change an Applicant surface in it.

> The engine still carries a small in-network `frontend/static/` shell for migration
> purposes, but it is **not** the front door and serves no operator-facing UI. Do not
> add new surfaces there.

Two requirements govern the look and behavior:

- **FR-UI-1 — white-labeled, no-build clone.** Surfaces reuse the workspace's existing
  vanilla, no-build design system (hand-authored HTML + ES modules, no bundler). No
  vendor/persona codename and no `FR-`/`NFR-` jargon in user-facing strings — the
  product is **Applicant**.
- **FR-UI-2 — progressive activation, never dead UI.** A surface whose engine backing
  isn't configured yet is present but greyed/locked, never shown as if live. State is
  computed, not hand-toggled (see [Feature activation](#feature-activation)).

## How a surface is wired (the three layers)

Every Applicant surface is the same chain — **engine router → workspace proxy → JS glue
→ nav/section**. "Reachable through that whole chain" is the definition of done
(see the working principles in [extending.md](extending.md)), not "the engine
implements it and tests pass."

1. **Proxy route** — `workspace/routes/applicant_*_routes.py`. A thin,
   auth-protected, owner-scoped FastAPI route under `/api/applicant/*` that forwards
   to the engine client. It contains **no business logic** — the engine owns that.

   | Route file | Surface(s) it proxies |
   |---|---|
   | `applicant_routes.py` | `GET /api/applicant/features` — the feature-state payload |
   | `applicant_setup_routes.py` | OOBE wizard: LLM, channels, fonts, intake, base-résumé + LaTeX accept/reject |
   | `applicant_documents_routes.py` | Documents / résumé library + redline revision loop |
   | `applicant_memory_routes.py` | Profile: attribute cloud + learned/AI attributes + résumé-conversion learning |
   | `applicant_chat_routes.py` | Chat/assistant, campaign list/create, pending list, remote résumé actions |
   | `applicant_email_routes.py` | Daily digest per campaign, approve/decline-with-feedback, feedback survey |
   | `applicant_portal_routes.py` | Pending-actions portal (aggregated across all campaigns) |
   | `applicant_remote_routes.py` | Live remote session: view URL, takeover, submit-self, authorize-engine-finish |
   | `applicant_vault_routes.py` | Credential vault: list tenants, bank credentials, capture from takeover |
   | `applicant_admin_routes.py` | Activity/debug observability: history, screenshots, logs, workflow state, variants, mark-submitted |
   | `applicant_ops_routes.py` | Operator controls: run mode, throughput, intent, discovery-source toggles, Update trigger |
   | `applicant_internal_routes.py` | **Engine → workspace** callback channel (token-gated; not an operator surface) |

2. **Engine client + feature layer** — `workspace/src/applicant_engine.py` is the httpx
   client that every proxy calls; it reads `ENGINE_URL` (default `http://api:8000`) and
   raises a typed `EngineError` on any failure, so a proxy never leaks a broken page.
   `workspace/src/applicant_features.py` computes section state (below).

3. **Glue module** — `workspace/static/js/applicant*.js`. One ES module per surface,
   driving its proxy routes:

   | JS module | Surface | State |
   |---|---|---|
   | `applicantOnboarding.js` | OOBE setup wizard (blocking overlay) | active |
   | `applicantPortal.js` | Pending-actions portal (home base) | active |
   | `applicantChat.js` | Job assistant (chat + job actions) | active |
   | `applicantRemote.js` | Live remote view / takeover | active |
   | `applicantVault.js` | Credential vault | active |
   | `applicantDebug.js` | Activity / debug (observability + ops) | active |
   | `emailLibrary/applicantDigest.js` | Daily digest panel (injected into the email surface) | active |

   Profile (memory: attribute + criteria editors) and documents redline are wired
   through their proxy routes and the existing workspace document/memory surfaces.

## Feature activation

`workspace/src/applicant_features.py` is the progressive-activation layer (serving
`GET /api/applicant/features`). It does **not** hand-toggle sections — it derives each
section's state from the engine:

- reads the engine's setup/gate status (`GET /api/setup/status`) and dormant-surface
  registry (`GET /api/dormant-surfaces`),
- evaluates each section's gate predicate (`onboarding_complete`, `llm_configured`,
  `channels_configured`),
- resolves a state string per section:

  | State | Meaning |
  |---|---|
  | `active` | engine reachable AND this section's backing is configured/live |
  | `configured` | backing configured but the engine is momentarily unreachable |
  | `locked` | backing not yet configured (e.g. onboarding incomplete) — greyed |
  | `disabled` | present-but-disabled by product decision (no engine backing) |

The layer is read-only and never raises: if the engine can't be reached it degrades to
`configured`/`locked` so the nav still renders. Each section entry carries the DOM
`nav_ids` the frontend greys/locks (sidebar rail + toolbar/overflow buttons).

The Applicant section map (`APPLICANT_SECTIONS`):

| Key | Title | Gate predicate | `present_but_disabled` |
|---|---|---|---|
| `documents` | Documents / résumé library | `onboarding_complete` | no |
| `memory` | Memory / skills (attributes + learning) | `onboarding_complete` | no |
| `chat` | Chat / assistant (job actions) | `llm_configured` | no |
| `email` | Email / notifications & digests | `channels_configured` | no |
| `debug` | Activity / debug | `llm_configured` | no |
| `compare` | Compare | — | **yes** |

**Compare ships disabled.** It has no engine backing; the feature map sets
`present_but_disabled: True`, so it is always reported `disabled` — visible in the nav,
greyed, never wired.

**Calendar, Deep-Research, and Cookbook** remain native workspace surfaces; they are
*not* Applicant sections. Where the engine needs them it calls back through the
token-gated internal channel (`applicant_internal_routes.py`), not through a new
operator-facing surface.

## Recipe: add a new Applicant surface

1. **Engine first.** Add/confirm the engine router under
   `src/applicant/app/routers/` that owns the logic.
2. **Proxy route** — add a `workspace/routes/applicant_<name>_routes.py` that forwards
   to a method on the engine client (`workspace/src/applicant_engine.py`),
   auth-protected and owner-scoped. Keep it thin — no logic.
3. **Feature entry** — add a section to `APPLICANT_SECTIONS` in
   `workspace/src/applicant_features.py` with its `nav_ids`, gate `requires`
   predicate, and any `dormant_keys`. Leave it to compute its own state.
4. **Glue module** — add `workspace/static/js/applicant<Name>.js` that drives the proxy
   routes, reads `/api/applicant/features` for its section state, and renders greyed
   when not `active`. Reuse the workspace design-system classes; no new bundler/deps.
5. **Lift and shift first.** If a working component for this already exists anywhere in
   the tree, copy it into place and adapt it — do not rebuild from scratch (the
   binding working principle in [extending.md](extending.md)).
6. **Verify reachability.** The surface is done only when it is reachable/operable in
   the front door across the whole chain — not when the engine implements it.

## Styling and white-label rules

- Reuse the workspace's existing design-system classes; no per-surface bundler or new
  runtime dependencies (FR-UI-1).
- No vendor/persona codename and no internal requirement jargon (`FR-`/`NFR-`) in any
  user-facing string — the product is **Applicant** everywhere (FR-UI-1).
- Never present a failed engine call as live data: when a section isn't `active`, render
  it greyed/locked rather than as if wired (FR-UI-2).
- The workspace keeps its own coarse feature mechanism (`/api/auth/features` +
  `data/features.json`) for its native app features — that is untouched; the
  Applicant feature layer is a separate, derived read-only layer.
