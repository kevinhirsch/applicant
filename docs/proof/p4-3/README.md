# P4-3 — Proof assets

**Date:** 2026-07-09 · **Backlog:** P4-3 · **Depends on:** P0-2, P1-2, P1-4

> **Scope note:** this story's DoD asks for three things — a 2-minute demo video, a
> shareable digest-email sample, and a before/after tailoring diff. The video needs a
> live stack plus an owner voiceover, neither of which exists in this environment.
> The other two are producible from the P0-2 `DEMO_MODE` seed with no live stack and
> **are real, generated artifacts** — not mockups — checked in here. The video is
> storyboarded (`docs/proof/demo-script.md`) so recording it is a mechanical,
> ready-to-execute owner task, not an open design question.

## What's here

- `digest-sample.html` — the P1-4 branded digest email template
  (`DigestService.render_email`, unmodified), rendered with the real seven-posting
  P0-2 demo seed. Standalone, self-contained HTML; open it directly in a browser or
  screenshot it for marketing use. Same file also lives at
  `workspace/static/proof/digest-sample.html` (the servable, front-door-reachable
  copy — see "Reachability" below).
- `tailoring-diff.html` — a real before/after tailoring diff for the demo seed's
  Globex "Staff Software Engineer, Platform" posting, in two stages:
  1. **base résumé → AI-tailored draft** — the demo seed's own base-résumé intake
     text (`dev_seed._DEMO_BASE_RESUME_TEXT`) versus the tailored material
     (`dev_seed.build_demo_material`), diffed with `LatexTailor.render_redline` —
     the exact per-line `difflib.SequenceMatcher` diff engine + `redline-add`/
     `redline-sub`/`redline-eq` classes the real redline review screen renders.
  2. **tailored draft → your redline pass** — reconstructed from the demo seed's
     own `RevisionSession.redline_state` additions/subtractions (the "add a
     Kubernetes bullet" / "drop the wiki bullet" turns), same diff engine. The page
     also calls out that the added bullet closes a gap the seeded résumé variant's
     own fit-score (`fit_scores.missing_terms`) already flagged — a real
     cross-reference inside the seed data, not invented narrative.
  Also at `workspace/static/proof/tailoring-diff.html`.

Both files are generated (not hand-written) by
`scripts/proof/gen_p4_3_proof_assets.py`, which builds the P0-2 demo bundle into an
in-memory `StoragePort` and calls the SAME product code the front-door calls — no
DB, network, LLM, or TeX install required:

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run python scripts/proof/gen_p4_3_proof_assets.py
```

Re-running regenerates both output locations from the same deterministic seed
builders, so the two copies can never drift from each other or go stale by hand-edit.

## Reachability (CLAUDE.md principle #2)

The `workspace/static/proof/*.html` copies are served by the existing `/static`
mount — no new route. `workspace/static/landing.html`'s `#proof` screenshot-strip
section (P4-2) links its "Daily digest" and "Redline resume review" tiles straight
to these two files (`static/proof/digest-sample.html`,
`static/proof/tailoring-diff.html`); the hero video slot links to the storyboard
script as the closest real stand-in for the still-missing recording. See
`docs/proof/demo-script.md` for the video plan and
`workspace/tests/test_applicant_p4_3_proof_assets.py` for the content/existence
pin (both files exist, both front-door links exist, no lorem-ipsum placeholder
text, no upstream-fork codenames).

## What is NOT here (the honest gap)

**The 2-minute demo video capture itself.** That needs: a live stack (`docker
compose up` or the local dev boot sequence in `CLAUDE.md`) with the P0-2 seed
loaded, screen-recording software, and the owner's voiceover reading
`docs/proof/demo-script.md`. Nothing in this environment can drive a browser
against a real rendered UI and capture video output — this is squarely the
"owner + live stack" remainder the backlog `P4-3` DoD names. `road-to-market.md`
records the story as **PARTIAL** for exactly this reason.
