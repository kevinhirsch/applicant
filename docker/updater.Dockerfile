# Applicant — updater sidecar (FR-OOBE-4, NFR-ZEROCLI-1).
#
# A tiny image that has the Docker CLI + Compose v2 plugin (to drive the host
# Docker via the mounted socket), plus bash/git/curl so it can run the normal
# scripts/update.sh --apply. It does NOT run the app — it only watches the shared
# control volume and dispatches updates. Kept minimal: no Python, no app deps.
#
# Base image pinned by immutable DIGEST, not the mutable `docker:27-cli` tag
# (#160, #374) — the 27-cli tag floats across patch releases, so pin it for a
# reproducible build (tag kept in the comment). Resolve a bump with:
# docker buildx imagetools inspect docker:27-cli
FROM docker:27-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c

# scripts/update.sh needs bash + git (source sync) + curl (heartbeat); the
# Compose v2 plugin drives the prod stack. pg_dump runs inside the postgres
# container (via `compose exec`), so no client is needed here.
RUN apk add --no-cache bash git curl docker-cli-compose

# Append-only build output so the captured update.log stays readable.
ENV BUILDKIT_PROGRESS=plain

# The daemon + repo are bind-mounted at runtime (the host repo -> /repo); this is
# only a sane default working dir.
WORKDIR /repo

# Privileged management sidecar — intentionally NOT dropped to a non-root USER (#161).
# Unlike the api/front-door app images, this container's whole job is to drive the
# HOST Docker daemon over the bind-mounted /var/run/docker.sock and run git/compose
# against the bind-mounted host checkout at /repo (incl. reading .env). Both the
# socket GID and the host-repo owner UID are host-specific and unknown at build time,
# so a fixed build-time USER would either lose access to docker.sock (EACCES) or be
# unable to write the repo. Harden this surface by limiting blast radius instead:
# deploy it only when the in-app updater is enabled, and treat the socket grant —
# not a container UID — as the real privilege boundary (see docker-compose.prod.yml).
ENTRYPOINT ["/bin/bash", "/repo/scripts/updater-daemon.sh"]
