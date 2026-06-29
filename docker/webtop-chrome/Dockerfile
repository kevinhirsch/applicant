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
# Google's signing key is pinned by FINGERPRINT, not "trust whatever the URL
# returns" (#164): download the key, dearmor it, and assert its fingerprint matches
# Google's published Linux Package Signing key before writing it into the apt
# keyring — a swapped/MITM'd key fails the build instead of silently signing a
# malicious repo. The apt source uses https (not http) so the index/.deb transport
# is also authenticated end to end.
ARG GOOGLE_SIGNING_KEY_FPR="EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub -o /tmp/google-key.pub && \
    gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg /tmp/google-key.pub && \
    fpr="$(gpg --show-keys --with-colons --with-fingerprint /tmp/google-key.pub \
        | awk -F: '/^fpr:/ {print $10; exit}')" && \
    if [ "$fpr" != "${GOOGLE_SIGNING_KEY_FPR}" ]; then \
        echo "ERROR: Google signing key fingerprint mismatch: got '$fpr', expected '${GOOGLE_SIGNING_KEY_FPR}'" >&2; \
        exit 1; \
    fi && \
    rm -f /tmp/google-key.pub && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
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
# The AT-SPI bus + xdotool/wmctrl helpers below are the display-stack dependency and
# are always baked (small, no behavior change). The driver itself (TryCUA cua-driver,
# MIT — license confirmed, see NOTICE) is opt-in at build time so the default image
# build needs no network fetch; absent it, the engine's health preflight reports the
# driver missing and the front-door control renders LOCKED (FR-CUA-9/12) — never a
# surface that silently does nothing. Two bake options:
#   * INSTALL_CUA_DRIVER=1 → run the official upstream installer (fetches the platform
#     binary + GeoIP), then put it on PATH.
#   * CUA_DRIVER_URL=<url>  → drop a prebuilt binary deterministically (air-gapped /
#     pinned mirrors). Takes precedence when set.
# To light up desktop assist at runtime, also set the engine COMPUTER_USE_BACKEND=cua.
ARG CUA_DRIVER_URL=""
ARG INSTALL_CUA_DRIVER="0"
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        at-spi2-core \
        libatk-adaptor \
        xdotool \
        wmctrl && \
    if [ -n "${CUA_DRIVER_URL}" ]; then \
        curl -fsSL "${CUA_DRIVER_URL}" -o /usr/local/bin/cua-driver && \
        chmod 0755 /usr/local/bin/cua-driver ; \
    elif [ "${INSTALL_CUA_DRIVER}" = "1" ]; then \
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)" && \
        ( command -v cua-driver >/dev/null 2>&1 || \
          for p in /root/.local/bin/cua-driver "$HOME/.local/bin/cua-driver" /root/.cua-driver/bin/cua-driver; do \
              [ -x "$p" ] && ln -sf "$p" /usr/local/bin/cua-driver && break ; \
          done ) ; \
    else \
        echo "desktop-assist driver not baked (set INSTALL_CUA_DRIVER=1 or CUA_DRIVER_URL) — surface stays locked (FR-CUA-9)" ; \
    fi && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Driver anonymous telemetry OFF by default (engine config CUA_TELEMETRY=false).
ENV CUA_DRIVER_RS_TELEMETRY_ENABLED=0

EXPOSE 3000
