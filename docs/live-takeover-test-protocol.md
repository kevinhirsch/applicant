# Live-Takeover End-to-End Test Protocol (prod, run locally)

A reproducible protocol for validating the **live-takeover / remote-session** flow
against a real, locally-running production stack. Live takeover is the path where
the engine drives a real browser in a sandbox, the human watches in real time, and
**takes control for the parts only a human may do** — creating an account, clearing
a verification/CAPTCHA, and the final submit. This cannot be exercised in CI or a
plain dev box; it needs the actual sandbox, so test it here before relying on it.

> The engine **cannot self-authorize a final submit** (review-before-submit +
> pre-fill stop-boundary are enforced in the core). This protocol verifies that the
> human handoffs actually work end-to-end, not just that the UI renders.

---

## 0. Which backend are you testing?

There are two sandbox backends (engine `SANDBOX_BACKEND`). Test the one you will run
in production:

| Backend | `SANDBOX_BACKEND` | Browser transport | Human takeover surface | External infra |
|---|---|---|---|---|
| **Local desktop** (simplest "prod locally") | `local` | Chrome launched **inside the `api` container** (no CDP) | the `takeover-desktop` service — a containerized, web-streamed Linux desktop (`--profile takeover`) | none |
| **Proxmox / Windows** (full stealth) | `proxmox-windows` | Chrome on a cloned **Windows VM** over **CDP** (`PROXMOX_CDP_PORT`, default 9222) | RDP / web stream to the VM | a Proxmox host + a prepared Windows template |

Run the matrix below for your backend. If you only have one machine, use **Local
desktop** — it exercises the entire engine↔sandbox↔front-door chain with no Proxmox.

---

## 1. Prerequisites

Common:
- The full Compose stack builds and boots: `docker compose -f docker/docker-compose.prod.yml up -d --build` (the engine image bakes Google Chrome + patchright; verify with `docker compose exec api which google-chrome`).
- A configured LLM (Settings → Connect a model) and a completed profile, so an application can reach pre-fill. Onboarding gate must be open (`GET /api/applicant/setup/status` → `automated_work_allowed: true`).
- At least one approved role in the pipeline (digest → approve) so there is an application to drive.

**Local desktop** extra:
- Bring the desktop up: `docker compose -f docker/docker-compose.prod.yml --profile takeover up -d takeover-desktop`.
- Env: `SANDBOX_BACKEND=local`, `BROWSER_CHANNEL=chrome`, `TAKEOVER_DESKTOP` (e.g. `cinnamon`), and `TAKEOVER_DESKTOP_BASE_URL` set to a host the browser can reach (the one-click live-session link host). Confirm the stream is reachable in a browser before proceeding.

**Proxmox / Windows** extra (set in `.env`, NOT compose):
- `SANDBOX_BACKEND=proxmox-windows`
- `PROXMOX_API_URL`, `PROXMOX_NODE`, `PROXMOX_TOKEN_ID` (+ token secret per your secret mechanism)
- `PROXMOX_TEMPLATE_VMID` (a Windows template with Chrome installed and launched with `--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0` on boot), `PROXMOX_CLONE_MODE` (`linked`/`full`)
- `PROXMOX_CDP_HOST` (blank = use the guest IP), `PROXMOX_CDP_PORT` (default 9222)
- `PROXMOX_TAKEOVER_METHOD` + `PROXMOX_RDP_USERNAME` + `PROXMOX_TAKEOVER_URL_TEMPLATE` for the human view
- Network: the `api` container must reach the VM's CDP port and the Proxmox API; the human's browser must reach the takeover URL.

---

## 2. Smoke tests (do these before the full walk)

Authenticate to the front-door, then (all via the white-labeled `/api/applicant/*`
proxy — the public surface):

1. **Sandbox config accepted.** `GET /api/applicant/setup/sandbox-connection` returns the active backend; `POST` your settings and re-GET to confirm they persisted. In the UI: Settings → Automation.
2. **Caveat copy renders.** `GET /api/applicant/remote/caveat` returns the honest "anti-detection is best-effort…" text (the UI shows it in the live-session modal). Verify it is plain-language and white-labeled (no `FR-`/`NFR-`, no codenames).
3. **Sessions list.** `GET /api/applicant/remote/sessions` returns `[]` (or live sessions) with **200**, never a 5xx.
4. **(Proxmox only) CDP reachable.** From the `api` container: `curl http://<vm-cdp-host>:9222/json/version` returns Chrome's CDP banner. If this fails, the takeover will degrade to the stub — fix networking first.
5. **(Local only) Desktop stream reachable.** Open `TAKEOVER_DESKTOP_BASE_URL` in a browser; you should see the live desktop.

A failure here means the deployed image/host is missing a dependency — that is the
signal to fix the image/network, not the test.

---

## 3. End-to-end walk (the real flow)

Drive it as a user through the front-door. At each step verify **behavior**, not just
HTTP codes.

1. **Approve a role.** Portal → "Today's roles" → Approve (or digest decision). The
   application advances toward pre-fill.
2. **Pre-fill runs in the sandbox.** The engine opens the real browser in the
   sandbox and fills the application up to the **stop boundary** (it will not create
   an account, solve a CAPTCHA, or submit). Verify: the application reaches a
   review/needs-human state, and (Proxmox) a VM was cloned / (Local) Chrome ran in
   the `api` container.
3. **Final-approval request surfaces.** `POST /api/applicant/remote/applications/{id}/request-final-approval` is what the engine calls; the Portal should show a pending action whose action carries a **live-session view URL**. Verify the notification copy is plain-language.
4. **Open the live session.** Portal action → "Open live session" (or Settings →
   Open live session). The remote modal opens: `GET /api/applicant/remote/sessions`
   then `GET /api/applicant/remote/sessions/{id}/view-url`. Verify the live view
   (iframe/stream) actually shows the sandbox browser, and the controls render:
   **Take control, Open in new tab, Refresh sessions**, the account/verification
   handoffs, **I'll submit it myself**, **Authorize the assistant to finish**.
5. **Take control.** Click **Take control** (`POST …/sessions/{id}/takeover`). Verify
   input now routes to you in the live view (type in a field; it appears in the
   sandbox browser). Test "Open in new tab" as a fallback path.
6. **Account-creation handoff.** Do the account creation yourself, then click
   **"I created the account — continue"** (`POST …/applications/{id}/resume-account-step`).
   Verify the engine resumes pre-fill from where it stopped (does not redo your work).
7. **Verification handoff.** When a verification/CAPTCHA appears, solve it, then click
   **"I cleared the verification — continue"** (`POST …/applications/{id}/resume-detection-step`).
   Verify the engine resumes.
8. **Final submit — both branches:**
   - **Human submits:** click **"I'll submit it myself"** (`POST …/applications/{id}/submit-self`); submit in the live view; verify the application is marked submitted and the action clears from the Portal.
   - **Authorize engine:** on a separate application, click **"Authorize the assistant to finish"** (`POST …/applications/{id}/authorize-engine-finish`); verify the engine completes the submit ONLY after this explicit authorization, and the outcome is logged.
9. **Credential capture → Vault.** If you created/typed credentials during takeover,
   verify the Vault offers to save them (Settings → Saved sign-ins / `GET
   /api/applicant/vault/{campaign_id}/tenants`) and that the saved sign-in appears.
10. **Outcome + teardown.** Verify `GET /api/applicant/admin/outcomes/{id}` /
    `…/log/{id}` records the submit, and the sandbox is torn down (Proxmox: the cloned
    VM is destroyed; Local: Chrome exits). No orphaned VMs/processes.

---

## 4. Failure & edge cases (must degrade gracefully, never crash)

- **Sandbox unavailable** (Proxmox API down / desktop service stopped): the live
  session shows the honest empty state ("No live session is open yet.") and the
  Portal still lets the human take over manually; no 5xx.
- **CDP drops mid-session** (Proxmox): the engine should surface a recoverable error
  and offer reconnect/refresh, not silently hang.
- **Token gating:** with `APPLICANT_INTERNAL_TOKEN` unset, the engine↔workspace
  callback channel is disabled — confirm the live-session features degrade cleanly.
- **Authorization gate:** confirm the engine **never** submits without an explicit
  `submit-self` (human) or `authorize-engine-finish` — try to advance past pre-fill
  without either and verify it blocks.
- **Refresh/resume durability:** close the live-session tab mid-flow and reopen; the
  session and its turn state should resume (durable orchestration).

---

## 5. Wiring-only test WITHOUT a Windows VM (optional, fastest)

To exercise the CDP plumbing without Proxmox: run a headful Chrome anywhere the `api`
container can reach it with `--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0`,
set `SANDBOX_BACKEND=proxmox-windows` with a `FakeProxmoxClient`-style stub (or point
`PROXMOX_CDP_HOST`/`PORT` at that Chrome) and confirm `connect_over_cdp` attaches and
pre-fill drives it. This validates the CDP seam end-to-end; it does **not** validate
the Proxmox provisioning or the Windows takeover surface, so still run §3 on the real
backend before launch.

---

## 6. Sign-off checklist (low-risk launch)

- [ ] Smoke tests (§2) all green for your backend.
- [ ] Full walk (§3) steps 1–10 verified, both submit branches.
- [ ] Failure cases (§4) degrade gracefully (no 5xx, no orphaned VMs, no submit without authorization).
- [ ] Live-session + caveat copy is plain-language and white-labeled.
- [ ] Vault captured any credentials entered during takeover.
- [ ] Sandbox torn down after each run.
