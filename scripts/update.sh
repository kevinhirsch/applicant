#!/usr/bin/env bash
#
# Applicant — one-liner updater (FR-INSTALL-2, FR-OOBE-4, NFR-ZEROCLI-1).
#
# Invoked by the in-UI Update button (via /api/update/trigger) OR directly:
#   bash scripts/update.sh [--apply] [--rollback]
#
# Update flow (the safe order — backup BEFORE migrate, so rollback is always
# possible):
#   1. Back up the Postgres database (timestamped dump).
#   2. Pull the new images / code.
#   3. Run database migrations (Alembic).
#   4. Restart the stack.
# A failure at any step leaves the prior DB dump intact for --rollback.
#
# SAFETY: this is a WELL-COMMENTED SCAFFOLD STUB. It performs NO destructive
# operations by default — it PRINTS the steps it would run. Pass --apply to run
# them. --rollback restores the most recent backup (also dry-run unless --apply).
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_ROOT}/.env"
BACKUP_DIR="${APPLICANT_BACKUP_DIR:-${REPO_ROOT}/.backups}"
# Backup retention (issue #282): keep only the most recent BACKUP_KEEP_COUNT dumps
# (default 7) so daily backups cannot fill the disk indefinitely; older ones are
# pruned after each successful backup. Set to 0 to disable pruning (keep forever).
BACKUP_KEEP_COUNT="${BACKUP_KEEP_COUNT:-7}"
# Pre-update snapshot of the deployable state (issue #279): the git commit and the
# image refs that were live BEFORE this update, so --rollback can revert the code +
# images alongside the DB rather than leaving new code on top of restored old data.
DEPLOY_SNAPSHOT="${BACKUP_DIR}/last-deploy.images"

# Append-only, line-based build output (no redraw frames) so update logs stay readable.
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"
# Skip the default provenance/SBOM attestations on local builds: they add an
# "exporting attestation manifest" + "manifest list" round to every image export
# (slower, and wraps the image in a manifest list) with no value for a self-hosted
# build that is never published to a registry.
export BUILDX_NO_DEFAULT_ATTESTATIONS="${BUILDX_NO_DEFAULT_ATTESTATIONS:-1}"

# Load persisted DB credentials so backup/migrate/restart authenticate with the
# SAME password Postgres baked into its data volume at first install. Without this
# the migration step fails ("password authentication failed"). Explicit env wins.
if [[ -f "${ENV_FILE}" ]]; then
  while IFS='=' read -r _k _v; do
    [[ "${_k}" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    [[ -n "${!_k:-}" ]] || export "${_k}=${_v}"
  done <"${ENV_FILE}"
fi

# Persist the ABSOLUTE host repo path for the updater sidecar's bind mount
# (FR-OOBE-4): the compose `updater` service mounts ${APPLICANT_REPO_DIR}:/repo so
# the in-UI Update button can run this script against the host Docker. install.sh
# writes it on fresh installs; back-fill it here for older deployments. Set ONLY
# when absent so the updater container (which runs this with REPO_ROOT=/repo) can
# never clobber the real host path already saved in .env.
if [[ -z "${APPLICANT_REPO_DIR:-}" ]]; then
  APPLICANT_REPO_DIR="${REPO_ROOT}"
  if [[ -f "${ENV_FILE}" ]] && ! grep -q '^APPLICANT_REPO_DIR=' "${ENV_FILE}"; then
    printf 'APPLICANT_REPO_DIR=%s\n' "${REPO_ROOT}" >>"${ENV_FILE}"
  fi
fi
export APPLICANT_REPO_DIR

DB_SERVICE="postgres"
DB_NAME="${POSTGRES_DB:-applicant}"
DB_USER="${POSTGRES_USER:-applicant}"
# set -u safe default; .env (sourced above) overrides it. Used by the heartbeat.
APP_URL="${APP_URL:-http://localhost:8000}"
APPLY=0
ROLLBACK=0

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --rollback) ROLLBACK=1 ;;
    -h|--help)
      echo "Usage: update.sh [--apply] [--rollback]"
      echo "  (default: dry-run — prints steps; --apply runs them)"
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;33m[update]\033[0m %s\n' "$*"; }
run() {
  # Execute when --apply, otherwise echo the command (dry-run default).
  if [[ "${APPLY}" -eq 1 ]]; then "$@"; else echo "    (would run) $*"; fi
}

# Heartbeat: block until the front-door UI answers /api/health on the public
# port AND the internal engine's /healthz reports green. Non-zero unless BOTH are
# healthy — the engine /healthz now runs a real DB check, so a degraded engine
# (e.g. DB unreachable after the restart) MUST fail the update, not be reported as
# a soft warning while the run still "succeeds".
heartbeat() {
  local port="$1" tries=60 i ui_ok=0
  log "Heartbeat: waiting for the UI on :${port}/api/health and the engine /healthz …"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS -o /dev/null "http://localhost:${port}/api/health" 2>/dev/null; then
      ui_ok=1
      if docker compose -f "${COMPOSE_FILE}" exec -T api \
           python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=5).status==200 else 1)" 2>/dev/null; then
        log "UI is up (/api/health 200) and the engine is healthy (/healthz). Stack is green."
        return 0
      fi
    fi
    sleep 5
  done
  if [[ "${ui_ok}" -eq 1 ]]; then
    echo "Heartbeat FAILED: the UI is up but the engine /healthz never went green after $((tries * 5))s (DB unreachable?)." >&2
  else
    echo "Heartbeat FAILED: UI did not become healthy on :${port} after $((tries * 5))s." >&2
  fi
  docker compose -f "${COMPOSE_FILE}" ps || true
  return 1
}

TS="$(date +%Y%m%d-%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/applicant-${TS}.sql"

# Restore a specific dump into the running postgres over STDIN. Shared by the manual
# --rollback path and the AUTO-rollback that fires when a migration fails mid-update.
# Feed the dump to the container's psql over STDIN (host-side redirect). Do NOT use
# `psql -f "${file}"`: -f opens the file INSIDE the postgres container, where this
# host path does not exist, so the restore would fail with "No such file or
# directory". The dump is written host-side via `pg_dump > file`, so the restore must
# read it host-side and pipe it in the same way. The dumps use --clean --if-exists,
# so a restore DROPs+recreates objects idempotently (no leftover partial-migration
# schema). Use ON_ERROR_STOP so a broken restore is reported as a failure.
restore_dump() {
  local file="$1"
  if [[ "${APPLY}" -eq 1 ]]; then
    docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
      psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" <"${file}"
  else
    echo "    (would run) docker compose -f ${COMPOSE_FILE} exec -T ${DB_SERVICE} psql -v ON_ERROR_STOP=1 -U ${DB_USER} -d ${DB_NAME} <${file}"
  fi
}

# Backup retention (issue #282): keep only the newest ${BACKUP_KEEP_COUNT} dumps so
# daily backups can never fill the disk. Prune anything older than the newest N by
# count (newest-first), and prune the matching image-ref snapshots (issue #279)
# alongside their dumps so the two stay in lockstep. A count of 0 disables pruning.
prune_backups() {
  [[ "${BACKUP_KEEP_COUNT}" -gt 0 ]] || { log "Backup pruning disabled (BACKUP_KEEP_COUNT=0)."; return 0; }
  local stale
  # `ls -1t` is newest-first; tail past the keep-count is the set to delete.
  stale="$(ls -1t "${BACKUP_DIR}"/applicant-*.sql 2>/dev/null | tail -n "+$((BACKUP_KEEP_COUNT + 1))" || true)"
  if [[ -z "${stale}" ]]; then
    log "Backup retention: ${BACKUP_KEEP_COUNT} kept; nothing to prune."
    return 0
  fi
  log "Backup retention: keeping the newest ${BACKUP_KEEP_COUNT}; pruning $(wc -l <<<"${stale}") older dump(s)."
  while IFS= read -r f; do
    [[ -n "${f}" ]] || continue
    if [[ "${APPLY}" -eq 1 ]]; then
      # Drop the stale applicant-*.sql dump and its sibling image-ref snapshot.
      rm -f "${BACKUP_DIR}/$(basename "${f}")" "${f%.sql}.images"
    else
      echo "    (would run) rm -f ${f}   # prune old applicant-*.sql dump + .images sibling"
    fi
  done <<<"${stale}"
}

# --- shared rollback/recovery machinery (issues #18/#20/#279) ---------------
# A real rollback reverts the CODE + IMAGES alongside the database (issue #279):
# restoring only the DB would leave the NEW code/images on top of OLD data (after
# the new migrations already ran), a broken mix. Revert the git checkout to the
# snapshotted pre-update commit, re-point the images at their :previous tags
# (docker image tag), redeploy, then restore the DB dump. If the pre-update
# snapshot is missing we cannot safely revert code/images, so FAIL LOUDLY rather
# than silently doing a partial (DB-only) rollback.
#
# Factored into a function so it is not just the MANUAL `--rollback` path: it is
# also invoked AUTOMATICALLY below when `docker compose up -d` or the post-update
# heartbeat fails (issues #18/#20) — the exact moment the script *knows* the stack
# is half-updated or unhealthy, instead of only printing rollback guidance.
auto_rollback() {
  local reason="$1"
  log "AUTO-RECOVERY (${reason}) — reverting code + images + database to the pre-update snapshot."
  # Fail loudly if the snapshot is missing rather than a silent partial DB-only rollback (#279).
  if [[ ! -f "${DEPLOY_SNAPSHOT}" ]]; then
    echo "AUTO-RECOVERY FAILED: no pre-update snapshot at ${DEPLOY_SNAPSHOT}; refusing a partial DB-only rollback." >&2
    return 1
  fi
  GIT_REV=""; API_IMAGE_ID=""; UI_IMAGE_ID=""
  # shellcheck disable=SC1090
  source "${DEPLOY_SNAPSHOT}"
  # 1. Revert source to the snapshotted commit (git reset --hard; SELFTEST-guarded).
  [[ -n "${GIT_REV}" && -d "${REPO_ROOT}/.git" && "${APPLICANT_SELFTEST:-0}" != "1" ]] && run git -C "${REPO_ROOT}" reset --hard "${GIT_REV}"
  # 2. Re-point the images at their pre-update IDs (docker image tag …:previous).
  [[ -n "${API_IMAGE_ID}" ]] && run docker image tag applicant/api:previous applicant/api:latest
  [[ -n "${UI_IMAGE_ID}" ]] && run docker image tag applicant/ui:previous applicant/ui:latest
  # 3. Restore the most recent DB dump, then redeploy the reverted stack.
  local latest
  latest="$(ls -1t "${BACKUP_DIR}"/applicant-*.sql 2>/dev/null | head -n1 || true)"
  if [[ -z "${latest}" ]]; then
    echo "AUTO-RECOVERY: no DB backup in ${BACKUP_DIR}; nothing to roll back — the stack was NOT redeployed." >&2
    return 1
  fi
  log "AUTO-RECOVERY: restoring DB backup ${latest} and redeploying."
  if ! restore_dump "${latest}"; then
    echo "AUTO-RECOVERY: DB restore from ${latest} FAILED; the stack was NOT redeployed — restore manually: scripts/update.sh --rollback --apply" >&2
    return 1
  fi
  run docker compose -f "${COMPOSE_FILE}" up -d
  log "AUTO-RECOVERY complete (or dry-run printed above) — reverted to the pre-update snapshot."
  return 0
}

# --- rollback path (manual --rollback CLI invocation) -----------------------
if [[ "${ROLLBACK}" -eq 1 ]]; then
  if auto_rollback "manual --rollback"; then
    exit 0
  else
    exit 1
  fi
fi

# --- update path ------------------------------------------------------------
log "Update flow (sync code → backup → build → migrate → restart)."
run mkdir -p "${BACKUP_DIR}"
# Belt-and-suspenders: the default BACKUP_DIR lives inside the repo, and the dumps
# contain ALL user data. Drop a `*`-ignore so a stray `git add -A` can never commit
# a database dump even if the repo-root .gitignore lacks a .backups/ entry.
if [[ "${APPLY}" -eq 1 && ! -e "${BACKUP_DIR}/.gitignore" ]]; then
  ( umask 077; printf '*\n' >"${BACKUP_DIR}/.gitignore" )
fi

# --- 0/5 Sync the source checkout -------------------------------------------
# The whole point of an "update" is to run NEW code. The api image is built from
# this local checkout (pull_policy: build), so without syncing git first every
# rebuild just reproduces the old image. Fetch + hard-reset to the tracked branch
# (the deploy tree is not edited by hand). .env / .backups are untracked/ignored
# and survive the reset.
APPLICANT_BRANCH="${APPLICANT_BRANCH:-main}"
# What the sync changed drives the smart-skip below. Defaults are CONSERVATIVE:
# rebuild BOTH images, back up, and migrate unless we can positively PROVE an input
# is unchanged — so an aggressive skip can never miss a real change.
REBUILD_API=1; REBUILD_UI=1; RUN_MIGRATE=1
OLD_REV=""; NEW_REV=""
# APPLICANT_SELFTEST=1 skips the destructive git reset (set by the test suite so a
# unit test can never hard-reset the working tree to origin/main).
if [[ "${APPLICANT_SELFTEST:-0}" != "1" && -d "${REPO_ROOT}/.git" ]]; then
  OLD_REV="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
  log "0/5 Syncing source to origin/${APPLICANT_BRANCH}"
  run git -C "${REPO_ROOT}" fetch origin "${APPLICANT_BRANCH}"
  run git -C "${REPO_ROOT}" reset --hard "origin/${APPLICANT_BRANCH}"
  NEW_REV="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
else
  log "0/5 No git checkout at ${REPO_ROOT}; skipping source sync."
fi

# --- Smart-skip: only do the work the sync actually requires -------------------
# Compare the pre/post-sync revisions and rebuild only the image(s) whose build
# inputs changed, migrate only when a new Alembic revision landed, and back up only
# when we will migrate (a code-only deploy never touches the schema). Guarded to a
# real --apply run with a git checkout: the dry-run preview and the hermetic
# self-test keep the conservative do-everything defaults, so the full flow is still
# shown/tested. This block runs BEFORE the backup step on purpose.
if [[ "${APPLY}" -eq 1 && "${APPLICANT_SELFTEST:-0}" != "1" && -n "${OLD_REV}" && -n "${NEW_REV}" ]]; then
  if [[ "${OLD_REV}" == "${NEW_REV}" ]]; then
    log "Already at origin/${APPLICANT_BRANCH} (${NEW_REV:0:12}) — nothing new to deploy."
    REBUILD_API=0; REBUILD_UI=0; RUN_MIGRATE=0
  else
    CHANGED="$(git -C "${REPO_ROOT}" diff --name-only "${OLD_REV}" "${NEW_REV}" 2>/dev/null || true)"
    # Engine (api) image inputs — its source plus everything COPYed into its build.
    grep -qE '^(src/|pyproject\.toml|uv\.lock|README\.md|alembic\.ini|workspace/|templates/|scripts/|docker/Dockerfile)' <<<"${CHANGED}" || REBUILD_API=0
    # Front-door (applicant-ui) image inputs — the vendored app + its Dockerfile/entrypoint.
    grep -qE '^workspace/' <<<"${CHANGED}" || REBUILD_UI=0
    # Migrations — only a change under the Alembic versions dir adds/removes a revision.
    grep -qE '^src/applicant/adapters/storage/alembic/versions/' <<<"${CHANGED}" || RUN_MIGRATE=0
    log "Changed since ${OLD_REV:0:12}: api=$([[ ${REBUILD_API} -eq 1 ]] && echo rebuild || echo skip), ui=$([[ ${REBUILD_UI} -eq 1 ]] && echo rebuild || echo skip), migrate=$([[ ${RUN_MIGRATE} -eq 1 ]] && echo yes || echo no)"
  fi
  # Safety net: never skip building an image that does not yet exist (first deploy,
  # a pruned image, or a prior failed build). The skip is an optimization, not a
  # correctness gate.
  docker image inspect applicant/api:latest >/dev/null 2>&1 || REBUILD_API=1
  docker image inspect applicant/ui:latest  >/dev/null 2>&1 || REBUILD_UI=1

  # Migration-skip robustness (#19): the path-glob above only catches a NEW revision
  # file landing under the hardcoded versions/ dir — a path rename, a vendored
  # migration living elsewhere, or an env.py data-fix would be skipped while the new
  # code that needs the new schema deploys (exactly the skew the migrate step exists
  # to prevent). Never trust path-matching alone: compare the DB's ACTUAL applied
  # revision against the repo's alembic head(s) computed from the files now on disk
  # (post-sync) and force a migrate if they disagree, regardless of which files the
  # diff touched. Best-effort — if python3/psql/the DB are unavailable this simply
  # falls back to the conservative path-based decision above (never loosens it).
  if [[ "${RUN_MIGRATE}" -eq 0 ]] && command -v python3 >/dev/null 2>&1; then
    _alembic_versions_dir="${REPO_ROOT}/src/applicant/adapters/storage/alembic/versions"
    if [[ -d "${_alembic_versions_dir}" ]]; then
      _code_heads="$(python3 - "${_alembic_versions_dir}" <<'PYEOF' 2>/dev/null || true
import os, re, sys
d = sys.argv[1]
revs = set()
downs = set()
for fn in os.listdir(d):
    if not fn.endswith(".py"):
        continue
    try:
        text = open(os.path.join(d, fn), encoding="utf-8", errors="ignore").read()
    except OSError:
        continue
    m = re.search(r"^revision\s*[:=].*?['\"]([\w]+)['\"]", text, re.M)
    if not m:
        continue
    revs.add(m.group(1))
    for dm in re.finditer(r"^down_revision\s*[:=].*?['\"]([\w]+)['\"]", text, re.M):
        downs.add(dm.group(1))
print(",".join(sorted(revs - downs)))
PYEOF
      )"
      _db_current="$(docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
        psql -tA -U "${DB_USER}" -d "${DB_NAME}" \
        -c "select coalesce(string_agg(version_num, ',' order by version_num), '') from alembic_version" \
        2>/dev/null | tr -d '[:space:]' || true)"
      if [[ -n "${_code_heads}" && "${_code_heads}" != "${_db_current}" ]]; then
        log "Migration-skip override: repo alembic head(s) [${_code_heads}] differ from the DB's applied revision(s) [${_db_current:-none}] — migrating despite no matched path change."
        RUN_MIGRATE=1
      fi
    fi
  fi
fi

# --- Snapshot the pre-update deployable state for rollback (issue #279) --------
# BEFORE step 2/5 rebuilds the images, record the git commit and the current image
# IDs that are live right now. --rollback re-points the images at these IDs and
# checks the source back out to this commit, so a rollback reverts code + images
# together with the DB — not just the DB on top of new code. Re-tag the running
# images under stable :previous refs so the IDs survive a later rebuild/prune, and
# pin the per-dump .images sibling for count-paired rotation.
if [[ "${APPLY}" -eq 1 && "${APPLICANT_SELFTEST:-0}" != "1" ]]; then
  _api_prev="$(docker image inspect --format '{{.Id}}' applicant/api:latest 2>/dev/null || true)"
  _ui_prev="$(docker image inspect --format '{{.Id}}' applicant/ui:latest 2>/dev/null || true)"
  [[ -n "${_api_prev}" ]] && docker image tag "${_api_prev}" applicant/api:previous >/dev/null 2>&1 || true
  [[ -n "${_ui_prev}" ]] && docker image tag "${_ui_prev}" applicant/ui:previous >/dev/null 2>&1 || true
  {
    printf 'GIT_REV=%s\n' "${OLD_REV}"
    printf 'API_IMAGE_ID=%s\n' "${_api_prev}"
    printf 'UI_IMAGE_ID=%s\n' "${_ui_prev}"
  } >"${DEPLOY_SNAPSHOT}"
  # Pin a per-dump copy so rotation prunes the snapshot with its dump.
  [[ "${RUN_MIGRATE}" -eq 1 ]] && cp -f "${DEPLOY_SNAPSHOT}" "${DUMP_FILE%.sql}.images" 2>/dev/null || true
  log "Snapshotted pre-update state for rollback: git ${OLD_REV:0:12}, images api/ui:previous."
fi

if [[ "${RUN_MIGRATE}" -eq 1 ]]; then
log "1/5 Backing up the database to ${DUMP_FILE}"
# Back up BEFORE migrate so rollback is always possible (FR-INSTALL-2). A failed or
# empty backup MUST abort the update — never proceed to migrate with no valid dump.
if [[ "${APPLY}" -eq 1 ]]; then
  # --clean --if-exists: the dump DROPs objects (guarded by IF EXISTS) before
  # recreating them, so restoring it onto a partially-migrated DB is idempotent and
  # leaves no half-applied schema behind.
  if ! docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
      pg_dump --clean --if-exists -U "${DB_USER}" "${DB_NAME}" >"${DUMP_FILE}"; then
    echo "Backup failed (pg_dump errored); aborting before migrate." >&2
    rm -f "${DUMP_FILE}"
    exit 1
  fi
  if [[ ! -s "${DUMP_FILE}" ]]; then
    echo "Backup is empty (${DUMP_FILE}); aborting before migrate." >&2
    rm -f "${DUMP_FILE}"
    exit 1
  fi
  log "Backup OK ($(wc -c <"${DUMP_FILE}") bytes)."
else
  # Dry-run: print the command WITHOUT redirecting anything into the dump file.
  echo "    (would run) docker compose -f ${COMPOSE_FILE} exec -T ${DB_SERVICE} pg_dump --clean --if-exists -U ${DB_USER} ${DB_NAME} >${DUMP_FILE}"
fi
# Rotate old backups so daily dumps cannot fill the disk (issue #282).
prune_backups
else
  log "1/5 No migration in this update — skipping the database backup (schema untouched)."
fi

log "2/5 Pulling base images + rebuilding CHANGED local images from synced source"
run docker compose -f "${COMPOSE_FILE}" pull --ignore-buildable
# Rebuild only the images whose build inputs changed (decided above). Docker layer
# caching already makes an unchanged rebuild cheap, but skipping avoids the build
# context upload + cache check entirely. Both default to rebuild unless proven unchanged.
BUILD_TARGETS=()
[[ "${REBUILD_UI}" -eq 1 ]] && BUILD_TARGETS+=("applicant-ui")
[[ "${REBUILD_API}" -eq 1 ]] && BUILD_TARGETS+=("api")
if [[ "${#BUILD_TARGETS[@]}" -gt 0 ]]; then
  run docker compose -f "${COMPOSE_FILE}" build "${BUILD_TARGETS[@]}"
else
  log "    No image inputs changed — both local images already current, skipping build."
fi

if [[ "${RUN_MIGRATE}" -eq 1 ]]; then
log "3/5 Running database migrations (BLOCKING — gates the new stack)"
# Fail-closed: migrate as a BLOCKING one-off (`run --rm`, which does NOT serve
# traffic) BEFORE the new stack is brought up to serve. If `alembic upgrade head`
# fails, AUTO-RESTORE the dump we just took (so the DB is returned to its pre-update
# state) and abort non-zero — never leave a half-migrated schema being served.
if [[ "${APPLY}" -eq 1 ]]; then
  if ! docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head; then
    echo "Migration FAILED — auto-restoring the pre-update backup and aborting." >&2
    if restore_dump "${DUMP_FILE}"; then
      echo "Auto-rollback complete: DB restored from ${DUMP_FILE}. The new stack was NOT started." >&2
    else
      echo "Auto-rollback FAILED to restore ${DUMP_FILE}; restore manually: scripts/update.sh --rollback --apply" >&2
    fi
    exit 1
  fi
else
  echo "    (would run) docker compose -f ${COMPOSE_FILE} run --rm api uv run alembic upgrade head"
  echo "    (on failure, would auto-restore ${DUMP_FILE} and abort before serving)"
fi
else
  log "3/5 No new migration in this update — skipping (schema already at head)."
fi

log "4/5 Restarting the stack on the freshly built images (built once in 2/5 — no rebuild)"
# Plain `up -d` (no --build): step 2/5 already built applicant-ui + api from the
# synced source, so re-passing --build here would rebuild AND re-export/unpack the
# same images a second time — the slowest, disk-bound stage — for nothing.
#
# Auto-recovery (#18): migrate can succeed and `up -d` still fail (registry hiccup,
# port conflict, a transient daemon error) — the window where the new schema is live
# under old/mixed containers. Retry a bounded number of times first (transient), and
# if it still fails, AUTO-ROLL BACK (execute the recovery, not just print guidance)
# rather than leaving a half-updated stack for a human to notice.
if [[ "${APPLY}" -eq 1 ]]; then
  UP_OK=0
  for _up_attempt in 1 2 3; do
    if docker compose -f "${COMPOSE_FILE}" up -d; then
      UP_OK=1
      break
    fi
    echo "docker compose up -d failed (attempt ${_up_attempt}/3)." >&2
    [[ "${_up_attempt}" -lt 3 ]] && sleep 5
  done
  if [[ "${UP_OK}" -ne 1 ]]; then
    echo "docker compose up -d failed after 3 attempts — the stack may be half-updated (new schema, old/mixed containers)." >&2
    if auto_rollback "up -d failed after retries"; then
      echo "Auto-recovery restored the pre-update stack. Investigate the up -d failure (docker/daemon/port) before retrying the update." >&2
    else
      echo "Auto-recovery could not complete. Manual rollback: scripts/update.sh --rollback --apply" >&2
    fi
    exit 1
  fi
else
  run docker compose -f "${COMPOSE_FILE}" up -d
fi

log "5/5 Update applied."

# Heartbeat: verify the stack came back green before declaring success. A heartbeat
# failure is the one moment the script KNOWS the post-update stack is unhealthy, so
# (#20) it now actually EXECUTES the rollback it used to only recommend, instead of
# printing guidance and leaving a human to run it.
if [[ "${APPLY}" -eq 1 && "${APPLICANT_SELFTEST:-0}" != "1" ]]; then
  # Prefer APP_PORT from .env (the value compose publishes); else derive from APP_URL.
  APP_PORT="${APP_PORT:-${APP_URL##*:}}"; [[ "${APP_PORT}" =~ ^[0-9]+$ ]] || APP_PORT=8000
  if ! heartbeat "${APP_PORT}"; then
    echo "Update did not come up healthy." >&2
    if auto_rollback "heartbeat failed"; then
      echo "Auto-recovery restored the pre-update stack. Investigate before retrying the update." >&2
    else
      echo "Auto-recovery could not complete. Manual rollback: scripts/update.sh --rollback --apply" >&2
    fi
    exit 1
  fi
fi

if [[ "${APPLY}" -eq 1 ]]; then
  log "Update complete. If anything looks wrong, run: scripts/update.sh --rollback --apply"
else
  log "DRY RUN complete (no --apply). Re-run with --apply to perform the update."
fi
