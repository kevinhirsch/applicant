# P4-3 — 2-minute demo video: shot-by-shot script

**Status:** ready to record. Everything below is grounded in the real, already-shipped
golden path (digest → review → approve) and the P0-2 `DEMO_MODE` seed — there is no
open design question left, only the recording itself.

**What this is not:** a video file. Recording it needs a live stack (`docker compose`
or the local dev boot in the root `CLAUDE.md`) with the P0-2 demo seed loaded, screen
capture software, and the owner's voice reading the narration lines below. That
capture is the one remaining piece of P4-3 this environment cannot produce — see
`docs/proof/p4-3/README.md`.

## Before recording

`DEMO_MODE=1` must be set on the **engine (`api`)** service — it gates
`/api/dev/seed` and the front-door demo-status proxy the "Demo data" banner reads;
the workspace container itself carries no such flag, it only relays the engine's
`demo_active` status via `ENGINE_URL` (defaults to `http://api:8000` in compose).

```bash
# Bring up the stack (or local dev boot — see root CLAUDE.md "Commands" section)
# with DEMO_MODE=1 set on the api service, then seed the demo dataset against the
# running Postgres:
DEMO_MODE=1 DATABASE_URL=postgresql+psycopg://applicant:applicant@localhost:5432/applicant \
  uv run python scripts/seed_demo.py
```
This loads the demo campaign, 7 scored postings, applications spanning every
front-door state, a résumé variant under an open redline session, and the
"Demo data" banner + one-click "Clear demo data" affordance (`applicantDemoBanner.js`).
Sign in, confirm the "Demo data" banner is visible top of screen, then record.

## Shot list (target: ~2:00, narration in quotes is a suggestion, not a script to
read verbatim)

All screen names/labels/button text below are the literal shipped strings (file:line
cited per row) — nothing paraphrased, so the recording can be checked against source.

| # | Time | Screen | Action | Narration cue |
|---|------|--------|--------|----------------|
| 1 | 0:00–0:12 | Landing page (`workspace/static/landing.html`, `#trust`) | Scroll past the hero straight to "What Applicant does, and what it promises" | "Applicant finds postings, tailors your résumé, pre-fills the application — and never submits anything without you." |
| 2 | 0:12–0:22 | Sign in → **Today** (nav label `applicantNav.js:72`; this is the Pending-Actions **Portal** home base the rest of this doc calls "Portal" — same screen, `#portal` hash route) | Land on Today; point at the rail: waiting-on-you queue, pipeline counts, momentum/streak | "This is Today — my one home base. Everything waiting on me shows up right here." |
| 3 | 0:22–0:38 | Today rail → **Daily digest** gadget (`applicantRail.js:294`) | Click the gadget's **"Send it now"** button (`applicantRail.js:310`) to trigger `POST /campaigns/{id}/digest/deliver` live, on camera; toast reads "Sent — your digest is on its way." (`applicantRail.js:320`) | "I don't wait for the overnight run — I can send myself today's digest right now." |
| 4 | 0:38–0:55 | Portal digest card → **"Review today's roles"** (`applicantPortal.js:1504`) | Open the digest; show the 7 scored roles, each with a score + a plain-language "why suggested" rationale (Acme Robotics 88, Wayne Logistics 83, Globex 81, …) — the exact rows `docs/proof/p4-3/digest-sample.html` renders | "Every match is scored, with the reason stated in plain English — not a black box." |
| 5 | 0:55–1:15 | **Documents** (Library) card for the Globex — Staff Software Engineer, Platform résumé → **"Review and edit"** (`documentLibrary.js:3016`) opens the redline panel (`_renderApplicantReview`, `documentLibrary.js:3076`) | Show the redline (additions in green, removals struck through — the same `docs/proof/p4-3/tailoring-diff.html` diff), then the free-text "ask for a change" box and turn history | "Here's the résumé Applicant tailored for this specific role, with every change tracked — add a line, cut a line, or just tell it what to change in plain English." |
| 6 | 1:15–1:28 | Same panel | Click **"Approve resume"** (`documentLibrary.js:2940`) | "Nothing goes out until I say so." |
| 7 | 1:28–1:45 | Today/Portal → the `AWAITING_FINAL_APPROVAL` demo card | Open the pending final-approval item; show the live-takeover hand-off point (never actually clicking submit) | "The one thing Applicant can never do on its own is hit final submit — that's always a human action." |
| 8 | 1:45–1:55 | **Tracker** (nav label `applicantNav.js:75`) | Show its buckets — Applied, Awaiting response, Not moving forward, Went quiet, Archived (`applicantTracker.js:68-72`) — with the two seeded rows: one plain "Awaiting response", one carrying an interview-invited signal | "And here's the tracker — everything that's already out the door, plus what came back." |
| 9 | 1:55–2:00 | Today | Return to Today; end on the momentum/streak numbers | "One dashboard, one daily loop, and you're never out of the room." |

Recording note: the demo dataset also seeds a visible **"Demo data — N sample
application(s) and related activity are loaded. Nothing here is real."** banner with a
**"Clear demo data"** button (`applicantDemoBanner.js:40-48`) — leave it on screen for
shot 2 so the recording is honest about being a seeded walkthrough, not live user data.

## Why these beats and not others

- **Digest → review → approve → tracker is the actual daily loop** (root `CLAUDE.md`:
  "Daily loop: digest → review (redline add/subtract/free-text, `documentLibrary.js`)
  → approve/decline → final-submit (Portal / live takeover, `applicantRemote.js`)").
  The script does not invent a path; it walks the one the product already ships.
- **Every screen and label named above is real** — the "Send it now" button text is
  the literal shipped string (`applicantRail.js`), the redline colors/turn history are
  the literal shipped `documentLibrary.js` review panel, and the 7 scored postings +
  their scores/rationales are the literal P0-2 seed data (see
  `src/applicant/application/services/dev_seed.py`) — the same data
  `docs/proof/p4-3/digest-sample.html` and `docs/proof/p4-3/tailoring-diff.html`
  already render as static proof assets, so a viewer can sanity-check the video
  against those files.
- **The final-submit boundary gets its own beat (#7)** because it is Applicant's
  sharpest, least-common claim (see `docs/competitive-teardown.md`, P4-4): review-
  before-submit as an architectural invariant, not a policy toggle — worth 13 seconds
  of screen time on its own rather than folding it into another beat.
- **No EEO/demographic or work-authorization screen is shown.** Those questions are
  never AI-answered in either lane (`core/rules/sensitive_fields.py`) and are not a
  visually interesting beat for a 2-minute cut; the script omits them rather than
  force an awkward pause into the golden path.

## After recording

Attach the file (or a hosted link) here as `docs/proof/p4-3/demo-video.mp4` (or a
link in this file), flip this line from "ready to record" to "recorded", and drop
the same file into `workspace/static/landing.html`'s hero `.shot` placeholder
(replace the `.ph` placeholder markup with a real `<video>` element or a poster
image + link — the placeholder's HTML comment already flags this exact spot) —
no other template change needed.
