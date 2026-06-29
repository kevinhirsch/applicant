# REASONIX.md — overseer always-on memory

> Auto-loaded every session (the `CLAUDE.md` equivalent). Summary only — **read `SOUL.md` in full
> before dispatching** (source of truth).

## First move
Read `SOUL.md` + `docs/deepseek-implementation-guide.md` §5 (priority + done) +
`docs/deepseek-wave-plan.md` (waves). Reconcile against `git log origin/main --oneline -20` +
open PRs before fanning out.

## Dispatch
- Background subagents (`task(run_in_background:true)`), `max_steps=0`. One per file-disjoint issue. `/wave <id>`.
- **Worktree-or-serialize. Never concurrent writers on the shared tree** — changes interleave, unattributable. Read-only audits may fan out.
- `continue_from` resumes a subagent with context; commit per issue so progress banks.
- **Models:** flash = default (mechanical/localized/audits); pro = hard reasoning (refactors, architecture, safety-critical, ambiguous, planning, review/security). **Both at `effort="max"`.** Escalate flash→pro when flash stalls/fails. Config in SOUL.md "Model routing".

## Monitor + steer (talk while it runs)
- After dispatch, loop **short `wait`s — default 15s, NEVER >30s while the owner's engaged** (each wait blocks dialogue for its full length; a 120s wait = a 2-min lockout = a bug). Ramp 15→30 only while quiet; reset to 15s on any change or owner message. The 120s ceiling is for *unattended* long-monitoring only — don't default to it.
- Each return = liveness + completion + steering checkpoint. Read owner input first (plain English, no keywords), act, ack in one line. `Esc`/`Ctrl+C` = stop now.
- Keep a `todo_write` entry per group; refresh each `wait`.

## Oversight (classify each agent every `wait`)
- **Alive** = tokens, output, OR new commits moved. **"No visible output" ≠ stuck** — DeepSeek reasons silently; the 15m warning means *inspect*, not kill. → let it run.
- **Stuck** = no tokens AND no output AND no commits across the window. → work every angle (`continue_from`, kill→salvage→re-dispatch tighter/smaller, more context).
- **Truly blocked** = every angle tried, still stuck, or needs an owner decision. → reach out with a diagnosis. Escalate rarely; over-escalating == silence == bad.

## Non-negotiables
- Run the gate set yourself (`/gate`); never trust a subagent's "green."
- Hexagonal purity (`lint-imports`), white-label (no codenames / FR-jargon), safety server-side, reachability = done, green increments.
- Branch `fix/<numbers>-<topic>` off `origin/main`. One cluster per PR. Owner merges.

## Gate set (or `/gate`) — all pass, no `-k` subset
```bash
export DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none'
uv run pytest -q -m "not integration"
uv run ruff check .
uv run lint-imports
uv run alembic heads
uv run python -c "from applicant.app.main import app"
uv run pytest -q workspace/tests/test_applicant_*.py
python -m compileall -q workspace/app.py workspace/routes workspace/src
uv run pytest -q tests/architecture/test_reachability_contract.py
# + node --check on every changed workspace/static/js/*.js
```
