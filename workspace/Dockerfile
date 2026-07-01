# Base image pinned by immutable DIGEST, not the mutable `python:3.12-slim` tag
# (#160, #374) — a tag can be repointed upstream, so pinning keeps the build
# reproducible and closes the supply-chain risk. Tag kept in the comment for
# readability. Resolve a bump with: docker buildx imagetools inspect python:3.12-slim
# python:3.12-slim
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

# System deps. tmux is required by Cookbook for background downloads/serves.
# openssh-client is required for Cookbook remote server tests, setup, probes,
# downloads, and serves from Docker installs.
# git/cmake are required when Cookbook builds llama.cpp on first llama.cpp
# launch inside Docker.
# nodejs/npm provide npx for the optional built-in Browser MCP server.
# gosu lets the entrypoint drop privileges cleanly so signals still reach
# uvicorn directly (no extra shell layer like `su`/`sudo` would add).
# Optionally repoint apt at a faster Debian mirror when deb.debian.org's CDN node is
# slow for the build host (APT_MIRROR is a HOSTNAME; default keeps the official CDN).
ARG APT_MIRROR=deb.debian.org
RUN if [ "$APT_MIRROR" != "deb.debian.org" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" \
            /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list 2>/dev/null || true; \
    fi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl \
    git \
    nodejs \
    npm \
    tmux \
    openssh-client \
    gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create data directory (mount a volume here for persistence)
RUN mkdir -p data logs services/cache/search

# Entrypoint that drops to PUID/PGID (default 1000:1000) and repairs
# ownership on the bind-mounted /app/data and /app/logs. Without this,
# the container runs as root and writes root-owned files into host
# bind mounts — any later non-root run (or a host user trying to
# update them) silently fails on EPERM, breaking skill extraction,
# prefs persistence, mail attachments, etc.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 7000

# Non-root runtime (#161): the app does NOT run as root, but the privilege drop
# is done at RUNTIME by entrypoint.sh (the PUID/PGID + gosu pattern), not by a
# build-time `USER` directive. The entrypoint MUST start as root so it can chown
# the bind-mounted /app/data and /app/logs (and the in-image runtime caches under
# /app) to the configured PUID:PGID before `exec gosu "$PUID:$PGID"` drops to that
# unprivileged user — uvicorn then runs non-root. A static build-time `USER` here
# would strip the root needed for that chown and break bind-mount ownership repair,
# so the runtime drop is the correct mechanism (tune via PUID/PGID, default 1000).
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7000"]
