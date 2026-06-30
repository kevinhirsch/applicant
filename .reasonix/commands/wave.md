---
description: Dispatch a wave with isolated, uncapped, steerable subagents
argument-hint: [wave-id]
---
Dispatch wave "$ARGUMENTS" the Claude-Code way: isolated, uncapped, owner-steerable.

1. **Resolve & reconcile.** Pull the groups/issues for wave $ARGUMENTS from
   `docs/deepseek-wave-plan.md`. Reconcile against `git log origin/main --oneline -20` and open
   PRs; drop any issue that has since closed.

2. **Dispatch one background subagent per file-disjoint group**, with `max_steps=0` (no round
   cap), using the write-task brief template from `SOUL.md` *verbatim* — it already includes the
   round-budget, commit-after-each-issue, and inline-evidence lines. Record each `sa_` id.

3. **Isolate or serialize.** Concurrent write agents on the shared tree are unsafe (Wave 01:
   148 uncommitted, unattributable changes). If a per-agent working dir is available, give each
   its own worktree: `git worktree add ../wt-<group> origin/main` and run the agent there.
   Otherwise dispatch the groups **serially**. Read-only audit groups (`read_only_task`) may
   fan out freely regardless.

4. **Stay steerable & oversee.** After dispatch, run an active supervision loop of escalating
   short `wait`s — **default 15s, NEVER >30s while the owner's engaged** (each wait blocks
   dialogue for its full length; a 120s wait = a 2-min lockout = a bug); ramp 15→30 only while
   quiet, reset to 15s on any change/owner message; 120s is an unattended-only ceiling. On each `wait`
   return: handle any owner message first (natural language —
   interpret intent), then run the liveness/error check from SOUL.md "Oversight" —
   `kill_shell`+salvage+re-dispatch stalled agents (stalled = no token movement, output, or
   commits across the window — NOT the bare 15m "no visible output" warning), `continue_from`
   to correct failing ones, surface real blockers. Keep a `todo_write` per group.

5. **Land it.** When a group finishes: verify true scope with `git diff --stat
   origin/main...HEAD`, run `/gate`, then open ONE focused PR (`Closes #N` for each issue +
   gate summary). The owner merges.
