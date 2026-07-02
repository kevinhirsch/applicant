# Help, docs & self-explainability — exhaustive audit (lens 12)

**Lens.** Applicant is self-hosted: there is no vendor support line, no hosted docs site, no
account manager. The product must explain itself — its concepts, its controls, its failures,
and its own health — or the user is stranded. This pass audits help affordances, tooltip
coverage (counted per surface), first-use education, the invented vocabulary, the trust-center
content architecture, error→remediation mapping, self-hoster diagnostics, the user-docs story,
shortcut discoverability, the what's-new surface, and the chat assistant as a help channel.

**Dedup.** Goes beneath/beside `PRODUCT_EXHAUSTIVE_AUDIT.md` and the `exhaustive/` lenses.
Not repeated here: error taxonomy 401-vs-down + inline Retry (Top-25 #24), aria-labels/live
regions (#20), clickable toasts (#21), match-keyword explainer (#23), egress explainer
(trust #6), redaction note (trust #20), "explain this run" (trust #21), rationale clamp
(trust #13), shortcut *bindings* for applicant surfaces (ux-flows #9/#38, quick-wins #11),
generic "add tooltips to toggles" (quick-wins #28 — superseded by the census below), skipped-step
breadcrumbs (ux-flows #31). Trust #46 named the trust-center at headline level; item 5 below
specifies its full content architecture as that item requested.

---

## Tier 1 — Structural: the product has no help system

1. **No help entry point exists anywhere in the shell** — [VALUE: high · EFFORT: M] — The rail
   has ~20 launchers (`workspace/static/index.html:838` region: `#rail-portal`, `#rail-results`,
   `#rail-update`, …) and none is Help; the Settings nav (`index.html:1637-1644`) has Appearance
   and Shortcuts tabs but no Help/About tab; no applicant modal header carries a "?" launcher.
   A self-hosted user who wonders "what is this screen?" has literally nowhere to click. Add one
   `#rail-help` (or Settings → Help) entry opening a help panel; every item below hangs off it.

2. **There is no user manual — the entire docs tree is engineering-facing** — [VALUE: high ·
   EFFORT: L] — `README.md:1-6` is five lines pointing at `docs/overview.md`, which opens with
   codenames, service names, and repo paths (`docs/overview.md:1-30`). Nothing in `docs/`
   addresses the *operator as end-user*. Propose the minimum docs set, shipped as markdown in
   the image and rendered in-app (the front-door already renders markdown for chat): **Getting
   started** (OOBE → first digest), **Your daily loop** (digest → redline → approve → takeover →
   submit), **Safety & privacy** (feeds item 5), **Troubleshooting** (feeds items 33-39),
   **Glossary** (feeds item 7), **FAQ**. Anchor: `README.md:1`, `docs/overview.md:1`.

3. **The chat assistant cannot answer "how does X work?" — it is primed with zero product
   knowledge** — [VALUE: high · EFFORT: M] — The system prompt is persona-only
   (`_BUILTIN_IDENTITY`, `src/applicant/application/services/chat_service.py:649-664`); every
   context block appended in `_reply_text` (`chat_service.py:522-548`) is campaign/candidate/
   agent-state data (profile, essentials, status, interviews, memory) — no feature knowledge.
   Worse, the truthfulness rule ("only state what the provided context actually says… say you
   do not have it", `chat_service.py:658-660`) *obliges* it to refuse product questions or
   answer from ungrounded latent knowledge. Grep for `redline|viability` in the service: zero
   hits. Inject a curated product-knowledge/glossary block into the context stack (around
   `chat_service.py:522`), or add a `help` tool to `chat_tools.py:81-178` (current tools:
   remember/forget/playbooks/recall/desktop — nothing help-shaped).

4. **Help must not depend on a working model — today any "ask the assistant" path dies with the
   LLM** — [VALUE: high · EFFORT: S] — The engine chat's offline fallback
   (`_deterministic_reply`, `chat_service.py:981-1012`) only covers gaps/essentials/confirmation.
   When the user's local model is down — precisely the moment they need help — the only candidate
   help channel is dead. Static help pages (items 1-2) must be servable with no LLM and no engine
   (front-door-local), since "engine unreachable" is itself a top help topic.

5. **"How Applicant protects you" trust center — full content architecture** — [VALUE: high ·
   EFFORT: M] — Deepens trust #46, which asked for the page; this specifies it. One static,
   always-reachable page (rail Help + Settings + OOBE footer + the Portal "What it never does"
   button upgrades to open it), seven sections, each sourced from an artifact that already
   exists: **(a) The review line** — the never-does contract (`applicantPortal.js:323`
   `#applicant-portal-neverdoes`, engine list) + "the engine cannot self-authorize a final
   submit" (core stop-boundary); **(b) Your identity & connection** — egress/residential
   explanation + honest-fingerprint statement (today only the best-effort `egress_caveat`,
   `applicantRemote.js:315`); **(c) Truthfulness** — the fabrication guard and capped-confidence
   review flags (`docs/spec/master-spec.md:256`), asserted nowhere visible today; **(d) Your
   data stays home** — self-hosted storage map + vault sealing (the excellent copy at
   `applicantVault.js:55-66` verbatim); **(e) The paper trail** — submission snapshot ("exactly
   what was sent under your name", `workspace/routes/applicant_snapshot_routes.py`) + ordered
   audit-log export (`applicantDebug.js:84`); **(f) Sensitive answers** — the EEO
   decline-by-default policy; **(g) What it can never do for you** — CAPTCHA, verifications,
   account creation, final submit. Each section ends with "see it yourself" deep-links to the
   live surface.

6. **No per-surface "how this works" affordance; the Portal's "What it never does" button is the
   only header-level explainer in the product** — [VALUE: high · EFFORT: M] — Portal ships the
   pattern (`applicantPortal.js:323`: a small header button toggling an inline panel,
   `_toggleNeverDoesPanel` `:349-359`). No other applicant modal (Remote, Vault, Mind, Results,
   Debug, Update, Campaign, Gallery, Compare, redline) has any equivalent. Generalize it: a "?"
   in each modal header toggling a per-surface explainer card (content from the docs set, item 2).

## Tier 2 — The invented vocabulary has no home

7. **A glossary for the product's invented vocabulary — nowhere can a user learn these words** —
   [VALUE: high · EFFORT: M] — The UI speaks a dialect it never defines: *viability score*
   (`applicantDigest.js:252`), *redline* (`documentLibrary.js:2251` region), *variant*
   (Variants tab, `applicantDebug.js`), *model ladder / Level N* (`applicantModelLadder.js:96`),
   *exploration budget* (`applicantCampaignSettings.js:102`), *takeover / live session*
   (`applicantRemote.js:62`), *playbook* (`applicantMind.js:3`), *quiet hours*, *digest*.
   Create one glossary (docs set item 2) plus a shared `TERMS` strings module so tooltip
   wording is identical everywhere a term appears — and feed the same block to the chat context
   (item 3) so UI, docs, and assistant define terms identically.

8. **The "% match" chip — the number every approve/pass decision rides on — has no definition
   anywhere** — [VALUE: high · EFFORT: S] — `applicantDigest.js:260-263` renders
   `${score}% match` with no `title`. (Top-25 #23 surfaces the keyword breakdown; this is the
   prior step: a one-line "what this number is — how well this role fits your saved criteria,
   judged by your model" tooltip + glossary link, so the primary daily signal isn't an
   unexplained magic number.)

9. **"Exploration budget" is explained only in the admin Debug modal — the user-facing Campaign
   settings field is bare** — [VALUE: med · EFFORT: S] — The good sentence exists:
   "share of effort spent trying new or under-used sources instead of the proven ones"
   (`applicantDebug.js:423-425`) — but the owner-facing field (`applicantCampaignSettings.js:102-105`)
   has no tooltip at all. Copy the sentence to a `_tip` on the label.

10. **Exploration budget teaches two different mental models: a percent in Campaign settings, a
    0–1 decimal in Debug** — [VALUE: med · EFFORT: S] — `applicantCampaignSettings.js:79,105`
    renders/accepts a 0–100 percent; `applicantDebug.js:675` accepts "A number between 0 and 1"
    for the same value. A user seeing both will conclude they are different knobs. Pick one unit
    (percent) everywhere.

11. **"Saved playbooks" and memory-curation approvals are never explained** — [VALUE: med ·
    EFFORT: S] — The Mind surface (`applicantMind.js:3,40`) shows "What the assistant remembers",
    "Saved playbooks", and learning-curation approve/decline rows with no copy saying what a
    playbook *is*, when the agent consults one, or what approving/declining a "learning" changes
    about future behavior. A user is being asked to curate the agent's brain without being told
    the consequences of either button. Add a two-line intro + per-action tooltips.

12. **Takeover semantics are half-explained: how control comes back is never stated** —
    [VALUE: med · EFFORT: S] — The Remote intro (`applicantRemote.js:68-72`) says you can "take
    over at any moment" but never says how the assistant resumes, whether closing the modal ends
    the session, or what state the application is left in. The "I cleared the verification —
    continue" button (`applicantRemote.js:104`) implies the handback contract; state it in the
    intro: "when you're done, click Continue — the assistant picks up where you left off; closing
    this window doesn't end the session."

## Tier 3 — Tooltip coverage, counted (the census)

13. **Tooltip census: coverage is wildly uneven — four surfaces have effectively zero** —
    [VALUE: high · EFFORT: M] — `title=` counts per applicant surface (occurrences / file lines):
    **applicantCampaignSettings.js 0/267 · applicantUpdateView.js 0/88 · applicantCore.js 0 ·
    applicantActivity.js 2/491 · applicantChat.js 2/611 · applicantCompare.js 2/314 ·
    applicantGallery.js 3/275 · applicantMind.js 3/322 · applicantModelLadder.js 3/220 ·
    applicantResults.js 5(+ⓘ helper)/305 · applicantVault.js 6/376 · applicantDebug.js 11/864 ·
    applicantRemote.js 12/736 · applicantPortal.js 14/1522 · documentLibrary.js 28/3979 ·
    applicantOnboarding.js 22 `_tip()` calls (best-in-class)**. Work the zero/low files first;
    the wizard proves the team already has the voice and the helper — the gap is adoption.

14. **Campaign settings — the surface where users tune the agent's autonomy — is the worst
    offender: zero tooltips on every field** — [VALUE: high · EFFORT: S] — Every input in
    `applicantCampaignSettings.js` (`:79-171`: exploration budget, source toggles, caps/pace
    fields) ships a bare label. These knobs change what an autonomous agent does under the
    user's name; each needs a plain-language `_tip` ("how many applications per day it may
    prepare for your review", etc.).

15. **Four parallel tooltip primitives exist — consolidate one into `applicantCore.js`** —
    [VALUE: med · EFFORT: S] — The wizard's `_tip()` (`applicantOnboarding.js:214-218`,
    `role="img"` + aria-label — the best one), Results' ⓘ (`applicantResults.js:106-109`),
    the digest survey's hand-rolled ⓘ (`emailLibrary/applicantDigest.js:680`), and the native
    settings "?" (`settings.js:2633`). Export the wizard's `_tip` from `applicantCore.js:3` so
    every surface (items 8, 9, 11, 14) can adopt tooltips in one line, with one look.

16. **The entire tooltip strategy is `title=`-only — invisible on touch and to keyboard users** —
    [VALUE: med · EFFORT: M] — Native `title` tooltips never fire on tablets/phones and the tip
    spans aren't focusable (no `tabindex`), so on any non-mouse device the product's only
    micro-help layer simply does not exist. The shared primitive (item 15) should be a
    click/focus-toggled popover (aria-describedby) with `title` as fallback.

17. **Rail tooltips don't teach their shortcuts** — [VALUE: low · EFFORT: S] — Rail launcher
    titles (`index.html:838` region) never show the bound key; only search advertises Ctrl+K.
    Once applicant surfaces get binds (ux-flows #9), append the live keybind to each `title`
    ("Pending — Ctrl+Alt+P") from `window._applicantKeybinds` (`keyboard-shortcuts.js:50`) so
    shortcuts are learned in passing.

## Tier 4 — First-use education (one-time cards)

18. **Zero first-use education exists anywhere — and the kit to build it is already in the
    tree** — [VALUE: high · EFFORT: M] — The only persisted "seen" markers are the Portal's
    recap/notification timestamps (`applicantPortal.js:46-54`). Meanwhile the chat-hint kit
    already implements exactly the needed primitive: registered card, per-user "Got it" persist
    (`appkitChatHint`, used at `applicantChat.js:30-45` with `persistDismiss:true`). Lift it
    into a generic one-time explainer card (`applicant_seen_<surface>` keys) — lift-and-shift
    principle #1 — then apply it in items 19-22.

19. **Portal first-open card: "this is your home base"** — [VALUE: high · EFFORT: S] — First
    open of `applicantPortal.js:314` should show one dismissible card: "Things that need you
    wait here and clear when handled; informational notices can be dismissed; the agent keeps
    working in the background either way." Today the user infers the Portal's contract (persist
    vs dismiss, action vs info) from behavior alone.

20. **Redline first-open legend — meaning is currently carried by color alone** — [VALUE: high ·
    EFFORT: S] — The fallback change list encodes add/remove purely as green/red
    (`documentLibrary.js:2286-2288`), with no legend, and the review panel
    (`_renderApplicantReview`, `documentLibrary.js:2255`) never explains the mechanics
    ("green = added, struck red = removed vs *your* base resume; ask for changes in plain
    words below; nothing is used until you approve"). One first-use card + a persistent tiny
    legend fixes comprehension and the color-only accessibility failure at once.

21. **Remote first-open card + demote the permanent intro** — [VALUE: med · EFFORT: S] — The
    Remote intro paragraph (`applicantRemote.js:68-72`) is good copy shown forever, while the
    deeper mechanics (item 12: handback, session lifetime, which sign-in it uses) are never
    shown. Make the fuller explanation a first-use card; collapse the permanent paragraph to
    one line afterwards.

22. **Digest first-open: teach the feedback loop before the first approve/pass** — [VALUE: med ·
    EFFORT: S] — The pass button's `title` whispers it ("tell the assistant why — helps next
    time", `emailLibrary/applicantDigest.js:313`) but nothing teaches the loop up-front: "every
    approve/pass tunes what tomorrow's digest contains; passing with a reason teaches fastest."
    One card above the first-ever digest render (`applicantDigest.js:179` toolbar region).

23. **OOBE send-off should teach the daily rhythm, not just unlock nav** — [VALUE: med ·
    EFFORT: S] — Wizard completion calls `refreshApplicantFeatures()` and stops
    (`applicantOnboarding.js:1614`). Distinct from ux-flows #46 (auto-routing): the *content*
    gap — a final card saying "here's what happens next: I search continuously; your digest
    arrives at ~HH:MM; approvals wait in Pending; you'll get a notification when I need you."
    The user leaves setup without ever being told the product's cadence.

## Tier 5 — Error → remediation mapping

24. **Adopt "every error names its next step" — ~25 bare `Could not <verb>` toasts enumerated** —
    [VALUE: high · EFFORT: M] — Failure-only toasts with no remediation:
    `applicantPortal.js:963,982,1015,1039,1063,1131,1168,1208,1226` (update/snooze/approve/send/
    continue sign-in/authorize/save/dismiss), `applicantVault.js:166,205,266,359`,
    `applicantMind.js:164,177,208,234`, `applicantCampaignSettings.js:156,185,198,230`,
    `applicantChat.js:146,458,492`, `applicantDebug.js:125`, `documentLibrary.js:141,663,686,
    1005,1054`. Each should append the applicable next step ("— check the engine under
    Settings → System health" / "try again" / "reload"), sourced from one small
    error-remediation map in `applicantCore.js` keyed on the transport classes it already
    distinguishes (`applicantCore.js:84-87`).

25. **Requirement-ID jargon leaks into a user-visible error — a white-label violation shipping
    today** — [VALUE: high · EFFORT: S] — `require_automated_work` returns HTTP 409 with detail
    "Automated work is blocked until onboarding is complete and the LLM + notification channels
    are configured **(FR-ONBOARD-2, FR-OOBE-3)**" (`src/applicant/app/deps.py:321-325`), and
    workspace toasts surface engine `detail` verbatim (`applicantCore.js:52-53`). Strip the FR
    codes, and extend the CI white-label denylist to catch `FR-`/`NFR-` in user-facing string
    literals — today it only checks codenames.

26. **Setup-gate errors should carry the fix action, not just name it** — [VALUE: med ·
    EFFORT: M] — "Connect an AI model first to continue. You can do this in the setup wizard or
    under Settings." (`deps.py:304`) is the house's best error text, but it lands as a dead
    toast. `window.launchApplicantSetup` already exists; give `_toast` an optional action slot
    so gate errors render "[Open setup]" — an error that fixes itself in one click.

27. **Raw Python exception text reaches the user on the upload paths** — [VALUE: med ·
    EFFORT: S] — `f"Could not parse the uploaded base resume: {exc}"`
    (`src/applicant/app/routers/onboarding.py:182`), font detect/install
    (`src/applicant/app/routers/fonts.py:105,132`), and sandbox provisioning
    (`src/applicant/app/routers/remote.py:97` `f"Sandbox provisioning is unavailable: {exc}"`)
    all interpolate `exc` into user-visible detail. Map to plain causes ("this file doesn't look
    like a resume PDF/DOCX — try re-exporting it") and log the exception server-side instead.

28. **The strong SearXNG remediation exists engine-side but the user only ever sees "Could not
    run research right now."** — [VALUE: med · EFFORT: M] — The adapter produces a precise fix
    ("SearXNG must enable the JSON output format and set a secret_key…", error code
    `searxng_json_disabled`, `src/applicant/adapters/discovery/clients.py:129-134`) but the
    digest UI collapses everything to a bare failure (`emailLibrary/applicantDigest.js:399,433,476`).
    Thread the error *code* through the proxy and map it to a remediation line + Troubleshooting
    link client-side.

29. **A schema/migration mismatch produces no user-facing message at all** — [VALUE: med ·
    EFFORT: M] — No string anywhere tells a self-hoster "the database is a version behind — run
    the updater (or `alembic upgrade head`)". After a partial update this presents as random
    500s. Detect head-mismatch at startup (engine knows its Alembic head) and surface it via
    `/healthz` + a front-door banner with the fix.

30. **Model-endpoint test failures — the single most common setup stumble — surface raw
    exception strings** — [VALUE: high · EFFORT: M] — `src/applicant/app/routers/model_endpoints.py:89,112`
    pass `str(exc)` through as the 4xx detail; the wizard shows it verbatim
    (`applicantOnboarding.js:405`). Classify the four failure shapes users actually hit (host
    unreachable / 401 bad key / unknown model name / non-OpenAI-shaped reply) into plain
    sentences with the matching fix.

31. **The TeX/LibreOffice error texts instruct the end-user to perform env-var surgery** —
    [VALUE: med · EFFORT: S] — "Install a TeX engine and set RESUME_RENDER=auto"
    (`src/applicant/app/routers/conversion.py:90`; similar `documents.py:157`) is admirably
    actionable but speaks operator, not user, and names an env var with no context. Point at the
    help instead: "This server can't render PDFs yet — see Help → Troubleshooting → resume
    rendering" (page explains the image is missing TeX/LibreOffice and how to redeploy).

## Tier 6 — Self-hoster diagnostics (beyond the CLI doctor)

32. **Silent capability degradation is invisible in the front-door: the user's resumes can become
    stub PDFs and nothing ever says so** — [VALUE: high · EFFORT: M] — Adapters degrade silently
    when binaries are missing (`latex_tailor.py:96-98`, `docx_tailor.py:109`, browser
    `stealth.py:148`); the truth exists only as `/healthz` capability strings — "NOT FOUND
    (using stub PDF)", "DEGRADED (… Writer component missing)"
    (`src/applicant/observability/capabilities.py:31,68,71,99`) — which no workspace surface
    consumes. Proxy `capability_status` and render a plain-language card ("PDF rendering: using
    a placeholder — your real resume layout is NOT being produced. Fix: …") in Settings and as
    a Portal warning row when a user-affecting capability is stubbed.

33. **No system-health panel exists in the front-door at all** — [VALUE: high · EFFORT: M] —
    `/healthz` is rich (database, credential key dir, capabilities, version —
    `src/applicant/app/main.py:121-184`) and the scheduler heartbeat/stall alert exists
    (`src/applicant/app/routers/agent_status.py:156-164`), but nothing owner-visible shows any
    of it; the Debug modal's tabs (`applicantDebug.js:50-59`) cover activity/insights/logs/
    variants/run-controls — not health. Add Settings → "System health": engine reachable,
    DB ok, vault key dir, capabilities (item 32), scheduler last/next tick, version.

34. **The doctor is CLI-only; its checks never reach the UI** — [VALUE: med · EFFORT: M] —
    `scripts/install.sh:674` `mode_doctor()` builds the per-service health table, deep-probes
    the engine's `/healthz` and the front-door `/api/health` (`install.sh:681-701`) — useful
    exactly when the user is *not* comfortable with a terminal. The health panel (item 33)
    should reproduce the same verdicts, and the Troubleshooting doc should teach
    `install.sh --doctor` for the engine-fully-down case the UI can't cover.

35. **The Logs tab is a fixed 100-line dump of a 500-entry in-memory ring — no filter, no level,
    lost on every restart** — [VALUE: med · EFFORT: M] — `applicantDebug.js:454` hardcodes
    `?limit=100`; the engine serves only its `deque(maxlen=500)` ring
    (`src/applicant/observability/logging.py:20-26`, via `routers/admin.py:119`). Precisely the
    crash a self-hoster wants to diagnose destroys the evidence. Add level/text filtering and a
    limit control client-side, and a "download full log" that reaches beyond the ring.

36. **No runtime log-level control** — [VALUE: low · EFFORT: M] — `configure_logging` runs once
    at startup from env (`logging.py:166`, `config.py:244-245`); turning on DEBUG to chase a
    live issue requires a restart, which resets the very state being debugged. A
    level-switch on the health panel (admin-gated) closes the loop.

37. **No disk-usage or DB-size visibility anywhere — unbounded growth with no gauge** —
    [VALUE: med · EFFORT: M] — A 24/7 agent accumulates screenshots, artifacts, snapshots, and
    Postgres rows forever; the engine exposes no storage stats. The front-door already has the
    exact pattern to imitate for its own store (`workspace/routes/diagnostics_routes.py:23`
    `/api/db/stats`). Add engine parity (DB size, artifact-dir size) to `/healthz` or an ops
    route, shown on the health panel with a plain "this is normal / consider pruning" hint.

38. **A Troubleshooting playbook doc, linked from the failure states themselves** — [VALUE: high ·
    EFFORT: M] — Every "engine offline" rendering (`applicantCore.js:86` "Can't reach the
    assistant right now.", `applicantModelLadder.js:127`, Portal/Activity gated states) should
    link "Troubleshooting → the engine is offline" (check the stack: `docker compose ps`, run
    `install.sh --doctor`, look at the health panel). Same for model-down, browser-missing,
    render-degraded, notification-channel-silent. This is the docs-set page (item 2) that turns
    items 24-32 from dead ends into guided recoveries.

39. **The push-notification service has no compose healthcheck — a silent channel death is
    undiagnosable** — [VALUE: low · EFFORT: S] — `docker/docker-compose.prod.yml` healthchecks
    api/UI/postgres/searxng/chromadb but not the ntfy service, so `--doctor`'s table and any
    future health panel can't see a dead push channel — the user just stops getting phone
    alerts. Add the healthcheck and a "notification channels" line to item 33's panel.

## Tier 7 — Shortcuts, version & what's-new

40. **No "?" keyboard-shortcut cheatsheet — the shortcut list is buried in Settings** —
    [VALUE: med · EFFORT: S] — Shortcuts are discoverable only via Settings → Shortcuts
    (`index.html:2114-2124`, `#shortcuts-list`); there is no press-`?`/Shift+/ overlay, the
    de-facto standard. The Settings tab already renders the live keybind list — reuse that
    renderer in a lightweight overlay bound in `keyboard-shortcuts.js:138` (guarded against
    typing contexts). Complements — does not duplicate — ux-flows #9's new bindings.

41. **The product never states its own version anywhere in the UI** — [VALUE: med · EFFORT: S] —
    `/healthz` already returns `version` (`src/applicant/app/main.py:184`) but the update status
    payload omits it (`src/applicant/app/routers/update.py:87-98`) and no footer/Settings line
    shows it. "What version are you on?" is the first question of any troubleshooting exchange —
    including with the chat assistant. Show it in Settings → About and the Update modal.

42. **No changelog artifact exists, so no surface can ever say what changed** — [VALUE: med ·
    EFFORT: M] — There is no `CHANGELOG.md` in the repo. Without a user-facing changelog
    discipline ("what changed *for you*", not commit subjects), items 43-44 are unbuildable.
    Add the file, gate releases on updating it, and serve it via an ops route.

43. **Post-update, the user learns nothing — success is a toast and a dead shell log** —
    [VALUE: med · EFFORT: M] — The Update modal's entire narrative is the updater's raw 60-line
    `update.log` tail (`update.py:44,79-84`; rendered `applicantUpdate.js:109-112`) and the
    final toast "Update complete — Applicant is up to date." (`applicantUpdate.js:155`). Persist
    the last-seen version; on next open after a version change, show a "What's new" card
    (from item 42) — the payoff moment of the one-click updater.

44. **The update log tail is the only progress feedback — narrate the phases in plain
    language** — [VALUE: low · EFFORT: M] — `scripts/update.sh` has clean phases (git-sync →
    backup → build → migrate → restart → heartbeat) but the modal shows undifferentiated shell
    output. Emit a phase marker into `status.json` and render "Backing up your data… (2/6)"
    above the raw log — reassurance during the scariest minutes of self-hosting.

## Tier 8 — Copy patterns: fix, replicate, or catalog

45. **The locked-nav tooltip and toast never say *which* step unlocks the surface — though the
    registry knows** — [VALUE: med · EFFORT: S] — Locked launchers get the generic
    "`${title}` unlocks once the Applicant engine is configured" (`workspace/static/app.js:1322-1323`)
    and clicking toasts "Finish setup to unlock this" (`app.js:1360`) with no wizard link —
    while `workspace/src/applicant_features.py` computes exactly which requirement is unmet per
    section. Pipe the per-section reason into the tooltip ("unlocks after you connect a model")
    and give the toast an "[Open setup]" action (`window.launchApplicantSetup`).

46. **The assistant's starter chips include no help-shaped prompt** — [VALUE: med · EFFORT: S] —
    `_STARTER_PROMPTS` (`applicantChat.js:256-260`) offers three task chips ("Tell me what
    you're looking for", "What have you found so far?", "Change my criteria") — nothing invites
    "How does this all work?". Once item 3 grounds the assistant, add a "Explain how you work"
    chip; the chat becomes the product's discoverable help channel.

47. **Composer never hints its own send shortcut** — [VALUE: low · EFFORT: S] — Cmd/Ctrl+Enter
    is bound (`applicantChat.js:198`) but the placeholder (`applicantChat.js:180`) doesn't
    mention it. Standard fix: "… (Ctrl+Enter to send)".

48. **Catalog the house's best explainer copy and replicate it to the intro-less surfaces** —
    [VALUE: med · EFFORT: S] — The gold standards already written: the Vault's in-place
    encryption + sign-in-precedence explanation (`applicantVault.js:55-66`), the model-ladder
    "starts at Level 1 and climbs… cheapest first, strongest last" (`applicantModelLadder.js:132-134`),
    the Remote intro (`applicantRemote.js:68-72`), and the wizard's 22 `_tip()`s. Surfaces with
    *no* intro sentence at all: Gallery (`applicantGallery.js`), Compare (`applicantCompare.js`),
    Campaign settings (`applicantCampaignSettings.js`), Mind (item 11). Write the four missing
    intros in the same voice.

49. **The operator-facing agent how-to exists but is unshippable and unreachable** — [VALUE: low ·
    EFFORT: S] — `docs/autonomous-agent-howto.md:1-12` is addressed "Audience: the
    operator/owner" yet is FR-jargon-laden and never linked from the app. Either productize its
    operator sections into the user docs set (item 2) or mark it internal so nobody mistakes it
    for the missing manual.

50. **Two shells, two copies of explainer prose — no single source of truth for help strings** —
    [VALUE: low · EFFORT: M] — The engine's own built-in UI (`frontend/static/applicant/*.html`,
    ~38 title/help occurrences) explains setup/review/digest in parallel to the workspace
    surfaces; concept wording (scores, review, criteria) can drift between shells. As the
    glossary/TERMS module (item 7) lands, source both shells' concept strings from it — one
    definition per term, everywhere.
