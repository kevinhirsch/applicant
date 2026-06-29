---
description: Bring a fresh overseer current (config + playbook) and start a wave
argument-hint: [wave-id]
---
You're the overseer for kevinhirsch/applicant. Do this in order.

1) Read REASONIX.md, then SOUL.md in full. Follow them exactly.

2) Set your own config so you run uncapped, at max thinking, with flash/pro routing.
   Edit your user config — `~/.reasonix/config.toml` (Windows: `%AppData%\reasonix\config.toml`).
   MERGE these keys; do NOT clobber existing api_key / base_url / credential lines:

```toml
[agent]
temperature       = 0.0
max_steps         = 0
planner_max_steps = 0
planner_model     = "deepseek-v4-pro"
subagent_model    = "deepseek-v4-flash"
subagent_models   = { review = "deepseek-v4-pro", security_review = "deepseek-v4-pro" }

[permissions]
mode  = "ask"
allow = ["Bash(uv run:*)", "Bash(git:*)", "Bash(node --check:*)", "Bash(python -m compileall:*)", "Edit(*)"]
deny  = ["Bash(git push --force:*)", "Bash(rm -rf:*)", "Edit(.env*)", "Read(.env*)"]

[[providers]]
name    = "deepseek"
kind    = "openai"
models  = ["deepseek-v4-flash", "deepseek-v4-pro"]
default = "deepseek-v4-flash"
effort  = "max"
# keep your existing api_key / base_url for this provider
```

   Then confirm it's live: max_steps=0, deepseek effort=max, default=deepseek-v4-flash,
   planner_model=deepseek-v4-pro. If a key won't take effect without a restart (max_steps
   often won't), say so and tell me to relaunch you — then stop until I do.

3) Read docs/deepseek-wave-plan.md. Reconcile against `git log origin/main --oneline -20`
   + open PRs. Prune any closed issues.

4) Dispatch Wave $ARGUMENTS via `/wave $ARGUMENTS` — background subagents, one per
   file-disjoint issue, worktree-or-serialize, flash for mechanical work / pro for hard.
   Monitor with escalating short waits: FIRST 15s, cap EVERY wait at 120s. "No visible
   output" ≠ stuck. Commit per issue. Run /gate before any PR; I merge. Steer you in
   plain English anytime. Go.
