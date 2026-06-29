---
description: Bring an overseer onto the playbook and start a wave
argument-hint: [wave-id]
---
You're the overseer for kevinhirsch/applicant. Do this in order.

1) Read REASONIX.md, then SOUL.md in full. Follow them exactly.

2) Do NOT touch config. Model routing / max_steps / effort are a ONE-TIME owner setup in
   `~/.reasonix/config.toml` (needs a relaunch to take effect — not your job per run), and you
   can't reliably introspect your own config anyway (SOUL.md lesson 17). Assume it's set; proceed.

3) Read docs/deepseek-wave-plan.md. Reconcile against `git log origin/main --oneline -20`
   + open PRs. Prune any closed issues.

4) Dispatch Wave $ARGUMENTS via /wave $ARGUMENTS — background subagents, one per file-disjoint
   issue, worktree-or-serialize, flash for mechanical / pro for hard. Monitor with escalating
   short waits: FIRST 15s, cap EVERY wait at 120s. "No visible output" ≠ stuck. Commit per
   issue. Run /gate before any PR; I merge. Steer me in plain English anytime. Go.
