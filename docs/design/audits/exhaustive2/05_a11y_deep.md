# Applicant — Accessibility Deep Pass (lens 05, exhaustive2)

> **Lens.** Beyond the aria-label basics (rail labels, strip `role="status"`, 44px close buttons,
> reduce-motion spinner gating — already DONE or listed in `PRODUCT_EXHAUSTIVE_AUDIT.md` /
> `exhaustive/quick-wins-cross-cutting.md`; none of those are repeated here). This pass audits the
> full assistive flows: focus management and traps, live-region coverage for async mutations,
> keyboard completeness of the daily loop (digest → redline → approve → final authorize), semantic
> structure, form-label associations, toggle ARIA, the glass material's degradation under
> `prefers-reduced-transparency` / `forced-colors`, zoom reflow, touch targets, color-only meaning,
> and the remote live-view iframe.
>
> Grounded in `workspace/static/js/applicant*.js`, `ui.js`, `documentLibrary.js`, `emailInbox.js`,
> `emailLibrary/applicantDigest.js`, `index.html`, `style.css`. Every anchor verified against the
> tree at audit time. Format: `N. **Title** — [VALUE · EFFORT] — rationale + anchor.`
>
> **Headline verdict.** The daily loop is *operable* by keyboard (every load-bearing decision is a
> real `<button>`), and the modal kit (`initModalA11y`, `ui.js:829`) does move/trap/restore focus —
> but six surfaces wire it only on first creation so reopened modals silently lose all focus
> management; the confirm dialogs that gate the irreversible submit have no dialog semantics and
> never restore focus; outside `#toast` there is not a single live region in any applicant module,
> so most async mutations are inaudible; and the glass fallback system, while extensive for
> reduce-transparency, has essentially no `forced-colors` story.

---

## Ranked — highest value / lowest effort first

### A. Focus management & dialog integrity

1. **Six modals lose ALL focus management after their first close** — [VALUE: high · EFFORT: S] — Chat, Debug, Gallery, Update, Results, and Activity call `initModalA11y` inside `_ensureModalEl()` *behind the `if (_modalEl) return` guard*, so it runs only on first creation (`applicantChat.js:67,89`; `applicantDebug.js:62,96`; `applicantGallery.js:33,62`; `applicantUpdate.js:46,68`; `applicantResults.js:59,84`; `applicantActivity.js:231,257`). `_close()` runs the cleanup (removing the keydown trap), so every reopen after the first has **no focus move-in, no Tab trap, and no focus restore** (Activity/Debug keep Escape only via a duplicate inline listener, `applicantActivity.js:258`, `applicantDebug.js:97`). Portal/Vault/Mind/Remote do it right by re-initializing in their `open…()` (`applicantPortal.js:1460-1461`, `applicantVault.js:295`, `applicantMind.js:250`, `applicantRemote.js:686`) — move the call into each open path.

2. **`styledConfirm` — the gate on the irreversible submit — has no dialog semantics and never restores focus** — [VALUE: high · EFFORT: S] — The final-submit authorization and submit-self confirmations run through `uiModule.styledConfirm` (`applicantRemote.js:427,486,505`; also Portal row actions `applicantPortal.js:79`, Vault deletes `applicantVault.js:333`). Its overlay (`ui.js:606-620`) has **no `role="dialog"`, no `aria-modal`, no `aria-labelledby`** (the `<h4>Confirm</h4>` is unwired), Tab is untrapped (only ArrowLeft/Right toggles the pair, `ui.js:649-653`), and `cleanup()` (`ui.js:636-644`) never restores focus — after confirming or cancelling the product's most consequential decision, focus drops to `<body>`. Same for `styledPrompt` (`ui.js:684-700,721-730`), used by the digest pass/confirm flows (`applicantDigest.js:373,566`).

3. **The redline host `#doclib-modal` has no dialog role, no trap, no focus restore** — [VALUE: high · EFFORT: S] — The Library modal that hosts the entire redline review is created with only `className='modal'` (`documentLibrary.js:1539-1542`): no `role="dialog"`/`aria-modal`/`aria-label`, no `initModalA11y`. It wires its own document-level Escape (`documentLibrary.js:3898-3909`) and focuses the search input (`:3916`), but Tab escapes into the background app and closing never returns focus to the launcher. The daily loop's Beat-3 surface is the least dialog-like modal in the product.

4. **Compare modal never moves focus in at all** — [VALUE: med · EFFORT: S] — `applicantCompare.js` builds/open/closes its modal (`:118,264,127-131`) with an inline Escape listener (`:119`) but no `initModalA11y` and **zero `.focus()` calls in the file**: keyboard users open Compare and are still focused on the launcher behind the overlay, with no trap and no restore.

5. **No background inerting while any applicant modal is open** — [VALUE: med · EFFORT: M] — `inert` is used only by the appkit window stack (`appkitWindow.js:432-496`); no `.modal` overlay marks the app shell inert/`aria-hidden`. The Tab trap contains sighted keyboard users, but a screen-reader virtual cursor can wander into the fully-live background (rail, chat, sidebar) from inside the Portal or the final-submit dialog. Apply `inert` to the shell siblings while a modal is open (the pattern already exists in the kit).

6. **Refresh/step/tab re-renders destroy the focused element (focus falls to `<body>`)** — [VALUE: med · EFFORT: M] — Systemic `innerHTML` swaps of containers that hold focus: Portal list refresh + retry (`applicantPortal.js:879,1402,1443`) and digest sub-body (`:1326,1341,1378`); Onboarding step navigation rewrites the body/footer holding the just-clicked Next (`applicantOnboarding.js:202,207,276`); Debug drill-down close (`applicantDebug.js:361`); redline re-render on "Request change" (`documentLibrary.js:2255-2291,2358`); model-ladder row moves (`applicantModelLadder.js:98-100,130`). After each, re-focus a stable anchor (the list heading, the new step's first field, the tab button) — otherwise the trap is left with no focus inside it.

7. **Escape silently bails out of the blocking OOBE wizard** — [VALUE: med · EFFORT: S] — `initModalA11y` is passed `_dismiss` as the close function (`applicantOnboarding.js:1640-1641,1657-1658`), so Escape tears down the "wizard always wins" overlay (`:1603-1620` removes it and reloads features), discarding the in-progress step with no confirm — inconsistent with the gate's own contract (`:1628-1647`) and an accidental-keypress data-loss path. Make Escape confirm (reuse the `styledConfirm` guard at `:1716-1717`) or no-op on required steps.

8. **Focus-trap query doesn't filter invisible focusables** — [VALUE: low · EFFORT: S] — `initModalA11y`'s selector (`ui.js:839-841,858-860`) has no `display:none`/`offsetParent` filter, so any modal keeping hidden panels in the DOM gets wrong first/last wrap targets and Tab stops on invisible controls. It also omits `iframe` and `[contenteditable]` — see #22 for the Remote consequence. Harden once in the kit.

9. **Modal accessible names are hardcoded `aria-label`s that can drift from the visible title** — [VALUE: low · EFFORT: S] — Every applicant dialog names itself with a string (`applicantPortal.js:313` "Pending", `applicantDebug.js:68` "Applicant diagnostics", etc.) instead of `aria-labelledby` pointing at its visible `<h4>`; there are **zero** `aria-labelledby` in the whole static tree (grep). Point each at the heading so the spoken name always matches the screen.

10. **The digest surface is a pane with no landmark or dialog identity** — [VALUE: low · EFFORT: S] — `#applicant-digest-panel` mounts inside the email-library grid (`emailLibrary/applicantDigest.js:149-159`) with no `role`/`aria-label`/heading of its own and its body is re-rendered via `innerHTML` (`:160,195,206`); SR users get no "you are now in today's applications" boundary. Wrap it in a labelled `role="region"`.

### B. Live regions & async announcements

11. **Zero live regions in any applicant module — every surface leans on `#toast` alone** — [VALUE: high · EFFORT: M] — Verified inventory: the only live regions in the product are `#toast` (`index.html:2567`), the status strip (`index.html:1202`), the main chat `#chat-history` (`index.html:1249`), and one onboarding `role="alert"` (`applicantOnboarding.js:211`). There is not a single `aria-live`/`role=status|alert|log` in `applicantPortal.js`, `applicantChat.js`, `applicantRemote.js`, `applicantResults.js`, `applicantCompare.js`, `applicantGallery.js`, `applicantVault.js`, `applicantDebug.js`, `applicantUpdate.js`, `applicantMind.js`, `documentLibrary.js`, `emailInbox.js`, or `applicantDigest.js`. Add one polite status line per surface (a shared `announce()` in `applicantCore.js`) and route load/empty/resolve transitions through it.

12. **The shared loading/error/empty/gated kit is silent — fix once, fix every surface** — [VALUE: high · EFFORT: S] — `loadingHTML` (`applicantCore.js:95`, spinner is `aria-hidden`), `errorHTML` (`:112`), `emptyHTML` (`:103`), `gatedHTML` (`:122`) carry no `role`/`aria-live`/`aria-busy`. Every `innerHTML = loadingHTML(...)` → result swap in Portal/Results/Gallery/Compare/Debug/Activity is inaudible, and every engine-error banner (the moment a user most needs signal) says nothing. Give `errorHTML` `role="alert"` and mark the swap container `aria-busy` during loads — this is the new-kit follow-through the earlier `role="alert"` quick-win never reached.

13. **Job Assistant chat replies are inaudible** — [VALUE: high · EFFORT: S] — `#applicant-thread` (`applicantChat.js:177`) lacks the `role="log" aria-live="polite"` its sibling main-chat history has (`index.html:1249`); the "Thinking…" placeholder (`applicantChat.js:399`) and the reply swap (`_setBubbleBody`, `:319,405`) announce nothing — an SR user sends a question and hears only silence until they manually re-read the modal. One attribute pair on the thread container.

14. **Badge count changes are unannounced and not part of the Portal button's name** — [VALUE: high · EFFORT: S] — `_setBadge` (`applicantPortal.js:1244-1258`) rewrites `.rail-notes-badge` text with no live semantics and no `aria-hidden`, and `#rail-portal` (`index.html:850`) doesn't fold the count into an `aria-label` — so "3 items need you" arrives visually but never audibly, and the rail button reads without its count (or worse, the bare digit dangles as stray text). Set `aria-label="Pending — 3 items need you"` on the button when the badge updates.

15. **The strip's static `aria-label` masks its live text** — [VALUE: med · EFFORT: S] — `#applicant-status-strip` is a live region, but the fixed `aria-label="What your assistant is doing — open Activity"` (`index.html:1202`) supplies the accessible name while updates go to the child `#applicant-status-text` (`applicantActivity.js:190,212`); several SR/browser pairs will announce the stale label, and there's no `aria-atomic`. Drop the `aria-label` (let content name it) and add `aria-atomic="true"`.

16. **`role="status"` on a `<button>` destroys the strip's button semantics** — [VALUE: med · EFFORT: S] — The strip is a clickable `<button>` whose ARIA role is overridden to `status` (`index.html:1202`), so AT users are never told it's activatable (it opens Activity, `applicantActivity.js:450`) and it sits in the Tab order announcing as a passive status. Split it: an inner/adjacent `role="status"` span for the text, keep the wrapper a plain button named by its content.

17. **Portal rows appearing/resolving and the "N items need your attention" count are silent** — [VALUE: med · EFFORT: S] — Action results do toast (`applicantPortal.js:1009-1011,1034-1035`), but the row-removal + empty-state flip (`_removeNotifRow`, `:1232-1240`), new rows arriving on `_load` (`:1421-1429`), and the count header (`:870-874`) are all plain re-renders. Announce "2 items remaining" through the surface's status line (#11) when a row resolves.

18. **Toast auto-dismiss is 1.2s and takes its Undo button with it** — [VALUE: med · EFFORT: M] — Plain-string toasts hide after `1200ms` (`ui.js:336`), errors after `3000ms` (`:470`); the action/Undo button (`:370-391`) is a real button but exists only until `_hideTimer` fires (`:436-448`). WCAG 2.2.1: a timed control with no pause/extend. Pause the timer on hover **and focus**, lengthen defaults for toasts carrying actions, and honor a user "longer notifications" preference.

19. **The engine-update log is a 3-second silent rewrite** — [VALUE: low · EFFORT: S] — `applicantUpdate.js` polls every 3s (`:28,142`) and rewrites the whole body (`:102`); the `<pre id="applicant-update-log">` (`:111`) has no `role="log"`, so a blind admin driving an engine update gets zero progress. `role="log" aria-live="polite"` + append-only rows instead of full rewrites.

20. **Onboarding step changes and inline successes are silent** — [VALUE: med · EFFORT: S] — The wizard announces validation errors (`applicantOnboarding.js:211` has `role="alert"`) but not progress: step transitions rewrite the rail/body (`:185-190,202`) with no announcement or focus-move to the new step's heading, and `.admin-success` confirmations ("Test sent" `:620`, "Read N details…" `:1398`, also `:986,1032,1328,1474`) have no role — success is silent where failure is loud. Move focus to the new step heading and give successes `role="status"`.

21. **Redline gate flips ("All approved" / "Needs review") and panel renders are silent** — [VALUE: med · EFFORT: S] — Approve/decline fire toasts (`documentLibrary.js:2392,2193`), but the readiness badge flip (`:2117-2121`), the redline render itself (`:2255-2291`), and the "Working…" button-label swap on Request-change (`:2358`) are inaudible — the state that tells the user "you may now submit" never announces. Route the gate flip through a status line.

22. **Remote session phase transitions are only visible pixels** — [VALUE: med · EFFORT: M] — Takeover/submit results toast (`applicantRemote.js:372,395,495,513`), but the phase arc (launching → ready → your-turn → submitted) lives in the sandboxed iframe and the `#applicant-remote-empty` overlay toggle (`:80-82`) with no live region; a blind user cannot tell the session is ready for them, which is the entire point of the handoff. Mirror the phase into a `role="status"` line in the modal chrome.

23. **`aria-busy` exists once, statically, and is never toggled** — [VALUE: low · EFFORT: S] — The only occurrence in the product is the hardcoded `aria-busy="false"` on `#chat-container` (`index.html:1197`); no JS ever sets it (grep). Either wire it in the shared loading kit (#12) or delete the decoy.

### C. Keyboard completeness (the daily loop and around it)

24. **Verdict: the loop's decisions are keyboard-operable — protect that** — [VALUE: high · EFFORT: S] — Digest Approve/Pass/Research are real buttons (`applicantDigest.js:301,310,322`), redline Approve/Decline/Request-change are real buttons (`documentLibrary.js:2382,2400,2333`), the final pair ("I'll submit it myself" / "Authorize…") are real buttons in both surfaces (`applicantRemote.js:138,140`; `applicantPortal.js:780,783`), and no positive `tabindex` exists anywhere (grep). Add a regression check (playtest crawl step) asserting the loop's controls stay `<button>`s — the breaks below are all at the edges.

25. **Hover-revealed card controls are invisible to keyboard focus** — [VALUE: high · EFFORT: S] — Library/memory card action + menu buttons render at `opacity:0` and reveal on row hover only: `.memory-item:hover .memory-menu-btn` (`style.css:~7917-7920`) and `.memory-item:hover .memory-item-actions` (`:7967`) with **no `:focus-within` rule** — a keyboard user tabbing through Library cards (`documentLibrary.js:2143`) lands on invisible open/clone/archive/delete controls. Add `.memory-item:focus-within { … opacity:1 }` alongside every hover reveal.

26. **Email inbox rows open by mouse only** — [VALUE: high · EFFORT: M] — The row `div` opens the email on click with no `tabindex`/keydown/role (`emailInbox.js:580`); `.email-sender-clickable` filter spans (`:539,554`) and the per-email menu wrap (`:544,587`) are likewise click-only. The digest mounted inside this shell is fine, but a keyboard user cannot open a message in the surrounding inbox. Make rows `role="button" tabindex="0"` with Enter/Space, or wrap the subject in a real button.

27. **The redline pane can't be scrolled by keyboard** — [VALUE: med · EFFORT: S] — The redline is display-only HTML in a `max-height:200px;overflow:auto` div (`documentLibrary.js:2273,2281`) with no focusable children and no `tabindex="0"` — a keyboard user literally cannot read past the first 200px of the diff they're being asked to approve. Add `tabindex="0"` + a label ("Proposed changes, scrollable").

28. **Other scroll panes with no focus stop** — [VALUE: low · EFFORT: S] — Same fix for the Activity body (`applicantActivity.js:251`), Portal body (`applicantPortal.js:327`), and digest list (`applicantDigest.js:458`): zero `tabindex="0"` across all applicant modules (grep), so pure-text overflow (empty states, long notes) is keyboard-unreachable.

29. **Tab bars are buttons with `.active` classes — no tab semantics, no arrow keys** — [VALUE: med · EFFORT: M] — Library tabs (`documentLibrary.js:1549-1553`, `_switchLibTab` `:1787,1804`) and Debug's 8 tabs (`applicantDebug.js:88,100-102`) toggle `.active` with no `role="tablist"/"tab"`, `aria-selected`, or arrow-key nav — SR users hear undifferentiated buttons with no selected state. The repo already has the correct pattern to copy (`tasks.js:2486-2495`).

30. **Toggle buttons carry no pressed/expanded state (inventory)** — [VALUE: med · EFFORT: S] — Beyond the two correct ones (Remote preview `applicantRemote.js:132-134,547,560`; pause toggle `applicantActivity.js:96`), state is missing on: Portal "What it never does" expander (`applicantPortal.js:322,339,348-357` — add `aria-expanded`/`aria-controls`), Library filter chips (`documentLibrary.js:2694,3115,350,369` — `aria-pressed`), digest survey chips (`applicantDigest.js:686-701` — `aria-pressed`), and the email summary collapsibles which have `role="button" tabindex="0"` but no `aria-expanded` **and click-only activation — Enter/Space do nothing** (`emailLibrary.js:2850,3476,4099`).

31. **The pause kill-switch mixes a changing name with `aria-pressed`** — [VALUE: low · EFFORT: S] — `_setPauseBtn` flips both the label ("Pause…"/"Resume…") and `aria-pressed` (`applicantActivity.js:91-99`; markup `index.html:1210-1215`), so AT announces contradictions like "Resume your assistant, toggle button, pressed". Pick one idiom: stable name ("Automated work") + `aria-pressed`, or the changing action name with no pressed state.

32. **Focus can strand inside the live-session iframe** — [VALUE: low · EFFORT: M] — The trap's selector excludes `iframe` (`ui.js:840,859`) yet browsers Tab into it; once inside the sandboxed frame (`applicantRemote.js:76-79`) the modal's keydown trap can't see Tab, so wrap-around breaks and focus can strand in third-party ATS content mid-takeover. Include `iframe` in the focusable query and offer a documented Escape-hatch ("press Escape twice to return to the controls").

33. **No keyboard accelerators for the daily loop** — [VALUE: low · EFFORT: M] — `keyboard-shortcuts.js` maps Settings/Tasks/Notes/Memory/Library/Gallery/etc. (`:92-105,249-260`) but none of Portal/Activity/Results/digest; the only applicant shortcut is Cmd/Ctrl+Enter to send in chat (`applicantChat.js` composer). Add Portal + Activity to the existing trigger map so the most-repeated surfaces join the muscle memory.

34. **Row action names are indistinguishable in an SR rotor list** — [VALUE: med · EFFORT: S] — Every Portal row renders identical "Snooze"/"Done"/"Review"/"Send"/"Dismiss" button names (`applicantPortal.js:633,636,657,665,850`), and digest rows repeat Approve/Pass — a screen-reader "list all buttons" view yields ten indistinguishable "Done"s with no row context. Append the row title to each: `aria-label="Done — Frontend Engineer at Acme"`.
