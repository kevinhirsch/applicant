# Applicant — CUSTOM full-GNOME takeover desktop (FR-SANDBOX-2/3, FR-PREFILL-5).
#
# WHY THIS EXISTS
# ---------------
# The configurable takeover desktop (TAKEOVER_DESKTOP) ships Cinnamon and Xfce via
# ready-made LinuxServer *webtop* images (lscr.io/linuxserver/webtop:ubuntu-cinnamon
# and :ubuntu-xfce). Full GNOME, however, does NOT ship as a prebuilt webtop: GNOME
# assumes Wayland + a full systemd session, which the streaming webtop images do not
# provide. So `TAKEOVER_DESKTOP=gnome` resolves to THIS local custom image
# (applicant/webtop-gnome:latest): Ubuntu + ubuntu-desktop/GNOME forced onto **Xorg
# (X11)** + a web streamer (KasmVNC), so the desktop can be streamed to the browser
# and automated.
#
# TRADE-OFF (documented): this image is HEAVIER than the Cinnamon/Xfce webtops (the
# full GNOME stack pulls a large dependency tree) and GNOME-on-Xorg-without-systemd
# is a less-trodden path than the LinuxServer-maintained DEs. Prefer Cinnamon (the
# default) or Xfce unless GNOME is specifically required.
#
# X11 RATIONALE (all three DEs): X11 (not Wayland) is used because the web streaming
# layer + the automation/handoff path are X11-native; Wayland would complicate both.
#
# BUILD:   docker build -t applicant/webtop-gnome:latest docker/webtop-gnome
# RUN:     selected automatically when TAKEOVER_DESKTOP=gnome (see config.py table).

# Base on the LinuxServer KasmVNC runtime so we inherit the browser web-stream layer
# (KasmVNC + the /kasmweb entrypoint) and only need to add the GNOME session on X11.
#
# Pinned by immutable DIGEST, not the mutable `:ubuntu-kde` tag (#160, #374): the
# LinuxServer rolling tag is rebuilt frequently, so an unpinned build is a moving
# supply-chain target. Tag kept in the comment for readability; bump the digest
# deliberately. Resolve a new one with:
#   docker buildx imagetools inspect lscr.io/linuxserver/webtop:ubuntu-kde
# lscr.io/linuxserver/webtop:ubuntu-kde
FROM lscr.io/linuxserver/webtop:ubuntu-kde@sha256:32fb57cb5a97314faf690935b1b973562982afb5463a35764e3a57e7bcd40476

LABEL org.opencontainers.image.title="applicant-webtop-gnome" \
      org.opencontainers.image.description="Ubuntu + full GNOME on Xorg/X11, web-streamed (KasmVNC) takeover desktop" \
      org.opencontainers.image.source="https://github.com/kevinhirsch/applicant"

ENV DEBIAN_FRONTEND=noninteractive \
    TITLE="Applicant — GNOME takeover desktop"

# Install full GNOME. ubuntu-desktop is the canonical full GNOME meta-package; we add
# gnome-session-flashback as a guaranteed Xorg (X11) session entry so GNOME runs under
# the X server the web streamer exposes (NOT Wayland). xterm/dbus-x11 round out a
# usable, automatable X11 session. We skip recommends to keep the image as lean as a
# full-GNOME image can be (it is still heavier than the Cinnamon/Xfce webtops).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ubuntu-desktop-minimal \
        gnome-session \
        gnome-session-flashback \
        gnome-shell \
        gnome-terminal \
        dbus-x11 \
        xterm \
        x11-xserver-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install REAL Google Chrome (FR-STEALTH-1) so the human takes over the SAME real
# Chrome the engine drives — genuine Chrome TLS/JA3 + correct Sec-CH-UA client hints
# (the foundation of the coherent real-Linux/Chrome identity; not Chromium, not
# headless). Plus a realistic desktop FONT SET so font enumeration looks like a real
# machine, not a bare container. fc-cache rebuilds the font index.
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

# Force the X11 (Xorg) GNOME session for the streamed desktop. The LinuxServer image
# starts an Xorg server and runs the DE start script on it; we point that at a GNOME
# session under X11. (Wayland is explicitly avoided — see X11 RATIONALE above.)
ENV GNOME_SHELL_SESSION_MODE=ubuntu \
    XDG_SESSION_TYPE=x11 \
    XDG_CURRENT_DESKTOP=GNOME

# The LinuxServer base sources /defaults/startwm.sh to launch the DE on the X server.
# Override it to start GNOME on X11 (gnome-session). The web streamer (KasmVNC) and the
# tokenized one-click access are provided by the base image's entrypoint unchanged.
RUN mkdir -p /defaults && \
    printf '%s\n' \
        '#!/bin/bash' \
        '# Start full GNOME on Xorg (X11) for the streamed takeover desktop.' \
        'export XDG_SESSION_TYPE=x11' \
        'export GNOME_SHELL_SESSION_MODE=ubuntu' \
        'dbus-launch --exit-with-session gnome-session --session=gnome-flashback-metacity || \' \
        '    dbus-launch --exit-with-session gnome-session' \
        > /defaults/startwm.sh && \
    chmod +x /defaults/startwm.sh

# Desktop images need a roomy /dev/shm (browser + GNOME); the compose service sets
# shm_size and the security bits — see docker/docker-compose.prod.yml.
EXPOSE 3000
