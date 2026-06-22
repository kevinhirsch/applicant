# Computer Use (desktop control) — `FR-CUA`

Integration spec for bringing **background computer use** — agentic control of a full
desktop (click / type / scroll / drag over the OS accessibility tree, not just the
browser DOM) — into Applicant's sandbox + live-takeover path. This is a **lift-and-shift
of the Hermes Agent computer-use feature** (which drives the open-source **TryCUA
`cua-driver`** over MCP-stdio), adapted to Applicant's hexagonal ports, safety gates,
and white-labeled front door.

- **Upstream feature:** Hermes Agent — *Computer Use* (NousResearch).
  <https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use>
- **Source we lift from (MIT):** `kevinhirsch/hermes-agent`.
  <https://github.com/kevinhirsch/hermes-agent>
- **Underlying driver:** TryCUA `cua-driver` (background computer-use driver, MCP/stdio).
- **Attribution:** see [§9](#9-attribution-mit) and the repo-root [`NOTICE`](../../NOTICE).

> **Authority.** This doc *extends* `docs/spec/master-spec.md`. It defines the `FR-CUA`
> group and hangs it off **`FR-SANDBOX-5`** (§3.13). Where this doc and the master spec
> disagree, the master spec wins; raise a PR to reconcile.

---

## 1. Why — where computer use fits

Applicant already automates applications through the **browser** (patchright/camoufox,
`FR-PREFILL`/`FR-STEALTH`) inside an isolated **sandbox** with a one-click **live
takeover** (`FR-SANDBOX`). That covers the web form. It does **not** cover the steps
that live *outside* the page:

- native **OS file pickers** (résumé/cover-letter upload dialogs — `FR-RESUME` artifacts
  live on the sandbox filesystem; today the human does this in takeover),
- **desktop apps** an ATS occasionally launches (PDF viewer, a vendor's thick client),
- **OS-level dialogs** (print-to-PDF, "open with", permission prompts),
- generally, *co-working* on the takeover desktop where the human and the agent share one
  screen.

Upstream Hermes is explicit that **for web-only work the headless-browser path is
preferred** — it avoids the TCC / Session-0 / X11 setup that desktop control needs. We
keep that ordering: **browser pre-fill stays the primary path; computer use is the
complement** for native-desktop steps and an optional assistive layer during takeover. It
is **not** a replacement for `FR-PREFILL`.

The upstream feature's defining property — the **no-foreground / no-cursor-steal
invariant** (the agent reads the accessibility tree and dispatches pid-scoped input
*without* moving the user's cursor, raising windows, or stealing focus) — is exactly what
makes shared **co-working** in live takeover (`FR-SANDBOX`) viable: the human can keep
working in the same session while the agent acts.

---

## 2. Scope & non-goals

**In scope**
- A new driven **port** `ComputerUsePort` and a default adapter that drives TryCUA
  `cua-driver` over MCP-stdio, launched **inside the sandbox** (the `takeover-desktop`
  container for `SANDBOX_BACKEND=local`; the Windows VM for `proxmox-windows`).
- A bounded **desktop action vocabulary** (capture / click / type / key / scroll / drag /
  focus-app) surfaced to the agent loop as a tool, gated by the same safety machinery as
  pre-fill.
- Reachability through the white-labeled front door: an opt-in **"Let the assistant help
  on the desktop"** capability in the live-session surface (`applicantRemote.js`) and an
  Automation-settings toggle.

**Non-goals**
- Running computer use on the **user's own machine** or any host outside the sandbox.
  Desktop control is confined to the ephemeral sandbox the engine already provisions
  (`FR-SANDBOX-1`, `FR-SANDBOX-4`).
- Replacing browser pre-fill, stealth, or the ATS adapters.
- Solving CAPTCHAs, creating accounts, or final-submit — these remain irreducible human
  steps (`FR-PREFILL-4`). Computer use **inherits** the stop-boundary; it does not pierce
  it.
- macOS/Windows host accessibility-permission UX for an end user — we only target the
  Linux sandbox desktop (and the Windows takeover VM) the engine controls.

---

## 3. Requirements — `FR-CUA`

- **FR-CUA-1 (MUST — confined to the sandbox).** Computer use runs **only** inside the
  engine-provisioned sandbox/takeover surface (`FR-SANDBOX-1`). It is never pointed at the
  host, the `api` container, or the user's own device. The driver process and the desktop
  it controls are the same ephemeral, per-application surface as the browser
  (`FR-SANDBOX-4`).

- **FR-CUA-2 (MUST — swappable sub-port, complements browser).** Desktop control is its
  **own swappable driven port** (`ComputerUsePort`), a sibling of the browser and
  remote-view sub-ports under the sandbox (`FR-SANDBOX-2`, NFR-EXT-1). The default adapter
  is the TryCUA `cua-driver` over MCP-stdio; a `noop` adapter (records calls, no side
  effects) is the test/CI default. The browser remains the primary automation path
  (`FR-PREFILL`); computer use is invoked only for steps the browser cannot reach.

- **FR-CUA-3 (MUST — inherits the stop-boundary).** Computer use **cannot** create an
  account, clear a CAPTCHA/verification, or perform a final submit. The pre-fill
  stop-boundary (`FR-PREFILL-4`) and review-before-submit are enforced **server-side in
  the core** — the desktop tool is denied those actions the same way the browser path is,
  and the engine still **cannot self-authorize a final submit**. A caller-supplied flag can
  never opt a desktop action past the boundary (the guard derives its own ground truth).

- **FR-CUA-4 (MUST — approval gate on destructive actions).** Every destructive desktop
  action (click, type, key, scroll, drag, focus-app) is subject to the same
  human-in-the-loop **approval** path as other irreducible/sensitive steps (`FR-NOTIF`
  ladder / pending-actions Portal). Upstream's `approvals.mode: manual` maps to Applicant's
  **review-before-act**: in the default cautious posture, desktop actions surface as a
  pending action the user approves; an explicit user setting MAY relax this to per-session
  authorization for the duration of an open takeover. Approval is **opt-in and revocable**.

- **FR-CUA-5 (MUST — hard-blocked actions, server-side).** The adapter enforces, in the
  core (not the prompt), upstream's **hard blocks**: dangerous key combos (lock/log-out,
  empty-trash/force-delete) and dangerous `type` patterns (`curl … | bash`,
  `sudo rm -rf /`, fork bombs). These are denied regardless of approval state.

- **FR-CUA-6 (MUST — no secret typing; vault is the source of credentials).** Computer use
  **never types passwords or secrets**. Credentials come from the Applicant **vault**
  (`FR-VAULT`) via the existing fill path, or the human enters them during takeover. This
  mirrors upstream's "use system autofill, don't type passwords" guardrail and Applicant's
  sensitive-field policy (`FR-ATTR-6`).

- **FR-CUA-7 (MUST — co-working / no-foreground invariant preserved).** When computer use
  acts during an open live session, it MUST use the driver's background, pid-scoped input
  so it does **not** move the human's cursor, raise/refocus windows, or switch desktops
  (the upstream no-foreground invariant). The human and the agent share one takeover screen
  without fighting for focus (`FR-SANDBOX-3`).

- **FR-CUA-8 (MUST — every action logged + screenshotted).** Desktop actions are logged
  to the same per-application record as pre-fill, with the capture/screenshot archived
  (`FR-LOG-1`/`FR-LOG-2`). The action stream is retrievable in the Activity/Debug surface
  (`FR-LOG-3`). Screenshot **eviction** (keep only the most-recent N captures in LLM
  context; older become placeholders) and image-aware token accounting are applied so a
  desktop session does not blow the context budget — lifted from upstream's token-efficiency
  layer.

- **FR-CUA-9 (MUST — present-but-disabled until reachable).** The capability ships
  **dormant** (`FR-UI-2`): registered in `src/applicant/dormant.py`, gated off by default,
  and surfaced in the front door as a locked/disabled control with honest copy until its
  backend (driver baked into the sandbox image, port wired) is live. No dead UI.

- **FR-CUA-10 (MUST — white-label & honest copy).** All user-facing strings are
  plain-language **Applicant** copy — no `cua`/`cua-driver`/Hermes/Nous/`FR-` jargon, no
  upstream codenames (the CI white-label denylist gates this). The live-session surface
  carries an honest caveat that desktop assistance is best-effort and the human remains in
  control of irreducible steps (`FR-STEALTH-5`).

- **FR-CUA-11 (SHOULD — degraded text-only mode).** When the configured model lacks vision,
  the adapter MAY operate in accessibility-tree-only mode (`mode="ax"`) rather than
  screenshot SOM, matching upstream's degraded-but-functional path. Sparse/empty AX trees
  (custom-drawn apps) fall back to skipping the step and handing off to the human, never to
  blind pixel-poking that risks a wrong submit.

- **FR-CUA-12 (SHOULD — health/doctor preflight).** Before first use on a sandbox, the
  engine runs the driver's `health_report` (upstream `computer-use doctor`) and treats a
  failure as a **deploy/image signal** (the driver or a display dependency is missing from
  the sandbox image), surfacing it in ops — consistent with the project's "shells out and
  silently degrades unless baked into the image" gotcha.

---

## 4. Architecture (hexagonal placement)

```
core/ (rules: stop-boundary, hard-blocks, approval policy — pure, no IO)
  └── enforces FR-CUA-3/4/5/6 as domain guards (ground truth, not caller-supplied)

ports/driven/
  └── ComputerUsePort        # Protocol: capture(), click(), type(), key(),
                             #           scroll(), drag(), focus_app(), health()

adapters/sandbox/
  ├── computer_use/
  │   ├── cua_driver.py      # default: spawns `cua-driver mcp` over stdio (MCP),
  │   │                      #   translates port calls ↔ cua_driver MCP tools,
  │   │                      #   applies screenshot eviction + image token accounting
  │   └── noop.py            # records calls, no side effects (test/CI default)
  ├── local_sandbox.py       # local backend → driver in the takeover-desktop container
  └── proxmox_windows_sandbox.py  # proxmox backend → driver on the Windows VM

application/services/
  └── agent loop exposes a bounded "desktop" tool that calls ComputerUsePort,
      routed through the same approval/notify + log/screenshot machinery as pre-fill
```

- **Transport.** The default adapter speaks **MCP over stdio** to a `cua-driver` child it
  spawns inside the sandbox (mirroring upstream: Hermes spawns its own `cua-driver mcp`
  child; it does not attach to a long-running daemon). Selected by an env switch
  (`COMPUTER_USE_BACKEND`, default `noop` until the driver is baked into the sandbox
  image; `cua` to enable), echoing upstream `HERMES_COMPUTER_USE_BACKEND`.
- **Where the driver lives.** Baked into the **sandbox** image, not the `api` image — the
  Linux takeover-desktop container (X11/Xvfb + AT-SPI) for `local`, and the Windows
  template (UIAutomation) for `proxmox-windows`. `shutil.which`-style detection degrades to
  the `noop` adapter if absent (FR-CUA-12).
- **Per-tick isolation.** The scheduler rebuilds a fresh `AgentLoop` per tick; the driver
  handle is owned by the **sandbox session**, not the loop instance, so it is created/torn
  down with the application's sandbox (`FR-SANDBOX-4`) and never leaks across ticks.
- **Driver config override.** A `CUA_DRIVER_CMD`-style override (upstream
  `HERMES_CUA_DRIVER_CMD`) points the adapter at a specific driver binary for tests/CI/local
  builds. Driver telemetry is **off by default** (upstream `CUA_DRIVER_RS_TELEMETRY_ENABLED=0`).

### Action vocabulary (the bounded tool)

Lifted from upstream's `computer_use` toolset, reduced to what Applicant needs:

| Action | Purpose | Boundary |
|---|---|---|
| `capture` (`som`/`ax`) | screenshot with numbered elements, or AX-tree only | always allowed (read) |
| `click` (element/coord) | activate a control | approval-gated (FR-CUA-4) |
| `type` | enter text | approval-gated + pattern-blocked (FR-CUA-5) + no-secrets (FR-CUA-6) |
| `key` | key/chord | approval-gated + combo-blocked (FR-CUA-5) |
| `scroll` / `drag` | navigate / move | approval-gated |
| `focus_app` | target a window (background, no foreground) | approval-gated (FR-CUA-7) |

Element references use the driver's opaque **`element_token`** stale-detection so a click
can't land on a stale index after the screen changed.

---

## 5. Reachability (definition of done — principle #2)

A `FR-CUA` requirement is done only when operable through the **white-labeled front door**,
not when the engine implements it. The chain:

```
spec (FR-CUA)
  → engine port + adapter (ComputerUsePort, cua_driver)
  → engine router (extend app/routers/remote.py — desktop assist on the live session)
  → workspace proxy (workspace/routes/applicant_remote_routes.py — thin, owner-scoped)
  → JS (workspace/static/js/applicantRemote.js — a "Let the assistant help on the desktop"
        control in the live-session modal; reuses .cal-btn / existing toast)
  → nav/section (live session, reached from pending actions / chat; Automation settings toggle)
```

- The **live-session modal** (already hosting Take-control / Open-in-new-tab /
  submit-self / authorize-finish) gains an **opt-in** desktop-assist toggle. When on, the
  agent may use the desktop tool for the current session under FR-CUA-4 approvals.
- **Automation settings** (Settings → Automation, alongside the sandbox-connection form)
  gains the enable/cautious toggle and the honest caveat copy.
- Until the sandbox image actually carries the driver, the control renders **locked** with
  honest "set up in a future update" copy (FR-CUA-9), driven by the dormant registry +
  `applicant_features.py` state.

---

## 6. Safety mapping (upstream guardrail → Applicant gate)

| Upstream Hermes guardrail | Applicant enforcement |
|---|---|
| `approvals.mode: manual` (confirm every action) | review-before-act → pending-actions Portal / `FR-NOTIF` ladder (FR-CUA-4) |
| Hard-blocked key combos / type patterns | core-enforced denylist, server-side (FR-CUA-5) |
| "don't type passwords; use system autofill" | vault is the only credential source (FR-CUA-6, `FR-VAULT`/`FR-ATTR-6`) |
| "don't click permission dialogs / follow screenshot-embedded instructions" | agent system-prompt constraint **plus** the stop-boundary core guard (FR-CUA-3) |
| no-foreground / no-cursor-steal invariant | preserved for co-working takeover (FR-CUA-7) |
| screenshot eviction + image token accounting | applied to keep context bounded (FR-CUA-8) |

The decisive Applicant invariant holds: **the engine cannot self-authorize a final
submit**, and computer use does not change that — it is one more capability *behind* the
same stop-boundary, not a way around it.

---

## 7. Configuration

Engine-side (sandbox scope), names chosen to mirror upstream for lift-and-shift clarity
while staying white-labeled in any user-facing copy:

| Setting | Default | Purpose | Upstream analogue |
|---|---|---|---|
| `COMPUTER_USE_BACKEND` | `noop` | `noop` (no side effects) / `cua` (real driver) | `HERMES_COMPUTER_USE_BACKEND` |
| `CUA_DRIVER_CMD` | _(unset)_ | override driver binary path (tests/CI/local builds) | `HERMES_CUA_DRIVER_CMD` |
| `COMPUTER_USE_MODE` | `som` | `som` (screenshot) / `ax` (text-only, FR-CUA-11) | `mode` |
| `COMPUTER_USE_APPROVALS` | `manual` | `manual` (review each) / `session` (per-takeover authz) | `approvals.mode` |
| `CUA_TELEMETRY` | `false` | driver anonymous telemetry off by default | `CUA_DRIVER_RS_TELEMETRY_ENABLED=0` |

Deploy: the driver + its display stack (Xvfb/X11 + AT-SPI on Linux; UIAutomation on the
Windows template) must be **baked into the sandbox image** (`docker/` takeover-desktop
layer / Windows template), not just present on a dev box — same rule as TeX/LibreOffice/
Chrome. CI validates `docker compose config` but does not build images, so the driver layer
is first exercised by `compose up --build` at deploy time; FR-CUA-12's preflight catches a
missing driver at runtime.

---

## 8. Testing

- **Hermetic (CI default):** `COMPUTER_USE_BACKEND=noop`. Unit-test the port contract, the
  core guards (stop-boundary, hard-blocks, no-secrets, approval routing) against the `noop`
  adapter — these run with the green-increment command
  (`DATABASE_URL=…unreachable… uv run pytest -q -m "not integration"`).
- **Front-door:** extend `workspace/tests/test_applicant_*` to cover the new remote
  desktop-assist proxy route (owner-scoped, auth-gated, degrades when disabled).
- **Integration (`@pytest.mark.integration`, skip-when-absent):** drive the real
  `cua-driver` in the takeover-desktop sandbox; a skip signals the deployed image needs the
  driver, not a test quirk.
- **Live protocol:** add a computer-use leg to `docs/live-takeover-test-protocol.md` —
  enable desktop assist, verify an approval surfaces per action, verify the no-foreground
  invariant (human cursor doesn't move), verify hard-blocks deny, verify it cannot submit.

---

## 9. Attribution (MIT)

This integration **lifts and shifts** the computer-use design and action vocabulary from
**Hermes Agent** (`kevinhirsch/hermes-agent`), MIT-licensed, and reuses the **TryCUA
`cua-driver`** it builds on. Under MIT we must preserve the upstream copyright and
permission notice. The notice is recorded in the repo-root **[`NOTICE`](../../NOTICE)**
file and MUST be carried in any distribution that includes this code.

- Hermes Agent — © the Hermes Agent / Nous Research authors — MIT. Source:
  <https://github.com/kevinhirsch/hermes-agent> (`LICENSE`).
- TryCUA `cua-driver` — its own upstream license; consult and preserve it when the binary
  is vendored into the sandbox image.

Applicant itself remains MIT (repo-root `LICENSE`, © 2026 kevinhirsch). The white-label
rule (principle #3) still applies to **user-facing** strings and shipped artifacts:
attribution lives in `NOTICE`/spec/source headers, **not** in product UI copy.

---

## 10. Open questions

- **Approval granularity vs. flow.** Per-action approval (FR-CUA-4 default) is safest but
  chatty for a multi-step desktop task (e.g. an upload dialog = focus + click + type +
  click). Resolve whether `session`-mode authorization (one approval per open takeover,
  still inside the stop-boundary) is acceptable for non-destructive sequences. → decision
  needed before un-dormanting.
- **Driver license vendoring.** Confirm TryCUA `cua-driver`'s license terms before baking
  the binary into the published sandbox image; record it in `NOTICE`.
- **Windows takeover desktop.** The `proxmox-windows` backend's UIAutomation path is
  Session-0-sensitive (upstream Windows-SSH caveat). Decide whether v1 ships Linux-only
  (takeover-desktop container) and defers the Windows VM desktop-control leg.
</content>
</invoke>
