# EPIC SUPERVISED-APPLY — Camoufox supervised-desktop prefill + visual preview

**Owner:** Kevin · **Raised:** 2026-08-11 · **Priority: P0 / CORE**

## Why (Kevin, verbatim intent)
> "A core feature of Applicant is that it needs to be able to drive a full desktop
> environment with Camoufox and other applications that can be supervised through the
> browser. That would be the only way I could send an application myself that was
> prefilled and I would know exactly what was sent. Like I would need to visually
> preview it."

This is THE feature that makes the product trustworthy + usable for Kevin: Applicant
**prefills** an application in a **real Camoufox browser inside a supervised desktop he
can watch**, he **visually verifies exactly what will be submitted**, and **he** sends it.
Never auto-submit — that invariant is absolute.

## REUSE-FIRST — this is assemble + wire + deploy, NOT greenfield
The architecture already exists in design + substantial code:
- **`FR-STEALTH`** — `src/applicant/adapters/browser/stealth.py` (patchright / **Camoufox**), `core/stealth_policy.py`.
- **`FR-SANDBOX`** — `src/applicant/adapters/sandbox/remote_view.py`: containerized Ubuntu
  **webtop desktop** (Cinnamon/Xfce/GNOME on X11) with a one-click **live-session URL**
  (short-lived per-session token) for **view + takeover through the browser**; Neko/noVNC
  are swappable backends. `proxmox_windows_sandbox.py` = Windows-VM backend.
- **`FR-PREFILL`** — `application/services/prefill_service.py` + `core/rules/prefill_boundary.py`:
  fills ONLY from stored answers (never AI-guessed), routes every click through the
  **pre-fill-stop boundary** (never account-create, never final-submit, never CAPTCHA-solve),
  emits `BLOCKED_*` / `AWAITING_*` states + pending actions. Boundary is enforced
  **server-side in core**, not the prompt.
- **`FR-CUA`** — ADR-0005 (`docs/adr/0005-computer-use-cua-driver.md`): TryCUA `cua-driver`
  over MCP for off-page steps (résumé-upload native file pickers, OS dialogs) inside the
  sandbox; inherits the server-side stop-boundary; default backend `noop` until baked.

## The gap
These sub-ports are architected + partially built, but real backends **default to
noop/local-stub** and the **end-to-end flow is not wired + deployed + verified** on
10.0.1.11. Today Kevin CANNOT: pick a role → "Prefill application" → watch a live Camoufox
session in a webtop desktop fill from his stored answers → visually verify every field →
take over + submit himself.

## DoR
Four sub-ports exist behind clean ports; the sandbox image can bake webtop + Camoufox +
cua-driver; a queued role resolves to an apply URL + the stored-answer set; the stop-boundary
is enforced server-side (existing prefill tests green).

## AC (BDD / Gherkin)
```gherkin
Scenario: Prefill opens a watchable live session
  Given a role in my queue with a real apply URL
  When I click "Prefill application"
  Then a real Camoufox session opens inside a webtop desktop
  And I receive a one-click live-view URL to watch it

Scenario: Fields fill only from my stored answers, visibly
  Given the prefill is running in the live session
  Then every field is populated ONLY from my stored answers (never AI-guessed)
  And I can see each value being entered in the live view

Scenario: The agent stops at the submit boundary
  Given the form reaches a final submit, account-create, or CAPTCHA
  Then the agent stops at the boundary and hands control to me
  And it never clicks submit

Scenario: I verify and submit myself
  Given I have watched exactly what was filled
  When I take over the live session
  Then I can review every field and click submit myself
  And Applicant records what was submitted

Scenario: Off-page résumé upload
  Given a native file-picker dialog for résumé upload
  Then the CUA driver completes the pick inside the sandbox
  And it remains under the no-submit boundary

Scenario: Offline parity
  Given no LLM is configured
  Then stored-answer prefill still runs (the fill itself has no model dependency)
```

## DoD
Sandbox image baked (webtop + Camoufox + cua-driver) + deployed on 10.0.1.11; a "Prefill
application" affordance in the review UI mints a live-view URL; prefill fills from stored
answers with visible per-field entry; the stop-boundary is proven (attempted submit /
account-create / CAPTCHA → blocked) by tests **and** a live run; the takeover → user-submit
path records the submission; TDD + BDD; browser-verified end-to-end on 10.0.1.11; the
never-auto-submit invariant intact; GitHub `main` + Obsidian synced.

## Slices (overnight loop builds these, each TDD + commit/push/sync + browser-verify)
- **S1** — Map real-vs-noop/stub state of each sub-port (stealth/sandbox/prefill/cua) + the
  deploy state on 10.0.1.11; write the gap register.
- **S2** — Bake + deploy the sandbox image (webtop + Camoufox); prove a live-view URL opens
  and is controllable from the browser on 10.0.1.11.
- **S3** — Wire `prefill_service` to a real sandbox Camoufox session for ONE queued role;
  stored-answer fill; live-view shows the fields populate.
- **S4** — "Prefill application" affordance + live-view deep link in the review surface.
- **S5** — Hard-prove the stop-boundary (attempt submit → blocked) + wire takeover →
  user-submit recording.
- **S6** — CUA file-picker for résumé upload (off-page step), still under the boundary.
