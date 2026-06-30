# Applicant API image. python:3.12-slim + uv.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# Pin HOME + XDG cache/data dirs INSIDE the app tree (#161). The image drops to a
# non-root user at the end (see USER below), but the build steps that download the
# camoufox browser binary (`camoufox fetch`, which writes to the XDG data/cache dir)
# and uv's caches run as root. Anchoring HOME/XDG under /app means everything those
# steps write lands in the tree we chown to the runtime user — so the non-root
# process can still find the camoufox binary and write its caches at runtime,
# instead of them landing in an unreadable /root.
ENV HOME=/app \
    XDG_CACHE_HOME=/app/.cache \
    XDG_DATA_HOME=/app/.local/share \
    XDG_CONFIG_HOME=/app/.config \
    PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright

# Install uv (the project toolchain). Pinned by digest (#160, #374) — `:latest` is
# the worst-case mutable tag, so copy uv from an immutable image (tag in the comment
# for readability). Resolve a bump with: docker buildx imagetools inspect ghcr.io/astral-sh/uv:latest
# ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9 /uv /uvx /bin/

# System packages for the resume-render pipeline (FR-RESUME-3/4). The renderer
# auto-detects these via shutil.which() and silently degrades (no real PDF) when
# absent, so they must be in the image — both render paths are reachable depending
# on the user's onboarding accept/reject choice:
#   * LaTeX (primary): xelatex/lualatex + fontspec / moderncv / fontawesome5
#   * docx (fallback): LibreOffice headless (soffice --convert-to pdf)
# Targeted texlive subset (not texlive-full) to keep the image ~2GB instead of ~4GB.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fontconfig \
        texlive-xetex \
        texlive-luatex \
        texlive-latex-extra \
        texlive-latex-recommended \
        texlive-fonts-recommended \
        texlive-fonts-extra \
        lmodern \
    && rm -rf /var/lib/apt/lists/*

# Warm the xelatex/lualatex font + format cache at BUILD time. The first compile
# otherwise has to build this cache, which aborts (producing NO PDF, so the render
# silently degrades to an approximate preview) when the runtime user has no writable
# HOME/TEXMFVAR. Building it now — into a world-readable cache + a writable fallback —
# means the first real onboarding compile produces a true PDF. Best-effort: a failure
# here must not fail the image build (the adapter also points the cache at a writable
# scratch dir per compile).
RUN mkdir -p /tmp/texwarm \
    && printf '%s\n' \
        '\documentclass[11pt,a4paper,sans]{moderncv}' \
        '\moderncvstyle{banking}\moderncvcolor{blue}' \
        '\name{Test}{User}' \
        '\begin{document}\makecvtitle\section{Skills}\cvitem{}{Python}\end{document}' \
        > /tmp/texwarm/warm.tex \
    && (cd /tmp/texwarm && lualatex -interaction=nonstopmode -halt-on-error warm.tex || true) \
    && (cd /tmp/texwarm && xelatex  -interaction=nonstopmode -halt-on-error warm.tex || true) \
    && rm -rf /tmp/texwarm

# Camoufox runtime libraries (FR-PREFILL-1, FR-STEALTH-1). Camoufox is the DEFAULT
# browser engine (BROWSER_ENGINE=camoufox) — a Firefox-based anti-detect browser the
# engine drives for ALL outbound automation traffic. The browser binary itself is
# fetched below (`camoufox fetch`); these are the Firefox runtime libs it needs, plus
# Xvfb so it renders HEADFUL on a virtual display inside this display-less container
# (headful = no headless fingerprint tell).
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        libgtk-3-0 \
        libx11-xcb1 \
        libxcb1 \
        libdbus-glib-1-2 \
        libxtst6 \
        libxt6 \
        libpci3 \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Real Google Chrome for the FALLBACK chromium engine (BROWSER_ENGINE=chromium) and
# the Proxmox Windows CDP backend (FR-PREFILL-1, FR-STEALTH-1). The engine drives it
# via patchright (the 'browser' extra) with channel=chrome. Real Chrome — not bundled
# Chromium — minimizes automation tells for stealth; the .deb pulls its own runtime
# libs. The local chromium-engine sandbox launches this inside THIS container (no CDP
# endpoint), so the binary must live in the engine image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget gnupg ca-certificates \
    && wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y --no-install-recommends /tmp/google-chrome.deb \
    && rm -f /tmp/google-chrome.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Dependency layer (cache-stable) ------------------------------------------
# Install ONLY third-party dependencies first, from the lockfile, WITHOUT the
# project's own source. This is the expensive layer (the full dep tree, plus the
# camoufox browser download below), so isolating it from the app code means it is
# reused from cache across every code-only update: it busts ONLY when
# pyproject.toml / uv.lock change, never when src/ changes. Includes the 'browser'
# extra (camoufox + patchright) so the real PatchrightBrowser the engine wires
# unconditionally (container.py) can launch a browser. --no-install-project:
# resolve+install deps but skip building/installing the local `applicant` package
# (that needs the source, copied in the cheap layer below).
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --extra browser --frozen --no-install-project \
    || uv sync --no-dev --extra browser --no-install-project

# Fetch the Camoufox browser binary + the GeoIP dataset (the `geoip` extra) into the
# image so the DEFAULT engine launches offline at runtime — the engine detects tools
# via shutil.which()/lazy import and silently degrades when absent, so the binary
# must be baked in here (CI does not build images; this layer is first exercised at
# deploy `compose up --build`). --no-sync runs camoufox from the dependency venv
# above WITHOUT re-syncing (the local project is not copied yet), and because this
# layer depends only on the deps it is cached across code changes instead of
# re-downloading hundreds of MB on every update.
RUN uv run --no-sync camoufox fetch

# Fetch the patchright/Chromium browser binary for the FALLBACK chromium engine
# (BROWSER_ENGINE=chromium). The default chromium launch uses channel=chrome (the
# real Google Chrome .deb above), but patchright's driver still needs a browser
# bundle that MATCHES the installed patchright/playwright revision — patchright
# `install chromium` pulls exactly that matched revision, which avoids the
# "bundled chromium vs driver" revision mismatch a hand-pinned download would risk.
# Anchored under /app via PLAYWRIGHT_BROWSERS_PATH so the binary lands in the tree
# chowned to the non-root runtime user (same rationale as the camoufox fetch).
# Like camoufox, this is integration-only and not exercised by CI (which does not
# build images) — first run at deploy `compose up --build`. Must confirm there:
# the download succeeds and the engine launches chromium without falling back.
RUN uv run --no-sync patchright install chromium

# --- Project layer (cheap; rebuilt on code changes) ---------------------------
# Now copy the engine source and install just the local `applicant` package on top
# of the already-installed deps. A code change busts only this fast layer — no apt,
# no dependency reinstall, no camoufox re-fetch.
COPY src ./src
RUN uv sync --no-dev --extra browser --frozen || uv sync --no-dev --extra browser

# App code + workspace static + LaTeX/docx templates (loaded at runtime as
# parents[4]/templates by the resume-render engines — must be in the image).
COPY alembic.ini ./
COPY frontend ./frontend
COPY workspace/static ./workspace/static
COPY templates ./templates
COPY scripts ./scripts

# --- Drop privileges (#161) ---------------------------------------------------
# Run the API as a dedicated non-root user instead of root, so a compromised app
# process has no root inside the container. Everything above ran as root (apt, the
# camoufox fetch, uv sync into /app/.venv), so create the user LAST and hand it the
# whole app tree — incl. the venv, the camoufox binary, and the XDG cache/data dirs
# pinned under /app above, which the renderer/browser write to at runtime.
RUN groupadd --system --gid 10001 applicant \
    && useradd --system --uid 10001 --gid applicant --home-dir /app --shell /usr/sbin/nologin applicant \
    && mkdir -p /app/.cache /app/.local/share /app/.config \
    && chown -R applicant:applicant /app
USER applicant

EXPOSE 8000

# Run the FastAPI app via uvicorn.
CMD ["uv", "run", "uvicorn", "applicant.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
