# ADR-0005: Computer use (desktop control) via TryCUA `cua-driver`, lifted from Hermes Agent

**Status:** Proposed (extends master spec §3.13 `FR-SANDBOX`; new `FR-CUA` group specced in
[`docs/spec/computer-use.md`](../spec/computer-use.md)).

## Context

Applicant automates job applications through the **browser** (patchright/camoufox) inside
an isolated **sandbox** with one-click **live takeover** (`FR-SANDBOX`, `FR-PREFILL`,
`FR-STEALTH`). The browser path cannot reach steps that live outside the page: native OS
file pickers (résumé upload dialogs), occasional desktop apps an ATS launches, OS-level
dialogs, and — more broadly — true **co-working** on the takeover desktop where a human and
the agent share one screen.

The **Hermes Agent** computer-use feature (MIT, `kevinhirsch/hermes-agent`) solves exactly
this: agentic desktop control built on the open-source **TryCUA `cua-driver`**, spoken over
**MCP/stdio**, with a **no-foreground / no-cursor-steal invariant** (pid-scoped input via
platform accessibility layers — AT-SPI/UIAutomation/AX — that never raises windows or moves
the user's cursor). It ships a bounded action vocabulary (capture/click/type/key/scroll/
drag/focus-app), multi-layer safety (per-action approvals, hard-blocked combos/patterns,
no-password-typing), and token-efficiency layers (screenshot eviction, image token
accounting). Per working principle #1, lifting this working component beats rebuilding it.

Upstream is explicit that **web-only tasks should use the headless-browser path**, not
desktop control. That matches Applicant: browser pre-fill is primary; desktop control is a
**complement** for off-page steps, not a replacement.

## Decision

Adopt **TryCUA `cua-driver` over MCP/stdio** as the default adapter behind a new driven
port **`ComputerUsePort`**, a swappable sub-port of the sandbox (sibling of the browser and
remote-view sub-ports), **lifted from Hermes Agent** and adapted to Applicant's gates:

- The driver is spawned as a child **inside the sandbox** (takeover-desktop container for
  `SANDBOX_BACKEND=local`; the Windows VM for `proxmox-windows`) — never the host or `api`
  container. Default backend is `noop` (no side effects) until the driver is baked into the
  sandbox image; `cua` enables the real driver.
- Computer use **inherits Applicant's stop-boundary**: it cannot create accounts, clear
  CAPTCHAs, or final-submit; the guards are enforced **server-side in the core**, not the
  prompt. The engine still cannot self-authorize a submit.
- Upstream guardrails map onto Applicant gates: per-action approvals → review-before-act /
  pending-actions Portal; hard-blocks → core denylist; no-password-typing → vault is the
  only credential source. The no-foreground invariant is preserved for co-working takeover.
- User-facing surfacing is white-labeled (no `cua`/Hermes/Nous codenames; CI denylist
  gates it) and ships **dormant** until reachable.

MIT attribution for Hermes Agent (and the `cua-driver` upstream license) is recorded in the
repo-root **`NOTICE`** and carried in distributions.

Alternatives considered: **build desktop control from scratch on raw Playwright/X11** —
rejected (principle #1; reinvents the no-foreground invariant and the safety layers Hermes
already ships). **Stick to browser-only** — rejected (leaves native upload dialogs and
co-working unhandled). **A different CUA stack (e.g. Anthropic computer-use reference loop
only)** — `cua-driver` is the driver layer; the agent loop/model is orthogonal and already
provided by Applicant's configured model.

## Consequences

- **Positive:** Off-page steps (file pickers, desktop dialogs) and human↔agent co-working
  become reachable in takeover without piercing the safety model. Lift-and-shift of a
  proven component (principle #1). Swappable behind a port (NFR-EXT-1); `noop` keeps CI
  hermetic.
- **Negative / cost:** A new external binary the **sandbox image** must carry (Xvfb/X11 +
  AT-SPI on Linux; UIAutomation on Windows) — same "bake-into-image-or-silently-degrade"
  class as TeX/LibreOffice/Chrome; CI only validates `compose config`, so the layer is
  first exercised at `compose up --build`. Per-action approvals are chatty for multi-step
  desktop tasks (see spec §10 open question). macOS uses private SkyLight SPIs upstream —
  not in scope; we target the Linux sandbox + Windows VM only.
- **License diligence:** the `cua-driver` upstream license must be confirmed and preserved
  in `NOTICE` before the binary is vendored into a published image.
