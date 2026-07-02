# Applicant Front-Door — UX Flows & Information-Architecture Audit

**Lens:** navigational + state model, findability, cross-surface continuity, state completeness.
**Scope:** the modal-per-feature front-door (`workspace/`). ~16 engine-backed surfaces, all `.modal`
overlays, opened from an icon rail + sidebar with no URL routing and no central dispatcher.
**Out of scope (covered by `APPLE_GENIUS_IMPROVEMENTS.md`):** pure visual/glass/color/HIG styling.

Format: `N. **Title** — [VALUE · EFFORT] — rationale + anchor.`

---

## Tier 1 — structural IA & cross-surface continuity (highest ROU)

1. **No URL / deep-link routing to any surface** — [VALUE: high · EFFORT: M] — Zero surfaces are addressable by URL: no `location.hash`, `pushState`, or `hashchange` anywhere in the applicant JS (grep across `static/js/*.js` returns only sessions/modelPicker). A user cannot bookmark the Portal, share "review this document," deep-link from a Discord/email notification to the exact redline, or reload back into where they were — every reload dumps them to the empty shell. This is the single largest IA gap: adopt a `#portal`, `#documents/<appId>`, `#remote/<appId>` hash scheme and have each module's `open*()` read/write it. It also unlocks findings #2, #10, #13.

2. **Email/Discord/ntfy notifications cannot route to the surface they describe** — [VALUE: high · EFFORT: M] — The fan-out channels are the whole point of "glance and relax" (JOURNEY_MAP Beat 5), but with no deep-linkable URLs (#1) a "document ready to review" email can only say "open the app and find it." The engine→channel notification should embed a front-door URL (`…/#documents/<appId>`) so the user lands on the exact redline. Anchor: `applicant_features.py` notification fan-out; blocked on #1.

3. **Redline approval dead-ends — no forward path to final-submit / takeover** — [VALUE: high · EFFORT: M] — After the user approves all materials in the Documents redline, the surface shows only an "All approved" badge (`documentLibrary.js:2116-2121`) with **no CTA onward** to the live session / final-submit. The most consequential flow in the product (Beat 3→4, review→submit) is broken into disjoint modal jumps: approve here, then manually close, find the Portal, find the row, open the session. When `all_approved` flips true, render a "Continue to submit →" button that calls `window.openApplicantRemoteSession(appId)`. Anchor: `documentLibrary.js:2116`.

4. **Portal deep-links are one-way with no return/breadcrumb** — [VALUE: high · EFFORT: M] — Portal → redline (`_openRedline`, `applicantPortal.js:632`), Portal → digest (`_openDigest`:646), Portal → session (`_openSession`:655) all `_close()` the Portal and open the target with **no way back**. The user's "home base + inbox" vanishes the instant they act on a row; to handle the next item they must re-open the Portal from the rail and re-scan. Give every deep-linked surface a "← Back to Pending" affordance, or keep the Portal open behind the target. Anchor: `applicantPortal.js:637,650,658`.

5. **Two near-identical "chat" surfaces with the same icon** — [VALUE: high · EFFORT: M] — The rail has both the workspace-native chat (`#rail-chats`/welcome screen, main content area) **and** the Applicant "Job Assistant" (`#rail-assistant` → `applicantChat.js` modal), using the **same speech-bubble SVG** (`index.html:843` vs `854`). Users cannot tell which chat does what ("why are there two message icons?"); the job-assistant is buried as a modal while generic chat owns the whole content pane. Differentiate the icon + label, or merge job-actions into the primary chat as a mode. Anchor: `index.html:843,854,1159`.

6. **`rail-archive` and `tool-library-btn` are duplicate openers with divergent labels** — [VALUE: med · EFFORT: S] — `#rail-archive` (title "Applications & documents") and `#tool-library-btn` (title "Documents") both open the same `doclib-modal` (`app.js:3424`, `modalManager.js:1383`). Two rail entries, two different names, one destination — classic findability noise. Collapse to one, or give archive a distinct destination. Anchor: `app.js:3424`.

7. **Modal-per-feature IA fragments a fundamentally linear daily loop** — [VALUE: high · EFFORT: L] — The core journey is a *sequence* (digest → redline → approve → takeover → submit), but each beat is an isolated overlay the user must open, act in, close, and re-navigate (findings #3, #4). Consider a "Today" / run-through mode that walks the pending queue item-by-item in one persistent frame (like an email triage flow) rather than making the user assemble the sequence from scattered modals. This is the strategic version of #3/#4. Anchor: whole Portal/redline/remote chain.

8. **No global command palette across surfaces** — [VALUE: high · EFFORT: M] — Ctrl+K (`search-chat.js`) searches **chat sessions only** and navigates back to chat (`navigateToSession`:111); there is no way to jump to Portal/Documents/Memory/Gallery/Remote by name. With 16 modal surfaces and no URLs, a "jump to surface / search applications & postings" palette is the highest-leverage findability fix. Extend the existing Ctrl+K overlay with a surface/entity provider. Anchor: `search-chat.js:1,111`.

9. **Applicant surfaces have no keyboard shortcuts; the shortcut map ignores them** — [VALUE: med · EFFORT: S] — `keyboard-shortcuts.js` binds open-tool shortcuts for calendar/compare/cookbook/research/gallery/library/memory/notes/tasks/theme (`:249-260`) but **none** for Portal, Activity, Job-Assistant, Remote, Vault, Debug, Update, or the Applicant Gallery — the surfaces the user lives in daily. Add `open_portal`, `open_activity`, `open_assistant` etc. to `_defaultKeybinds` and `_toolBtns`. Anchor: `keyboard-shortcuts.js:5-13,249`.

10. **Reload/restart loses all in-flight surface state** — [VALUE: med · EFFORT: M] — Because surfaces are transient modals with no URL state (#1) and `close()` tears down DOM + JS state (`modalManager.js` `close`), a browser refresh (or the front-end being re-served, which happens per request) drops the user out of a half-reviewed redline or an open live session back to the blank shell. At minimum persist "last open surface + context" to restore on load. Anchor: `modalManager.js` close/teardown.

---

## Tier 2 — state completeness & consistency (findability of system status)

11. **BLOCKED/GATED state absent in 13 of 16 surfaces** — [VALUE: high · EFFORT: M] — Only Portal (`applicantPortal.js:327`), Activity (`:248`), and Debug (`:148`) render a distinct "not configured yet — here's what to do" gated state. The other 13 (Chat, Remote, Vault, Mind, ModelLadder, Memory, Gallery, Compare, Email, Documents, Campaign, Update) conflate "engine unreachable" with "feature needs setup" or show nothing — so a user who reaches a surface before onboarding is complete sees a blank/errored panel instead of "Connect a model to unlock this." Extract one `_renderGated(host, reason, ctaFn)` and adopt everywhere. Anchor: per matrix below.

12. **ERROR state missing in ~half the surfaces** — [VALUE: high · EFFORT: M] — `applicantRemote.js`, `applicantVault.js`, `memory.js`, and `documentLibrary`'s applicant tab have no engine-unreachable handling (Remote/Vault have *none*). When the engine `api` service is down, these silently fail or hang on a spinner — worst for Remote (the live-session takeover) and Vault (credentials), the two highest-gravity surfaces. Add a consistent offline card with retry. Anchor: matrix; Remote `applicantRemote.js`, Vault `applicantVault.js`.

13. **LOADING rendered five different ways** — [VALUE: med · EFFORT: S] — `.hwfit-loading` div (Portal, Chat, Activity, Debug, Gallery, Campaign, ModelLadder), `spinnerModule.createWhirlpool()` (emailInbox `:315`), plain "Loading…" text (Mind `:251`, Vault `:159`), inline patterns (documentLibrary), and *nothing* (Remote, Compare). The product's "is it working?" moment (JOURNEY_MAP Beat 2) reads as five different apps. Standardize on one loading primitive. Anchor: matrix rows.

14. **EMPTY state missing in 6 surfaces** — [VALUE: med · EFFORT: S] — Compare, Mind, Update, ModelLadder, and parts of Memory have no empty state; a fresh user opening Mind or Compare sees a blank panel with no "nothing here yet, here's how it fills" copy. Journey Beat 2/6 explicitly call for designed empty states, not blank cards. Anchor: matrix (Mind `applicantMind.js`, Compare `applicantCompare.js`).

15. **Empty/error/gated states hand-rolled per surface, not shared** — [VALUE: med · EFFORT: M] — Even where states exist, three surfaces define `_renderEmpty`/`_renderOffline`/`_renderGated` locally (Portal/Activity/Debug) and everyone else inlines strings. There is no shared state-view kit, guaranteeing drift. Promote the Portal trio into `applicantCore.js` (which already exports `_toast`/`_fetchJSON`/`_post`) and adopt across surfaces. Anchor: `applicantCore.js`; Portal `:312,327,353`.

16. **"All approved" badge in redline is a status cue with no action** — [VALUE: med · EFFORT: S] — Related to #3: the gate badge (`documentLibrary.js:2119`) tells the user materials are approved but the surface offers nothing to do with that state, so the successful terminal state of the redline is a dead-end tile. Pair the badge with the continue-to-submit CTA. Anchor: `documentLibrary.js:2119`.

17. **Remote empty state is the only state Remote has** — [VALUE: high · EFFORT: M] — `applicantRemote.js:78` renders "No live session is open yet," but there is no loading state while the iframe view-url resolves, no error state if the sandbox is unreachable, and no gated state if takeover isn't configured — on the product's single irreversible surface (Beat 4). A blank/black iframe during a slow load reads as "broken" at the worst possible moment. Anchor: `applicantRemote.js:70-80`.

---

## Tier 3 — notification / Portal / inbox relationship

18. **Informational toasts tell users to navigate manually instead of being clickable** — [VALUE: high · EFFORT: S] — `showToast` supports an `{action, onAction}` clickable button (`ui.js:364-391`) but **no Applicant surface uses it**. Instead Portal toasts print instructions as dead text: "Open the Library → Applications tab to review" (`applicantPortal.js:643`), "Open Email to review your matched roles" (`:652`). Make these toasts carry an action button that opens the surface directly. Anchor: `applicantPortal.js:643,652,666`; `ui.js:364`.

19. **Portal is the notification center but individual surfaces don't badge unread work** — [VALUE: med · EFFORT: M] — Only `#rail-portal` gets a live count badge (`applicantPortal.js:675,973`). The Documents, Email, and Activity rails don't reflect "N items need you here," so the user must open the Portal to learn where work is — the rail can't be glanced. Surface per-section counts on their rails. Anchor: `applicantPortal.js:_setBadge`.

20. **No cross-check that resolving in the Portal reflects back in the origin surface** — [VALUE: med · EFFORT: M] — Portal resolve (`_doResolve`) refreshes the Portal row, but if the user also has the Documents modal open (deep-linked from a prior row), approving from the Portal doesn't refresh the open redline — two views of the same application drift. Broadcast a `applicant:action-resolved` event that open surfaces listen for. Anchor: `applicantPortal.js` resolve handlers `:697-902`.

21. **Toasts auto-hide (1.2–5s) so a missed "document ready" is only re-findable by opening the Portal** — [VALUE: med · EFFORT: S] — `ui.js:449` auto-dismisses; a user away from the screen misses the toast entirely. This is fine *because* the Portal persists it as a row — but that contract is invisible. Add a subtle "→ in Pending" persistence cue, or a notification-history view. Anchor: `ui.js:449`; Portal `_infoNotifs`.

22. **Portal badge polls at 60s; Activity strip at 45s; Update log at 3s — no unified freshness model** — [VALUE: low · EFFORT: S] — Three different poll intervals (`applicantPortal.js:36` 60s; status strip 45s; update 3s) mean "how current is this?" varies by surface with no indication. A stale Portal badge can lag a real action by a minute. Consider a shared poller / visibility-aware refresh. Anchor: `applicantPortal.js:36`.

---

## Tier 4 — nav hierarchy, locking, and findability

23. **Locked-nav click gives a generic toast, not the specific unlock action** — [VALUE: med · EFFORT: S] — Clicking a greyed nav item fires `showToast('Finish setup to unlock this')` (`app.js:1356-1363`) — but it doesn't say *which* setup, nor launch it. Since the gate reason is known (`section.title unlocks once…`), the toast should be specific ("Connect a model to unlock Chat") and offer a "Set up" action that calls `window.launchApplicantSetup()`. Anchor: `app.js:1356`.

24. **Locked tooltip overwrites the element's real title and may not restore** — [VALUE: low · EFFORT: S] — The gating code stashes the original title in `dataset.applicantLockTitle` but the restore path is asymmetric with the write (`app.js` `e.data.applicantLockTitle` typo-shaped access noted in the guard); verify unlocking restores the original descriptive tooltip rather than leaving the lock reason. Anchor: `app.js:~1340`.

25. **~16 surfaces on a flat rail with no grouping** — [VALUE: med · EFFORT: M] — Portal, Activity, Assistant, Archive, Memory, Email, Research, Gallery, Calendar, Compare, Update, Settings plus hidden dynamic rails all sit as peers in one vertical rail (`index.html:838-876`). There's no visual grouping of "daily loop" (Portal/Email/Documents/Remote) vs "insight" (Activity/Compare/Gallery/Mind) vs "config" (Settings/Update/Campaigns). Group with rail dividers/sections so the daily-loop surfaces are found first. Anchor: `index.html:838-876`.

26. **Settings-seam surfaces (Remote, Vault) have no rail presence** — [VALUE: med · EFFORT: M] — Remote/takeover and Vault are only reachable via Settings → buttons (`#settings-open-remote`, `#settings-open-vault`, `index.html:1683,1688`) or a Portal deep-link. During an active application the user needs the live session fast; burying it two clicks deep in Settings is a findability miss for a time-sensitive surface. Consider a contextual rail entry when a live session is active. Anchor: `index.html:1683-1688`; `applicant_features.py:156-178`.

27. **Desktop-assist has nav_ids: [] — a registered surface with no way in** — [VALUE: low · EFFORT: S] — The `desktop_assist` section (`applicant_features.py:186-194`) has empty `nav_ids`; its controls are embedded in Remote + Settings. Fine while dormant, but it means the feature-state layer tracks a surface that can never be independently found or linked. Document the embedded-only pattern or fold its state into Remote's. Anchor: `applicant_features.py:190`.

28. **Activity modal doesn't link to its own deeper view (Debug/Insights)** — [VALUE: med · EFFORT: S] — The Activity modal shows run history + snapshot but has no link onward to the Debug surface's Insights/Logs/Variants tabs, which are the detailed version of the same data. A curious user (Beat 2/6) hits a ceiling. Add "Open full activity / insights →" to the Activity modal when Debug is available. Anchor: `applicantActivity.js` (no debug link found); `applicantDebug.js` tabs.

29. **Debug packs 8 admin tabs into one modal with no deep-linking to a tab** — [VALUE: med · EFFORT: M] — Activity/Insights/Logs/Variants/Run/Sources/Tools/Update all live in one `applicantDebug.js` modal (FEATURE_MAP §3.2). You can't link "open Debug → Logs"; every visit re-lands on the default tab. Combined with #1, expose per-tab hashes. Anchor: `applicantDebug.js` tab switcher.

30. **Update surface exists on the rail AND as a Debug tab** — [VALUE: low · EFFORT: S] — Update is both `#rail-update` (`applicantUpdate.js`) and a tab inside Debug (FEATURE_MAP §3.2). Two entry points to the same capability with no indication they're the same — pick the canonical one. Anchor: `applicant_features.py:142` + Debug tab.

---

## Tier 5 — onboarding, mobile, and orphan/dead-end states

31. **Wizard "Skip" advances but nothing tracks skipped-vs-done for later** — [VALUE: med · EFFORT: S] — The wizard supports Back/Skip/Continue (`applicantOnboarding.js:265,284`) and resumes at the first incomplete step (`_firstIncompleteStep:138`), but a skipped optional step leaves no breadcrumb ("2 optional steps skipped — finish in Settings"). Users who skip fonts/sandbox may never rediscover them. Surface skipped steps as a Settings nudge. Anchor: `applicantOnboarding.js:284,138`.

32. **No progress/"where am I" persistence if the wizard is closed mid-flow** — [VALUE: med · EFFORT: S] — The wizard re-opens at the first incomplete step on next load (good), but within a session there's no saved "you were on step 3" if it's dismissed — and being a modal, an accidental Escape/backdrop click can drop the user out of a long form. Confirm the gating overlay resists accidental dismissal and consider a resume banner. Anchor: `applicantOnboarding.js:20,138`.

33. **Remote iframe is cramped inside the mobile bottom-sheet** — [VALUE: med · EFFORT: M] — On mobile, `.modal-content` becomes an 85vh bottom sheet (`style.css:4613-4690`), but Remote's live iframe is fixed `min-height:40dvh` inside chrome + control cards (`applicantRemote.js:70-119`) — the live view the user must *watch and take over* ends up a tiny strip. The one media-rich surface needs a mobile-specific full-bleed treatment. Anchor: `applicantRemote.js:71`; `style.css:4676`.

34. **Modals set inline `--window-w`/`max-height` that only apply on desktop** — [VALUE: low · EFFORT: S] — Surfaces hard-set desktop sizing inline (Remote `--window-w:980px` `:56`, Chat `720px` `:73`); the mobile sheet ignores these via `!important` (`style.css:4676`). Correct, but it means desktop width lives in JS while mobile lives in CSS — a per-surface split that's easy to break. Move to the kit tokens. Anchor: `applicantRemote.js:56`, `applicantChat.js:73`.

35. **Mobile hides the close X in favor of swipe-down, but stacked/deep modals may not be swipe-dismissable** — [VALUE: med · EFFORT: M] — `.modal-close` is `display:none !important` on mobile (`style.css:4688`) assuming swipe-down works; but surfaces with their own scrollable body + `touch-action:pan-y` (Remote, Debug) can trap the swipe in inner scroll, leaving no visible dismiss on mobile. Verify every applicant modal is swipe-dismissable on touch or keep an X. Anchor: `style.css:4688`.

36. **No inter-modal stacking policy — opening surface B over A orphans A** — [VALUE: med · EFFORT: M] — Deep-links `_close()` the origin (#4), but non-deep-link cases (opening Vault from within Remote, `applicantRemote.js:23` imports `openApplicantVault`) stack modals via the z-counter (`modalManager.js:63`). Two full-screen overlays with only the top one obvious is context-loss; define whether B replaces A or clearly nests. Anchor: `modalManager.js:63`; `applicantRemote.js:23`.

37. **Minimize-to-dock exists for workspace tools but Applicant surfaces aren't registered** — [VALUE: med · EFFORT: M] — `modalManager` minimize/dock chips are keyed to a fixed `_LABELS` map (`modalManager.js:107-130`) covering cookbook/calendar/gallery/tasks/library/memory/notes/email/etc. — but **not** Portal, Remote, Chat, Vault, Debug, Activity. So Applicant surfaces can't be minimized-and-kept-alive the way native tools can; closing them tears down state (#10). Register them for parity. Anchor: `modalManager.js:107`.

38. **"Toggle window" shortcut (Ctrl+,) ignores every Applicant surface** — [VALUE: low · EFFORT: S] — `_WINDOW_TRIGGERS` (`keyboard-shortcuts.js:92-105`) maps settings/theme/tasks/notes/memory/library/gallery/research/cookbook/compare/calendar/email — but not Portal/Remote/Assistant/Vault/Debug/Activity, so the reopen-last-window shortcut can never target them. Extend the map. Anchor: `keyboard-shortcuts.js:92`.

39. **Escape behavior differs across surfaces** — [VALUE: low · EFFORT: S] — Some modals wire their own `Escape`→close (`applicantActivity.js:164`), others rely on the global bulk-cancel capture handler (`keyboard-shortcuts.js:67`), and the redline's nested review panel may swallow Escape. Users can't trust Escape to consistently back out one level. Define a uniform Escape = close-top-modal. Anchor: `applicantActivity.js:164`; `keyboard-shortcuts.js:67`.

40. **Live-session picker is buried inside the Remote modal, not surfaced as nav** — [VALUE: low · EFFORT: S] — Multiple concurrent live sessions are switched via a `<select>` inside Remote (`applicantRemote.js:59`); there's no rail/Portal indication that N sessions are live and which needs attention. If two applications are mid-prefill, the user can't see both without opening Remote and cycling the dropdown. Anchor: `applicantRemote.js:59`.

---

## Tier 6 — smaller flow polish

41. **Compare requires the user to hand-type 2+ entity IDs** — [VALUE: med · EFFORT: M] — Compare asks the user to supply application/posting IDs (FEATURE_MAP §3.2; `applicantCompare.js`) with no picker — but IDs aren't exposed anywhere the user can copy them, so the surface is effectively unusable without going through Debug/Gallery to find IDs. Add an entity picker or "compare these" affordances from Portal/Gallery rows. Anchor: `applicantCompare.js` input fields.

42. **Gallery and Compare are engine-backed but the registry once marked Compare "disabled"** — [VALUE: low · EFFORT: S] — The `applicant_features.py` docstring still describes Compare as the `disabled` example (`:26,50`) though the entry now gates on `llm_configured` (`:223-231`). Stale guidance risks a future regression re-disabling a working surface. Align the docstring. Anchor: `applicant_features.py:26,223`.

43. **`configured` (engine transiently offline) state has no user-facing distinction from `active`** — [VALUE: med · EFFORT: S] — The feature layer computes a `configured` state (backing set up but engine unreachable, `applicant_features.py:284-287`) distinct from `active`/`locked`, but `refreshApplicantFeatures` (`app.js:1314`) only branches on `active` vs not — so a transient engine outage greys the surface identically to "never configured," misleading the user into re-running setup. Render `configured` as "temporarily offline, retrying" rather than locked. Anchor: `app.js:1314`; `applicant_features.py:284`.

44. **Status strip is the only always-on element; everything else is behind a click** — [VALUE: med · EFFORT: M] — The persistent Activity strip (`index.html:1200`) is the sole ambient surface; pending-action urgency, live-session state, and errors are all one-or-more clicks away in modals. For an *autonomous agent the user supervises* (JOURNEY_MAP thesis), consider a slim always-visible "N need you / 1 live session" affordance beside the strip so the supervisory state is glanceable without opening the Portal. Anchor: `index.html:1200`; `applicantPortal.js` badge.

45. **No "what changed since I last looked" across surfaces** — [VALUE: low · EFFORT: M] — The Portal tracks a `NOTIF_SEEN_KEY` timestamp (`applicantPortal.js:82,102`) for toast de-dupe, but there's no per-surface "3 new since yesterday" marker on Documents/Gallery/Activity. A daily-cadence product benefits from unread/new markers so the user knows where to look. Anchor: `applicantPortal.js:82`.

46. **Onboarding completion doesn't auto-route to the natural first destination** — [VALUE: med · EFFORT: S] — On wizard completion it calls `refreshApplicantFeatures()` (`applicantOnboarding.js:1614`) to unlock nav but leaves the user on the empty shell — the Beat 1→2 handoff ("is it working?") requires them to hunt for the Activity strip / Portal themselves. Auto-open the Activity or Portal on first completion with a "here's your home base" cue. Anchor: `applicantOnboarding.js:1614`.

47. **Each module re-implements late-button-wiring with setInterval retry loops** — [VALUE: low · EFFORT: M] — Every surface polls for its rail button (`applicantPortal.js:_boot` setInterval; Activity `:_boot`) because there's no central dispatcher. This is fragile (races, double-wiring guards) and means a nav button added later must remember to add its own loop. A single delegated `rail.addEventListener('click', e => dispatch(e.target.id))` would centralize opening and eliminate the retry loops. Anchor: `applicantPortal.js:1184`; `applicantActivity.js:343`.

---

## State-completeness matrix (source for Tier 2)

| Surface | EMPTY | LOADING | ERROR | GATED |
|---|---|---|---|---|
| Portal | ✓ 353 | ✓ 291 | ✓ 312 | ✓ 327 |
| Activity | ✓ 255 | ✓ 158 | ✓ 239 | ✓ 248 |
| Debug | ✓ 159 | ✓ 91 | ✓ 141 | ✓ 148 |
| Chat | ✓ 118 | ✓ 82 | ✗ | ✗ |
| Compare | ✗ | ✓ 170 | ✓ 119 | ✗ |
| Gallery | ✓ 172 | ✓ 57 | ✓ 165 | ✗ |
| Mind | ✗ | ✓ 251 | ✓ 61 | ✗ |
| Remote | ✓ 78 | ✗ | ✗ | ✗ |
| Vault | ✓ 172 | ✓ 159 | ✗ | ✗ |
| Update | ✗ | ✓ 63 | ✓(view) | ✗ |
| ModelLadder | ✗ | ✓ 210 | ✓ 127 | ✗ |
| Campaign | ✓ 256 | ✓ 238 | ✓ 241 | ✗ |
| Memory | ✓ 589 | ✗ | ✗ | ✗ |
| Email | ✓ 442 | ✓ 315 | ✓ 343 | ✗ |
| Documents | ✓ 389 | ✓ 420 | ✗(applicant tab) | ✗ |

GATED present in 3/16; ERROR missing in ~7/16; the two highest-gravity surfaces (Remote, Vault)
have the thinnest coverage.
