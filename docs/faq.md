# FAQ — the top 20 predictable questions (P5-2)

This is the pre-written support surface for the questions people actually hit while
running Applicant day to day — as distinct from `workspace/static/landing.html`'s
`#faq`, which is pre-signup marketing copy (what Applicant promises before you've
installed it). Every answer below is grounded in the actual mechanism in the code,
not a guess at what "should" happen — where something is a known current gap, it says
so plainly rather than glossing over it.

**Reachable in the app too:** Settings → Help & FAQ (`workspace/static/index.html`,
`data-settings-tab="help"`) carries the identical 20 questions as a native
`<details>`/`<summary>` accordion — the same disclosure pattern the app already uses
elsewhere (`applicantTracker.js`'s history rows, the landing page's own `#faq`). This
file is the docs-site mirror of that surface (P3-4's docs site, once it exists, sources
its FAQ page from this file so the two can't drift). If P5-1 ("Support machinery") has
landed by the time you're reading this, see [`docs/support.md`](support.md) for the
redacted diagnostic-bundle command and issue templates — the next step past this page,
not a replacement for it.

---

### 1. No jobs are showing up in Discovery — is something broken?

Usually not — discovery deliberately refuses to run until you've told it what to look
for. With zero search criteria configured, the cold-start guard
(`src/applicant/core/rules/discovery_gate.py`, `require_criteria_before_discovery`)
blocks the run rather than surfacing arbitrary postings on a neutral placeholder score.
Set at least one of: a target title, location, work mode, salary floor, or keyword in
Settings → Job Search. Once criteria exist, check each source's own status there too —
a source can say "found nothing on the last check", "couldn't be searched on the last
check", or "skipped on the last check to avoid over-asking" per-source, so a single
failing board never hides behind a healthy-looking lifetime total.

### 2. Today's digest is empty — did it stop working?

An empty digest states the fact and why, on purpose — it never renders as silence.
When nothing cleared the review bar that day, the digest carries an explicit
empty-day note ("No new viable roles today — criteria unchanged, discovery still
running.") plus what was actually searched, and any per-source shortfalls from #1.
If you see a blank digest with no such note at all, that's the actual bug to report
(see #20) — the honest-empty case always explains itself.

### 3. Settings says my model key is invalid, or the connection failed.

The engine classifies the failure before showing it to you rather than dumping a raw
error: a 401/403 response reads as "The server rejected the API key."; a name that
doesn't resolve reads as "Couldn't find that server address."; a reachable host that
refuses the connection reads as "Couldn't reach the server — is it running and the
address right?"; a hung request reads as "The server didn't respond in time." Re-enter
the key/URL in Settings → Add Models and use "Test" before saving. (One current rough
edge: the *save*/"add" path on that same form can still show a provider's raw error
text instead of one of the messages above — if you see something clearly not in plain
English, that's the gap, not a sign the key itself is fine.)

### 4. A job posting hit a CAPTCHA (or some other verification step) — what happens?

Applicant hands it to you, every time, with no configuration that turns this off.
CAPTCHAs, email verification, and SMS verification are hard-coded as steps the engine
will never attempt to solve or bypass (`core/rules/prefill_boundary.py`) — the run
pauses, you get a notification, and you take the live browser session over, clear the
step, then click Continue. Closing that window doesn't end the session; it just stops
you watching. This is the "assisted" reality behind Applicant's automation — not a
missing feature, a deliberate stop-boundary.

### 5. Why didn't it just submit the application for me?

Because it isn't allowed to, structurally. The engine pre-fills every field it can,
then stops at the final submit unless you've explicitly turned on friction-free
submission for that application (`core/rules/prefill_boundary.py` — "Final submit
requires explicit user authorization"). Review-before-submit isn't a UI convention
sitting on top of the automation; it's a rule the core enforces on every path, so the
engine cannot self-authorize a final submit no matter which surface drives it.

### 6. It skipped the EEO / demographic questions on this application.

That's correct behavior, not a miss. Race, gender, disability status, veteran status,
and similar self-identification questions are never answered by AI, in chat or in
pre-fill (`core/rules/sensitive_fields.py`). They're filled only from an answer you've
explicitly stored yourself; with no stored answer, the honest default is
"decline to self-identify" — never a guessed value. Passing an AI-suggested value into
that path is a hard error in the code, not just discouraged.

### 7. What about work-authorization questions specifically?

Same never-guessed family, opposite default. EEO questions default to declining;
work-authorization is a routine, expected question on most applications, so it's
answered from your own stored answer when you have one — and left for you, not
guessed, when you don't. Either way, no AI model ever produces the answer itself.

### 8. My local model is "weak" — will it mangle my resume when it's parsed?

Grounded in an actual test: a real résumé was run through the free local-floor model
class, and it produced a perfect corrected parse — every field landed right, nothing
was invented — once its reasoning mode was turned off (the one deployment trap: left
on, it can burn its whole answer budget "thinking" and return nothing). The verify
layer also can't quietly get this wrong: any correction has to trace back to the
original resume text, and if the model's output comes back malformed or its own
confidence is low, the system automatically retries one tier higher on the model
ladder rather than accepting a shaky answer. If every attempt fails, you get the
plain deterministic parse plus a visible "not verified" note — never a silent, unlabeled
guess.

### 9. What's the "model ladder" / "Level 1, 2, 3" I keep seeing?

It's the order the engine tries models in for a given task: it starts at Level 1 (your
cheapest/local model) and climbs to stronger, more expensive models only when the
cheaper one isn't confident enough or fails outright — cheapest first, strongest last.
You configure which endpoint sits at which level in Settings → AI Defaults.

### 10. My resume shows a "not verified" note, or a value looks shuffled from my original.

That note is the honesty mechanism from #8 telling the truth about itself — an
unverified parse says so, rather than pretending to have been checked. If a value was
dropped or restored during the automated double-check, that's counted and shown too
(the wizard's "double-check" line), so nothing about the correction happens invisibly.
If you disagree with a specific field, correct it directly rather than treating the
note as informational only — it's flagging exactly where to look.

### 11. How do I make sure absolutely nothing goes to a third-party AI provider?

Set `LLM_LOCAL_ONLY=true` on the engine (see [`docs/private-mode.md`](private-mode.md)
for the full contract). This is enforced, not just preferred: the model-tier ladder is
filtered at its single point of construction so no cloud-hosted tier can ever be walked
while the mode is on, and "configured" itself is redefined to mean "a model this mode
allows" — it never silently falls back to a cloud endpoint. What the mode does **not**
cover, by design: discovery queries still reach job boards (that's the product working,
not a leak), the automation browser still visits the ATS site you're applying to, and
any notification channel you've opted into still sends its text there.

### 12. Is any of my data stored on Applicant's own servers?

No — there is no Applicant-operated server to store it on. Applicant is self-hosted:
your résumé, applications, and activity live in the Postgres/SQLite instance you
deployed, on whatever infrastructure you chose.

### 13. How do I back up everything, or move to a new machine?

`scripts/backup.sh --apply` produces one tarball with the Postgres dump, the
front-door's own data, the engine's durable state (including the vault key your
sealed credentials need to stay decryptable), and your deploy config — see
[`docs/backup-restore.md`](backup-restore.md). Restore with
`scripts/restore.sh --apply --from <tarball>`. Neither script does anything without
`--apply` — omit it and it prints what it *would* do without touching anything.

### 14. How do I get just my own résumé/applications/history out (not a full server backup)?

Settings → Account → "Download my data" — a zip of your own applications, documents,
profile, and recent activity, with no shell access or admin role needed. That's the
owner-facing export; #13's backup/restore scripts are the separate operator-facing
disaster-recovery path for the whole deployment.

### 15. Will it burn through my API budget, or apply to way too many jobs per day?

Both are capped, not just estimated after the fact. The daily application throughput
defaults to about 15/day and is hard-clamped so it can never exceed 30/day regardless
of settings. Separately, Settings → Job Search shows an always-labeled cost *estimate*
(today / this month / projected this month) computed server-side from actual token
usage — never a number you or the model can inflate or shrink by claiming a different
figure, and always presented as an estimate rather than an exact bill, since the engine
has no live access to your provider's real price list.

### 16. I'm not getting Discord/ntfy/email notifications.

First, confirm a channel is actually configured in Settings → Integrations/Notifications
— skip that step and everything correctly stays in-app only. If a channel is
configured: normal notifications (approvals, digests) hold briefly for the in-app
channel first, escalating to Discord after a short delay and to email after longer
still if nothing's been acted on; urgent ones (errors) go out immediately on every
channel at once, bypassing quiet hours. Two current rough edges worth knowing before
you assume a channel is dead: "Send a test" can report success even when the live send
underneath actually failed, and ntfy pushes don't yet carry a priority flag, so an
urgent alert and a routine one can look identical on your phone.

### 17. Does it fully automate LinkedIn Easy Apply?

Not yet — assisted mode only. Applicant prepares a deep link, your tailored materials,
and a checklist for LinkedIn's own Easy Apply flow, with your explicit consent before
any of it is used; a full autopilot for LinkedIn specifically is still on the roadmap,
not shipped today.

### 18. What happens when I take over a live browser session mid-application?

The assistant always stops before the steps only you should do (account creation,
clearing a verification, the final submit — see #4/#5). Click "Take control" to drive
the browser yourself; when you're done, click the matching "Continue" button and the
assistant picks up exactly where you left off. Simply closing the window doesn't end
the session — it only stops you watching it.

### 19. How do I know exactly what was submitted under my name?

Every stop-boundary submission is recorded as an immutable snapshot at the moment it
happened — the exact materials and answers sent, not a reconstruction after the fact —
and the full ordered audit log for a search is exportable from the Debug view. If a
submission ever looks different from what you approved, the snapshot is the source of
truth to check first.

### 20. Something's broken and I want to report it — what should I include?

Don't paste raw logs, `.env` files, or screenshots of Settings without checking them
first — several of them can contain your model API key or other secrets. If the
support machinery from P5-1 has landed in your checkout, run
`bash scripts/diagnostic-bundle.sh` (redacts secrets automatically before anything is
written) and attach the result to a GitHub issue using the matching template (bug
report / support question); see [`docs/support.md`](support.md) for the full picture.
Either way, the single biggest thing that speeds up a fix is a clear repro: what you
did, what you expected, and what you got instead.
