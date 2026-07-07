# Road-to-Market Backlog

Every bulleted item from the Phase 0 → market plan, transformed into actionable user
stories with a **Definition of Ready (DoR)** and **Definition of Done (DoD)**.

**How to read this**

- **Effort:** S = hours · M = 1–2 days · L = 3+ days.
- **Owner:** `eng` = buildable by the engineering agent · `you` = a decision or
  external action only the product owner can take · `both` = shared.
- **DoR** = preconditions that must hold before the story is picked up (no starting a
  story whose inputs don't exist). **DoD** = the checklist that lets the story be
  called finished — behavioural and verifiable, never "looks done."
- **The universal DoD** below is implied by every story; per-story DoD lists only the
  *additional* acceptance criteria.
- Phases are roughly sequential; items within a phase are ordered by dependency.
  The dependency spine is drawn at the end of each phase.

## Universal Definition of Done (applies to every story)

A story is not done until ALL of these hold, in addition to its own DoD:

1. The change is reachable and operable in the **white-labeled front-door** (not just
   the engine) where it has any user surface — verified by driving the actual UI.
2. Green increment: hermetic engine suite, front-door `test_applicant_*`, `npm test`,
   `ruff`, `lint-imports` (2 kept / 0 broken), both white-label greps, boot smoke,
   single Alembic head, `docker compose config` — all pass locally before merge.
3. No upstream-fork codenames or `FR-`/`NFR-` jargon in any user-facing string.
4. New user-facing behaviour has at least one automated test pinning it against
   regression (visual, unit, or contract as appropriate).
5. Any new setting/guard that protects safety or money is enforced **server-side**,
   never trusting a caller-supplied value.
6. Committed on a focused branch, PR opened as ready-for-review, CI green.

## Universal Definition of Ready (applies to every story)

1. The story's acceptance criteria (its DoD) are written and unambiguous.
2. Its listed dependencies are merged to `main` (or explicitly stubbed with agreement).
3. Any `you`-owned decision or credential the story needs is resolved and recorded.
4. Test fixtures/data the story needs exist (often: demo seed from P0-2).

---

# Phase 0 — Baseline

### P0-1 — Merge the window-chrome / nav / Settings baseline
**As** the team, **I want** the light-glass chrome, Home wordmark, Themes-on-sidebar,
Trust-removal, and Settings regroup on `main` **so that** all later work builds on a
stable visual floor.
**Effort:** S · **Owner:** eng · **Depends on:** — · **Status: DONE** (PR #640, merged as `a2b96af`).
**DoR:** PR #640 CI green; no unmerged conflicts.
**DoD:**
- [x] Squash-merged to `main`; local `main` realigned.
- [x] A fresh boot from `main` shows white frosted glass + clean windows + lands on Today.
- [x] Working branch reconciled to the squashed `main`.

### P0-2 — Seeded demo mode
**As** a demoer/developer, **I want** one env-gated command to load a believable
mid-flight state **so that** every screenshot, video, test fixture, and sales demo
comes from consistent, non-empty data.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:**
- Confirmed list of surfaces that must be non-empty (Today, Tracker, Results, Activity,
  Documents, Gallery, Profile, Daily updates, Calendar, Run log, chat).
- Agreement that seed runs against both in-memory and Postgres.
**DoD:**
- [ ] `DEMO_MODE=1` seed loads: 5 applications across the 5 stages; a digest of ~6
      scored roles each with a visible match rationale; 1 tailored résumé with a real
      redline diff (add + subtract + free-text edit); 1 interview event; ~15
      activity-feed entries; momentum + streak numbers; 2–3 Portal "waiting on you" items.
- [ ] The stale `:wave:` demo chat is replaced by a scripted Applicant conversation;
      2 documents seeded into the library.
- [ ] A visible "Demo data" banner is shown while seeded; a one-click **Clear demo data**
      removes all of it with no residue.
- [ ] Re-running the seed is idempotent (no duplicate rows).
- [ ] The seed path is unreachable when `DEMO_MODE` is unset (guarded + tested).
- [ ] No secret/API key is ever written into seed data (ties to P0-0/​#53).

### P0-3 — Today becomes a page (not a modal)
**As** a user, **I want** Today to be the app's home *page* rather than a floating
window over a chat **so that** the product reads as a job-autopilot dashboard.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1 (P0-2 recommended for review)
**DoR:**
- Decision recorded that only Today (not all surfaces) converts to a page in v1.
- Mobile behaviour agreed (keep bottom-sheet for now).
**DoD:**
- [ ] Login lands on Today rendered in the main content area — no scrim, no dim, no
      close ×, no focus trap.
- [ ] Chat is reachable in one click and back to Today in one click; hash routes
      `#portal`/`#chat` map to the two views.
- [ ] The brand wordmark switches to Today (consistent with P0-1's Home behaviour).
- [ ] The auto-land watcher added in PR #640 is removed; the "Today pops over a window"
      timing quirk no longer reproduces (there is nothing to stack).
- [ ] Deep links to other surfaces still open them; modal-stack tests updated to the
      view contract.

### P0-4 — De-workspace the surface
**As** a non-technical user, **I want** to never see model names, token counters, or
developer-tool furniture **so that** the product feels purpose-built, not a repurposed
AI playground.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:**
- Enumerated list of affordances to hide (sidebar, rail, slash commands, hint pills).
- Confirmed which workspace modules are out of the default product (Notes, Tasks, image
  editor, Cookbook, workspace gallery, research) vs. kept.
**DoD:**
- [ ] In the engine-backed Applicant chat: speaker reads "Applicant"; no model-name
      header, tok/s, %-context chip, per-message edit/delete controls, or composer model
      picker. (Raw-LLM path stays reachable via Compare/model list, unchanged.)
- [ ] Non-product workspace modules are hidden from default nav/rail/commands.
- [ ] Known mislabeled window titles fixed (Documents window no longer titled "Library";
      Daily updates window no longer titled "Email").
- [ ] A test asserts the Applicant chat surface renders **no** model-name literals.
- [ ] White-label greps still clean.

### P0-5 — Empty states that sell
**As** a first-run user, **I want** every empty section to tell me what the agent will
put there and when **so that** the product feels alive before it has data.
**Effort:** S–M · **Owner:** eng · **Depends on:** P0-1 (content benefits from P0-4 voice)
**DoR:**
- Approved one-line copy per section, in Applicant's first-person voice.
- Shared empty-state component design agreed (icon + sentence + one real CTA).
**DoD:**
- [ ] With `DEMO_MODE` **off** and a fresh account, every nav section shows a designed
      empty state — no blank panes anywhere.
- [ ] Each empty state's CTA routes somewhere real (no dead buttons).
- [ ] Empty states render correctly in both light and dark themes.

### P0-6 — Visual regression harness
**As** the team, **I want** every surface screenshot-diffed on each PR **so that**
visual quality ratchets forward instead of oscillating.
**Effort:** M · **Owner:** eng · **Depends on:** P0-2 (stable content), and blessing
must wait until P0-3/P0-4/P0-5 land (or baselines get blessed twice).
**DoR:**
- Determinism hooks identified: freeze aurora/canvas animation, pin the clock, seed
  demo content, mask any residual dynamic regions.
- Surface + viewport + theme matrix agreed.
**DoD:**
- [ ] `workspace/tests/visual/` walks login → Today → each nav section → Settings (each
      group) → theme picker → wizard steps, at 1440×900 and 1024×768, in white-glass and
      one dark theme.
- [ ] Runs are deterministic (animation frozen, clock pinned) — two consecutive runs
      produce a zero diff.
- [ ] A PR that visually regresses any covered surface fails CI with an uploaded diff
      image; `--bless` is the only way to accept a visual change.
- [ ] Baselines blessed **after** P0-3/4/5 are merged.
- [ ] Service-worker staleness addressed (versioned asset URLs or SW cache-bust on
      release) so updated assets aren't served stale.

**Phase 0 spine:** P0-1 → P0-2 → {P0-3, P0-4} → P0-5 → P0-6 (bless last).

---

# Phase 1 — Product completeness

### P1-0 — Revoke & rotate exposed secrets *(pulled from #53 — do first)*
**As** the owner, **I want** all previously-exposed API keys revoked and secret
scanning in CI **so that** no leaked credential survives into demo/seed artifacts.
**Effort:** S · **Owner:** both · **Depends on:** —
**DoR:** List of keys/locations to check (project history + the live demo DB's
configured key).
**DoD:**
- [ ] All previously-exposed OpenRouter (and any other) keys revoked at the provider.
- [ ] The demo/dev DB carries no real key; seed (P0-2) never emits one.
- [ ] CI runs a secret-scanning step that fails on committed credentials.

### P1-1 — Time-to-first-value under 10 minutes
**As** a new user, **I want** onboarding to reliably get me from install to a scheduled
first digest in under 10 minutes **so that** I reach value before I give up.
**Effort:** M · **Owner:** eng · **Depends on:** P0-2, P0-4
**DoR:**
- Provider preset list agreed (OpenRouter + "get a key" link, generic OpenAI-compatible
  URL, local auto-scan).
- Résumé-parse fixtures gathered (including the failing "UC Berkeley — 2013" single-year
  case and an achievements-bearing résumé).
**DoD:**
- [ ] Model-connect step offers presets + a **Verify** button that does a live
      round-trip and reports the failure *reason* (bad key / unreachable / no models)
      with recovery copy.
- [ ] Résumé import accepts PDF/docx/txt and shows a parsed preview **including
      achievements** (closes existing task #25).
- [ ] The single-year education parse renders correctly; a bad parse has an explicit
      "edit" path so it never silently poisons applications.
- [ ] Today shows an essentials checklist (model / profile / notifications) until the
      apply-readiness gate opens, with one-tap wizard resume.
- [ ] A "what happens next" card explains the first digest + approval flow.
- [ ] A stopwatch test from fresh install to "digest scheduled + profile parsed + channel
      set" completes under 10 minutes; every failure state on that path has a recovery action.

### P1-2 — Prove the loop on real boards *(start account setup immediately — longest lead)*
**As** the owner, **I want** recorded end-to-end proof runs on real ATS platforms
**so that** the product's central claim has evidence, not vibes.
**Effort:** L · **Owner:** both (you: employer trial accounts; eng: everything else)
**Depends on:** the stop-boundary + prefill code already on `main`; benefits from P1-1.
**DoR:**
- Greenhouse and Lever employer trial accounts created with self-owned test postings.
- Decision recorded on Workday scope (see P4-DEC-2 / prove via takeover vs. defer).
**DoD:**
- [ ] Full loop runs against ≥2 targets: discovery (URL injection OK) → prefill → stop at
      review → human approve → final submit → confirmation detected → tracker updates.
- [ ] Screen recording + engine run log + DOM snapshots saved to `docs/proof/` per target;
      snapshots re-used as form-fill regression fixtures.
- [ ] Every failure found is fixed or filed with a severity.
- [ ] Stealth stack (camoufox headful in-container) exercised under real network; findings logged.

### P1-3 — Honest health panel
**As** a self-hoster, **I want** every silent capability degrade surfaced with a fix-it
link **so that** I'm never confused by silent stubs.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:** Confirmed the engine's boot-time capability report contents (postgres, resume
renderer, browser, orchestrator) and where each fix lives.
**DoD:**
- [ ] Engine exposes the capability report via an endpoint; front-door proxies it
      (owner-gated) and renders it in Settings → System + a Today banner when anything
      load-bearing is degraded.
- [ ] Each degraded item shows actionable fix copy (not just a red dot).
- [ ] Engine-unreachable produces one designed banner in the front-door, not blank sections.

### P1-4 — Notifications out of the box
**As** a user, **I want** to set a notification channel during onboarding and get a test
digest immediately **so that** the product's heartbeat reaches me.
**Effort:** M · **Owner:** eng · **Depends on:** P1-1 (onboarding), P0-2 (on-demand digest)
**DoR:** Channels in scope confirmed (in-app always; email SMTP, ntfy, Discord webhook opt-in).
**DoD:**
- [ ] Channel setup appears as a Today checklist item (not buried in Settings).
- [ ] Each channel has a **Send test** button that delivers a real message.
- [ ] The digest email template is polished (doubles as marketing asset for P4).
- [ ] A "send my digest now" control exists so demos/first-runs don't wait for the tick.

### P1-5 — Rescue the stranded hardening commits
**As** the team, **I want** the two unmerged 1.0-hardening waves rebased onto `main`
**so that** observability, PII purge/retention, key rotation, and universal-ATS support
are available for Phase 2.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:**
- Confirmed the two work commits (`43670ab` wave 1, `cead689` wave 2) and that the old
  merge commit is to be skipped.
- Agreement to land as two PRs.
- **Decision:** OK to archive/delete `claude/applicant-production-ready-7iep6h` after landing.
**DoD:**
- [ ] Wave 1 (observability alerting, learning biasing, truthfulness fail-closed) and
      Wave 2 (universal-ATS, PII purge/retention, key rotation, chat-onboarding default)
      cherry-picked onto a main-based branch; conflicts resolved (re-implement where a
      pick fights too hard, using the commit as spec).
- [ ] Both waves' tests green on `main` via two PRs.
- [ ] PII-purge + key-rotation capabilities exist for Phase 2 to build on.
- [ ] Old stranded branch archived/deleted (after owner confirmation).

### P1-6 — Cost & pace guardrails
**As** a user paying for LLM calls, **I want** to see and cap my spend and application
pace **so that** I never fear a runaway bill.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:** Confirmed which providers report token usage (OpenRouter does); agreed
cost-estimate display locations.
**DoD:**
- [ ] Daily target (15) + hard cap (30) surfaced on Today.
- [ ] Per-run token usage captured where the provider reports it; per-application cost
      estimate + "today: N applications · ~$X" on Today; monthly projection in Settings.
- [ ] Caps enforced server-side; hitting a cap emits a notification (silence never
      means "stopped").

### P1-7 — Backup, restore, export
**As** a self-hoster, **I want** operator backup/restore and a user data export **so
that** an irreplaceable job search is never lost.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:** Confirmed data locations (Postgres, workspace `data/`, config) and that
`update.sh` already has a pre-migration backup step to share code with.
**DoD:**
- [ ] `scripts/backup.sh` produces one tarball (Postgres dump + workspace data + config);
      `restore.sh` documented; wired into `update.sh`'s pre-migration step.
- [ ] Settings → Account "Download my data" exports a zip (applications CSV+JSON,
      documents, profile, activity) that opens in Excel and a text editor.
- [ ] A scripted backup → destroy volumes → restore drill on the compose stack passes
      clean (app returns whole).

### P1-8 — Résumé↔JD keyword / ATS match score *(competitive gap #1)*
**As** a user, **I want** to see how well each tailored résumé covers the job's
keywords **so that** I trust the tailoring and can approve gap-fixes.
**Effort:** S · **Owner:** eng · **Depends on:** P0-2 (digest/review fixtures)
**DoR:** Confirmed `ResumeVariant.fit_scores` is the storage home; rubric for keyword
coverage agreed.
**DoD:**
- [ ] A deterministic keyword-coverage metric (JD terms vs tailored variant text) is
      computed alongside the LLM fit score and stored in `fit_scores`.
- [ ] Coverage chip shown on digest cards; a "missing terms" panel in redline review.
- [ ] Missing keywords surface as **suggested redline additions the user approves** —
      never auto-inserted (honours the fabrication guard); a suggested term flows through
      the existing redline approve path.

### P1-9 — Save-a-job-from-any-page capture *(competitive gap #2)*
**As** a user, **I want** to drop any job URL into Applicant **so that** roles I find
myself enter the same reviewed pipeline.
**Effort:** S (+S) · **Owner:** eng · **Depends on:** P0-2; discovery parse/score path on `main`
**DoR:** Confirmed the discovery service can accept a single URL and run it through
parse/score (intake endpoint to be added — currently no direct-URL intake exists).
**DoD:**
- [ ] "Add job by URL" input on Today/Tracker → new owner-gated engine intake endpoint →
      existing discovery parse/score → appears in the digest tagged "added by you".
- [ ] A bookmarklet opens `‹host›/capture?url=…` in a popup that reuses the session
      cookie (no browser-extension packaging/store review for v1).
- [ ] A pasted or bookmarked posting appears scored in Pending within ~1 minute.

### P1-10 — Multiple base profiles = light up multi-campaign *(competitive gap #4)*
**As** a user targeting different tracks, **I want** separate campaigns each with its
own base résumé **so that** e.g. "PM-track" and "Eng-track" run independently.
**Effort:** M · **Owner:** eng · **Depends on:** P0-2, P0-3 (Today filters by campaign)
**DoR:**
- Confirmed `Campaign` is designed multi-ready and `ResumeVariant` is campaign-scoped
  with a root (base) variant — **verified: yes** (`campaign.py`, `resume_variant.py`).
- The dormant `multi_campaign_switcher` nav slot identified.
**DoD:**
- [ ] Create a second campaign (name + criteria + its own base résumé); each campaign's
      root variant is its base.
- [ ] The dormant campaign switcher is un-locked and functional; Today/digest/Tracker
      filter by campaign.
- [ ] Services that assume "the single active campaign" (scheduler tick, digest assembly)
      audited and made campaign-aware.
- [ ] The fabrication guard's ground truth scopes to the campaign's own base profile
      (via existing variant lineage), verified by test.
- [ ] Two campaigns run side by side with different base résumés and separate
      digests/pacing.

### P1-11 — LinkedIn Easy Apply: detect & tag *(competitive gap #3, step A)*
**As** a user, **I want** Easy Apply-able roles flagged in my digest **so that** I know
the channel exists even before automation.
**Effort:** S · **Owner:** eng · **Depends on:** P0-2
**DoR:** Confirmed JobSpy exposes the Easy Apply attribute in discovery results.
**DoD:**
- [ ] Discovery marks Easy Apply-able postings; the digest shows the channel per role.
- [ ] Zero automation/login risk introduced by this step (detection only).

**Phase 1 spine:** P1-0 (first) → P1-1 → {P1-3, P1-4, P1-6, P1-7} in parallel · P1-5
parallel · P1-8 → P1-9 → P1-10 (competitive track) · P1-11 seeds the Easy Apply track ·
P1-2 spans the whole phase (external lead time).

---

# Phase 2 — Trust, legal, security & the deeper product-value proofs

*(Detailed at story level here because several items are launch-blocking and were the
"gaps people hit at the end.")*

### P2-1 — ToS posture + Terms of Use *(launch-blocking)*
**Effort:** M · **Owner:** you (decision) + eng (drafts) · **Depends on:** —
**DoR:** Owner decision on positioning ("assistive automation, human approves every
send"); legal entity identified for the terms to bind to.
**DoD:**
- [ ] Terms of Use + Acceptable Use published, stating the human-final-say posture.
- [ ] The claim is consistent with P2-8 (final-say invariant test).

### P2-2 — Privacy story + policy
**Effort:** M · **Owner:** eng drafts / you approve · **Depends on:** P1-5 (purge/retention)
**DoR:** Confirmed what data leaves the box (only to the chosen LLM provider) and the
GDPR/CCPA export+delete mechanism (builds on P1-7 export + P1-5 purge).
**DoD:**
- [ ] Privacy policy published (local-first; data egress only to chosen provider).
- [ ] Export + delete both work end to end and are documented.

### P2-3 — Security pass
**Effort:** M · **Owner:** eng · **Depends on:** P1-5
**DoR:** `security-review` skill available; scope agreed (secrets-at-rest, deps,
authenticated-endpoint sweep).
**DoD:**
- [ ] Security review run; findings triaged and high/critical fixed.
- [ ] Secrets-at-rest audit + dependency audit + authenticated-endpoint sweep complete.

### P2-4 — License compliance *(launch-blocking, cheap now)*
**Effort:** S · **Owner:** eng + you confirm · **Depends on:** —
**DoR:** Upstream fork license identified.
**DoD:**
- [ ] Verified the upstream license permits commercial white-label.
- [ ] NOTICE / third-party attributions complete (camoufox, patchright, JobSpy,
      moderncv, and all bundled deps).

### P2-5 — Fabrication-guard evidence
**Effort:** S · **Owner:** eng · **Depends on:** —
**DoD:** The guard's tests are turned into a citable "never invents your experience"
claim with a reproducible artifact.

### P2-6 — LLM output eval harness *(product-value protection — was the biggest gap)*
**Effort:** M · **Owner:** eng · **Depends on:** P0-2 (fixtures)
**DoR:** Golden set assembled (3–4 profiles × ~20 real postings); rubric agreed
(relevance, tone, honesty/zero-fabrication, diff quality).
**DoD:**
- [ ] Harness runs the golden set through tailoring/scoring/digest on every meaningful
      prompt or model change and scores against the rubric.
- [ ] A regression in any rubric dimension fails the check; results are reviewable.

### P2-7 — Sensitive-question policy *(ethical + marketing line)*
**Effort:** M · **Owner:** eng · **Depends on:** the screening-answer library (migration 0011)
**DoR:** Confirmed the sensitive categories (EEO/demographic: race, gender, disability,
veteran; plus work-authorization handling).
**DoD:**
- [ ] The engine **never** auto-answers sensitive/demographic questions — they are
      flagged for the human at review, enforced server-side and tested.
- [ ] Work-authorization questions get explicit, user-confirmed handling.

### P2-8 — "Human final say" invariant test
**Effort:** S · **Owner:** eng · **Depends on:** —
**DoD:** A test proves no code path reaches final submit without an approval record
(citable invariant, like the fabrication guard).

### P2-9 — App-door hardening
**Effort:** M · **Owner:** eng · **Depends on:** —
**DoD:**
- [ ] Strong-password enforced at first login; existing TOTP 2FA surfaced; login attempts
      rate-limited.
- [ ] A reverse-proxy/HTTPS guide (Caddy/Traefik snippet) shipped.

### P2-10 — ATS-parseability proof
**Effort:** M · **Owner:** eng · **Depends on:** P1-2 (generated PDFs)
**DoD:** Generated PDFs run through an open-source ATS parser; fields extract cleanly;
result is a citable "ATS-safe" claim.

### P2-11 — Verified local-only private mode
**Effort:** M · **Owner:** eng · **Depends on:** local model path
**DoD:** A tested configuration where no profile/job data leaves the box (local model
only); documented + asserted.

### P2-12 — Durability drills
**Effort:** M · **Owner:** eng · **Depends on:** P1-2
**DoD:** Kill engine mid-prefill, kill browser mid-run, hit a CAPTCHA wall, take a source
offline — each drill passes (restart-survival) or files a bug.

### P2-13 — Source reliability matrix
**Effort:** M · **Owner:** eng · **Depends on:** —
**DoD:** Discovery quality tested across 2–3 regions/categories; per-source health
surfaced in UI (ties to P1-3); expectations documented.

### P2-14 — LinkedIn Easy Apply: assisted mode *(launch feature; parallel track)*
**Effort:** M · **Owner:** both (you: real aged LinkedIn account; eng: build)
**Depends on:** P1-11, screening-answer library, stealth persistent profile
**DoR:**
- A real, owner-controlled aged LinkedIn account for proof runs.
- Owner-approved consent-screen stance ("automates your LinkedIn account against their
  ToS; you accept the account risk").
**DoD:**
- [ ] Logged-in session in the persistent stealth profile; agent walks the Easy Apply
      modal (screening-answer library handles Q&A) and **stops at Submit** → review/
      takeover surface → human sends.
- [ ] Consent screen shown and recorded before first use.
- [ ] A recorded proof run on the real account exists.

---

# Phase 3 — Packaging & distribution

### P3-1 — One-command install, tested targets
**Effort:** M–L · **Owner:** eng · **Depends on:** Phase 1 complete
**DoD:** `docker compose up` verified on Ubuntu/Debian + the Proxmox script + one
NAS-class box; clean upgrade (`update.sh`) and uninstall paths tested.

### P3-2 — Requirements & model matrix
**Effort:** S–M · **Owner:** eng · **DoD:** Published table — models good-enough per
tier, supported APIs, RAM/VRAM minimums, cost-per-application.

### P3-3 — Business model + licensing *(owner decision)*
**Effort:** M · **Owner:** you decide / eng builds · **Depends on:** P2-4, P4-DEC-1
**DoR:** Pricing model chosen (recommendation: paid license via Paddle/Lemon Squeezy,
$49–99/yr or one-time+update-year, free trial mode).
**DoD:** Privacy-respecting license check implemented; trial mode works; purchase flow
tested end to end.

### P3-4 — Docs site
**Effort:** M · **Owner:** eng · **DoD:** Quickstart, FAQ, troubleshooting,
security/privacy pages; generated from the repo so it can't drift.

### P3-5 — Release engineering
**Effort:** M · **Owner:** eng · **DoD:** Versioned releases, changelog, signed images on
GHCR, stable/beta channels.

### P3-6 — Workspace DB migration strategy *(operational gap — decide before first schema change)*
**Effort:** M · **Owner:** eng · **DoD:** A mechanism exists for evolving the workspace
SQLite schema across releases (the engine has Alembic; the workspace does not); the first
post-launch schema change upgrades cleanly in a test.

### P3-7 — Platform matrix *(operational)*
**Effort:** S–M · **Owner:** eng + you decide · **DoD:** amd64-only constraint documented
OR multi-arch built; Docker-on-WSL2 path tested.

### P3-8 — Digest deliverability *(operational)*
**Effort:** S–M · **Owner:** eng · **DoD:** ntfy/Discord defaulted as the recommended
channel; SPF/DKIM guidance shipped for the SMTP path.

---

# Phase 4 — Go-to-market

### P4-1 — Positioning: name the enemy
**Effort:** S · **Owner:** you + eng · **DoD:** A one-sentence positioning statement
("autopilot with a human final say — self-hosted, private, honest") that every asset flows from.

### P4-2 — Landing page
**Effort:** M · **Owner:** eng · **Depends on:** P0-2 (hero data), P4-1
**DoD:** `landing.html` rebuilt around the demo hero video, privacy stance, pricing, FAQ.

### P4-3 — Proof assets
**Effort:** M · **Owner:** eng (+ you voiceover) · **Depends on:** P0-2, P1-2, P1-4
**DoD:** 2-minute demo video from seeded data; the digest email as a shareable sample;
a before/after tailoring diff.

### P4-4 — Competitive teardown
**Effort:** M · **Owner:** eng · **DoD:** Feature grid + failure modes + pricing for
AIHawk, LazyApply, Simplify, and the tracker/AIApply classes; verifies the current
comp set (confirm Sonara status) and sharpens P4-1.

### P4-5 — Early-access cohort
**Effort:** M · **Owner:** you recruit / eng instrument · **DoD:** 10–20 users with a
feedback channel and a weekly fix cadence; quotes captured for testimonials.

### P4-6 — Pricing validation *(owner)*
**Effort:** S · **Owner:** you · **Depends on:** P4-5, P3-3
**DoD:** Price tested with the cohort before public launch; decision recorded.

### P4-DEC-1 — Source-available vs. closed *(owner decision, needed by P3-3/P4-2)*
**Owner:** you · **DoD:** Decision recorded; interacts with P2-4 fork license; shapes
pricing, distribution, trust.

### P4-DEC-2 — Takeover-desktop scope for v1 *(owner decision, affects P1-2)*
**Owner:** you · **DoD:** In/out decision recorded; adjusts the P1-2 proof matrix and
marketing claims.

### P4-7 — Name check *(cheap now, painful later)*
**Effort:** S · **Owner:** you · **DoD:** Trademark search, domain, social handles, and
self-hosted-store collision check for "Applicant" complete; go/no-go on the name.

---

# Phase 5 — Launch & operate

### P5-1 — Support machinery
**Effort:** M · **Owner:** eng · **DoD:** Issue templates + a redacted diagnostic-bundle
command + a small Discord/forum.

### P5-2 — Pre-written support surface *(operational)*
**Effort:** M · **Owner:** eng · **Depends on:** P5-1 · **DoD:** Top-20 predictable FAQs
written before launch (no jobs found, empty digest, invalid key, CAPTCHA hit, weak model, …).

### P5-3 — Opt-in error telemetry
**Effort:** S–M · **Owner:** eng · **DoD:** Crash reporting that respects the privacy
story; opt-in; actionable.

### P5-4 — Launch sequence
**Effort:** M · **Owner:** you + eng · **Depends on:** cohort fixes · **DoD:** Soft launch
→ fix top 10 → Show HN + r/selfhosted + Product Hunt staggered a week apart; comparison
content vs. LazyApply-class tools for SEO.

### P5-5 — Post-launch flywheel
**Effort:** ongoing · **Owner:** both · **DoD:** Weekly releases, public roadmap,
testimonial collection; then the expansion decisions — self-hosted app-store listings
(Unraid CA, Umbrel, CasaOS) and an eventual hosted tier.

### P5-6 — Full LinkedIn Easy Apply autopilot *(post-launch, flagged)*
**Effort:** L · **Owner:** eng · **Depends on:** P2-14
**DoD:** Autopilot behind a flag; hard caps well under LinkedIn tolerance (existing pacing
ledger); takeover fallback on checkpoint/2FA; explicit consent; recorded safe run.

---

# Cross-phase experience & quality (schedule alongside their phase)

### X-1 — Mobile golden-path audit
**Effort:** M · **Owner:** eng · **Schedule with:** P0-6 (add mobile to the harness)
**DoD:** The "digest → review on phone → approve" path walked at 390×844; issues fixed;
mobile added to the visual matrix.

### X-2 — Cross-browser smoke
**Effort:** S–M · **Owner:** eng · **Schedule with:** P0-6
**DoD:** Golden path passes in Firefox + WebKit; the `@supports` solid-panel fallback
looks intentional where glass is unsupported.

### X-3 — Performance budget
**Effort:** M · **Owner:** eng · **Schedule with:** Phase 1
**DoD:** Login→interactive and window-open latency measured; budgets set; cheap wins taken
(boot warm-up, blur/aurora GPU cost on modest hardware).

### X-4 — Accessibility pass
**Effort:** M · **Owner:** eng · **Schedule with:** Phase 1
**DoD:** Keyboard-only completes the golden path; a WCAG-AA contrast sweep across the
theme system passes.

---

# Owner-only decisions, gathered (unblock these early)

| ID | Decision | Blocks |
|----|----------|--------|
| P1-0 | Which keys to revoke; enable secret scanning | first, always |
| P1-2 / P4-DEC-2 | Employer trial accounts; Workday/takeover scope | P1-2 proof runs |
| P1-5 | OK to archive the old designated branch | branch cleanup |
| P2-1 | Terms posture + legal entity | launch |
| P2-4 | Fork license permits commercial white-label | launch |
| P2-14 | Real LinkedIn account + consent-screen stance | Easy Apply |
| P3-3 / P4-6 | Business model + price | packaging, launch |
| P4-DEC-1 | Source-available vs. closed | pricing, landing page |
| P4-7 | Name check on "Applicant" | branding, stores |
