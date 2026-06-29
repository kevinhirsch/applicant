# Applicant API image. python:3.12-slim + uv.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# Install uv (the project toolchain).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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

# --- Project layer (cheap; rebuilt on code changes) ---------------------------
# Now copy the engine source and install just the local `applicant` package on top
# of the already-installed deps. A code change busts only this fast layer — no apt,
# no dependency reinstall, no camoufox re-fetch.
COPY src ./src
RUN uv sync --no-dev --extra browser --frozen || uv sync --no-dev --extra browser

# App code + workspace static + LaTeX/docx templates (loaded at runtime as
# parents[4]/templates by the resume-render engines — must be in the image).
COPY alembic.ini ./
COPY workspace/static ./workspace/static
COPY templates ./templates
COPY scripts ./scripts

EXPOSE 8000

# Run the FastAPI app via uvicorn.
CMD ["uv", "run", "uvicorn", "applicant.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
