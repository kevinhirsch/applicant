# Surface reachability map

Mandated by **FR-UI-2** (§3.19) and the scaffold-and-gray / progressive-activation
principle (§2): no surface ships as if live before its backing exists. In the
two-app architecture this is enforced two ways:

1. **Engine dormant-surface registry** — `src/applicant/dormant.py` (machine-readable
   source of truth; `tests/unit/test_phase4_services.py` asserts registry/UI
   consistency). Each engine-side surface flips from `dormant` to `live` as its
   backend lands.
2. **Front-door progressive activation** — `workspace/src/applicant_features.py`
   computes each workspace section's state (`active` / `configured` / `locked` /
   `disabled`) from the engine's setup status + dormant registry, so the nav greys/locks
   sections until the engine is configured, and never renders dead UI (see
   [frontend.md](frontend.md)).

This doc is the surface-by-surface map of what is **reachable in the workspace front
door** today, plus the one surface that ships **present-but-disabled**.

## Reachable surfaces (front door → engine)

Each row is wired across the whole chain — engine router → workspace
`/api/applicant/*` proxy → JS glue → nav/section.

| Surface | Front-door section / JS | Engine router | Activation gate | Status |
|---|---|---|---|---|
| OOBE setup / onboarding wizard | `applicantOnboarding.js` (blocking overlay) | `setup` / `onboarding` / `fonts` / `conversion` / `model_endpoints` | auto-launches; gates the rest | **live** |
| Pending-actions portal | `applicantPortal.js` (home base) | `pending_actions` | always (the queue) | **live** |
| Documents / résumé redline review | documents section + redline | `documents` | `onboarding_complete` | **live** |
| Profile — criteria editor | memory/profile section | `criteria` | `onboarding_complete` | **live** |
| Profile — attribute-cloud editor | memory/profile section | `attributes` | `onboarding_complete` | **live** |
| Profile — learning (attributes + conversion) | memory/profile section | `attributes` / `conversion` | `onboarding_complete` | **live** |
| Chat / assistant + job actions | `applicantChat.js` | `chat` (+ `campaigns`, `pending_actions`, `remote`) | `llm_configured` | **live** |
| Email / digest panel | `emailLibrary/applicantDigest.js` | `digest` | `channels_configured` | **live** |
| Feedback survey | digest/feedback flow | `feedback` | `channels_configured` | **live** |
| Activity / debug (logs, screenshots, history, workflow state, variants) | `applicantDebug.js` | `admin` | `llm_configured` | **live** |
| Run controls / mark-submitted / Update button | `applicantDebug.js` (ops tab) | `ops` / `admin` / `update` | `llm_configured` | **live** |
| Live remote view / takeover + submit/authorize | `applicantRemote.js` | `remote` | reached from pending actions / chat | **live** |
| Credential vault | `applicantVault.js` | `credentials` | `onboarding_complete` | **live** |
| Profile — what the assistant remembers | `applicantMind.js` (memory panel) | `agent_memory` (`/api/agent-memory`) → `/api/applicant/mind/memory` | `llm_configured` | **live** |
| Profile — saved playbooks | `applicantMind.js` (playbooks panel) | `agent_memory` (`/api/agent-memory/skills`) → `/api/applicant/mind/skills` | `llm_configured` | **live** |
| Learning curation approvals | `applicantMind.js` / `applicantPortal.js` (approve/deny) | `agent_memory` (`/api/agent-memory/curation`) → `/api/applicant/mind/curation` | `llm_configured` | **live** |

The three learning surfaces above come from the assistant-learning substrate
(`docs/spec/agent-intelligence.md`, the `FR-MIND` group) — a lift-and-shift of the Hermes
Agent (MIT) learning loop. They are wired end-to-end today: the engine answers from its
self-contained in-process store by default, and `MIND_BACKEND=bridge` points the ports at
the front-door memory/playbooks store over the internal callback channel. Self-writes the
assistant proposes are staged for review (default on) and surface as approve/deny items in
the portal — only approval applies a proposal, so the advisory-not-authorization rule holds.

## Present-but-disabled surface

| Surface | Front-door section | Engine backing | Status |
|---|---|---|---|
| Compare | `compare` (rail + toolbar button) | none | **disabled** (visible, greyed, never wired) |
| Desktop assist (live session) | `applicantRemote.js` (opt-in toggle in the live-session modal) | `remote` desktop endpoints → `/api/applicant/.../desktop/*`; `ComputerUsePort` (`noop` default) | **dormant** (present-but-grayed) |

`Compare` has no Applicant engine backing. `workspace/src/applicant_features.py` sets
`present_but_disabled: True` for it, so the feature layer always reports it `disabled`.

**Desktop assist** is the optional background desktop-control capability
(`docs/spec/computer-use.md`, the `FR-CUA` group) — a lift-and-shift of the Hermes Agent
(MIT) computer-use feature. The port, core safety guards (stop-boundary, hard-blocks,
no-secrets), and the front-door toggle + proxy routes are all wired, but the surface ships
**present-but-grayed**: the engine boots the safe no-side-effects backend, and the toggle
stays locked with honest copy until the desktop driver and its display stack are baked into
the **sandbox** image (not the `api` image) and the health preflight passes. It is registered
`dormant` as `desktop_assist` in `src/applicant/dormant.py` and flips to live once the driver
lands — same "bake the binary into the image or it silently degrades" rule as TeX/LibreOffice/
Chrome. The honest disabled state is driven by the dormant registry +
`workspace/src/applicant_features.py`.

## Adjacencies (not Applicant surfaces)

`Calendar`, `Deep-Research`, and `Cookbook` remain **native workspace** surfaces — they
are not Applicant-mapped sections in `APPLICANT_SECTIONS`. The engine reaches their
capabilities (calendar interview detection, deep-research runs, cookbook-served local
models) through the **token-gated internal callback channel**
(`workspace/routes/applicant_internal_routes.py`, gated by `APPLICANT_INTERNAL_TOKEN`),
not through a separate operator-facing surface.

## Engine-side dormant registry (for reference)

Within the engine, the surfaces that had grayed scaffolds during earlier phases are now
`live` in `src/applicant/dormant.py`; the assistant-learning surfaces are live, and
`desktop_assist` is the one surface still `dormant` (its driver is not yet baked in):

| Engine surface key | Status |
|---|---|
| Digest (in-app) | live |
| Redline / revision | live |
| Debug / admin | live |
| Criteria editor | live |
| Attribute-cloud editor | live |
| Tool-toggle registry | live |
| Chatbot | live |
| Update trigger | live |
| Remote-session takeover | live |
| `assistant_memory` (what the assistant remembers) | live |
| `saved_playbooks` | live |
| `curation_approvals` (learning curation queue) | live |
| `desktop_assist` (computer use) | dormant |

The remote-session takeover defaults to the **configurable Ubuntu webtop full desktop**
(`REMOTE_VIEW_BACKEND=webtop`; DE = `TAKEOVER_DESKTOP` → cinnamon default / xfce / gnome
/ pantheon on X11, an image swap), with **Neko (browser-only) and noVNC still
selectable** via the swappable RemoteView sub-port. Image selection + tokenized URL +
handoff (`app=`) + lifecycle are wired/unit-tested; the real container start-stop +
shared-profile continuity are integration-gated.

The remaining historically-grayed items (resume aggressiveness control, multi-campaign
switcher) are tracked below.

## Still-grayed engine scaffolds

### Resume aggressiveness / tuning control

- **Surface:** A slider/stepper on the résumé redline surface tuning adaptation
  aggressiveness toward job-getting potential.
- **Requirement ID(s):** FR-RESUME-9 (explicitly "built but grayed out now; ship a stub
  spec"); §12 open item.
- **Wiring remaining:** Define the aggressiveness scale, bind it to generation
  parameters, persist per campaign, and confirm it never relaxes the truthfulness
  guardrail (FR-RESUME-2).

### Multi-campaign switcher

- **Surface:** A campaign selector/switcher (MVP-1 runs a single campaign; the chat
  surface already lists/creates campaigns).
- **Requirement ID(s):** FR-CRIT-4 (multi-ready); NFR-EXT-1; §2 "Campaign-scoped,
  multi-ready".
- **Wiring remaining:** The schema is already campaign-scoped (see
  [data-model.md](data-model.md)) and cross-campaign isolation is tested; the remaining
  work is the multi-campaign switcher UI binding in the front door.

---

**Process rule:** any new surface added to the front door that is not yet wired MUST be
added to `APPLICANT_SECTIONS` with its gate predicate and reported `locked`/`disabled`
until its backing lands, and any new engine scaffold MUST be registered in
`src/applicant/dormant.py` (FR-UI-2). No dead UI ships as if live.
