# Applicant — updater sidecar (FR-OOBE-4, NFR-ZEROCLI-1).
#
# A tiny image that has the Docker CLI + Compose v2 plugin (to drive the host
# Docker via the mounted socket), plus bash/git/curl so it can run the normal
# scripts/update.sh --apply. It does NOT run the app — it only watches the shared
# control volume and dispatches updates. Kept minimal: no Python, no app deps.
FROM docker:27-cli

# scripts/update.sh needs bash + git (source sync) + curl (heartbeat); the
# Compose v2 plugin drives the prod stack. pg_dump runs inside the postgres
# container (via `compose exec`), so no client is needed here.
RUN apk add --no-cache bash git curl docker-cli-compose

# Append-only build output so the captured update.log stays readable.
ENV BUILDKIT_PROGRESS=plain

# The daemon + repo are bind-mounted at runtime (the host repo -> /repo); this is
# only a sane default working dir.
WORKDIR /repo

ENTRYPOINT ["/bin/bash", "/repo/scripts/updater-daemon.sh"]
