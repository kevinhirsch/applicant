# Starter prompt — hand the AZ-0 build to a coding agent

> Copy-paste the block below into the coding agent (an Agent Zero instance or any capable coding
> agent) that will execute Phase AZ-0. It is self-contained: the agent needs no conversation
> history, only repo access with push rights to the working branch and an environment that can run
> the gate commands.

---

You are the coding agent for the **Applicant 2.0 port**. You work in the repo
`kevinhirsch/applicant` on the branch **`claude/refactor-agent-zero-applicant-xn7xoc`** (PR #822 —
the spec + foundations PR). Do **not** open a new PR for this phase, do **not** merge anything, and
do **not** push to any other branch.

## 0 · Environment first
Verify you can run the repo's gate commands (`uv`, `node`/`npm`, `docker compose`). If anything is
missing, set it up before touching a story.

## 1 · Read first, in this order — this is the spec; its decisions are FINAL
1. `CLAUDE.md` — repo working principles + the exact gate commands
2. `docs/agent-zero-plane-map.md` — architecture, the safety line, updateability discipline
3. `docs/backlog/agent-zero-port.md` — parity matrix, phases, decisions **D1–D26**, backlog governance
4. `docs/design/agent-zero-user-journey.md` — the product-experience spec
5. `docs/backlog/road-to-market.md` — the universal DoR/DoD every story inherits

## 2 · Mission
Execute **Phase AZ-0 only**, one story at a time, in dependency order:
**#823 → #824 → #825 → #826 → #827 → #828.**
GitHub issues are canonical — each carries explicit DoR and DoD. Check every DoR box before
starting a story; a story is done only when **every DoD checkbox is true**. **#828 (the MCP seam
proof) is the phase gate: complete it, report, and STOP** — no AZ-1 work without the owner's
explicit go.

## 3 · Hard rules (violating any of these = stop and ask, do not proceed)
- **Never edit any file inside the vendored `agent-zero/` subtree.** All additions live out-of-tree
  at `a0-applicant/`, `a0-webui/`, `branding/` (decision D6). The subtree must remain
  byte-identical to the pinned upstream release tag — treat that as a CI-checkable invariant.
- The engine (`src/applicant/`) and workspace (`workspace/`) code are **untouched** in AZ-0, except
  the compose/deploy wiring the stories explicitly name.
- **Safety is server-side.** Never gate a safety check on caller-supplied input. The engine's
  guarded path is the only route to consequential job-application actions; nothing you build may
  create another.
- **White-label:** no upstream codenames and no spec jargon in user-facing strings. Run **both**
  denylist greps from `.github/workflows/ci.yml` verbatim (with their exclusion lists) before
  every commit.
- **Green increments:** before every push, run the full gate set from `CLAUDE.md` — the hermetic
  engine suite (unreachable `DATABASE_URL` command), the front-door `test_applicant_*` tests,
  `cd workspace && npm test`, `uv run ruff check .`, `uv run lint-imports` (2 kept / 0 broken),
  the boot smoke, `uv run alembic heads` (single head), and `docker compose … config`. All green
  or you don't push.
- One commit per story: `AZ0-N: <what>` and `Closes #NNN` only when the full DoD holds. Never
  force-push.

## 4 · When blocked or ambiguous
Comment on the story's GitHub issue with what you found and what you need. Do **not** guess on
anything touching safety, licensing, or the D1–D26 decisions — findings that contradict the spec
go to the owner, never worked around silently.

## 5 · Report
After #828: post the seam-proof evidence on PR #822 — the agent listing campaigns/pending actions
over the real MCP transport, and the server-side **refusal** of a consequential submit attempt —
plus a per-story phase summary. Then stop and await the go/no-go.
