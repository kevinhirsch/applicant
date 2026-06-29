Dispatch wave "$ARGUMENTS" the Claude-Code way: isolated, uncapped, owner-steerable.

1. **Resolve & reconcile.** Pull the groups/issues for wave $ARGUMENTS from the wave plan in
   the overseer's working notes. Reconcile against `git log origin/main --oneline -20` and open
   PRs; drop any issue that has since closed.

2. **Dispatch one background subagent per file-disjoint group**, with `max_steps=0` (no round
   cap), using the write-task brief template from `SOUL.md` *verbatim* — it already includes the
   round-budget, commit-after-each-issue, and inline-evidence lines. Record each `sa_` id.

3. **Isolate or serialize.** Concurrent write agents on the shared tree are unsafe (Wave 01:
   148 uncommitted, unattributable changes). If a per-agent working dir is available, give each
   its own worktree: `git worktree add ../wt-<group> origin/main` and run the agent there.
   Otherwise dispatch the groups **serially**. Read-only audit groups (`read_only_task`) may
   fan out freely regardless.

4. **Stay steerable.** End the turn after dispatch; poll in short increments (`wait`/
   `bash_output`), never one long blocking wait. At each poll: handle any owner message first
   (natural language — interpret intent), then continue. Keep a `todo_write` entry per group.

5. **Land it.** When a group finishes: verify true scope with `git diff --stat
   origin/main...HEAD`, run `/gate`, then open ONE focused PR (`Closes #N` for each issue +
   gate summary). The owner merges.
