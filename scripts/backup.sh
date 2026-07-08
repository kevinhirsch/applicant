#!/usr/bin/env bash
#
# Applicant — full backup (P1-7, issue #659).
#
# Produces ONE tarball containing everything needed to restore an irreplaceable
# job search on a fresh host:
#   - db.sql                    Postgres dump (--clean --if-exists, same
#                                command/flags update.sh's pre-migration
#                                backup step already runs — CLAUDE.md
#                                principle #1, lift-and-shift; see
#                                scripts/lib/backup-common.sh)
#   - workspace-data.tar.gz      the front-door UI's own `data/` (its sqlite
#                                DB, uploaded documents, prefs, caches — the
#                                `ui-data` named volume)
#   - engine-state.tar.gz        the engine's durable /data volumes: secrets
#                                (credential vault master key), checkpoints,
#                                fonts, profiles (signed-in browser sessions)
#   - config/.env                the deploy secrets/config (POSTGRES_PASSWORD,
#                                APPLICANT_INTERNAL_TOKEN, LLM keys, ...)
#   - MANIFEST.txt                what actually landed in this tarball
#
# Usage:
#   scripts/backup.sh [--apply] [--output PATH] [--reuse-db-dump FILE]
#     (default: dry-run — prints the steps it would run; pass --apply to run them)
#
# Restore with scripts/restore.sh (see that script's header, or
# docs/backup-restore.md, for the full walkthrough).
#
# This script is ALSO what scripts/update.sh's pre-migration step calls (see the
# "P1-7" marker in update.sh) to produce the same full tarball backup alongside
# its own existing DB-only safety dump used for the immediate --rollback path —
# the two are deliberately independent so this addition can never weaken the
# already-tested migrate-safety rollback. update.sh passes --reuse-db-dump with
# the dump file it just took so this script does not hit Postgres a second time.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
# Overridable (APPLICANT_ENV_FILE) so tests can point this at a scratch path
# instead of ever touching the real deploy .env — mirrors APPLICANT_BACKUP_DIR
# below. Real deploys leave this unset and get the normal repo-root .env.
ENV_FILE="${APPLICANT_ENV_FILE:-${REPO_ROOT}/.env}"
BACKUP_DIR="${APPLICANT_BACKUP_DIR:-${REPO_ROOT}/.backups}"
# Full-tarball backups get their OWN retention count/namespace, separate from
# update.sh's `applicant-*.sql` DB-only dumps (issue #282 precedent) — a
# fresh count so the two rotations never interfere with each other's history.
BACKUP_KEEP_COUNT="${BACKUP_KEEP_COUNT:-7}"

# shellcheck source=lib/backup-common.sh
source "${REPO_ROOT}/scripts/lib/backup-common.sh"
bkup_load_env "${ENV_FILE}"

DB_SERVICE="postgres"
UI_SERVICE="applicant-ui"
API_SERVICE="api"
DB_NAME="${POSTGRES_DB:-applicant}"
DB_USER="${POSTGRES_USER:-applicant}"

APPLY=0
OUTPUT=""
# Reuse an ALREADY-taken DB dump instead of pg_dump-ing a second time (this is
# how update.sh's pre-migration step calls in: it just ran pg_dump for its own
# rollback-safety file, so pass that same file here rather than hitting
# Postgres twice for one backup cycle).
REUSE_DB_DUMP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --output) OUTPUT="${2:?--output requires a PATH}"; shift 2 ;;
    --output=*) OUTPUT="${1#--output=}"; shift ;;
    --reuse-db-dump) REUSE_DB_DUMP="${2:?--reuse-db-dump requires a FILE}"; shift 2 ;;
    --reuse-db-dump=*) REUSE_DB_DUMP="${1#--reuse-db-dump=}"; shift ;;
    -h|--help)
      echo "Usage: backup.sh [--apply] [--output PATH] [--reuse-db-dump FILE]"
      echo "  (default: dry-run — prints the steps it would run; --apply runs them)"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m[backup]\033[0m %s\n' "$*"; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
[[ -n "${OUTPUT}" ]] || OUTPUT="${BACKUP_DIR}/applicant-full-${TS}.tar.gz"

if [[ "${APPLY}" -eq 1 ]]; then
  ( umask 077; mkdir -p "${BACKUP_DIR}" )
  # Same belt-and-suspenders as update.sh: a stray `git add -A` must never
  # commit a backup (these tarballs contain ALL user data).
  if [[ ! -e "${BACKUP_DIR}/.gitignore" ]]; then
    ( umask 077; printf '*\n' >"${BACKUP_DIR}/.gitignore" )
  fi
  WORK_DIR="$(mktemp -d)"
  trap 'rm -rf "${WORK_DIR}"' EXIT
  mkdir -p "${WORK_DIR}/config"
else
  # Dry run: nothing is created on disk — this path is only ever interpolated
  # into the "(would run) ..." command previews the helpers below print.
  WORK_DIR="${BACKUP_DIR}/.dry-run-preview"
fi

HAS_DB=0
HAS_WORKSPACE=0
HAS_SECRETS=0
HAS_CONFIG=0

log "1/5 Postgres dump"
if [[ -n "${REUSE_DB_DUMP}" ]]; then
  if [[ -s "${REUSE_DB_DUMP}" ]]; then
    log "    reusing an already-taken dump: ${REUSE_DB_DUMP}"
    if [[ "${APPLY}" -eq 1 ]]; then
      cp "${REUSE_DB_DUMP}" "${WORK_DIR}/db.sql"
    else
      echo "    (would run) cp ${REUSE_DB_DUMP} ${WORK_DIR}/db.sql"
    fi
    HAS_DB=1
  else
    echo "    (warn) --reuse-db-dump file is missing/empty; falling back to a fresh pg_dump" >&2
  fi
fi
if [[ "${HAS_DB}" -ne 1 ]]; then
  if bkup_dump_database "${COMPOSE_FILE}" "${DB_SERVICE}" "${DB_USER}" "${DB_NAME}" \
       "${WORK_DIR}/db.sql" "${APPLY}"; then
    HAS_DB=1
  else
    # A "backup" that cannot restore Postgres is not a backup — automation
    # keying off exit 0 must never archive one (disaster-recovery invariant).
    echo "Backup FAILED: Postgres dump failed; refusing to create a backup without db.sql." >&2
    exit 1
  fi
fi

log "2/5 Workspace data/ (front-door UI)"
if bkup_export_workspace_data "${COMPOSE_FILE}" "${UI_SERVICE}" "${WORK_DIR}/workspace-data.tar.gz" "${APPLY}"; then
  HAS_WORKSPACE=1
else
  echo "    (warn) workspace data export failed (is the applicant-ui container up?) — the backup will NOT include workspace-data.tar.gz." >&2
fi

log "3/5 Engine durable state (vault master key, checkpoints, fonts, browser profiles)"
if bkup_export_engine_state "${COMPOSE_FILE}" "${API_SERVICE}" "${WORK_DIR}/engine-state.tar.gz" "${APPLY}"; then
  HAS_SECRETS=1
else
  echo "    (warn) engine state export failed — the backup will NOT include the credential vault key (sealed credentials in db.sql cannot be decrypted from this backup after a volume wipe), nor checkpoints/fonts/browser profiles." >&2
fi

log "4/5 Config (.env)"
if bkup_collect_config "${ENV_FILE}" "${WORK_DIR}/config" "${APPLY}"; then
  [[ -f "${ENV_FILE}" ]] && HAS_CONFIG=1
fi

log "5/5 Assembling one tarball -> ${OUTPUT}"
if [[ "${APPLY}" -eq 1 ]]; then
  bkup_write_manifest "${WORK_DIR}/MANIFEST.txt" "${HAS_DB}" "${HAS_WORKSPACE}" "${HAS_CONFIG}" "${HAS_SECRETS}"
else
  echo "    (would run) write MANIFEST.txt (db=${HAS_DB} workspace=${HAS_WORKSPACE} secrets=${HAS_SECRETS} config=${HAS_CONFIG})"
fi
bkup_make_tarball "${OUTPUT}" "${WORK_DIR}" "${APPLY}"

if [[ "${APPLY}" -eq 1 ]]; then
  if [[ ! -s "${OUTPUT}" ]]; then
    echo "Backup FAILED: ${OUTPUT} is missing or empty." >&2
    exit 1
  fi
  log "Backup complete: ${OUTPUT} ($(wc -c <"${OUTPUT}") bytes)."
  if [[ "${HAS_DB}" -ne 1 ]]; then
    echo "WARNING: this backup has NO Postgres dump — it cannot restore the database." >&2
  fi
  if [[ "${HAS_SECRETS}" -ne 1 ]]; then
    echo "WARNING: this backup has NO credential vault key — after a volume wipe, sealed credentials restored from db.sql cannot be decrypted." >&2
  fi

  # Retention: keep only the newest BACKUP_KEEP_COUNT full tarballs (issue #282
  # precedent, separate namespace/count from update.sh's applicant-*.sql dumps).
  if [[ "${BACKUP_KEEP_COUNT}" -gt 0 ]]; then
    stale="$(ls -1t "${BACKUP_DIR}"/applicant-full-*.tar.gz 2>/dev/null | tail -n "+$((BACKUP_KEEP_COUNT + 1))" || true)"
    if [[ -n "${stale}" ]]; then
      log "Retention: keeping the newest ${BACKUP_KEEP_COUNT} full backups; pruning older ones."
      while IFS= read -r f; do
        [[ -n "${f}" ]] && rm -f "${f}"
      done <<<"${stale}"
    fi
  fi
else
  log "DRY RUN complete (no --apply). Re-run with --apply to produce the tarball."
fi
