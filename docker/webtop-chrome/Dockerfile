# Applicant — Chrome-enabled takeover webtop (FR-SANDBOX-2/3, FR-STEALTH-1).
#
# WHY THIS EXISTS
# ---------------
# The driving browser is REAL Google Chrome (not Chromium, not headless): it yields
# the genuine Chrome TLS/JA3 + HTTP/2 fingerprint and the correct Sec-CH-UA client
# hints automatically, which is the foundation of the coherent real-Linux/Chrome
# identity (FR-STEALTH-1). When the human takes over an irreducible step, they must
# take over the SAME Chrome — so every takeover desktop must ship google-chrome-stable.
#
# The stock LinuxServer *webtop* images (cinnamon/xfce) do NOT ship Google Chrome,
# so this derived image adds it on top, plus a realistic desktop font set so font
# enumeration looks like a real machine instead of a bare container (FR-STEALTH-1).
#
# BUILD (Cinnamon — the default DE):
#   docker build -t applicant/webtop-chrome:cinnamon \
#     --build-arg BASE=lscr.io/linuxserver/webtop:ubuntu-cinnamon docker/webtop-chrome
# BUILD (Xfce):
#   docker build -t applicant/webtop-chrome:xfce \
#     --build-arg BASE=lscr.io/linuxserver/webtop:ubuntu-xfce docker/webtop-chrome
#
# RUN: selected automatically by TAKEOVER_DESKTOP (cinnamon|xfce) -> the
#      applicant/webtop-chrome:<de> image (see src/applicant/app/config.py table).
#
# X11 RATIONALE: like the other takeover desktops, this runs on Xorg (X11), not
# Wayland — the web-streaming layer (KasmVNC) and the automation/handoff path are
# X11-native. Chrome runs headful on that X server (NOT --headless).

ARG BASE=lscr.io/linuxserver/webtop:ubuntu-cinnamon
FROM ${BASE}

LABEL org.opencontainers.image.title="applicant-webtop-chrome" \
      org.opencontainers.image.description="LinuxServer webtop + Google Chrome (real, headful) + realistic fonts for the coherent real-Linux/Chrome identity (FR-STEALTH-1)" \
      org.opencontainers.image.source="https://github.com/kevinhirsch/applicant"

ENV DEBIAN_FRONTEND=noninteractive \
    TITLE="Applicant — Chrome takeover desktop"

# Install REAL Google Chrome (google-chrome-stable) from Google's apt repo, plus a
# realistic desktop FONT SET (FR-STEALTH-1) so font enumeration matches a real
# machine: the Liberation/DejaVu/Noto core, common web fonts (Microsoft corefonts:
# Arial/Times/Verdana...), emoji + CJK coverage. fc-cache rebuilds the font index.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list && \
    # MS corefonts require accepting the EULA non-interactively.
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
        | debconf-set-selections && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        google-chrome-stable \
        fonts-liberation \
        fonts-dejavu-core \
        fonts-noto-core \
        fonts-noto-color-emoji \
        fonts-noto-cjk \
        fonts-freefont-ttf \
        ttf-mscorefonts-installer && \
    fc-cache -f && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# --- Desktop assist (FR-CUA, docs/spec/computer-use.md) ----------------------
# Background desktop control (file-upload dialogs / OS windows the browser can't
# reach) needs (a) the Linux DISPLAY STACK the driver reads — the AT-SPI
# accessibility bus on the X11 desktop this image already runs — and (b) the
# desktop-control DRIVER binary itself. Same rule as Chrome/TeX/LibreOffice: the
# engine detects the driver via PATH and silently degrades to the no-op backend
# (rendering the front-door control locked, FR-CUA-9/12) unless the binary is
# BAKED INTO THIS SANDBOX IMAGE — not just present on a dev box.
#
# The AT-SPI bus + xdotool/wmctrl helpers below are the display-stack dependency
# and are safe to bake now (small, no behavior change). The driver binary is NOT
# yet vendored (license review pending, spec §9/§10), so it is installed only when
# CUA_DRIVER_URL is provided at build time; absent that, the surface stays dormant
# and the engine's health preflight reports the driver missing (a deploy signal).
ARG CUA_DRIVER_URL=""
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        at-spi2-core \
        libatk-adaptor \
        xdotool \
        wmctrl && \
    if [ -n "${CUA_DRIVER_URL}" ]; then \
        curl -fsSL "${CUA_DRIVER_URL}" -o /usr/local/bin/cua-driver && \
        chmod 0755 /usr/local/bin/cua-driver ; \
    else \
        echo "desktop-assist driver not baked (CUA_DRIVER_URL unset) — surface stays dormant (FR-CUA-9)" ; \
    fi && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Driver anonymous telemetry OFF by default (engine config CUA_TELEMETRY=false).
ENV CUA_DRIVER_RS_TELEMETRY_ENABLED=0

EXPOSE 3000
