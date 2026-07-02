# Applicant — Settings & Configuration, End to End (lens 11)

> **Lens.** The entire configuration surface: the Settings-modal IA, every engine env var in
> `src/applicant/app/config.py` (exposure matrix below), validation-on-save, the save model,
> defaults sanity, findability, export/backup, installer ↔ in-app parity, restart honesty,
> dangerous-setting guards, and per-campaign vs global clarity.
>
> Grounded in: `src/applicant/app/config.py`, `src/applicant/app/routers/setup.py`,
> `src/applicant/application/services/setup_service.py`, `scripts/install.sh`,
> `docker/docker-compose.prod.yml`, `.env.example`, `workspace/static/js/settings.js`,
> `workspace/static/js/applicantOnboarding.js`, `applicantModelLadder.js`,
> `applicantCampaignSettings.js`, `workspace/routes/applicant_setup_routes.py`.
>
> **Dedup:** excludes items already listed in `PRODUCT_EXHAUSTIVE_AUDIT.md` /
> `exhaustive/quick-wins-cross-cutting.md` — the wallpaper picker (#24), low-power toggle (#25),
> first-campaign default seed (#36), plain-language microcopy renames (#28–29), skipped-step
> breadcrumbs (§7.7), and local-model auto-detect (§7.2).
>
> Format: `N. **Title** — [VALUE · EFFORT] — rationale + anchor.`

---

## Part 1 — The engine env-var exposure matrix

Every field of `Settings` in `src/applicant/app/config.py` (~93 vars), and where it can actually
be set today. Legend:

- **UI** — runtime-editable through the front-door (wizard/Settings → engine setup API →
  `app_config` table / vault). The engine's runtime-write surface is *only*
  `src/applicant/app/routers/setup.py`, persisting exactly four keys
  (`setup_service.py:137-140`): `llm.tier_ladder`, `wizard.steps_complete`, `notify.channels`,
  `sandbox.proxmox_windows`.
- **Compose** — has a `${VAR:-default}` passthrough in `docker/docker-compose.prod.yml`'s `api`
  service, so it is *reachable* in the shipped deploy (via exported env at `install.sh` time).
- **.env.ex** — documented in the root `.env.example`.
- **Docs** — mentioned anywhere under `docs/` (mostly `docs/overview.md`).
- **Installer** — `scripts/install.sh` prompts for **none** of these. It generates
  `APPLICANT_INTERNAL_TOKEN` (`install.sh:318`), and its interactive reconfigure covers only
  address/port (`install.sh:400-437`). The column is therefore omitted.
- **Verdict** — `UI` (runtime-editable), `deploy` (compose-reachable, env-only),
  `documented-dark` (in `.env.example`/docs but **not plumbed into the `api` container** — see
  item 1), `dark` (no UI, no installer, no compose, no docs).

| Env var (config.py) | Default | UI | Compose | .env.ex | Docs | Verdict |
|---|---|---|---|---|---|---|
| `APPLICANT_MODE` (:158) | "" | – | – | ✓ | – | documented-dark |
| `DATABASE_URL` (:161) | localhost PG | – | ✓ (:108) | ✓ | ✓ | deploy |
| `APP_STATIC_DIR` (:167) | frontend/static | – | ✓ (:109, pinned) | ✓ | – | deploy |
| `LLM_PROVIDER/_BASE_URL/_API_KEY/_MODEL` (:170-173) | "" | **✓** setup `/llm`, `/llm/tiers` | – | ✓ | ✓ | **UI** |
| `CONTEXT_COMPRESS_THRESHOLD` (:179) | 64000 | – | – | – | ✓ | documented-dark |
| `PREFIX_CACHE` (:182) | auto | – | – | – | ✓ | documented-dark |
| `CREDENTIAL_KEYFILE` (:185) | secrets/master.key | – | ✓ (:114) | ✓ | ✓ | deploy |
| `PII_RETENTION_DAYS/_SCHEDULE` (:192,196) | 0 / off | – | – | – | – | **dark** |
| `ORCHESTRATOR_BACKEND` (:199) | shim | – | ✓ (:118) | ✓ | ✓ | deploy |
| `CHECKPOINT_DIR` (:200) | .applicant_checkpoints | – | ✓ (:123) | ✓ | ✓ | deploy |
| `APPROVAL_TIMEOUT_DAYS` (:207) | 30 | – | – | – | – | **dark** |
| `APPROVAL_WAIT_SECONDS` (:215) | None | – | – | – | – | **dark** |
| `SCHEDULER_ENABLED` (:223) | True (comment says off!) | – | ✓ (:130) | ✓ | ✓ | deploy |
| `SCHEDULER_INTERVAL_SECONDS` (:224) | 60 | – | – | ✓ | ✓ | documented-dark |
| `LOOP_FAILURE_ALERT_THRESHOLD` (:233) | 3 | – | – | – | – | **dark** |
| `SANDBOX_CONCURRENCY` (:239) | 3 | – | – | ✓ | ✓ | documented-dark |
| `LLM_RATE_LIMIT/_PERIOD` (:240-241) | 30/min | – | – | ✓ | – | documented-dark |
| `LOG_FORMAT` (:244) | pretty | – | pinned `json` (:208, no `${}`) | ✓ | – | documented-dark |
| `LOG_LEVEL` (:245) | INFO | – | – | ✓ | – | documented-dark |
| `DISCORD_WEBHOOK_URL` (:249) | "" | **✓** setup `/channels` | – | ✓ | ✓ | **UI** |
| `APPRISE_URLS` (:250) | "" | **✓** `/channels` | – | ✓ | ✓ | **UI** |
| `NTFY_URL` (:254) | "" | **✓** `/channels` | – | – | ✓ | **UI** |
| `NOTIFICATIONS_LIVE` (:255) | False | – | ✓ (:135, true) | – | ✓ | deploy |
| `WORKSPACE_URL` (:264) | applicant-ui:7000 | – | pinned (:151) | – | ✓ | deploy |
| `APPLICANT_INTERNAL_TOKEN` (:265) | "" | – | ✓ (:152) + installer-generated | – | ✓ | deploy |
| `MATERIAL_RESEARCH_ENABLED` (:279) | False | – | ✓ (:197) | – | – | deploy |
| `MIND_BACKEND` (:289) | in_memory (bridge in prod) | – | ✓ (:160) | ✓ | ✓ | deploy |
| `MEMORY_WRITE_APPROVAL` / `SKILLS_WRITE_APPROVAL` (:293-294) | True | – | ✓ (:161-162) | ✓ | ✓ | deploy |
| `MEMORY_MAX_CHARS` / `USER_MAX_CHARS` (:297-298) | 8000/4000 | – | ✓ (:163-164) | ✓ | ✓ | deploy |
| `CURATION_SCHEDULE` (:302) | off | – | ✓ (:165, off) | ✓ | ✓ | deploy |
| `ESSENTIALS_NUDGE_SCHEDULE` (:308) | daily | – | ✓ (:170) | ✓ | – | deploy |
| `STATUS_UPDATE_SCHEDULE` (:313) | off | – | ✓ (:171) | ✓ | – | deploy |
| `CURATION_MODEL` (:316) | "" | – | ✓ (:166) | ✓ | ✓ | deploy |
| `CHAT_TOOLS` (:324) | off | – | – | – | ✓ | documented-dark |
| `LOOP_TOOLS` (:334) | off | – | – | – | – | **dark** |
| `FONTS_DIR` (:338) | .applicant_fonts | – | ✓ (:117) | – | – | deploy |
| `BROWSER_PROFILES_DIR` (:344) | .applicant_profiles | – | ✓ (:127) | – | – | deploy |
| `RESUME_RENDER` (:350) | auto | – | – | – | – | **dark** |
| `DISCOVERY_LIVE` (:354) | False | per-campaign source toggles only | ✓ (:134, true) | – | ✓ | deploy |
| `SEARXNG_URL` (:355) | "" | – | ✓ (:145) | – | ✓ | deploy |
| `DISCOVERY_PROXIES` (:357) | "" | – | – | – | ✓ | documented-dark |
| `EGRESS_MODE` / `EGRESS_PROXY_URL` (:363-364) | direct / "" | – | – | ✓ | ✓ | documented-dark |
| `EGRESS_RESIDENTIAL` (:369) | False | – | – | – | ✓ | documented-dark |
| `BROWSER_ENGINE` (:377) | camoufox | – | ✓ (:144) | ✓ | – | deploy |
| `BROWSER_CHANNEL` (:384) | chrome | – | – | – | ✓ | documented-dark |
| `BROWSER_REAL` (:392) | False | – | ✓ (:140, true) | – | ✓ | deploy |
| `ATS_MATCH_RATE_FLOOR` (:402) | 0.2 | – | – | – | – | **dark** |
| `ALLOW_AUTOMATED_ACCOUNTS` (:411) | False | – | – | ✓ | ✓ | documented-dark |
| `CAPTCHA_STRATEGY/_SERVICE/_API_KEY` (:425-430) | human/capsolver/"" | – | ✓ (:204-206) | – | ✓ | deploy |
| `EGRESS_PROXY` (:433) | "" | – | ✓ (:207) | – | – | deploy |
| `COMPUTER_USE_BACKEND/_MODE/_APPROVALS` (:443-452) | noop/som/manual | – | ✓ (:177-180) | ✓ | ✓ | deploy |
| `CUA_DRIVER_CMD` / `CUA_TELEMETRY` (:445,454) | "" / False | – | ✓ (:178,181) | ✓ | ✓ | deploy |
| `CUA_DRIVER_OVERRIDE_AVAILABLE` (:460) | False | – | – | – | – | **dark** |
| `EGRESS_TIMEZONE` / `EGRESS_LOCALE` (:469-470) | America/Phoenix / en-US | – | – | – | ✓ | documented-dark |
| `TAKEOVER_DESKTOP` (:478) | cinnamon | – | – (only IMAGE) | ✓ | ✓ | documented-dark |
| `TAKEOVER_DESKTOP_IMAGE` (:480) | "" | – | ✓ (:275) | ✓ | ✓ | deploy |
| `REMOTE_VIEW_BACKEND` (:483) | webtop | – | – | ✓ | ✓ | documented-dark |
| `TAKEOVER_DESKTOP_BASE_URL` (:485) | `https://sandbox.local/webtop` | – | – | – | ✓ | documented-dark |
| `SANDBOX_BACKEND` (:495) | local | status shown, **not switchable** | – | ✓ | ✓ | documented-dark |
| `STEALTH_PERSONA` (:500) | "" (derived) | – | – | ✓ | ✓ | documented-dark |
| `PROXMOX_*` (10 vars, :506-525) | "" | **✓** setup `/sandbox-connection` (env is fallback only) | – | ✓ | ✓ | **UI** |
| `PREFILL_USE_PLANNER` (:532) | False | – | – | – | – | **dark** |
| `LLM_SMART_ROUTING/_PREFER_LOCAL` (:546-550) | True/True | – | ✓ (:190-191) | – | – | deploy |
| `PRESUBMIT_MAX_LISTING_AGE_DAYS` (:556) | 90 | – | – | – | – | **dark** |
| `PRESUBMIT_DUPLICATE_COOLDOWN_DAYS` (:561) | 30 | – | – | – | – | **dark** |
| `PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY` (:565) | 3 | – | – | – | – | **dark** |
| `PRESUBMIT_ELIGIBILITY_ENABLED` (:571) | True | – | – | – | – | **dark** |

**Runtime knobs that are NOT env vars** (core constants / DB columns):

| Knob | Where | Default | User-editable? |
|---|---|---|---|
| Daily throughput target | `core/entities/campaign.py:19,39` | **15/day, hard cap 30** | ✓ per-campaign UI (`applicantCampaignSettings.js:96-100`) + chat (`chat_service.py:1195+`) |
| Exploration budget | campaign column | — | ✓ per-campaign UI (`applicantCampaignSettings.js:101-106`) |
| Run mode | campaign column | continuous | ✓ per-campaign UI |
| Discovery-source on/off | per-campaign | on | ✓ (`applicantCampaignSettings.js:146-159`) |
| Ghosting SLA | `post_submission_service.py:21,115` | **14 days** | ✗ hardcoded |
| Silence/ghost SLA (second one!) | `silence_service.py:21` | **30 days** | ✗ hardcoded |
| Follow-up due | `followup_service.py:21` | 10 days | ✗ hardcoded |
| Thank-you / check-in delay | `post_submission_service.py:22-23` | 2 h / 7 days | ✗ hardcoded |
| Digest delivery time | `agent_loop.py:253-257,522-531` | first tick after UTC midnight | ✗ **does not exist as a knob** |
| Quiet hours + per-channel hold | `app_config` `notify.channels` | off / 22:00–07:00 | ✓ UI (`setup.py:268`) |
| Email escalation backstop | same | 15 min | ✓ UI (`setup.py:58`) |

---

## Part 2 — Ranked findings

1. **The `.env` config surface is dead for the engine — `api` gets no `env_file`** — [VALUE: high · EFFORT: S] — `.env.example` documents ~50 engine vars and says "Copy to .env and edit," but in `docker/docker-compose.prod.yml` only `applicant-ui` loads `../.env` (`docker-compose.prod.yml:36-38`); the `api` service (`:94-238`) does not. A var reaches the engine only if the compose `environment:` block explicitly references it with `${…}` — so `SANDBOX_BACKEND=proxmox-windows`, `EGRESS_MODE=residential-proxy`, `TAKEOVER_DESKTOP=gnome`, `LOG_LEVEL=DEBUG`, `APPLICANT_MODE=production`, `SCHEDULER_INTERVAL_SECONDS`, `LLM_RATE_LIMIT`, all `PROXMOX_*` fallbacks etc. set in `.env` are **silently ignored** in the shipped deploy. Every "documented-dark" verdict in the matrix is this one bug. Fix: add `env_file: {path: ../.env, required: false}` to the `api` service (one hunk) and the whole documented surface comes alive.

2. **There is no "Engine" settings pane — build one on the runtime-config pattern that already exists** — [VALUE: high · EFFORT: L] — The engine's entire runtime-tunable surface is four `app_config` keys (`setup_service.py:137-140`) behind `routers/setup.py`; everything else is env-frozen at boot. Yet the zero-restart pattern is already proven: `POST /channels` reconfigures the live notifier in place (`setup.py:251-259`). Add an owner/admin "Engine" pane (a `GET/PUT /api/setup/engine-config` over `app_config`) for the knobs users actually feel: digest time (item 6), ghosting/follow-up SLAs (items 11, 21), pre-submit caps (item 22), approval timeout (item 23), status-update/curation schedules (items 40–41), PII retention (item 43) — each with its plain-language label, default, and a "restart needed?" badge (item 20). This is the parent of a dozen items below.

3. **Settings offers "My own Windows VM (Proxmox)" but the backend can never actually switch** — [VALUE: high · EFFORT: M] — The Automation pane's picker (`applicantOnboarding.js:777-780`) renders `local` vs `proxmox-windows`, and the form saves the connection — but the POST body has no backend field (`_renderSandbox` collect, `applicantOnboarding.js:901-911`; `SandboxConnectionIn`, `setup.py:79-97`), and `SetupService._sandbox_backend` is fixed at boot from `SANDBOX_BACKEND` (`setup_service.py:158-172`), which is neither compose-wired nor installer-set (matrix). So a user can fill in the whole Proxmox form and the engine keeps driving the local sandbox forever — the picker is a silent lie. Either persist the backend choice via the same endpoint (and rebuild the sandbox adapter or flag "takes effect after restart"), or render the picker read-only with an honest "selected at deploy time" note.

4. **Per-channel quiet-hours choice is silently dropped by the front-door proxy** — [VALUE: high · EFFORT: S] — The UI sends `discord_respects_quiet` / `email_respects_quiet` (`applicantOnboarding.js:649-650`) and the engine accepts them (`setup.py:75-76`), but the workspace proxy's `QuietHoursIn` model only declares `enabled/start/end/tz` and forwards `body.model_dump()` (`workspace/routes/applicant_setup_routes.py:132-143,399`), so pydantic discards the fields. "Hold Discord overnight, send email anytime" saves with a success toast and never takes effect. Add the two fields to the proxy model (+ a proxy-fidelity regression test that diffs proxy body models against engine ones).

5. **A configured notification channel can never be removed from the UI** — [VALUE: high · EFFORT: S] — `POST /api/setup/channels` rejects a body with no channel and no timeout ("Add a Discord webhook and/or an email address…", `setup.py:235-244`), and the ntfy field treats blank as "keep saved" (`applicantOnboarding.js:585-588`). So once Discord/email/ntfy are set there is no way to clear one (revoked webhook, changed address) or turn push off — only quiet hours forever. Add explicit per-channel "Remove" affordances and let the engine accept an explicit-empty write.

6. **Daily digest time doesn't exist as a setting — it lands whenever the first tick after UTC midnight runs** — [VALUE: high · EFFORT: M] — The digest is delivered once per (campaign, UTC day) by the loop ledger (`agent_loop.py:253-257,522-531`); with a 60 s tick that means ~00:00 UTC — evening/afternoon in the Americas, and quiet hours only *defer the push*, not the generation moment (`adapters/notification/apprise_notifier.py:19`). "Your digest arrives at 7 am with your coffee" is the product's core ritual (Journey Beat 3) and it is currently un-settable. Add `digest_hour` + timezone (reuse the quiet-hours tz) to the Notifications pane and gate the ledger on it.

7. **The Settings IA has no "Applicant" group — engine settings are scattered across three unlabeled clusters** — [VALUE: high · EFFORT: M] — The 17-tab sidebar (`index.html:1588-1666`) intermixes: Campaign (tab 3), Fonts (5), Automation (6), Update (7) in the "AI plumbing" group; Applicant Notifications (11) in the comms group; while the ladder, vault, live-session, and re-run-setup cards hide *inside* the AI-Defaults panel (`index.html:1681-1701`). A user hunting "where do I change how my job search behaves" must know that "Campaign" ≠ "AI Defaults" ≠ "Automation" ≠ "Notifications" are all the same product. Proposed taxonomy: one labeled **Applicant** sidebar section (mirroring the existing "Admin" label pattern, `index.html:1653`) containing *Job searches (campaigns) · Models (ladder + endpoints) · Notifications · Documents & fonts · Automation & sandbox · Privacy & data · Update*; leave workspace-native chat/appearance/account groups as-is.

8. **No capability/dependency report anywhere in Settings — silent degradation is invisible** — [VALUE: high · EFFORT: M] — The engine detects TeX, LibreOffice, the browser, and the desktop driver via `shutil.which()` and *silently degrades* when absent (CLAUDE.md "Runtime dependencies"; `RESUME_RENDER=auto`, `config.py:346-350`). A deploy with a broken image renders stub resumes and simulated pre-fill with no UI signal. Add a "System report" card (Settings → Update/System): real-render available (TeX/LibreOffice), browser engine + binary present, desktop-assist driver, notifications live/dry (item 28), orchestrator backend, egress mode. The desktop-assist card already models the honest-state pattern (`applicantOnboarding.js:743-761`) — generalize it.

9. **The model ladder makes users re-type URL + key that the endpoint manager already stores — and has no test button** — [VALUE: high · EFFORT: M] — Tiers are free-text provider/URL/key/model rows (`applicantModelLadder.js:104-119`) even though saved endpoints with sealed keys, providers, and *probing* already exist (`admin.js:366,646`; `POST /api/model-endpoints/test`, `model_routes.py:1093`) and the wizard already wires "endpoint → engine" via `/llm/from-endpoint` (`setup.py:153-179`). Lift-and-shift (CLAUDE.md principle #1): let each tier pick a saved endpoint + model (with per-tier override for the exotic case), and add "Test this level" reusing the existing probe. Kills the double-entry, the unvalidated key, and the no-feedback save in one move.

10. **Standardize the save model — four different persistence behaviors coexist, two inside a single tab** — [VALUE: high · EFFORT: M] — AI-Defaults cards auto-save per field on `change` (`settings.js:548-549,617-618,786-788`); Reminders debounce-save on input (`settings.js:2232-2251,2455-2471`); the ladder and campaign cards need explicit Save (`applicantModelLadder.js:139`, `applicantCampaignSettings.js:108`); Appearance writes localStorage instantly (`settings.js:1601-1650`). Within the Campaign tab, field edits need "Save changes" but source toggles persist immediately (`applicantCampaignSettings.js:146-159`). Pick one rule (suggest: instant-save for single toggles/selects, explicit Save + dirty badge for multi-field cards), document it, and apply it across panes.

11. **Two contradictory ghosting SLAs are hardcoded — 14 days in one service, 30 in another** — [VALUE: high · EFFORT: S] — `post_submission_service.py:21` (`DEFAULT_SLA_DAYS = 14`, and `check_ghosting(..., sla_days=14)` at `:115`) vs `silence_service.py:21` (`DEFAULT_GHOST_SLA_DAYS = 30`). Same concept ("how long is silence before we call it ghosted"), divergent by 2×, neither env-configurable nor UI-visible. Verdict on the defaults themselves: 14 days is aggressive for large-company pipelines (4–6-week cycles are normal), 30 is defensible; but first *unify* them into one constant, then expose it per-campaign ("consider an application ghosted after N days", default 21–30) in the Campaign tab / Engine pane.

12. **The installer's "reconfigure" covers exactly two things — publish address and port** — [VALUE: med · EFFORT: M] — `maybe_reconfigure`/`configure_web_server` (`install.sh:400-465`) prompt only for host + port; the help text (`install.sh:244-249`) adds `POSTGRES_*` and the apt mirror as pre-set env, and that's the entire installer config domain. Parity matrix: **installer-settable** = APP_URL/APP_PORT (+POSTGRES_* preset, secrets generated); **UI-settable** = LLM/tiers/channels/quiet-hours/Proxmox/campaigns/fonts; **neither** = everything else in the matrix. That's a defensible zero-CLI split *if* item 1 is fixed and the dry-run/`--help` text points at where each class lives — today it never mentions `.env.example` or that engine tuning exists at all. Add one "Advanced: engine options live in .env (see .env.example); Settings covers the rest" breadcrumb to `show_config` (`install.sh:168-180`).

13. **No config export/import — enumerate and close the reinstall-loss story** — [VALUE: high · EFFORT: M] — What a user loses on a lost host or `--purge` (`install.sh:730-743` deletes volumes *and* `.env`): the vault master key (all sealed credentials become permanently undecryptable — compose warns at `docker-compose.prod.yml:110-114`), Postgres (campaigns, profile, learning, audit), shim checkpoints, installed fonts, signed-in browser profiles, the UI sqlite, and `.env` (`POSTGRES_PASSWORD`, `APPLICANT_INTERNAL_TOKEN`). The workspace has `/api/export`–`/api/import` (`admin.js:1965-2005`) but it covers only the UI app — no engine equivalent exists. Add (a) a "Download settings backup" (app_config + campaigns + criteria, secrets excluded or key-wrapped) in Settings, (b) a `--backup` installer verb bundling `pg_dump` + `.env` + the secrets volume, and (c) a pre-purge prompt offering it.

14. **Every deployment fingerprints as Phoenix, Arizona by default** — [VALUE: high · EFFORT: M] — `EGRESS_TIMEZONE=America/Phoenix`, `EGRESS_LOCALE=en-US` (`config.py:464-470`) are threaded into the browser context so tz/locale match the exit IP — but they're documented-dark (matrix), so a user in Berlin runs automation whose clock claims Arizona while egressing from a German residential IP: exactly the incoherence the stealth layer exists to avoid (FR-STEALTH-1↔4). Derive the default from the host's tz (or the onboarding location section, which already collects it), and surface it read-only in the Automation pane with an override.

15. **Takeover links point at `https://sandbox.local/webtop` out of the box** — [VALUE: high · EFFORT: S] — `TAKEOVER_DESKTOP_BASE_URL` defaults to a placeholder domain (`config.py:485-487`, wired at `container.py:288`) and is absent from compose, installer, and `.env.example`. The one-click "take over" moment — the product's highest-gravity interaction — mints a dead URL on a default deploy. Default it from `APP_URL` + the published `TAKEOVER_PORT` (both known to the installer, `install.sh:356-372`), and show the resolved link in the Automation pane so a misconfiguration is visible before a takeover is ever needed.

16. **The takeover desktop service itself can't be enabled from the installer or Settings** — [VALUE: high · EFFORT: M] — The `takeover-desktop` service ships behind `--profile takeover` (`docker-compose.prod.yml:273-274`); the only mention of how to start it is a test-protocol doc (`docs/live-takeover-test-protocol.md:39`). `install.sh` never offers the profile, and no Settings surface reflects "the takeover desktop is not deployed." A user reaches their first CAPTCHA/final-submit and the live view has nothing behind it. Add an installer question ("Enable the takeover desktop? [Y/n]" → persist `COMPOSE_PROFILES=takeover` to `.env`) and an honest state in the Automation pane when the service is absent.

17. **The Proxmox connection form has no "Test connection"** — [VALUE: high · EFFORT: M] — Nine fields including an API token and RDP credentials (`applicantOnboarding.js:788-823`) are saved with only presence checks (`:913`); a wrong URL/token/VMID surfaces only when the first takeover session fails to clone a VM. Channels have "Send a test" (`setup.py:300`), model endpoints have `/test` (`model_routes.py:1093`) — the *highest-stakes* connection form is the only one without a probe. Add `POST /api/setup/sandbox-connection/test` (Proxmox API version check + node exists + VMID found + optional CDP reachability), with per-check results.

18. **`SCHEDULER_ENABLED`: comment, code, and `.env.example` disagree three ways** — [VALUE: med · EFFORT: S] — The field comment says "OFF by default so the default test lane… never spins a live background loop" but the default is `True` (`config.py:219-223`); `.env.example:37` documents `SCHEDULER_ENABLED=false` as the shipped default; compose sets true (`:130`). Whichever is intended, two of the three are lying to whoever reads them — and a hand-run engine (`uvicorn` outside compose) quietly runs the 24/7 loop against whatever DB it finds. Align the default with the comment (False) or rewrite the comment + `.env.example`.

19. **`APPLICANT_MODE=production` — the master preset — is fully dark and disagrees with the shipped compose** — [VALUE: med · EFFORT: S] — The one-switch production preset (`config.py:158,575-597`) selects `orchestrator_backend=dbos`, while `docker-compose.prod.yml:118` defaults `ORCHESTRATOR_BACKEND=shim` and sets the other four flags individually — so the "production" the preset defines and the production the stack ships are different systems, and no doc mentions `APPLICANT_MODE` at all (matrix). Either make compose use `APPLICANT_MODE=production` + overrides, or document the preset as legacy/test-only; today it's a drift trap for anyone who finds it in `.env.example:8`.

20. **No "restart required" concept anywhere in the UI** — [VALUE: med · EFFORT: M] — Runtime-API settings apply instantly (notifier reconfigure, `setup.py:251-259`), env settings need a container recreate, and nothing tells the user which is which — the Update pane is the only restart-shaped surface (`applicantOnboarding.js:1692-1736`) and it does a full git-pull rebuild. When the Engine pane (item 2) lands, tag each setting live-apply vs restart; independently, add a plain "Restart engine" action to Update/System (the updater sidecar already has the docker socket, `docker-compose.prod.yml:378-395`) so an env change doesn't require SSH.

21. **Follow-up timing is hardcoded (10-day due, 2 h thank-you, 7-day check-in) with no owner control** — [VALUE: med · EFFORT: M] — `followup_service.py:21,27` and `post_submission_service.py:22-23`. Defaults judged: 10 days to a follow-up nudge and 7 days to a check-in draft are reasonable openers, but follow-up cadence is personal (some users never want to nudge; some want day-5) and the drafts are review-gated anyway. One "Follow up after N days (0 = never)" per campaign, surfaced next to the tracker when it ships (master audit Top-25 #4).

22. **The four `PRESUBMIT_*` guards silently shape behavior users will blame on the product** — [VALUE: med · EFFORT: M] — Listing-age ≤90 d, duplicate cooldown 30 d, ≤3 apps/company/day, eligibility filter on (`config.py:553-573`) — all dark. Defaults judged sane (90 d generous, 3/company/day right, eligibility-on correct), but the *duplicate cooldown* will visibly refuse a re-apply the user explicitly wants ("the role was reposted!") with no override and no UI explanation of which guard fired. Surface them read-only in the Engine pane with the block reason, and add a per-posting "apply anyway" override that routes through review.

23. **Approvals silently expire after 30 days — no warning, no setting** — [VALUE: med · EFFORT: M] — `APPROVAL_TIMEOUT_DAYS=30` (`config.py:203-207`) times out the durable approval gate; a user back from a long break finds workflows dead with no notification that expiry was near. The default (30 d) is fine; the invisibility isn't. Show "expires in N days" on aging Portal approval rows, send a pre-expiry nudge through the existing ladder, and expose the window in the Engine pane. (Also consolidate the redundant `APPROVAL_WAIT_SECONDS` override, `config.py:209-217` — two env knobs with subtle precedence for one concept.)

24. **No settings search across 17 tabs** — [VALUE: med · EFFORT: M] — The sidebar is a static button list (`index.html:1586-1666`; tab wiring `settings.js:19-39`) with zero filter; "where is quiet hours?" requires knowing it's under *Notifications* (Applicant's) not *Reminders* (the workspace's). Add a filter field above the nav that matches tab titles + card `<h2>`s (they're all in the DOM already) and jumps to + highlights the matching card. Pairs with the taxonomy fix (item 7).

25. **Five of the seventeen tabs eject you into a different modal mid-click** — [VALUE: med · EFFORT: M] — `ADMIN_TABS = {services, integrations, tools, users, system}` short-circuits to `window.adminModule.open(tab)` (`settings.js:17,22-27`), swapping modal shells (different chrome, different position) for what reads as adjacent items in one list. Unify the shells or visually mark the handoff; today "Add Models" (the most-needed tab for setup) is the jarring one.

26. **Two parallel notification systems ask for the same channels twice** — [VALUE: med · EFFORT: M] — Workspace *Reminders* configures its own ntfy topic + email-to (`settings.js:2455-2471`), while Applicant *Notifications* configures Discord/Apprise/ntfy separately (`applicantOnboarding.js:463-476`); a user must paste the same ntfy topic into two panes to get both calendar reminders and application alerts on their phone. At minimum cross-link the panes ("Applicant's alerts are configured separately →"); better, a shared channel store the Applicant channels step reads as defaults.

27. **Engine env-var jargon leaks into user-facing copy: "set NOTIFICATIONS_LIVE=true to deliver"** — [VALUE: med · EFFORT: S] — The channels test returns `note: "dry run — set NOTIFICATIONS_LIVE=true to deliver"` (`setup.py:329`) and the UI prints it verbatim (`applicantOnboarding.js:614-618`). Plain-language principle (CLAUDE.md #3): users can't set env vars from the browser. Rewrite as "Test saved, but live sending is switched off on this server — ask whoever installed Applicant to enable it," and let the engine return a structured `live:false` the UI phrases.

28. **Notifications dry-run mode is diagnosable but not fixable from the product** — [VALUE: med · EFFORT: M] — `NOTIFICATIONS_LIVE` defaults false in code (`config.py:255`), true only via compose (`:135`); any non-compose deploy (dev box, future bare-metal) shows the honest "dry run" note forever with no switch anywhere. Since real sending is a deliberate safety gate, expose it as an admin-only toggle in the Engine pane (write-through `app_config`, live-reconfigure like channels) rather than env-only.

29. **The stack ships an internal ntfy server the UI never mentions — it teaches ntfy.sh instead** — [VALUE: med · EFFORT: S] — `docker-compose.prod.yml:354-363` runs `ntfy` in every deploy, but the channels step's placeholder and how-to point at public `ntfy.sh` (`applicantOnboarding.js:475,494-499`), and the engine's `NTFY_URL` defaults empty (`config.py:254`). Self-hosters get a privacy-preserving push server they don't know they have (needs a reverse-proxy publish, per the compose comment). Either document/one-click the in-stack option in the help card or drop the service from the default stack.

30. **Quiet-hours timezone is free text with no validation or auto-detect** — [VALUE: med · EFFORT: S] — The tz input accepts anything (`applicantOnboarding.js:531-532`); the engine validates HH:MM but not tz (`setup_service.py:442-443`), so `PST` or `Berlin` silently misbehaves at notify time. Use `Intl.supportedValuesOf('timeZone')` for a datalist, default from `Intl.DateTimeFormat().resolvedOptions().timeZone`, and reject unknown zones server-side (same fail-loud pattern the config validators use, `config.py:632-644`).

31. **Relocated wizard steps keep wizard chrome in Settings — "Save & continue" that continues nowhere and secretly advances the wizard** — [VALUE: med · EFFORT: S] — `mountSettingsStep` reuses the step renderers verbatim (`applicantOnboarding.js:1745-1774`), so Settings→Notifications shows a primary "Save & continue" (`:578`) whose handler also POSTs `/setup/advance/channels` (`:719`, via `_advanceAndContinue` `:244-252`), and Settings→Automation with the built-in sandbox selected makes it a pure no-op advance (`:894-899`). Pass a context flag so Settings renders "Save" and skips the wizard-step advance side effect.

32. **"Send a test" silently persists unsaved channel edits first** — [VALUE: low · EFFORT: S] — The test handler saves the form (`POST /channels`) before testing (`applicantOnboarding.js:601-610`) — reasonable mechanically, but a user "just testing" a pasted webhook has now committed it with no signal. Say so ("Saved and sent a test") or test-without-persist server-side.

33. **Ladder edits are lost on modal close — no dirty guard on the one form where order is the data** — [VALUE: med · EFFORT: S] — Reorder/add/remove only mutate local `_tiers` until "Save ladder" (`applicantModelLadder.js:143-149`); closing Settings or switching tabs re-mounts fresh (`settings.js:70-80`) and discards silently. Add a dirty flag + confirm-on-unmount (quick-wins #30 covers Vault/Onboarding; the ladder needs the same).

34. **Campaign tab: unsaved-fields footgun next to instant toggles** — [VALUE: med · EFFORT: S] — Editing name/mode/target requires "Save changes" (`applicantCampaignSettings.js:108,177-188`) while the source checkboxes in the same card persist on click with a toast (`:146-159`); users trained by the toggles will edit throughput and close. Either autosave the fields on change (they're all single-value PATCHes) or add a dirty badge on the Save button.

35. **The takeover desktop flavor (4 supported options) has no UI or installer picker** — [VALUE: med · EFFORT: M] — `TAKEOVER_DESKTOP` supports cinnamon/xfce/gnome/pantheon with a resolution table and validator (`config.py:14-41,478,609-618`) — a *user-visible aesthetic choice* (the desktop you see during takeover) — yet only the raw image override is compose-wired (`:275`) and the DE var is documented-dark. A dropdown in the Automation pane (with "applies after the desktop restarts") or an installer question would make the four images somebody built actually selectable.

36. **Residential-proxy egress deserves a guarded UI, not an env-only attestation** — [VALUE: med · EFFORT: M] — The datacenter-egress refusal is excellent server-side safety (`EGRESS_RESIDENTIAL`, `config.py:359-369`), but the whole egress trio is documented-dark; when a proxy user misconfigures it the browser *refuses to launch* with no UI explanation. Add an advanced Automation card: mode select, proxy URL, and an explicit checkbox — "I confirm this proxy is a residential exit" — mapping to the attestation, plus the refusal reason surfaced in the live-session error state. The checkbox *is* the guard the env var was designed to be.

37. **CAPTCHA strategy is a consent-grade setting whose legal caveat lives only in a compose comment** — [VALUE: med · EFFORT: M] — `CAPTCHA_STRATEGY=avoid|service` (`config.py:413-433`) has its "most job sites prohibit CAPTCHA circumvention — opt in knowingly" warning in `docker-compose.prod.yml:199-204` where no user will read it. If/when surfaced (Engine pane), it needs the dangerous-settings treatment: default `human`, an explicit typed-consent modal for `service`, the key sealed to the vault (already done), and the caveat in-product. Until then, at least mirror the caveat into `.env.example` (it's absent there).

38. **Memory/skills write-approval — the user-authority policy — is env-only** — [VALUE: med · EFFORT: M] — `MEMORY_WRITE_APPROVAL` / `SKILLS_WRITE_APPROVAL` (`config.py:290-294`) decide whether the agent's self-writes stage for review; that's a *trust* setting the owner should hold, and the Memory/Mind surface (`applicantMind.js`) reviews the queue but can't change the policy. Add the two toggles to the Mind surface (skills/identity stay approval-locked per FR-MIND-9 — say so inline).

39. **`CHAT_TOOLS` / `LOOP_TOOLS` capability switches are dark — the tool-using agent can't be enabled from the product** — [VALUE: med · EFFORT: M] — Both default `off` and are absent from compose/installer/`.env.example` (`config.py:317-334`; `LOOP_TOOLS` has zero doc hits). These flip the assistant from single-shot to tool-dispatch (with all writes still review-staged) — exactly the kind of "let it do more" opt-in users expect as a toggle next to the memory-approval controls (item 38), with the safety framing already written in the field comments.

40. **The learning loop's curation ships dormant in prod with no switch** — [VALUE: med · EFFORT: S] — Prod compose turns the memory bridge on (`MIND_BACKEND=bridge`, `docker-compose.prod.yml:160`) but leaves `CURATION_SCHEDULE=off` (`:165`) — the closed-loop "memory curates itself daily" behavior is built, wired, and off for everyone, invisible. A "Curate memory daily" toggle in Mind (or at least default `daily` in prod compose like the essentials nudge at `:170`) makes the learning story real.

41. **Schedule-string settings skip the fail-loud validator pattern the rest of config.py models** — [VALUE: med · EFFORT: S] — `EGRESS_MODE`/`CAPTCHA_STRATEGY`/etc. reject typos at load (`config.py:632-657`), but the four cadence fields (`pii_retention_schedule` :196, `curation_schedule` :302, `essentials_nudge_schedule` :308, `status_update_schedule` :313) accept any string — `dailly` silently means "off," the exact failure mode item 12 in the egress validator was written to prevent. Add one shared `off|daily` validator.

42. **`STATUS_UPDATE_SCHEDULE` — the "proactive daily status update" — deserves a Notifications toggle** — [VALUE: med · EFFORT: S] — It's a user-preference notification cadence (`config.py:309-313`), off by default, env-only (compose `:171`); its sibling knobs (quiet hours, email backstop) are already UI-managed in the same conceptual pane. One checkbox ("Send me a daily status update") writing through `notify.channels` finishes the set — and directly serves the master audit's "while you were away" theme.

43. **PII retention is a privacy setting with no privacy surface** — [VALUE: med · EFFORT: M] — `PII_RETENTION_DAYS=0` (keep forever) + `PII_RETENTION_SCHEDULE=off` (`config.py:186-196`) are fully dark (zero doc hits) in a product whose wedge is self-hosted privacy (product-gaps lens). Add a "Privacy & data" card (fits the taxonomy of item 7): retention window, sweep schedule, and what gets pruned — plus the data-export of item 13.

44. **Log verbosity is unchangeable: `LOG_FORMAT` pinned, `LOG_LEVEL` dark** — [VALUE: med · EFFORT: S] — Compose hardcodes `LOG_FORMAT: json` with no `${}` (`docker-compose.prod.yml:208`) and never passes `LOG_LEVEL` (`config.py:244-245`); debugging a live self-host means editing compose and recreating. Make both passthroughs (`${LOG_FORMAT:-json}`, `${LOG_LEVEL:-INFO}`) and consider a temporary "verbose logging (1 h)" action in the System/Debug surface.

45. **Env-configured LLM shows a blank ladder — two sources of truth, one rendered** — [VALUE: med · EFFORT: S] — The gate opens from *either* the persisted ladder or env `LLM_*` (`is_setup_gate_open`, `setup_service.py:741-743`; `_llm_preconfigured`), but `GET /llm/tiers` returns only the store (`setup_service.py:252-256`), so a deploy configured via env runs fine while Settings→AI shows an empty Level-1 form (`applicantModelLadder.js:65`) — inviting the user to "fix" a working config. Render the env-derived tier as a read-only Level 1 ("configured at deploy") until a ladder is saved.

46. **The vault master key has no escrow/export guidance in-product** — [VALUE: med · EFFORT: S] — Losing the `secrets` volume permanently orphans every sealed credential (compose comment `docker-compose.prod.yml:110-114,219`), yet neither the Vault surface nor Update/System says "back up this one file." A one-line warning + "download key backup" (admin, re-auth-gated) in the vault card turns a catastrophic failure mode into a documented chore. Pairs with item 13.

47. **The updater sidecar holds root-equivalent Docker control, on by default, with zero in-product disclosure** — [VALUE: med · EFFORT: S] — `updater` mounts `/var/run/docker.sock` (`docker-compose.prod.yml:373-395`); opting out means editing compose. The Update pane (`applicantOnboarding.js:1692-1736`) should disclose "one-click updates are enabled; the updater can control this server's Docker — disable by removing the updater service" — a dangerous-capability transparency line, not a new control.

48. **LLM rate limiting is one global knob; the ladder is where it belongs** — [VALUE: low · EFFORT: M] — `LLM_RATE_LIMIT=30/min` applies per-provider globally (`config.py:239-241`, documented-dark); local endpoints need no cap while cloud tiers have provider-specific rate cards. Fold an optional "requests/min" field into each ladder tier (defaulting from the global) once item 9 lands.

49. **`SANDBOX_CONCURRENCY` deserves a "how hard can it work" slider** — [VALUE: low · EFFORT: S] — Cap 3 (`config.py:239`) is right for a NUC, wasteful on a big host, heavy on a Pi — and it's documented-dark. A 1–10 field in the Engine pane (live-applies to the queue if feasible; else restart-badged) with plain copy ("how many applications Applicant works on at once").

50. **Nothing tells the user which settings are per-campaign vs global** — [VALUE: med · EFFORT: S] — Throughput/mode/budget/sources are per-campaign (`applicantCampaignSettings.js:71-118`); quiet hours, the ladder, presubmit caps, and sandbox concurrency are global — and no pane says so. Add scope captions ("Applies to this job search only" / "Applies to everything Applicant does") to the Campaign cards and the future Engine pane; the multi-campaign user cannot currently predict blast radius.

51. **The throughput field hides both the cap and the clamp** — [VALUE: low · EFFORT: S] — The input says "capped for safety" with `max=30` (`applicantCampaignSettings.js:96-99`) but never states the cap or why (FR-AGENT-1); out-of-range and chat-set values are clamped engine-side silently (`campaign.py:24-26`). Show "up to 30/day" in the sub-label and toast the clamped value when it differs from what was typed. (Distinct from quick-wins #36, which seeds the *default*.)

52. **Email channel = a raw Apprise URL with the password in clear text** — [VALUE: med · EFFORT: M] — The email field asks for `mailto://user:pass@gmail.com` in a plain text input (`applicantOnboarding.js:466-470,488-493`) — password visible on screen, URL-grammar burden on the user, and a Google App Password dance explained only in prose. Offer structured fields (host/port/user/password[masked]/to) that compose the Apprise URL server-side, keeping the raw-URL input as the "advanced" fallback.

53. **Admin-only gating of Settings tabs is arbitrary** — [VALUE: low · EFFORT: S] — Automation and Update are `admin-only` (`index.html:1608-1615`) while Campaign, Fonts, and Notifications — which also reconfigure the shared engine — are owner-visible; multi-user deploys get an inconsistent authority story (any user can change the global quiet hours?). Decide the rule (engine-global ⇒ admin; per-owner ⇒ owner) and apply it to tab visibility *and* the proxy privilege checks (`applicant_setup_routes.py` uses one `_CONFIG_PRIV` for all writes).

54. **The Settings modal's header subtitle describes one tab out of seventeen** — [VALUE: low · EFFORT: S] — "Toggle on/off visibility of tools and modules across the interface" (`index.html:1584`) sits above *every* pane but describes only Appearance's visibility toggles — actively misleading on Campaign/Notifications/AI. Drop it or make it per-tab.

55. **Ladder context-window is a magic number with silent fallback** — [VALUE: low · EFFORT: S] — Free integer `min=1024` (`applicantModelLadder.js:118`), silently defaulting to 8192 on parse failure (`:79`); users don't know their model's window. Autofill from the endpoint's probed model metadata where available (the endpoint manager already probes models) and label it "advanced."

56. **Settings tabs aren't deep-linkable** — [VALUE: low · EFFORT: S] — `/settings` opens the modal (`settings.js:1621`) but there's no per-tab anchor (`#settings/notifications`), so docs, toasts, and the wizard can't route to the exact pane — every "set it up later in Settings" hint (`applicantOnboarding.js:456`) lands on the default tab. Cheap hash param + `initTabs` read.

57. **`ALLOW_AUTOMATED_ACCOUNTS` is a well-guarded capability nobody can find** — [VALUE: low · EFFORT: M] — The server-derived opt-in for account creation from vaulted credentials (`config.py:406-411`) is documented-dark; the user who *has* pre-vaulted a credential set still hits the account-create hand-off with no hint the opt-in exists. Surface it read-only in the Automation pane with the safety framing (CAPTCHA/verification/final-submit stay human regardless).

58. **`.env.example` is missing the vars users will look for first** — [VALUE: low · EFFORT: S] — No `NTFY_URL`, `EGRESS_RESIDENTIAL`, `TAKEOVER_DESKTOP_BASE_URL`, `BROWSER_CHANNEL`, `NOTIFICATIONS_LIVE`, `DISCOVERY_LIVE`, `BROWSER_REAL`, `MATERIAL_RESEARCH_ENABLED`, `CAPTCHA_*`, `LLM_SMART_ROUTING*`, or any `PRESUBMIT_*`/`PII_*` entries (matrix column) — the template documents ~55% of the surface. Once item 1 makes `.env` real, regenerate the template from `config.py` (the field comments are already excellent) and add a CI check that every `Settings` alias appears in it.

59. **Doctor mode checks containers, not capabilities** — [VALUE: med · EFFORT: M] — `install.sh --doctor` (`install.sh:674-703`) verifies service health and `/healthz`, but not the silent-degrade set (TeX present? browser binary? camoufox fetched? notifications live? takeover profile up?) — the exact failures that produce "green stack, stub output." Add the engine's capability report (item 8) as a `--doctor` section so deploy-time and in-app diagnostics agree.

60. **Defaults verdicts for the remaining dark knobs (keep dark, but write them down)** — [VALUE: low · EFFORT: S] — Judged sane and fine to leave env-only once documented (item 58): `CONTEXT_COMPRESS_THRESHOLD=64000` (config.py:179 — good), `PREFIX_CACHE=auto` (:182 — good), `SCHEDULER_INTERVAL_SECONDS=60` (:224 — good), `LOOP_FAILURE_ALERT_THRESHOLD=3` (:233 — good), `MEMORY/USER_MAX_CHARS` 8000/4000 (:297-298 — good), `ATS_MATCH_RATE_FLOOR=0.2` (:402 — good floor, but the *flag event* should be user-visible when it fires, per FR-PREFILL-6), `APPROVAL_*` (see item 23), `PROXMOX_CLONE_MODE=snapshot-revert` (:510 — right operator default). Publishing a one-line verdict per knob in `.env.example` prevents each future audit from re-litigating them.

---

## Part 3 — The clean taxonomy (proposal, one picture)

```
Settings
├─ (workspace-native: Add Models · AI Defaults · Search · Integrations · Email ·
│   Reminders · Appearance · Shortcuts · Account · Admin{Tools/Users/System})
└─ Applicant                       ← new labeled sidebar group (item 7)
   ├─ Job searches      — campaigns: name/mode/target/budget/sources; scope-labeled (items 34,50,51)
   ├─ Models            — ladder picking from saved endpoints + per-tier test (items 9,33,45,48,55)
   ├─ Notifications     — channels (+remove, item 5) · quiet hours (+tz picker, item 30) ·
   │                      digest time (item 6) · daily status update (item 42) · email backstop
   ├─ Documents & fonts — fonts step · resume-render capability state (item 8)
   ├─ Automation        — sandbox backend (honest, item 3) · Proxmox conn + test (item 17) ·
   │                      takeover desktop flavor + link (items 15,16,35) · egress (guarded, item 36) ·
   │                      desktop assist · agent tools (items 38,39)
   ├─ Privacy & data    — PII retention (item 43) · export/backup (items 13,46) · audit pointers
   └─ Engine (admin)    — the runtime-config pane (item 2): SLAs, caps, schedules, live/dry flags,
                          each with scope + restart badges (items 20,22,23,28,40,41,44,49)
```
