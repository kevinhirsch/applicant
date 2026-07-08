#!/usr/bin/env bash
#
# Shared backup/restore primitives (P1-7, issue #659).
#
# Lift-and-shift note: the Postgres dump command here is the EXACT command
# `scripts/update.sh` already runs as its pre-migration safety dump (`pg_dump
# --clean --if-exists`, host-side redirect) -- CLAUDE.md principle #1 ("lift and
# shift first"). `update.sh`'s OWN inline dump/restore code is intentionally left
# untouched (several tests in tests/unit/test_update_script_*.py statically parse
# its literal source text for the `pg_dump`/`psql <STDIN` invocations and would
# break if those were replaced with a call into this file), but `scripts/backup.sh`,
# `scripts/restore.sh`, and update.sh's NEW full-tarball step (see the "P1-7" marker
# in update.sh) all share these functions rather than re-implementing them.
#
# Every function here is a plain bash function (no subshell-only side effects
# beyond writing the files it's told to write) so it can be sourced and unit
# tested directly, not just invoked end-to-end via a wrapper script.
#
# Safe to `source` multiple times.

# Guard against double-sourcing redefining functions (harmless, but keep it tidy).
if [[ -n "${_APPLICANT_BACKUP_COMMON_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
_APPLICANT_BACKUP_COMMON_LOADED=1

# --- env loading -------------------------------------------------------------

# bkup_load_env ENV_FILE
#
# Load KEY=VALUE lines from ENV_FILE into the current shell environment, WITHOUT
# clobbering a variable the caller already set explicitly (explicit env wins,
# mirroring update.sh's own loader). No-op when ENV_FILE does not exist.
bkup_load_env() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || return 0
  local _k _v
  while IFS='=' read -r _k _v; do
    [[ "${_k}" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    [[ -n "${!_k:-}" ]] || export "${_k}=${_v}"
  done <"${env_file}"
}

# --- Postgres dump / restore --------------------------------------------------

# bkup_dump_database COMPOSE_FILE DB_SERVICE DB_USER DB_NAME OUT_FILE APPLY
#
# Same command update.sh's pre-migration backup step runs: `pg_dump --clean
# --if-exists` (idempotent restore: DROPs+recreates objects) streamed host-side
# into OUT_FILE. Returns 1 (and removes a partial/empty OUT_FILE) on failure so
# callers never bundle a broken/empty dump into a tarball.
bkup_dump_database() {
  local compose_file="$1" db_service="$2" db_user="$3" db_name="$4" out_file="$5" apply="$6"
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) docker compose -f ${compose_file} exec -T ${db_service} pg_dump --clean --if-exists -U ${db_user} ${db_name} >${out_file}"
    return 0
  fi
  if ! docker compose -f "${compose_file}" exec -T "${db_service}" \
      pg_dump --clean --if-exists -U "${db_user}" "${db_name}" >"${out_file}"; then
    rm -f "${out_file}"
    return 1
  fi
  if [[ ! -s "${out_file}" ]]; then
    rm -f "${out_file}"
    return 1
  fi
  return 0
}

# bkup_restore_database COMPOSE_FILE DB_SERVICE DB_USER DB_NAME DUMP_FILE APPLY
#
# Streams DUMP_FILE into the container's psql over STDIN (never `psql -f`, which
# would look for the path INSIDE the container -- mirrors update.sh's own
# restore_dump, same reasoning documented there).
bkup_restore_database() {
  local compose_file="$1" db_service="$2" db_user="$3" db_name="$4" dump_file="$5" apply="$6"
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) docker compose -f ${compose_file} exec -T ${db_service} psql -v ON_ERROR_STOP=1 -U ${db_user} -d ${db_name} <${dump_file}"
    return 0
  fi
  docker compose -f "${compose_file}" exec -T "${db_service}" \
    psql -v ON_ERROR_STOP=1 -U "${db_user}" -d "${db_name}" <"${dump_file}"
}

# --- workspace data/ (the front-door UI's own named volume) -------------------

# bkup_export_workspace_data COMPOSE_FILE UI_SERVICE OUT_FILE APPLY
#
# Streams a gzip tar of the running UI container's /app/data (the `ui-data`
# named volume: its sqlite DB, uploaded documents, prefs, caches) host-side into
# OUT_FILE -- the exact same "docker compose exec -T ... > host file" pattern
# `bkup_dump_database`/update.sh use for Postgres, applied to the UI container
# instead (a named volume has no host path to read directly, so streaming a tar
# through the container that already has it mounted is the only portable way to
# reach it without hard-coding the compose-project-prefixed volume name).
#
# Best-effort by design: an unreachable/not-yet-up UI container degrades to a
# warning, not a hard failure -- the caller decides whether that is fatal for
# its use (backup.sh warns and still bundles what it has; nothing here decides
# that policy).
bkup_export_workspace_data() {
  local compose_file="$1" ui_service="$2" out_file="$3" apply="$4"
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) docker compose -f ${compose_file} exec -T ${ui_service} tar -czf - -C /app data >${out_file}"
    return 0
  fi
  if ! docker compose -f "${compose_file}" exec -T "${ui_service}" \
      tar -czf - -C /app data >"${out_file}"; then
    rm -f "${out_file}"
    return 1
  fi
  if [[ ! -s "${out_file}" ]]; then
    rm -f "${out_file}"
    return 1
  fi
  return 0
}

# bkup_restore_workspace_data COMPOSE_FILE UI_SERVICE TAR_FILE APPLY
#
# Inverse of bkup_export_workspace_data: streams TAR_FILE host-side into the
# container and extracts it at /app (recreating /app/data from the archive,
# which was captured with `-C /app data` so paths inside are already relative
# to /app).
bkup_restore_workspace_data() {
  local compose_file="$1" ui_service="$2" tar_file="$3" apply="$4"
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) docker compose -f ${compose_file} exec -T ${ui_service} tar -xzf - -C /app <${tar_file}"
    return 0
  fi
  docker compose -f "${compose_file}" exec -T "${ui_service}" \
    tar -xzf - -C /app <"${tar_file}"
}

# --- config (.env) -------------------------------------------------------------

# bkup_collect_config ENV_FILE OUT_DIR APPLY
#
# Copies ENV_FILE (the deploy secrets/config -- POSTGRES_PASSWORD,
# APPLICANT_INTERNAL_TOKEN, LLM keys, etc.) into OUT_DIR/.env at mode 600.
# A missing ENV_FILE is NOT an error (a fresh checkout that has not run
# install.sh yet has none) -- the tarball then simply carries no config/
# member and restore.sh says so plainly rather than silently pretending
# nothing was ever there.
bkup_collect_config() {
  local env_file="$1" out_dir="$2" apply="$3"
  if [[ ! -f "${env_file}" ]]; then
    echo "    (skip) no ${env_file} to collect (fresh checkout without a persisted .env)"
    return 0
  fi
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) install -m 600 ${env_file} ${out_dir}/.env"
    return 0
  fi
  mkdir -p "${out_dir}"
  install -m 600 "${env_file}" "${out_dir}/.env"
}

# bkup_restore_config CONFIG_DIR ENV_FILE APPLY
#
# Inverse of bkup_collect_config. Never silently overwrites a DIFFERENT existing
# .env: if ENV_FILE already exists, the restored copy is written alongside it as
# ENV_FILE.restored so the operator can diff/merge by hand instead of losing
# whichever secrets were live before the restore.
bkup_restore_config() {
  local config_dir="$1" env_file="$2" apply="$3"
  if [[ ! -f "${config_dir}/.env" ]]; then
    echo "    (skip) backup carries no config/.env member"
    return 0
  fi
  local dest="${env_file}"
  if [[ -f "${env_file}" ]]; then
    dest="${env_file}.restored"
  fi
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) install -m 600 ${config_dir}/.env ${dest}"
    [[ "${dest}" != "${env_file}" ]] && echo "    (note) ${env_file} already exists -- restored copy written to ${dest}, not overwritten"
    return 0
  fi
  install -m 600 "${config_dir}/.env" "${dest}"
  if [[ "${dest}" != "${env_file}" ]]; then
    echo "    ${env_file} already existed -- restored config written to ${dest} instead (diff/merge by hand)."
  fi
}

# --- tarball assembly ----------------------------------------------------------

# bkup_make_tarball OUT_PATH WORK_DIR APPLY
#
# Bundles every file already staged under WORK_DIR (db.sql, workspace-data.tar.gz,
# config/.env, MANIFEST.txt -- whichever of those the caller successfully staged)
# into ONE gzip tarball at OUT_PATH.
bkup_make_tarball() {
  local out_path="$1" work_dir="$2" apply="$3"
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) tar -czf ${out_path} -C ${work_dir} ."
    return 0
  fi
  tar -czf "${out_path}" -C "${work_dir}" .
}

# bkup_extract_tarball TARBALL_PATH DEST_DIR APPLY
#
# Inverse of bkup_make_tarball: extracts TARBALL_PATH into DEST_DIR (created if
# absent).
bkup_extract_tarball() {
  local tarball_path="$1" dest_dir="$2" apply="$3"
  if [[ "${apply}" -ne 1 ]]; then
    echo "    (would run) mkdir -p ${dest_dir} && tar -xzf ${tarball_path} -C ${dest_dir}"
    return 0
  fi
  mkdir -p "${dest_dir}"
  tar -xzf "${tarball_path}" -C "${dest_dir}"
}

# bkup_write_manifest OUT_FILE HAS_DB HAS_WORKSPACE HAS_CONFIG
#
# A small, honest plain-text manifest describing what actually landed in the
# tarball (H-series honesty invariant: never let a degraded/partial backup look
# indistinguishable from a full one). Written into the staging dir before
# bkup_make_tarball bundles everything up.
bkup_write_manifest() {
  local out_file="$1" has_db="$2" has_workspace="$3" has_config="$4"
  {
    printf 'Applicant backup manifest\n'
    printf 'created_at: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'db.sql (Postgres dump): %s\n' "$([[ "${has_db}" -eq 1 ]] && echo present || echo MISSING)"
    printf 'workspace-data.tar.gz (front-door UI data/): %s\n' "$([[ "${has_workspace}" -eq 1 ]] && echo present || echo MISSING)"
    printf 'config/.env: %s\n' "$([[ "${has_config}" -eq 1 ]] && echo present || echo "absent (no .env on this host)")"
  } >"${out_file}"
}
