# Applicant Front-Door — Micro-Interactions & Input Mechanics (exhaustive pass 2, lens 01)

> **Lens.** Fine-grained interaction mechanics across the front-door surfaces: button states,
> form-field mechanics (validation timing, enter-to-submit, paste/IME handling, autofocus, masks,
> limits), focus order + restore, double-submit guards, optimistic-UI + undo pairs, selection/copy
> affordances, scroll preservation, loading-state churn, debounce/race guards, hit targets, and
> animation consistency.
>
> **Dedup.** Items in `PRODUCT_EXHAUSTIVE_AUDIT.md` and `exhaustive/` (quick-wins, ux-flows) are
> NOT repeated; several findings below are *residual adoption gaps* of fixes those audits already
> landed (the shared kit exists — some surfaces missed it), or concrete confirmations of things the
> prior audits only asked to "verify".
>
> Format: `N. **Title** — [VALUE: high|med|low · EFFORT: S|M|L] — rationale + anchor.`

---

## Tier 1 — data-loss and double-submit hazards

1. **Portal Refresh destroys typed-but-unsent answers** — [VALUE: high · EFFORT: M] — `_load(true)` re-renders every pending row via `innerHTML` (`workspace/static/js/applicantPortal.js:879`, triggered by the header Refresh at `:338`), so text half-typed into an agent-question textarea (`_renderAnswer`, `:651`) or a missing-detail value (`:668`) is silently wiped. The 60s badge poll doesn't re-render, but one tap of Refresh does. Skip re-rendering rows whose inputs are dirty, or carry input values across the render.

2. **Chat clears the composer before the request succeeds** — [VALUE: high · EFFORT: S] — `_send` empties the input pre-flight (`workspace/static/js/applicantChat.js:395`). On failure the message survives only inside the transient retry bubble; close the modal (or send another message) and it is gone. Restore the failed message to the composer (or don't clear until the POST resolves).

3. **Chat retry duplicates the user's bubble** — [VALUE: med · EFFORT: S] — the error-bubble Retry calls `_send(message)` (`workspace/static/js/applicantChat.js:421-425`), which `_appendMessage('user', …)` again (`:396`) — every retry adds another copy of the same user message to the thread. Re-send without re-appending.

4. **Escape kills the blocking OOBE overlay and discards the current section** — [VALUE: high · EFFORT: S] — `initModalA11y(_overlay, _dismiss)` wires Escape/close straight to `_dismiss` (`workspace/static/js/applicantOnboarding.js:1640-1642`, `:1657-1659`), which removes the overlay from the DOM (`:1609`). One stray Escape mid-intake throws away everything typed into the unsaved section — this confirms the prior audit's "verify the gating overlay resists accidental dismissal" (ux-flows #32) fails today. Suppress Escape (or confirm) while an intake form is dirty.

5. **Work history / education / references can hold exactly one entry** — [VALUE: high · EFFORT: M] — the section specs declare `repeat: true` (`workspace/static/js/applicantOnboarding.js:1101`, `:1114`, `:1124`) but `_renderIntakeSection` renders a single fieldset with no "Add another role/degree/reference" affordance (`:1228-1247`). A user with three jobs physically cannot enter them — the flag is ignored end-to-end.

6. **Draft cover-letter / screening-answer buttons have no double-click guard** — [VALUE: med · EFFORT: S] — `#doclib-gen-cover-btn` / `#doclib-gen-answer-btn` fire a POST without disabling themselves (`workspace/static/js/documentLibrary.js:1986-2024`); an impatient double-click drafts two cover letters (two engine generations, two review items). Disable while in flight, like every other Applicant button.

7. **Remote's final-submit buttons show no busy state and no terminal state** — [VALUE: high · EFFORT: S] — `_onAuthorizeFinish`/`_onSubmitSelf` rely on the invisible `_busy` flag (`workspace/static/js/applicantRemote.js:484-519`): the danger button never reads "Submitting…", is never `disabled`, and after success the whole "Finish the application" card stays fully active — the user can tap Authorize again on the product's one irreversible surface. The Portal's own final row does this right (`applicantPortal.js:1156-1158`); Remote should match and flip the card to a "Submitted ✓" terminal state.

8. **Backdrop-click closes the Portal over dirty inputs** — [VALUE: med · EFFORT: S] — `modal.addEventListener('click', e => { if (e.target === modal) _close(); })` (`workspace/static/js/applicantPortal.js:340`) with no dirty check on answer/missing-detail inputs. Prior audit covered Vault/Onboarding discard-confirm (quick-wins #30); the Portal's inline answer rows are the same hazard, unlisted.

9. **Compare's campaign picker duplicates its options on every reopen** — [VALUE: med · EFFORT: S] — `openApplicantCompare` calls `_loadCampaigns()` each open (`workspace/static/js/applicantCompare.js:276`) and `_loadCampaigns` appends `<option>`s without clearing previous ones (`:149-156`) — after three opens each campaign is listed three times. Clear (keeping "All campaigns") before appending.

10. **Screening-answer question captured with `window.prompt()`** — [VALUE: med · EFFORT: S] — `documentLibrary.js:2010` uses the native single-line prompt for what is usually a multi-sentence screening question: no multiline, no paste comfort, off-theme, blocks the main thread. The digest's Pass flow already uses `styledPrompt` with placeholder + maxLength (`emailLibrary/applicantDigest.js:373-381`) — lift it.

11. **Model-ladder API keys are saved untrimmed** — [VALUE: med · EFFORT: S] — `_syncFromDOM` trims `base_url` and `model` but stores the key raw (`workspace/static/js/applicantModelLadder.js:80-82`). A key pasted with a trailing newline/space (the normal paste from a provider dashboard) is sealed as-is and fails auth later with no visible cause. `.trim()` the key.

12. **Onboarding conflict "Apply choices" double-posts** — [VALUE: low · EFFORT: S] — the handler loops sequential POSTs with the button never disabled (`workspace/static/js/applicantOnboarding.js:1464-1478`); a double-click interleaves two write loops. Disable + "Applying…" while in flight.

13. **Ladder tier removal is silent even when a saved API key dies with it** — [VALUE: med · EFFORT: S] — `_remove` splices the tier with no confirm (`workspace/static/js/applicantModelLadder.js:165-170`); on save the tier's `api_key_ref` is gone for good. A one-line styledConfirm when `_hasKey` is true prevents an unrecoverable mis-click.

## Tier 2 — form-field mechanics (enter, IME, masks, validation timing)

14. **Enter doesn't send in the Job Assistant — and nothing says so** — [VALUE: high · EFFORT: S] — only Cmd/Ctrl+Enter sends (`workspace/static/js/applicantChat.js:199-201`); plain Enter inserts a newline. Every mainstream chat trains Enter-to-send, the placeholder gives no hint, and there's no "⌘↩ to send" caption. Either adopt Enter-to-send + Shift+Enter newline, or advertise the chord under the composer.

15. **No `e.isComposing` guard on any Enter handler** — [VALUE: med · EFFORT: S] — IME users (CJK, dead-key layouts) committing a composition with Enter will trigger create-campaign (`workspace/static/js/applicantChat.js:152`), the application-ID lookup (`workspace/static/js/documentLibrary.js:1940`, `:1954`), and the variant lookup. Standard guard: `if (e.isComposing || e.keyCode === 229) return;`.

16. **Portal answer textarea has no Cmd/Ctrl+Enter submit** — [VALUE: med · EFFORT: S] — the most-repeated daily input (`_renderAnswer`, `workspace/static/js/applicantPortal.js:651-659`) is click-only; the chat composer 20px away accepts the chord. Add the same keydown → Send.

17. **Missing-detail row: no Enter-to-save** — [VALUE: low · EFFORT: S] — the two inline inputs (`workspace/static/js/applicantPortal.js:668-683`) require a mouse trip to "Save & continue". Enter in the value field should submit.

18. **Vault forms have no Enter-to-submit** — [VALUE: med · EFFORT: S] — all three credential forms (Google, default, per-site — `workspace/static/js/applicantVault.js:73-111`) are bare inputs with click-only Save; Enter in a password field does nothing. Password entry is the canonical enter-to-submit form.

19. **No show/hide toggle on any password field** — [VALUE: med · EFFORT: M] — Vault secrets (`applicantVault.js:75,88,107`), ladder API key (`applicantModelLadder.js:114`), Proxmox token/RDP password (`applicantOnboarding.js:799,817`) are all typed blind with no reveal affordance and no caps-lock hint. One shared eye-toggle helper in applicantCore would fix six fields.

20. **Dates, years and salary are unmasked free text** — [VALUE: med · EFFORT: M] — `start_date`/`end_date` are `type:text` "MM/YYYY" (`workspace/static/js/applicantOnboarding.js:1106-1107`), education years free text (`:1118-1119`), salary floor free text (`:1093`). No mask, no pattern, no validation timing — typos ("13/2020") surface only when an application is half-filled downstream. Add lightweight masks/`pattern` + inline validation on blur.

21. **Missing `inputmode`/`autocomplete` hints across intake** — [VALUE: low · EFFORT: S] — phone (`applicantOnboarding.js:1058`) lacks `inputmode="tel"`, salary lacks `inputmode="numeric"`, email fields lack `autocomplete="email"` — mobile users get full QWERTY for numeric fields through a 12-step interview.

22. **EEO detail input never rehydrates and never hides** — [VALUE: med · EFFORT: S] — the "Your answer (optional)" input is always rendered with `value=""` (`workspace/static/js/applicantOnboarding.js:1184`) so a saved detail vanishes on resume/Back; and it stays visible while "decline to self-identify" is selected — a dead input inviting text the selection says won't be used. Rehydrate + show only for "prefer to answer".

23. **Intake `<form>` has no submit handler** — [VALUE: low · EFFORT: S] — `#ao-intake-form` (`workspace/static/js/applicantOnboarding.js:1241`) never wires `onsubmit` preventDefault; browsers' implicit-submission rules make Enter a page-navigating GET in single-input edge cases, and it forfeits free Enter-to-continue. `form.onsubmit = e => { e.preventDefault(); next(); }`.

24. **Campaign create/rename: no Enter-to-commit, no maxlength** — [VALUE: low · EFFORT: S] — `#cs-create-name` and the per-campaign name input (`workspace/static/js/applicantCampaignSettings.js:88,250`) are click-only and unbounded; the chat's create-campaign input (`applicantChat.js:152`) already binds Enter — mirror it.

25. **Throughput input silently self-corrects after save** — [VALUE: low · EFFORT: S] — the number input allows typing 500 (`min/max` only constrain spinners, `applicantCampaignSettings.js:98`); the engine caps it and the re-render shows a different number with no message. Clamp on `change` with a one-line "capped at 30 for safety" note.

26. **Email-backstop minutes clamp silently** — [VALUE: low · EFFORT: S] — `_renderChannels` clamps 1–1440 in JS at save (`workspace/static/js/applicantOnboarding.js:694`) with no feedback that "5000" became "1440". Reflect the clamped value into the input + say so in the status span.

27. **Compare: no Cmd/Ctrl+Enter to run from the ids textarea** — [VALUE: low · EFFORT: S] — the whole surface is keyboard-hostile: type ids, then mouse to "Compare" (`workspace/static/js/applicantCompare.js:107-112`). Add the chord.

28. **Chat textarea is fixed rows=2 with manual resize only** — [VALUE: low · EFFORT: M] — `applicantChat.js:180-181`; a three-line question scrolls inside a two-line box. Auto-grow to ~6 rows like modern composers (the Portal answer boxes share the pattern).

29. **Portal Send/Save buttons aren't gated on empty input** — [VALUE: low · EFFORT: S] — chat gates its Send on non-empty content (`applicantChat.js:230-240`) but the Portal's answer Send and missing-detail Save are always enabled and just silently `focus()` on empty (`applicantPortal.js:1027`, `:1194-1195`). Adopt the same `_syncSendEnabled` pattern (or at least toast why nothing happened).

30. **Missing-detail "Field" name is editable free text** — [VALUE: med · EFFORT: S] — `_renderMissing` pre-fills the engine-requested attribute name into an editable input (`workspace/static/js/applicantPortal.js:677`); a stray edit renames the attribute and the engine acquires the wrong key. Render it as a read-only label (editable only when the engine sent no name).

31. **Vault username field keeps the plaintext after save; secret field placeholder never flips to "saved"** — [VALUE: low · EFFORT: S] — after `_onSaveAccount` only the secret is cleared (`workspace/static/js/applicantVault.js:263`); the ladder's "•••••••• (saved)" placeholder trick (`applicantModelLadder.js:114`) isn't reused, so re-opening the vault reads as "not filled in" even when saved ✓ sits in the tiny status span.

## Tier 3 — busy states, optimistic UI, and re-render churn

32. **Results modal re-renders its whole body every 60s while you read it** — [VALUE: high · EFFORT: S] — `pollVisible(() => _load(false), 60000)` (`workspace/static/js/applicantResults.js:266`) swaps `host.innerHTML` (`:199-208`) on every tick: scroll position jumps to top and any text selection dies mid-read. Diff the payload and skip the render when unchanged (or only update numbers in place).

33. **Update modal rebuilds the card every 3s during a run** — [VALUE: med · EFFORT: M] — `_startPolling` calls `_render(status)` per tick (`workspace/static/js/applicantUpdate.js:142-158`), recreating the log `<pre>` (`:102-113`): the user's scroll position inside the log resets every 3 seconds and selection is impossible. Update the `<pre>` text in place, keep scroll pinned to bottom only when already at bottom.

34. **Busy labels swap to "…", shrinking the button under the pointer** — [VALUE: low · EFFORT: S] — Done/Snooze/Dismiss flip `textContent = '…'` (`workspace/static/js/applicantPortal.js:955-956`, `:973-974`, `:1218-1219`), collapsing the button width and shifting the row's action cluster mid-click. Reserve width (`min-width` on `.cal-btn` busy state) or overlay a spinner instead of replacing the label.

35. **Refresh buttons never show a busy state anywhere** — [VALUE: med · EFFORT: S] — Portal (`applicantPortal.js:323`), Activity (`applicantActivity.js:246`), Results (`applicantResults.js:74`), Vault (`applicantVault.js:117`), Remote "Refresh sessions" (`applicantRemote.js:91`), Digest (`emailLibrary/applicantDigest.js:168`). Combined with the silent `_loading` no-op guard (`applicantPortal.js:1399`), a second click does *nothing visible* — the classic "is it broken?" moment. One shared busy-toggle helper.

36. **Digest Refresh has no in-flight guard at all** — [VALUE: med · EFFORT: S] — `_loadDigest` (`workspace/static/js/emailLibrary/applicantDigest.js:785-801`) has no `_loading` flag; rapid clicks stack fetches and the slowest response wins, possibly rendering stale rows over fresh ones. Add the guard + a monotonic seq (see #44).

37. **Remote Take-control / resume buttons give zero feedback while working** — [VALUE: med · EFFORT: S] — `_onTakeover`/`_resume` are `_busy`-guarded but the buttons never disable or relabel (`workspace/static/js/applicantRemote.js:367-405`); on a slow sandbox the click appears to do nothing, inviting repeat clicks that are silently swallowed.

38. **Mind reloads the entire modal after every approve/deny/forget** — [VALUE: med · EFFORT: M] — each action awaits `openApplicantMind()` (`workspace/static/js/applicantMind.js:162`, `:176`, `:207`): three fetches re-run, scroll resets, every expanded playbook collapses. Remove the acted-on row in place (the Portal's `_removeRow` pattern) and only refresh counts.

39. **Campaign settings: save/archive re-mounts the whole panel** — [VALUE: med · EFFORT: S] — `mountApplicantCampaignSettings(host)` re-runs on every save (`workspace/static/js/applicantCampaignSettings.js:183`, `:196`, `:228`), resetting Settings scroll and reloading every campaign's sources. Patch the edited card instead.

40. **Approve/Decline in the redline collapses your context** — [VALUE: med · EFFORT: M] — success calls `_loadApplicantMaterials` (`workspace/static/js/documentLibrary.js:2393`, `:2411`), which tears down the open review panel and re-renders the list from scratch: scroll to top, the redline you just approved vanishes, and there's no "next item needs review" hand-off. Flip the acted card's badge in place and keep the list position.

41. **Archive campaign: no confirm, no undo** — [VALUE: med · EFFORT: S] — one tap on Archive (`workspace/static/js/applicantCampaignSettings.js:189-201`) stops a whole job search (agent stops working it) with no confirm and no toast-undo, while the far-less-consequential pause-all *does* confirm (`applicantActivity.js:120-122`). Weight should follow consequence.

42. **Optimistic resume leaves stale "Paused" strip text** — [VALUE: low · EFFORT: S] — `_applyPauseOptimistic(running)` only sets the text for the paused direction (`workspace/static/js/applicantActivity.js:104-113`); tapping Resume flips the dot to live but the label still reads "Paused" until the next poll reconciles. Set an optimistic "Resuming…"/"Working…" label too.

43. **Preview accept/reject both stay live after choosing** — [VALUE: low · EFFORT: S] — in the resume-conversion preview, clicking "Use this version" leaves "Keep my original" enabled (`workspace/static/js/applicantOnboarding.js:1505-1514`); clicking both fires both POSTs and the last silently wins. Disable the pair once either resolves and render the chosen state.

44. **Campaign-switch races: only Chat has a stale-render guard** — [VALUE: med · EFFORT: S] — chat guards async renders with `_renderSeq` (`workspace/static/js/applicantChat.js:47`, `:513`), but Gallery (`applicantGallery.js:66-69` + the two awaits in `_renderGallery`), the Portal digest embed (`applicantPortal.js:1368-1371`), and the Email digest panel (`applicantDigest.js:844-848`) have none — scrub the picker quickly and a slow earlier fetch paints the wrong campaign's data last. Lift the seq pattern into the kit.

45. **Portal bulk "Approve all N" freezes on one label through multi-campaign batches** — [VALUE: low · EFFORT: S] — the sequential per-campaign loop (`workspace/static/js/applicantPortal.js:1003-1010`) shows only "Approving…" with no progress ("3 of 12…") even though rows visibly pop out one at a time on success.

46. **Two-factor wait: 60 seconds of frozen label with no countdown or cancel** — [VALUE: med · EFFORT: M] — "Waiting for your phone…" (`workspace/static/js/applicantPortal.js:1114`) holds up to a minute with no ticking countdown (the copy promises "within 60 seconds") and no way to abort the wait. A simple `59…58…` suffix in the label sets expectation and signals liveness.

47. **Back/Skip in the wizard silently ignore clicks while busy** — [VALUE: low · EFFORT: S] — `if (!_busy)` guards (`workspace/static/js/applicantOnboarding.js:282-284`) with no disabled styling; during a slow section save the nav looks broken. Disable visually while `_busy`.

48. **Portal final-authorize removes a row keyed by `undefined`** — [VALUE: low · EFFORT: S] — `_removeRow(host, actionId)` runs unconditionally (`workspace/static/js/applicantPortal.js:1163`) even when `actionId` is missing (only `_doResolve` is guarded at `:1162`), silently no-op'ing against `CSS.escape("undefined")`. Guard it and fall back to a list refresh.

## Tier 4 — focus, scroll, and state restore

49. **Chat history evaporates on every open and campaign switch** — [VALUE: high · EFFORT: M] — `_renderConversation` → `_renderThreadIntro` clears the thread (`workspace/static/js/applicantChat.js:219-226`), and `openApplicantChat` re-renders from scratch (`:553-568`): close the modal to check the Portal, reopen, and the whole conversation is gone with no recall. Keep the thread DOM (or replay from the engine's chat history) across opens within the session.

50. **Model-ladder reorder drops keyboard focus to `<body>`** — [VALUE: med · EFFORT: S] — ↑/↓ trigger a full `_render` (`workspace/static/js/applicantModelLadder.js:143-147`, `:157-163`); the button under focus is destroyed, so a keyboard user must Tab back from the top after *every single move*. Re-focus the equivalent button on the moved row after render.

51. **The ladder ignores the existing drag-sort module** — [VALUE: low · EFFORT: M] — reordering is arrow-buttons only while `workspace/static/js/dragSort.js` ships in the same tree (used by the memory UI). Lift-and-shift it for pointer users; keep arrows for keyboard.

52. **Portal scroll position lost on manual refresh** — [VALUE: low · EFFORT: S] — `_renderList` replaces the container's innerHTML (`workspace/static/js/applicantPortal.js:879`); reading item 12 of 20 and tapping Refresh dumps you back to the top. Capture/restore `scrollTop` around the swap.

53. **Relative times never re-render while a surface stays open** — [VALUE: low · EFFORT: M] — Activity's `_relTime` (`workspace/static/js/applicantActivity.js:47-68`) and the Portal's `age_label`s are computed once at render; leave the modal open 20 minutes and "just now" lies. One shared 60s repaint of `[data-reltime]` nodes.

54. **The Portal greeting goes stale across day-part boundaries** — [VALUE: low · EFFORT: S] — `_greetingLine` (`workspace/static/js/applicantPortal.js:380-386`) is computed at load; a pinned tab crossing noon still says "Good morning". Recompute on the badge poll tick.

55. **Escape can't close Remote once focus is inside the live iframe** — [VALUE: low · EFFORT: M] — keydowns inside the sandboxed session iframe (`workspace/static/js/applicantRemote.js:76-79`) never reach the modal's handlers, so the surface's only keyboard exit dies exactly when the user is interacting with the session. Show a visible affordance (the ✕ is there, but on mobile it's hidden per `style.css` swipe rules) and/or refocus the shell on hover-out.

56. **Double Escape wiring on most modals** — [VALUE: low · EFFORT: S] — Chat (`applicantChat.js:88-90`), Activity (`applicantActivity.js:257-258`), Results (`applicantResults.js:84-85`), Gallery (`applicantGallery.js:62-63`), Compare, Update all bind their own `keydown Escape → _close` *and* pass `_close` to `initModalA11y` — `_close` runs twice per Escape. Harmless today (guarded), but it's duplicated teardown waiting to double-fire a side effect. Pick one.

57. **Desktop notifications aren't clickable** — [VALUE: med · EFFORT: S] — `_maybeDesktopNotify` fires `new Notification(...)` with no `onclick` (`workspace/static/js/applicantPortal.js:160-167`); the OS toast can't focus the tab or open the Portal — the exact dead-end the in-app clickable toasts fix (already landed) recreated one layer out. `n.onclick = () => { window.focus(); openApplicantPortal(); }`.

58. **Gallery keeps the campaign only per page-session** — [VALUE: low · EFFORT: S] — `_campaignId` is module state (`workspace/static/js/applicantGallery.js:28`); the digest already persists the last campaign to localStorage (`applicantDigest.js:28`, `:825-830`) — Gallery reloads to the first campaign after every page refresh. Read/write the same `applicant-digest-last-campaign` key (it's deliberately shared).

59. **Compare doesn't clear stale results when the inputs change** — [VALUE: low · EFFORT: S] — switching kind (Applications → Postings) or campaign leaves the previous comparison table sitting under the new inputs (`workspace/static/js/applicantCompare.js:172-203` only renders on Run) — an easy mis-read of old data against new intent. Clear or dim the result area on any control change.

60. **Wizard rail emits `aria-current="false"` literally** — [VALUE: low · EFFORT: S] — `_renderRail` sets `aria-current="${cur ? 'step' : 'false'}"` (`workspace/static/js/applicantOnboarding.js:190`); the attribute should be omitted when not current — some AT announce the string "false".

## Tier 5 — affordances: selection, copy, expand, and hit targets

61. **Remote's session picker labels are raw UUIDs** — [VALUE: med · EFFORT: S] — `Application ${s.application_id}` (`workspace/static/js/applicantRemote.js:310`) renders "Application 3f8c1a…" in the switcher for the highest-tension surface; the Portal already derives "Role · Company" (`applicantPortal.js:269-275`). Pass the same label through the sessions payload.

62. **Gallery "Screenshots" show no image** — [VALUE: high · EFFORT: M] — a screenshot card is an icon + page-ref + URL (`workspace/static/js/applicantGallery.js:140-153`); the one surface named "Gallery" renders zero pixels of the captures and offers no click-to-view/lightbox. Serve thumbnails through the proxy and open full-size on click.

63. **Redline viewport capped at 200px with no expand** — [VALUE: med · EFFORT: S] — the primary review artifact (a full resume diff) scrolls inside a 200px box (`workspace/static/js/documentLibrary.js:2273`) with no "expand"/full-height affordance — the daily consent decision is made through a letterbox. Add an expand toggle (the card already lifts its own height cap at `:2236`).

64. **Gallery material snippets hard-cut at 240 chars with no ellipsis or "view full"** — [VALUE: low · EFFORT: S] — `String(m.content).slice(0, 240)` (`workspace/static/js/applicantGallery.js:170`) truncates mid-word with no `…` and no expansion; the material is otherwise unviewable from the Gallery.

65. **Variant cards are inert** — [VALUE: med · EFFORT: M] — the resume-variant library rows show lineage/fit/approval (`workspace/static/js/documentLibrary.js:2070-2083`) but aren't clickable — no way to read the variant, compare it to its parent, or approve from here. At minimum deep-link into the materials view.

66. **Emergency hand-off values: `user-select:all` but no copy button** — [VALUE: low · EFFORT: S] — the pasteable values (`workspace/static/js/applicantPortal.js:696-700`) rely on manual select+copy mid-crisis; `ui.js` already has the copy-with-toast helper the Compare table uses. One 📋 per row.

67. **Saved sign-ins can't be deleted or replaced from the list** — [VALUE: med · EFFORT: M] — vault rows render lock + tenant key only (`workspace/static/js/applicantVault.js:177-183`); removing a stale/wrong credential has no UI at all (re-saving same tenant presumably overwrites, but nothing says so). Add per-row remove/replace.

68. **Portal "Recent updates" have no clear-all** — [VALUE: med · EFFORT: S] — informational notifications dismiss one-by-one (`workspace/static/js/applicantPortal.js:850`, `:876-879`) while digest rows got a bulk affordance; after a busy overnight the user taps Dismiss ×9. "Clear all updates" hitting the seen endpoint in batch.

69. **Survey chips have no pressed semantics** — [VALUE: low · EFFORT: S] — selection is a bare `.active` class toggle on buttons (`workspace/static/js/emailLibrary/applicantDigest.js:691-702`); AT users can't perceive which choice is selected. `aria-pressed` (or a real radiogroup) per chip.

70. **Mind's expandable playbook rows show no expansion state** — [VALUE: low · EFFORT: S] — rows are `role="button"` + cursor pointer (`workspace/static/js/applicantMind.js:103-111`) with no chevron and no `aria-expanded` toggled in `_wireSkillRows` (`:215-241`); nothing communicates open/closed, visually or to AT.

71. **Digest research report: no copy/save, no way back to a past brief** — [VALUE: low · EFFORT: M] — the report modal (`workspace/static/js/emailLibrary/applicantDigest.js:444-555`) is fire-and-forget: no copy button, and although the engine caches briefs, dismissing the modal loses the report with no re-open path from the row.

72. **Compare copy-id gives no feedback in the fallback path** — [VALUE: low · EFFORT: S] — `_copy` falls back to bare `navigator.clipboard.writeText` with no toast (`workspace/static/js/applicantCompare.js:56-61`); if `uiModule.copyToClipboard` is absent the click is indistinguishable from a no-op.

73. **The final-submit "self" button carries a paragraph as its label** — [VALUE: low · EFFORT: S] — "I'll submit it myself (open live session)" (`workspace/static/js/applicantPortal.js:780-782`) wraps to two lines on dense rows and mobile, misaligning the decision pair; move "(open live session)" into the title/hint and keep the label short.

74. **Pass-reason is lost when the decline POST fails** — [VALUE: low · EFFORT: S] — the digest Pass flow collects a mandatory reason via prompt, then on failure just re-enables the row (`workspace/static/js/emailLibrary/applicantDigest.js:389-399`) — the typed reason is gone and must be retyped. Stash it on the row and pre-fill the retry prompt.

75. **Toast burst cap silently swallows overflow** — [VALUE: low · EFFORT: S] — `_toastNew` shows at most the 3 newest notifications (`workspace/static/js/applicantPortal.js:150`); with 6 new arrivals nothing says "+3 more in Pending". Make the last toast a summary ("…and 3 more — open Pending").

## Tier 6 — consistency, kit-adoption residue, and polish nits

76. **`window.confirm` still used on two brand-critical confirms** — [VALUE: med · EFFORT: S] — the global pause (`workspace/static/js/applicantActivity.js:120-122`) and Mind's Forget (`workspace/static/js/applicantMind.js:191`) pop the native browser dialog while every neighbouring flow uses `styledConfirm` (Portal `:77-82`, Remote `:427-432`). Same for the wizard's Update fallback (`applicantOnboarding.js:1721`).

77. **Close-button aria-label fix missed the two newest surfaces** — [VALUE: med · EFFORT: S] — Results (`workspace/static/js/applicantResults.js:75`) and Update (`workspace/static/js/applicantUpdate.js:60`) ship `title="Close"` only — the exact one-liner the prior audit landed on Chat/Activity/Gallery regressed by copy-paste-from-old-template. Also Mind's close is a text "Close" `.cal-btn` while every sibling is a ✖ glyph (`applicantMind.js:41`) — pick one close primitive.

78. **Loud `console.error` on routine soft-degrades** — [VALUE: med · EFFORT: S] — the "Silent catch" refactor left `catch(e => console.error('Silent catch in applicantRemote:', e))` on *normal* paths (`workspace/static/js/applicantRemote.js:175`, `:218`, `:373`, `:698-699`; `applicantVault.js:141,202,264,296-298`; `applicantOnboarding.js:247,259`) and a vague `console.error('Failed:', e)` (`applicantPortal.js:1181`) — a healthy-but-engine-offline session floods the console with errors, burying real ones. Downgrade to a tagged `console.debug`.

79. **Chat/Mind conflate auth failure with "connect a model"** — [VALUE: med · EFFORT: S] — both catch-alls render the gated/offline copy (`workspace/static/js/applicantChat.js:564-567`; `applicantMind.js:276-279`) even when `err.kind === 'auth'`; an expired session tells the user to go configure a model. `errText()` already branches this — use it.

80. **Chat's gated CTA is a styled `<span>`, not a button** — [VALUE: med · EFFORT: S] — `_renderOffline` passes "Open Settings → Connect a model" as inert text into the kit's CTA slot (`workspace/static/js/applicantChat.js:110-115`) — the quick-wins "empty states route forward" fix landed as prose again. Make it a `.cal-btn` calling `window.launchApplicantSetup()` (the Gallery CTA at `applicantGallery.js:91-105` is the model).

81. **Vault error state predates the kit: no Retry** — [VALUE: med · EFFORT: S] — `_loadTenants` failure writes the message into the empty-slot div (`workspace/static/js/applicantVault.js:164-167`) with no `errorHTML`/`wireRetry`; the user must close and reopen the vault. Same for Mind's plain "Loading…" (`applicantMind.js:251`) vs the kit spinner.

82. **Update's 3s run-poll isn't visibility-aware** — [VALUE: low · EFFORT: S] — `_startPolling` is a raw `setInterval` (`workspace/static/js/applicantUpdate.js:140-158`) while every other poll moved to `pollVisible`; a backgrounded tab hammers the ops proxy for the whole update. Wrap it (resume-on-visible also re-syncs the log).

83. **The Settings one-click-update duplicate lacks live progress** — [VALUE: med · EFFORT: S] — `_renderUpdate` in the wizard/Settings (`workspace/static/js/applicantOnboarding.js:1692-1735`) fires the trigger and prints one static line — no 3s status poll, no log tail, and the button re-enables mid-run (invites a second trigger) while the rail Update surface does all of this correctly (`applicantUpdate.js:140-185`). Delegate to `applicantUpdateModule.openApplicantUpdate()` instead of a parallel implementation.

84. **Starter prompts linger after the conversation starts** — [VALUE: low · EFFORT: S] — the three starter chips render once and persist between the thread and composer forever (`workspace/static/js/applicantChat.js:207`, `:262-271`), consuming vertical space mid-conversation. Hide them after the first user message.

85. **Digest row fade-out animates opacity but the gap snaps shut** — [VALUE: low · EFFORT: S] — `_fadeOutRow` declares a `max-height` transition but never sets a max-height value (`workspace/static/js/emailLibrary/applicantDigest.js:344-348`), so rows below jump abruptly when the node is removed. Set an explicit start/end max-height (and honor reduce-motion by skipping straight to remove).

86. **Mixed button kits inside one Remote toolbar** — [VALUE: low · EFFORT: S] — "Take control" is `.cal-btn cal-btn-primary` beside `.memory-toolbar-btn` siblings in the same row (`workspace/static/js/applicantRemote.js:87-92`), with different heights/hover treatments; the resume card repeats the mix. One family per row.

87. **Remote's inline submit-self confirm drifts from the exported builder** — [VALUE: low · EFFORT: S] — `_onSubmitSelf` hand-writes its confirm copy (`workspace/static/js/applicantRemote.js:486-489`) while `_submitSelfConfirmMessage` (`:476-482`) exists precisely so Portal and Remote say the same thing. Two sources of truth for stop-boundary wording.

88. **"engine ready" status leaks jargon into the Library** — [VALUE: low · EFFORT: S] — the Applications tab stats span literally prints "engine ready" (`workspace/static/js/documentLibrary.js:2036`); the product voice is "assistant", not "engine" (white-label principle #3's plain-language cousin).

89. **Portal "What it never does" toggle lacks `aria-expanded`** — [VALUE: low · EFFORT: S] — the header button shows/hides the panel (`workspace/static/js/applicantPortal.js:322`, `:348-357`) with no expanded state on the control, and when the list is unavailable the click is a silent no-op (`:354`) — disable the button instead.

90. **Quiet-hours second channel select has a `&nbsp;` label** — [VALUE: low · EFFORT: S] — the email hold/send select sits under an empty label (`workspace/static/js/applicantOnboarding.js:541-546`); screen readers announce an unlabeled combobox in the middle of a settings card. Give it a real (visually-hidden if needed) label.

91. **Resume file is uploaded twice** — [VALUE: low · EFFORT: M] — after `uploadPending()` posts the résumé to `/base-resume`, the same `File` is re-POSTed wholesale to `/fonts/detect` (`workspace/static/js/applicantOnboarding.js:1408-1412`) — a 10MB PDF costs 20MB of upload on the slowest step of OOBE. Let the engine run font-detection against the just-stored document instead.

92. **Digest campaign picker changes aren't debounced and don't cancel** — [VALUE: low · EFFORT: S] — Portal digest embed (`workspace/static/js/applicantPortal.js:1368-1371`) and the Email panel (`applicantDigest.js:844-848`) fire a fetch per `change` with no abort of the previous request — pairs with the seq-guard gap in #44; wire both to the kit's AbortController.

93. **Chat's dead `seq` parameter in `_renderThreadIntro`** — [VALUE: low · EFFORT: S] — the campaign-switch path passes `seq` (`workspace/static/js/applicantChat.js:190`) but `_renderThreadIntro(seq)` ignores it (`:219`) — the intro isn't stale-guarded even though pending is; a slow switch can interleave intro/pending from different campaigns.

94. **`_close()` display-state conventions differ per surface** — [VALUE: low · EFFORT: S] — Portal resets `style.display = ''` (`applicantPortal.js:363`), Activity/Results/Update force `display:none` (`applicantActivity.js:269`), Mind uses raw `style.display` with no `.hidden` class at all (`applicantMind.js:54`) — modals reopened by other code paths (`classList.remove('hidden')` only) can stay invisible or double-render depending on which one you hit. One close/open helper in the kit.

95. **Update "Try again" state and disabled reasoning are invisible to AT** — [VALUE: low · EFFORT: S] — when `canTrigger` is false the button is `disabled` with no explanation of *why* (`workspace/static/js/applicantUpdate.js:106-108`); pair the disabled state with the headline reason as `title`/`aria-describedby` (plain-language + tooltips principle).

96. **Onboarding "A key is saved — leave blank to keep it" only in ladder, not the vault-adjacent forms** — [VALUE: low · EFFORT: S] — the ntfy field masks a saved topic (`workspace/static/js/applicantOnboarding.js:475`) and the ladder marks saved keys (`applicantModelLadder.js:91`), but the Proxmox token/RDP password fields say "leave blank to keep the saved one" only inside a hover tooltip (`:796`, `:814`) — surface the saved-marker inline like their siblings do.

97. **`emptyHTML`'s CTA slot is unused almost everywhere** — [VALUE: low · EFFORT: S] — the kit supports a CTA (`workspace/static/js/applicantCore.js:103-109`) but Results' empty (`applicantResults.js:213-220`), Activity's "Warming up" (`applicantActivity.js:349-357`), and Compare's seed state (`applicantCompare.js:270-275`) all pass none — each has an obvious forward action (open Activity, open Portal, pick from Gallery). Cheap continuation of the "no dead-end empty states" thread on the *new* surfaces.
