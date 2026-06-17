# Applicant — CUSTOM Pantheon takeover desktop (FR-SANDBOX-2/3, FR-PREFILL-5).
#
# WHY THIS EXISTS
# ---------------
# The configurable takeover desktop (TAKEOVER_DESKTOP) ships Cinnamon and Xfce via
# ready-made LinuxServer *webtop* images. Pantheon — elementary OS's desktop — does
# NOT ship as a prebuilt webtop, and elementary OS itself has no maintained
# container/cloud base. Per the project decision we keep a SINGLE Ubuntu base and
# layer Pantheon on top (cosmetic-only): `TAKEOVER_DESKTOP=pantheon` resolves to THIS
# local custom image (applicant/webtop-pantheon:latest): Ubuntu + Pantheon's Gala
# window manager + Wingpanel + Plank on **Xorg (X11)** + a web streamer (KasmVNC).
#
# TRADE-OFF (documented): this is Pantheon-on-Ubuntu, not elementary OS, so it is NOT
# pixel-pure elementary (elementary's stylesheet/AppCenter assume elementary OS) — it
# renders the Pantheon shell, fully usable, but ~90% of the authentic look. The OS
# behind the browser is not fingerprinted by target sites, so this is purely the
# human-takeover aesthetic, with zero stealth/functional impact (Chrome + the
# residential IP are what matter for FR-STEALTH-1). Prefer Cinnamon (default) or Xfce
# unless the Pantheon look is specifically wanted.
#
# X11 RATIONALE (all DEs): X11 (not Wayland) is used because the web streaming layer +
# the automation/handoff path are X11-native; Wayland would complicate both.
#
# BUILD:   docker build -t applicant/webtop-pantheon:latest docker/webtop-pantheon
# RUN:     selected automatically when TAKEOVER_DESKTOP=pantheon (see config.py table).

# Base on the LinuxServer KasmVNC runtime so we inherit the browser web-stream layer
# (KasmVNC + the /kasmweb entrypoint) and only need to add the Pantheon shell on X11.
FROM lscr.io/linuxserver/webtop:ubuntu-kde

LABEL org.opencontainers.image.title="applicant-webtop-pantheon" \
      org.opencontainers.image.description="Ubuntu + Pantheon (Gala/Wingpanel/Plank) on Xorg/X11, web-streamed (KasmVNC) takeover desktop" \
      org.opencontainers.image.source="https://github.com/kevinhirsch/applicant"

ENV DEBIAN_FRONTEND=noninteractive \
    TITLE="Applicant — Pantheon takeover desktop"

# Install the Pantheon shell components from the Ubuntu archive (universe): Gala (the
# window manager), Wingpanel (top panel), Plank (dock), and Switchboard (settings).
# These provide the Pantheon desktop experience on Ubuntu without requiring elementary
# OS. (For a more complete/current Pantheon you may enable ppa:elementary-os/stable
# for a MATCHING Ubuntu release — left out by default to avoid PPA/release-mismatch
# breakage on whatever Ubuntu the webtop base tracks.) dbus-x11/xterm round out a
# usable, automatable X11 session.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gala \
        wingpanel \
        plank \
        switchboard \
        pantheon-default-settings \
        elementary-icon-theme \
        dbus-x11 \
        xterm \
        x11-xserver-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install REAL Google Chrome (FR-STEALTH-1) so the human takes over the SAME real
# Chrome the engine drives — genuine Chrome TLS/JA3 + correct Sec-CH-UA client hints
# (the coherent real-Linux/Chrome identity; not Chromium, not headless). Plus a
# realistic desktop FONT SET so font enumeration looks like a real machine, not a bare
# container. fc-cache rebuilds the font index.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
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

# Run the Pantheon shell on Xorg (X11) for the streamed desktop. (Wayland is avoided —
# see X11 RATIONALE above.)
ENV XDG_SESSION_TYPE=x11 \
    XDG_CURRENT_DESKTOP=Pantheon

# The LinuxServer base sources /defaults/startwm.sh to launch the DE on the X server.
# Override it to start Pantheon on X11: Gala (WM) with Wingpanel (panel) + Plank (dock)
# as the session. The web streamer (KasmVNC) and the tokenized one-click access are
# provided by the base image's entrypoint unchanged.
RUN mkdir -p /defaults && \
    printf '%s\n' \
        '#!/bin/bash' \
        '# Start the Pantheon shell on Xorg (X11) for the streamed takeover desktop.' \
        'export XDG_SESSION_TYPE=x11' \
        'export XDG_CURRENT_DESKTOP=Pantheon' \
        'eval "$(dbus-launch --sh-syntax)"' \
        'plank &' \
        'wingpanel &' \
        'exec gala' \
        > /defaults/startwm.sh && \
    chmod +x /defaults/startwm.sh

# Desktop images need a roomy /dev/shm (browser + DE); the compose service sets
# shm_size and the security bits — see docker/docker-compose.prod.yml.
EXPOSE 3000
