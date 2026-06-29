# REASONIX.md — overseer always-on memory

> Auto-loaded into the cache-stable prefix every session (the Claude-Code `CLAUDE.md`
> equivalent). This is the always-on summary. **Read `SOUL.md` in full before dispatching** —
> it is the complete operating manual and the source of truth.

## First move
Read `SOUL.md` (full manual) and `docs/deepseek-implementation-guide.md` §5 (priority order +
already-done). Reconcile against `git log origin/main --oneline -20` + open PRs before fanning out.

## Non-negotiables
- Hexagonal purity (`lint-imports` enforces), white-label (no upstream codenames / FR-jargon in
  user-facing strings), safety enforced server-side (never gate on caller input),
  reachability = done (spec → engine → workspace proxy → JS → nav), green increments.
- **Run the gate set yourself; never trust a subagent's "green."** Use `/gate`.
- Branch `fix/<numbers>-<topic>` off `origin/main`. One cluster per PR. Owner merges.

## Dispatch defaults (mirror Claude Code)
- Background subagents (`task(run_in_background:true)`), `agent.max_steps = 0` — no round cap.
- **Concurrent write agents are unsafe on the shared tree** even when file-disjoint: isolate
  each in its own `git worktree`, or SERIALIZE. Read-only audits may fan out. Never `git stash`
  concurrently. Use `/wave <id>`.
- Steer in natural language while it runs; queued input lands at the next poll boundary.
  End the turn after dispatch so an owner message or completion wakes you. `Esc`/`Ctrl+C` = stop now.
- Maintain a `todo_write` entry per group; refresh every poll.

## The gate set (or run `/gate`)
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
No `-k` subsets. All must pass before a PR.
