# Session close-out — 2026-07-21 → 2026-07-22 (the journey-debug + handoff session)

> Companion to `HANDOFF.md` (which is the canonical pick-up doc). This note captures ONLY the
> session-final state that a future session cannot reconstruct from git history alone: exact ref
> positions, what made it to GitHub vs. what did not, what was lost to the reboot, running
> containers/instances left behind, and the precise resume checklist. Written at close, ~03:15 local.

## 1. What made it to GitHub (origin = github.com/kevinhirsch/applicant)

| item | status |
|---|---|
| `HANDOFF.md` (375-line 2026-07-22 revision) | ✅ ON `origin/main` — commit `8e11153cb`, uploaded via A0's github MCP (dispatch ctx `ihandoffpush`), verified **byte-identical** to the branch copy |
| This close-out doc + `scripts/journey_via_sidebar.py` + `scripts/diagnostics/*` | dispatched to A0's github MCP for upload to `origin/main` at close (ctx `ihandoffsync2`) — verify `origin/main` history if it matters |
| The full program (panel fixes, 190+ commits) | ❌ NOT on origin — no push credentials exist in the container or host (deliberate). See §3 for the exact push procedure. |

Note: `origin/main` also moved externally during the session to `3b83ed7bb`
("docs: AZ-0 post-merge housekeeping — D22 revised, kickoff prompt re-pointed (#864)") — an
unrelated PR-style commit not present in local history. Local main is therefore BEHIND origin/main
by that lineage; merge before pushing (§3).

## 2. Exact local ref positions at close (repo: `/a0/usr/projects/applicant` in container `agent-zero`)

- `claude/refactor-agent-zero-applicant-xn7xoc` (the program branch) — tip includes, newest first:
  - `271f97704` diagnostics preservation (this commit)
  - `638d6eec8` scripts/journey_via_sidebar.py (the gold-standard crawler)
  - `d43784555` HANDOFF.md 2026-07-22 revision
  - `21470f8f2` null-INIT fix (empty-shape x-data initializers — criteria/ops)
  - `16c20d84b` null-guard sweep (criteria/ops), `51e61dad4` (criteria/ops/research/tracker)
  - `e70891408` api-prefix fix (38 panels)
  - `3ca6dad76` / `8882eb57a` / `06bda0eb3` / `4130aa3bb` modal-init fixes (~30 panels)
- `main` (local) — `e993cbdbd` merge of the branch as of the HANDOFF commit, PLUS a follow-up merge
  at close bringing in `638d6eec8`/`271f97704`/this doc (see git log). Every branch commit is on
  local main at close.
- `_premerge_backup_main` — local main exactly as it was BEFORE the program merge (`c976ee264`).
  Delete only after the owner is happy with the merge.
- `origin/claude/refactor-agent-zero-applicant-xn7xoc` — ~310 commits behind the local branch.

## 3. To publish everything (owner, from any credentialed environment)

```bash
cd /a0/usr/projects/applicant        # or clone fresh and fetch from this machine
git fetch origin
git checkout main
git merge origin/main                 # brings in 3b83ed7bb + the MCP handoff commit(s); resolve HANDOFF.md by keeping local (identical content, different commits)
git push origin main
git push origin claude/refactor-agent-zero-applicant-xn7xoc
```

## 4. Lost to the host reboot (context, not code)

The host rebooted mid-session (~02:00); `/tmp` (Claude's session scratchpad) was wiped. Lost files
and their disposition:
- `deferred.tsv` (21 deferred issues + reasons) — substance reconstructed in `HANDOFF.md` §8 and the
  memory file `applicant-backlog-drive-state.md`. The per-issue one-liners are gone; re-derive from
  the issue list + HANDOFF §8 if needed.
- `to-close.tsv`, `done_oracles_*.json`, `spec_*.txt` — working artifacts of the already-completed
  close pipeline; nothing pending depended on them (all 25 closes were executed + verified).
- Everything that mattered long-term survived: the crawler + diagnostics lived in container
  `/a0/tmp` (reboot-proof) and are now committed under `scripts/`.

## 5. Instances / processes left running at close

- `applicant-e2e` (:8091) — the disposable wired test instance, running the POST-fix image
  (`applicant/a0:latest`). Safe to keep for testing or `docker rm -f applicant-e2e`.
- The production compose stack (project `docker`) — all up. **`docker-a0-1` (:8090) still runs the
  PRE-fix image.** First action next session: rebuild + `up -d --no-deps a0` (HANDOFF §5.3), then
  journey-crawl :8090.
- `agent-zero` (:5080) — the coder, idle. Drive chats worth cleaning:
  `iapiprefix`, `inullread`, `inullread2`, `ihandoffpush`, `ihandoffsync2`
  (`~/agent-zero-ops/az-rmchat.sh <ctx>`).
- All Claude-side monitors/watchers from the session are dead (reboot + session close) — re-arm the
  commit Monitor when driving resumes (HANDOFF §6.1).

## 6. Verification ground truth at close (do not re-litigate)

- Journey crawl vs the wired e2e instance: **19/20 panels CLEAN with real engine data**; Digest and
  Chat "CLICK-FAIL"s are crawler text-matching/overlay artifacts, NOT product bugs (Digest verified
  clean in the first post-fix crawl; launcher + openModal path verified correct).
- Unit suite at the known baseline (the ONLY allowed failures: `test_prod_compose_env_file`,
  `test_deploy_hardening_lens04` + documented compose/doc-drift set). Panel/proxy subset: 775 passed;
  criteria/ops subset: 131 passed post-fix.
- `/api/plugins/applicant/campaigns` returns 200 with live postgres rows — the engine data path is
  proven end-to-end through the shell.

## 7. Resume checklist (first 30 minutes of the next session)

1. `docker ps` — confirm stack + read `HANDOFF.md` top-to-bottom (it is current as of this close).
2. Roll production (§5 above / HANDOFF §5.3) and journey-crawl :8090.
3. Verify `origin/main` got the close-time MCP upload (this doc + scripts); if not, re-dispatch A0.
4. Close the journey-arc panel issues + #854 via A0's github MCP (evidence: HANDOFF §4.4).
5. Re-arm the commit Monitor and resume the backlog pipeline (HANDOFF §6.1, §10).

## 8. Addendum — state of the origin/main mirror of this upload (verified at close)

The MCP upload landed as `fa5b56d5e` on origin/main: **7/9 files byte-identical**. Two differ, both
benign, both to be overwritten by the owner's credentialed push of local main:
- `docs/ops/session-close-2026-07-22.md` (this file): A0's secrets-masker substituted a
  `§§secret(...)` placeholder for the literal coder-container name in 5 places in the ORIGIN copy
  (the masker rewrites file contents before A0's model sees them, so an A0 re-upload cannot fix it).
  THIS local copy is canonical.
- `scripts/diagnostics/journey_crawl.py`: origin copy lost one trailing blank line. Cosmetic.
When pushing (§3), these two paths (and HANDOFF.md, identical content but different commits) should
resolve to the LOCAL versions.
