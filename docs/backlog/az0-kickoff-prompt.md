# Starter prompt — hand the AZ-0 build to a coding agent

> **HISTORICAL (retired 2026-07-22) — do not re-run.** Phase AZ-0 is **complete**: #823–828 are all
> closed and the #828 seam proof **passed live** (campaigns listed over MCP; a consequential submit
> refused server-side). The referenced "AZ-0 PR #864" is merged/closed (it ended up carrying docs
> only — the build itself happened on the A0 container's local branch and was never pushed; see
> `HANDOFF.md` §11 and `docs/ops/session-close-2026-07-22.md`). This file is preserved as the
> record of the kickoff contract; for current next steps see `docs/backlog/agent-zero-port.md` §7.

> Copy-paste the block below into the coding agent (an Agent Zero instance or any capable coding
> agent) that will execute Phase AZ-0. It is self-contained: the agent needs no conversation
> history, only repo access with push rights to the working branch and an environment that can run
> the gate commands.

---

You are the coding agent for the **Applicant 2.0 port**. **Before editing anything, verify your
checkout**: the `origin` remote must be `kevinhirsch/applicant` and the current branch must be
**`claude/refactor-agent-zero-applicant-xn7xoc`** (the working branch for Phase AZ-0; the spec
itself is already merged to `main` via PR #822). Your pushes land on the open **AZ-0 PR: #864**
from this branch. **If the remote or branch does not match, stop and report the mismatch — do not
edit, commit, or push.** Do **not** open any new PR, do **not** merge anything, and do **not**
push to any other branch.

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
- **White-label:** no upstream codenames and no spec jargon in user-facing strings. Two explicit
  gates cover this: the **codename greps** — run both denylist greps from
  `.github/workflows/ci.yml` verbatim (with their exclusion lists) before every commit — and the
  **spec-jargon copy tests** (`tests/unit/test_ui_surfaces.py`,
  `tests/unit/test_deps_error_messages.py`, which run inside the hermetic suite) — any new
  user-facing surface you add must be covered by an equivalent copy check.
- **Green increments:** before every push, run the full gate set from `CLAUDE.md` — the hermetic
  engine suite (unreachable `DATABASE_URL` command), the front-door `test_applicant_*` tests,
  `cd workspace && npm test`, `uv run ruff check .`, `uv run lint-imports` (2 kept / 0 broken),
  the boot smoke, `uv run alembic heads` (single head), and `docker compose … config`. All green
  or you don't push. **Once the subtree exists (AZ0-1 onward), also verify the subtree invariant
  before every push — both halves**: (a) the tracked tree matches the pinned upstream tag
  (`git diff` of `agent-zero/` vs the tag is empty), **and** (b) nothing untracked or ignored has
  landed under it (`git status --ignored --porcelain -- agent-zero/` prints nothing) — a plain
  diff alone cannot prove byte identity. The full `scripts/vendor-sync.sh` / `git subtree pull`
  **round-trip** is AZ0-1's DoD proof — re-run it whenever a change could touch the subtree, not
  on every push.
- One commit per story: `AZ0-N: <what>` and `Closes #NNN` only when the full DoD holds. Never
  force-push.

## 4 · When blocked or ambiguous
Comment on the story's GitHub issue with what you found and what you need. Do **not** guess on
anything touching safety, licensing, or the D1–D26 decisions — findings that contradict the spec
go to the owner, never worked around silently.

## 5 · Report
After #828: post the seam-proof evidence on the **AZ-0 PR (#864)** — the agent listing campaigns/pending
actions over the real MCP transport, and the server-side **refusal** of a consequential submit
attempt — plus a per-story phase summary. Then stop and await the go/no-go.
