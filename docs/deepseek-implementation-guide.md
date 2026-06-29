# Implementation guide for an autonomous coding agent (DeepSeek)

You are implementing tracked work for **Applicant** — an autonomous job-application engine:
a hexagonal FastAPI **engine** in `src/applicant/` and a white-labeled **front-door** in
`workspace/`. Almost everything is already specified. Your job is to turn **`@pending`
acceptance specs into GREEN** by implementing the real code behind them — one focused PR at a time.

## 1. Read these first (the map)
- **`docs/release-readiness-1.0.md`** — the 1.0 scope cut + the finite **1.0-blocking set**. Start here.
- **`docs/issue-acceptance-traceability.md`** — every open issue → its acceptance feature → step module → green/pending.
- **`CLAUDE.md`** — architecture + binding principles. Obey it.
- Every GitHub issue carries a **work-order comment**: *Requirement (MUST) / Where (file:line) / Acceptance criteria / Definition of done*. That comment is your spec for that issue.

## 2. The loop (per issue)
1. Pick an issue from the priority queue (§5). Read its work-order comment + its
   `tests/bdd/features/enhancements/enh_<N>_*.feature`.
2. `@pending` scenarios are TDD reds — implement the real change at the **Where** seam.
3. Remove the `@pending` tag and rewrite the bound step (in the named
   `tests/bdd/steps/test_*_steps.py`) to assert the now-true behaviour with **real
   assertions** — never `assert True`.
4. Run every gate (§3). Iterate until green.
5. One issue (or one tight cluster) per PR. Branch, push, open a PR.

## 3. Gates — ALL must pass before a PR ("green increments")
```bash
# hermetic test lane (forces in-memory; the REAL gate):
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' uv run pytest -q -m "not integration"
uv run ruff check .
uv run lint-imports                 # hexagonal layering + core-purity (2 contracts, 0 broken)
uv run alembic heads                # MUST be a single head (currently 0007_pii_retention_timestamps)
uv run python -c "from applicant.app.main import app"   # boot smoke
# front-door + workspace gates:
uv run pytest -q workspace/tests/test_applicant_*.py
python -m compileall -q workspace/app.py workspace/routes workspace/src
# for any changed JS (no JS test runner yet — issue #366): node --check <file>
```
A structural gate runs inside the suite: `tests/architecture/test_reachability_contract.py`.
**If you add an engine `/api/applicant/*` capability you MUST wire a workspace proxy + a JS
consumer (+ a nav section for a surface), or it fails.** Don't break it.

## 4. Hard rules (non-negotiable)
- **White-label:** no upstream-fork vendor/persona codenames, and no `FR-`/`NFR-` jargon, in
  user-facing strings (or shipped artifacts generally). The product is "Applicant". The CI
  white-label step holds the exact codename denylist and fails the build on any match — run
  `uv run ruff check .` plus that step's `git grep` before pushing if unsure.
- **Hexagonal:** `core/` is pure (no IO/outward imports); dependencies point inward. `lint-imports` enforces it.
- **Safety guards are server-side:** review-before-submit, the pre-fill stop-boundary, and the
  fabrication guard derive their own ground truth — never gate a safety check on a caller-supplied
  input. The fabrication check sits at the persistence boundary (fail-closed) — keep it there.
- **Single Alembic head:** any new migration chains to the current head; revision ids ≤ 32 chars.
- **No `assert True`** — specs assert real behaviour.
- **Squash-merge workflow:** after a merge, realign with `git fetch origin main && git reset --hard
  origin/main` before continuing (force-push is blocked).
- **Front-door JS has no unit-test harness yet (#366):** JS specs are source-pattern + logic
  assertions, so make the fix *genuinely correct* and run `node --check`.

## 5. Priority queue — finish the 1.0-blocking set first
**Already done on `main` (do NOT redo):** #362, #237, #238, #239, NFR-TRUTH fail-closed, #173, #177,
#363, #361, #406.

**Remaining 1.0-blocking — the front-door wave (do next, in order):**
1. **#381** — CSRF: server-side Origin/Referer allowlist in `workspace/core/middleware.py` for
   non-GET `/api/*` (keep the token-gated `/api/applicant/internal/*` channel + existing proxy tests green).
2. **#384 / #389** — email XSS: route received-email HTML through an allowlist sanitizer (composer
   `innerHTML` sink in `document.js`); replace the denylist email sanitizer (`emailLibrary/utils.js`)
   with a fixpoint allowlist that neutralizes inline `url()`.
3. **#379 / #380 / #382** — modal a11y: one shared `ui.js` focus-trap / Escape / focus-restore helper
   wired into every applicant modal (incl. the OOBE wizard).
4. **#400** — wire the missing-font install prompt into the résumé-upload step in
   `applicantOnboarding.js` (the engine already detects fonts).

Then **prompt-injection #360** and the rest of `@pending` per the readiness doc. Everything in
`docs/release-readiness-1.0.md` §2d is **post-1.0**.

## 6. Definition of done (per issue)
Its `@pending` scenario(s) pass with the tag removed + all §3 gates green + (if it touches the
front-door) the reachability contract still green. One focused PR, kept green.
