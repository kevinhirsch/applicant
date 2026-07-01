# Applicant — Quick Wins & Cross-Cutting Polish (lens 08)

> **Lens.** Highest value-to-effort wins across the *entire* product, plus concrete steps to
> **close the coverage gaps** (`APPLE_GENIUS_IMPROVEMENTS.md` §I — the trust-core flows never
> rendered/audited). Deliberately **excludes** the static visual/CSS/color/HIG-styling items already
> enumerated in that audit (§A–§H); this list is what's *cross-cutting or missing* — behavior,
> performance, a11y semantics, error/loading/empty states, microcopy, defaults, small features that
> punch above their weight, and telemetry.
>
> Grounded in `workspace/static/js/applicant*.js`, `workspace/static/index.html`,
> `workspace/routes/applicant_*_routes.py`, `src/applicant/`, `scripts/playtest_crawl.py`.
> Format: `N. **Title** — [VALUE · EFFORT] — rationale + anchor.`

---

## Ranked — best value/effort first

1. **Pause all polling when the tab is hidden** — [VALUE: high · EFFORT: S] — Portal badge (60s, `applicantPortal.js:1214`), Activity strip (45s, `applicantActivity.js:370`), and Update log (3s, `applicantUpdate.js:142`) all `setInterval` unconditionally and keep hitting the engine while the tab is backgrounded — wasted requests + battery on a 24/7 self-hosted app left open in a pinned tab. The pattern already exists: `emailLibrary/applicantDigest.js:887–906` guards on `document.visibilityState`. Add one shared `visibilitychange` guard (pause on hidden, immediate refresh on show).

2. **Add a request timeout / AbortController to `_fetchJSON`** — [VALUE: high · EFFORT: S] — `applicantCore.js:27` does a bare `fetch(url, {credentials})` with no timeout. If the internal `api` service hangs (engine tick busy, sandbox launching a browser), every surface spins on "Loading…" forever with no recovery. Wrap with an `AbortController` + ~15s timeout so a hung engine yields a real error state instead of an infinite spinner. Single chokepoint fixes every surface at once.

3. **Reuse the existing spinner for "Loading…" instead of bare text** — [VALUE: high · EFFORT: S] — A real spinner (`spinnerModule.createWhirlpool`) already exists and is used by `applicantUpdateView.js` and toasts, but Portal/Chat/Documents/Memory/Mind/Gallery/Compare/Debug/Vault all render a bare `<div class="hwfit-loading">Loading…</div>` (e.g. `applicantChat.js:82`, `applicantPortal.js:291`, `applicantGallery.js:57`, `applicantDebug.js:91`). Extract a `_loadingHTML()` helper in `applicantCore.js` that emits the whirlpool + label; adopt everywhere. Directly closes coverage-gap §I.2 ("streaming/thinking spinners never rendered").

4. **`aria-label` on all icon-only close buttons** — [VALUE: high · EFFORT: S] — The `✖` close buttons carry only `title="Close"` (announced inconsistently by screen readers) in Chat (`applicantChat.js:79`), Activity (`:153`), Compare (`:66`), Debug (`:76`), Gallery (`:47`), Update (`:60`). Portal already does it right (`applicantPortal.js:286` has both `aria-label` + `title`). One-line each.

5. **Make the Activity status strip a live region** — [VALUE: high · EFFORT: S] — `#applicant-status-strip` renders "Applicant is: …" and flips `.is-live`/`.is-paused` (`applicantActivity.js:104–122`) but has no `aria-live`/`role="status"`, so a screen-reader user gets zero signal that the agent is alive — the exact "is it doing anything?" heartbeat (Journey Beat 2). Add `role="status" aria-live="polite"` to the strip container. (Toasts are already fine: `index.html:2555` has `role="status" aria-live="polite"`.)

6. **`aria-label` the nav rail icon buttons** — [VALUE: high · EFFORT: S] — The whole left rail (`#rail-portal`, `#rail-activity`, `#rail-assistant`, `#rail-memory`, `#rail-email`, `#rail-gallery`, … `index.html:838–862`) is icon-only with `title=` only. The rail is the primary nav; a screen-reader user can't tell the buttons apart. Add `aria-label` to each (mirror the tooltip text).

7. **Inline "Retry" on error states** — [VALUE: high · EFFORT: S] — Gallery (`applicantGallery.js:165`), Compare (`applicantCompare.js:182`), Debug (`:326`), Chat (`:363`), Vault (`:166`) all render dead-end error text ("Engine not reachable" / "Couldn't reach…") with no retry — the user must close and reopen the whole surface. Add a neutral "Try again" button that re-invokes the loader. Pairs naturally with #2.

8. **Coalesce the Activity-strip and Portal-badge polls** — [VALUE: med · EFFORT: S] — The strip polls `/activity/status` (45s) and the badge polls `/portal/pending` (60s) independently; both answer "what's waiting?" and run forever. Either share one 45–60s tick that updates both, or let the badge read from the strip's payload. Halves steady-state request volume.

9. **Silent `catch` on the Activity strip hides the heartbeat with no signal** — [VALUE: med · EFFORT: S] — `applicantActivity.js:128` swallows fetch errors and just hides the strip, so a transient engine blip makes the pulse vanish silently (reads as "dead"). Show a neutral "reconnecting…" state instead of disappearing.

10. **Gate the Chat send button on non-empty input** — [VALUE: med · EFFORT: S] — The circular send is filled system-blue even with an empty field (`style.css:33391/33470`, wiring in `applicantChat.js`), inviting a no-op submit. Disable/dim until there's content. (Small, but it's the primary action on the most-used conversational surface.)

11. **Add a `/` and `Cmd/Ctrl+K` shortcut to open + focus the assistant** — [VALUE: med · EFFORT: S] — No Applicant-scoped global shortcuts exist (only in-composer `Cmd+Enter` to send, `applicantChat.js:198`). A single `/`-to-focus-chat / `Cmd+K`-to-open-Portal binding makes the daily loop keyboard-drivable. The rail already advertises `Ctrl+K` for conversation search (`index.html:838`) — align the Applicant surfaces to the same muscle memory.

12. **Explicit Escape handler on Vault & Onboarding modals** — [VALUE: med · EFFORT: S] — Chat/Activity/Gallery bind `keydown Escape` directly (`applicantChat.js:88`), but Vault (`applicantVault.js`) and Onboarding rely solely on `initModalA11y`. For a *blocking* OOBE overlay Escape should be intentional (probably suppressed, not accidental), and Vault should confirm Escape closes without losing typed secrets. Audit + make explicit.

13. **Kill unbounded boot-retry intervals cleanly** — [VALUE: low · EFFORT: S] — Every module runs a 500ms `setInterval` launcher-wiring retry that clears after ~20 tries (`applicantPortal.js:1200`, `applicantActivity.js:360`, +6 more). Harmless individually but it's 8 identical loops; extract one `_wireWhenReady(ids, fn)` helper in `applicantCore.js`. Reduces duplicated churn and the chance one forgets to clear.

14. **`role="alert"` on modal error messages** — [VALUE: med · EFFORT: S] — Only one live-error region exists in the whole Applicant surface (`applicantOnboarding.js:211`). Form-submit failures ("Could not save sign-in", "Couldn't reach the assistant") render as plain text and are silent to AT. Give inline error nodes `role="alert"`.

15. **Add a "connected/degraded" health indicator to the status strip** — [VALUE: high · EFFORT: M] — Today the strip only knows live/paused; if the engine is unreachable it silently blanks (#9). A tiny neutral "· offline" / "· reconnecting" affordance turns the always-visible strip into the product's real health telemetry (NFR-247-1) — the single cheapest observability win, since the strip is already always on screen.

16. **Chat is request/response, not streaming — no thinking indicator, no partial output** — [VALUE: high · EFFORT: M] — `applicantChat.js` has no `EventSource`/`getReader`/SSE (grep: zero stream primitives); it posts and waits for a full reply, showing bare "Loading…". The Journey Map's Beat 5 explicitly wants "live chat with bubbles." At minimum add a thinking pill/spinner during the wait (reuse `createWhirlpool`); ideally wire the engine's streaming chat endpoint. This is also coverage-gap §I.2 (dynamic optics never rendered).

17. **No "Stop"/cancel while the assistant is thinking** — [VALUE: med · EFFORT: M] — Because chat blocks on a full response (#16), a slow/looping model can't be interrupted (`applicantChat.js:55–57` notes steering controls were removed). Add a Stop affordance backed by the AbortController from #2. Cheap trust win on the highest-tension surface.

18. **Empty-state CTAs that dead-end should route forward** — [VALUE: med · EFFORT: S] — Gallery's empty state points at a disabled "No job searches yet" picker (`applicantGallery.js:157`) with no way out; Chat's "connect a model" offline text (`applicantChat.js:109`) is prose, not a button. Add one tinted CTA (`launchApplicantSetup()` / "Create a job search") so every empty state has a next step. (Portal already models this well at `:353–363`.)

19. **Debounce / dedupe the badge refresh on multi-surface open** — [VALUE: low · EFFORT: S] — Opening the Portal triggers a list load *and* the 60s badge keeps ticking; several surfaces call `refreshBadge()`/`refreshStatus()` on their own opens. A tiny in-flight guard (skip if a fetch is already pending) avoids double requests on rapid nav.

20. **`Cmd/Ctrl+Enter` to approve, `Esc` to send-back in the redline review** — [VALUE: med · EFFORT: M] — The digest→redline→approve loop (`documentLibrary.js`) is the daily consent gate (Journey Beat 3); making approve/decline/send-back keyboard-reachable speeds the single most-repeated action. (Verify the decision trio exists first — it's part of the unaudited flow, see gap section.)

21. **Bulk approve/decline in the digest** — [VALUE: med · EFFORT: M] — The daily digest lists multiple roles each needing an approve/decline; there's no select-all or bulk action. A "decline all remaining" / "approve visible" affordance turns a 10-tap chore into one. High leverage on the daily loop (FR-DIG).

22. **Portal filters / saved views** — [VALUE: med · EFFORT: M] — The Portal is a "dense, heterogeneous action queue" (feature-map §5) — approvals, reviews, questions, errors, final-submits — with no way to filter by type or hide informational rows. A simple segmented filter (Needs me / Info / All) makes a busy inbox scannable. Small feature, big daily payoff.

23. **Undo on destructive Portal/Memory actions via the toast action slot** — [VALUE: med · EFFORT: M] — `showToast` already supports an `action`/`onAction` button (`ui.js:336–343`) but it's unused by Applicant surfaces. Wire "Declined · Undo" / "Forgotten · Undo" on decline/forget so a mis-tap is recoverable — directly serves the "user is always authority over the agent's memory, reversible" promise (Journey Beat 6).

24. **Surface the wallpaper/mesh preset picker in Settings** — [VALUE: low · EFFORT: S] — In-app wallpaper is hard-pinned to `aurora` (`theme.js:36`) while login exposes all 5 presets; an OLED/low-power/distraction-reduced option is a sensible setting that should exist (also a perf lever — see #26).

25. **A "Reduce mesh animation / low-power mode" setting** — [VALUE: med · EFFORT: M] — The animated mesh + full-glass refraction run continuously with no user throttle (`theme.js:36`). A single "Calm/low-power" toggle (freeze the mesh, drop to Frosted) is both an a11y and a battery win on an always-open dashboard. Ties to the unmeasured full-glass perf gap (§I.6).

26. **Measure & document full-glass refraction cost** — [VALUE: med · EFFORT: M] — Coverage-gap §I.6: refraction across every window with real content is unmeasured. Add a one-off perf capture (see gap section) and, if the cost is real, default heavy surfaces (Debug logs, Gallery grids, Compare tables) to Frosted (cheaper) rather than full glass.

27. **Consistent close-glyph + hit-target across surfaces** — [VALUE: low · EFFORT: S] — Close controls mix `✖` vs `×`, `.close-btn` vs `.modal-close` (`applicantGallery.js:47` vs others) and several are <44px. Standardize one close primitive with a ≥44px padded hit region. (Behavioral/consistency, not styling.)

28. **Tooltip coverage on toggles and status chips** — [VALUE: low · EFFORT: S] — Debug source/tool toggles, run-mode chips, and the model-ladder tiers carry engineering-y labels with no `title`/tooltip explaining what toggling does. Add plain-language tooltips (the product's stated "plain language + tooltips" principle, CLAUDE.md #3).

29. **Plain-language microcopy for engineering labels** — [VALUE: low · EFFORT: S] — "Add/Added Models", "(Endpoints)", "L1→N tiers", "exploration budget" leak implementation vocabulary into user-facing strings (settings, model ladder). Rename to "Local model / Cloud API", "how hard to look beyond your exact criteria", etc. Cheap trust + white-label hygiene.

30. **Confirm-before-navigate-away with unsaved Vault/Onboarding input** — [VALUE: med · EFFORT: S] — Typing a credential or profile field and hitting Escape/backdrop-click discards it silently. Add a dirty-check `beforeunload`/confirm on the two surfaces where lost input is most costly (secrets, OOBE intake).

31. **Persist the last-selected campaign across surfaces** — [VALUE: med · EFFORT: S] — Gallery, Debug, Compare, Memory each have their own campaign picker that resets to default on open. Store the active campaign (localStorage or a shared module) so switching context once sticks everywhere. Removes a repeated per-surface re-selection tax.

32. **Show a relative-time "last updated" on polled surfaces** — [VALUE: low · EFFORT: S] — Portal/Activity/Update poll silently; nothing tells the user how fresh the data is (or that a poll failed). A tiny "updated 12s ago" caption (and "stale" after a failed poll) makes freshness legible and cheaply signals degradation.

33. **Copy-to-clipboard on logs / audit / IDs** — [VALUE: low · EFFORT: S] — Debug logs are a raw `<pre>` (`applicantDebug.js:440`) and Compare needs entity IDs typed in by hand (`applicantCompare.js`). A copy button on log lines and clickable-to-copy IDs removes manual transcription. `ui.js:221` already has a copy+toast helper to reuse.

34. **Prefill Compare with recent entity IDs instead of blank inputs** — [VALUE: med · EFFORT: M] — Compare makes the user paste 2+ raw IDs (`applicantCompare.js:76`) with no picker — a dead-end for anyone who doesn't have IDs memorized. Offer a recent-applications/postings dropdown. Turns an expert-only tool into a usable one.

35. **"Working…/Comparing…" needs a cancel + progress affordance** — [VALUE: low · EFFORT: S] — Compare shows text-only "Comparing…" with no spinner or cancel (`applicantCompare.js:169`); reuse the shared spinner and add cancel via AbortController (#2).

36. **Sensible default for daily throughput and run mode on first campaign** — [VALUE: low · EFFORT: S] — Campaign settings expose throughput (1–30) and run mode with no guided default; a first-time user faces raw knobs (`applicantCampaignSettings.js`). Pre-seed a conservative default ("5/day, continuous") with a one-line rationale so the campaign works before it's tuned.

37. **Debug tab count exceeds the scan ceiling (8 tabs)** — [VALUE: low · EFFORT: M] — `applicantDebug.js:50` renders 8 tabs (Activity/Insights/Logs/Variants/Run/Sources/Tools/Update); collapse Sources+Tools+Update into one "Config" pane. Reduces cognitive load on the admin surface. (Behavioral IA, not styling.)

38. **Announce badge-count changes politely** — [VALUE: low · EFFORT: S] — The Portal rail badge updates the count silently; wrap it in an `aria-live="polite"` so "3 items need you" is announced when new work arrives, matching the toast promise for sighted users.

39. **Guard the "Ask the assistant" button when chat module is absent** — [VALUE: low · EFFORT: S] — `applicantDebug.js:119` renders an "Ask the assistant" action that no-ops to a toast if chat isn't present — a dead control. Gate its render on module presence.

40. **Focus the first field / primary action on modal open** — [VALUE: low · EFFORT: S] — `initModalA11y` traps focus but confirm it also *moves* focus into the modal (to the first input for forms, or the primary CTA). Otherwise keyboard users start outside the trap. Quick verify + fix across Vault/Onboarding/Chat.

41. **`prefers-reduced-motion` audit of the spinner + strip dot** — [VALUE: low · EFFORT: S] — The whirlpool spinner and live/paused dot animate; confirm both are gated for reduce-motion (several `infinite` keyframes are known-ungated per §I.4). Cheap, and part of the "stillness = trustworthy agent" thesis.

42. **Error toast should differentiate 401/expired-session from engine-down** — [VALUE: med · EFFORT: S] — `_fetchJSON` throws with `err.status` (`applicantCore.js:34`) but callers show generic "Engine not reachable" for everything. A 401 means "your session expired — sign in again" (actionable) vs 502/timeout means "engine busy." Branch the message on `err.status`. Removes a common confusing dead-end.

43. **Skeleton rows for the Portal/Documents list on first load** — [VALUE: low · EFFORT: M] — Beyond a spinner (#3), the Portal and Documents lists benefit from 2–3 ghost rows so the layout doesn't jump when data arrives. Small, and it makes the most-used surface feel instant.

44. **Telemetry: count silent failures** — [VALUE: low · EFFORT: M] — Multiple `catch (_) {}` blocks (Activity strip, Portal notifs `:1006`) swallow errors with no trace. A tiny client error-beacon (or at least `console.warn` with a stable tag) makes field debugging of a self-hosted box possible without a repro.

45. **Auto-refresh the Portal list after resolving an action** — [VALUE: med · EFFORT: S] — Confirm that approving/declining a row re-fetches (or optimistically removes) so the resolved item disappears immediately rather than waiting for the 60s poll. If it waits, the queue feels stale right after the user acts — the worst moment for lag.

46. **Debounce campaign-switch fetches** — [VALUE: low · EFFORT: S] — Rapidly changing the campaign picker fires a fetch per change; debounce ~250ms so scrubbing the dropdown doesn't storm the engine.

47. **Consistent number/date formatting** — [VALUE: low · EFFORT: S] — Insights funnels render as dot-joined prose and timestamps are raw (`applicantDebug.js:393`, logs). A shared `_fmtDate`/`_fmtCount` in `applicantCore.js` (Intl-based, locale-aware) gives consistent, glanceable numbers everywhere for near-zero cost.

48. **"Never does" trust list should render on the gated Portal** — [VALUE: med · EFFORT: S] — `_neverDoesHTML()` exists (`applicantPortal.js:338`) to show the safety guarantees but the gated (pre-setup) view drops it — exactly when a nervous new user most needs the reassurance. Render it beneath the gate. (Behavioral/content, high trust ROI.)

---

## Closing the coverage gaps

> Job (2): turn each `§I` coverage gap into a concrete do-this task. The root blocker for gaps #1–#2
> is **there is no seed/demo data path** — `scripts/playtest_crawl.py` boots the stack and opens every
> surface *empty* (no model, no campaign), and there is **no engine debug/seed endpoint** (checked
> `src/applicant/app/routers/*` — `admin.py` is read-only query; no seed route). So the trust-core
> flows physically cannot be rendered populated today. Fix that first.

49. **Build a seed/demo fixture path in the engine** — [VALUE: high · EFFORT: M] — Add a dev-only, env-gated (`APPLICANT_ALLOW_SEED=1`) endpoint or `scripts/seed_demo.py` that inserts one campaign, a handful of discovered postings, a pending digest, a resume-variant with a redline session, and 3–4 Portal pending-actions of different kinds (digest-approval, material-review, agent-question, final-submit). Reuse `onboarding_seed.py` (`src/applicant/application/services/onboarding_seed.py`) as the model for pure derivation. **This unblocks every render below** and is the single highest-leverage gap-closer (§I.1).

50. **Extend `playtest_crawl.py` to seed-then-crawl** — [VALUE: high · EFFORT: S] — After #49, add a `--seed` flag to `scripts/playtest_crawl.py` that hits the seed endpoint before enumerating surfaces, so the crawl screenshots a *populated* Portal, a redline, a live chat, etc., instead of empty states. The crawl harness (login → open each seam → screenshot → click) already exists; it just needs data first.

51. **Render + audit Beat 3 (digest → redline → approve)** — [VALUE: high · EFFORT: M] — With seed data: connect a stub/local model, open the digest (`emailInbox.js`/`applicantDigest.js`), enter the redline review (`documentLibrary.js`), exercise add/subtract/free-text and approve/decline/send-back. Capture the additions/subtractions highlighting (content color must survive Reduce Transparency — it's engine-rendered HTML), and confirm the decision trio is consistent and keyboard-reachable (feeds #20). Currently **unjudged** (§I.1).

52. **Render + audit Beat 4 (live takeover / final-submit)** — [VALUE: high · EFFORT: M] — Drive a sandbox session to the takeover state (`applicantRemote.js`), render the live-view iframe, the "take control" handoff, and the final-submit decision pair ("I submitted" vs "authorize the assistant"). Verify the irreversible option reads as **destructive** and the decision isn't pushed below the fold by dormant cards. Highest-gravity beat, currently empty (§I.1).

53. **Render + audit a populated Portal + live chat bubbles** — [VALUE: high · EFFORT: S] — With #49's pending-actions and a connected model, screenshot the Portal with heterogeneous rows (the "dense queue" the design must handle) and a real chat exchange with `.msg-user`/`.msg-ai` bubbles + streaming/thinking state (§I.1 + §I.2). This is the steady-state (Beat 5) the whole product is judged on.

54. **Capture + audit Beat 0 (landing + login)** — [VALUE: high · EFFORT: S] — `landing.html` and `login.html` were never captured (§I.3) yet they're the first pixel of trust. Add both to the crawl's surface list (they're pre-auth, so crawl them before login), screenshot hero legibility over the mesh, the system-font stack, and one-CTA focus. Small — just add two entries + a pre-login capture step to `playtest_crawl.py`.

55. **Render the dynamic optics states (§I.2)** — [VALUE: med · EFFORT: M] — Adaptive-ink flip, specular/lensing-in-motion, streaming spinners, and toasts can't be judged from stills. Add a scripted interaction pass to the crawl: trigger a toast, start a chat stream, scroll a glass surface over a bright mesh lobe, and capture a short video/frame-sequence. Confirms the material actually behaves, not just renders.

56. **Render the a11y degraded states (§I.4)** — [VALUE: med · EFFORT: S] — The reduce-transparency / reduce-motion / increase-contrast fallbacks are wired but never rendered. Add crawl runs with Playwright's `colorScheme`/`reducedMotion`/`forcedColors` emulation (and a `prefers-reduced-transparency` media override) and screenshot each surface, confirming glass truly falls back to solid and motion truly stops. Cheap, and it's a trust promise to a whole user class.

57. **Render the responsive breadth (§I.5)** — [VALUE: med · EFFORT: S] — Only desktop + a couple mobile widths were captured. Add tablet (768/834), very-narrow (320), and very-wide (1920+) viewports to the crawl's screenshot loop. Pure config change to the existing harness — catches stepper truncation (`applicantOnboarding.js:179`), toolbar overflow, and clipped modals.

58. **Measure full-glass performance under real content (§I.6)** — [VALUE: med · EFFORT: M] — Refraction cost across every window with real data is unmeasured. Add a Playwright perf capture (CDP `Performance`/`Tracing`, or `performance.measure` around open+scroll) on the heaviest surfaces (Debug logs, Gallery grid, Compare table) both Frosted and full-glass, on a throttled CPU profile. Produces the number the "no perf hit" concern needs, and tells you whether to default heavy surfaces to Frosted (#26).

59. **Add the seed/render/audit loop to the playtest protocol doc** — [VALUE: low · EFFORT: S] — Fold #49–#58 into `docs/playtest-protocol.md` §6a so "connect a model + seed data → crawl → audit the trust-core beats" becomes the repeatable run-until-green procedure, not a one-off. Makes the coverage gaps stay closed.
