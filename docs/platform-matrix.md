# Platform matrix (P3-7)

This page answers the operator question P3-2 deferred: **what CPU architecture and
host OS does the production stack actually run on**, and what does a Windows/WSL2
operator need to know that a Linux operator doesn't. Every claim below is grounded
in what `docker/Dockerfile` and `scripts/proxmox-deploy.sh` actually download —
not a guess about upstream projects' roadmaps.

See also: [`docs/requirements-and-model-matrix.md`](requirements-and-model-matrix.md)
(§5 "Platform / OS constraints" points here), [`docs/overview.md`](overview.md)
(doc index + deploy topology), and [`docs/reverse-proxy-https.md`](reverse-proxy-https.md)
(exposing the stack once it's up).

---

## 1. Supported CPU architecture: **amd64 (x86_64) only**

The production engine image (`docker/Dockerfile`) hard-codes amd64 in three
separate places, so this isn't a soft preference — it's baked into the build:

1. **Real Google Chrome** (the `chromium` fallback browser engine, the Proxmox
   Windows CDP takeover backend, and the local `chromium`-engine sandbox all
   depend on it): the Dockerfile downloads

   ```
   https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
   ```

   — the architecture is literally in the filename. Google does not currently
   publish an official arm64 Linux `.deb`/`.rpm` for Chrome (there has been
   public discussion of an eventual arm64 Linux release, but as of this
   writing it is not a package this Dockerfile — or any automated build in
   this repo — can pull and verify). Installing that `.deb` on an arm64 base
   image fails outright (wrong package architecture), so this alone rules out
   an arm64 image today.

2. **Camoufox** (the *default* `BROWSER_ENGINE=camoufox`, used for ALL
   outbound pre-fill/automation traffic unless `chromium` is selected): the
   Dockerfile runs `camoufox fetch` to download a prebuilt browser bundle
   matching the build host's architecture. Camoufox's upstream build tooling
   targets arm64 as one of several build targets, but nothing in this repo's
   CI or deploy path has ever fetched, launched, or exercised that bundle on
   arm64 — CI does not build images (`docker compose config` only validates
   syntax), so an arm64 `camoufox fetch` here would be untested on first
   contact with a real arm64 host. Treating it as arm64-ready would violate
   the H-series honesty invariant (don't render an unverified thing as
   verified).

3. **patchright's matched Chromium** (the `chromium` engine's driver-matched
   browser bundle, `patchright install chromium`): downloads whatever revision
   matches the pinned `patchright` version for the build host's architecture.
   Even where an arm64 build exists upstream, it inherits the same "never
   exercised in this repo" caveat as Camoufox above, and is moot anyway once
   real Chrome (item 1) is unavailable on that arch, since the `chromium`
   engine's default channel is `chrome`.

**Not blockers, for the record:** the TeX toolchain (`texlive-xetex`,
`texlive-luatex`, etc.) and `libreoffice-writer` are both available as
native arm64 Debian packages — the resume-render pipeline is not what stops
arm64. It's specifically the browser/automation layer.

**`scripts/proxmox-deploy.sh`** independently hard-codes an amd64 Ubuntu cloud
image (`ubuntu-24.04-server-cloudimg-**amd64**.img`), so the Proxmox one-liner
path is also amd64-only, consistently with the container image it builds.

**Conclusion — documented, not built.** Per this story's DoD ("amd64-only
constraint documented OR multi-arch built"), the honest choice here is to
**document the constraint** rather than wire unverified `--platform
linux/amd64,linux/arm64` buildx targets: two of the three baked binaries
(real Chrome, and this repo's own untested Camoufox arm64 fetch) would make
an advertised multi-arch build either broken (Chrome) or silently unverified
(Camoufox) on arm64 — exactly the silent-degrade `docker/Dockerfile` already
goes out of its way to avoid for every other dependency (`shutil.which()`
degrade comments throughout). If Google ships a verified, installable arm64
Chrome `.deb`/`.rpm` and this repo actually exercises `camoufox fetch` +
patchright's chromium install on a real arm64 build, that closes the gap for
a future revision of this story — worth re-checking periodically, but not
assumed here.

**Practical guidance for operators on arm64 hosts** (Apple Silicon Docker
Desktop, AWS Graviton, Raspberry Pi/other arm64 SBCs, Windows-on-ARM):
run the stack on an amd64 host or VM instead of attempting to build the
`api` image natively. Docker Desktop's emulated amd64 support (QEMU/Rosetta)
can technically run an amd64 image on Apple Silicon, but that path is slow
for a texlive/Chrome/Camoufox-sized image and is **not verified by this
project** — treat it as unsupported, not as a documented fallback.

---

## 2. Docker-on-WSL2 (Windows) — setup path

**Status: procedure documented, not observed on a real WSL2 box in this
session's environment** (this container has no WSL host to actually run the
steps against) — labelled the same honest way as P1-2/P3-1's host-gated
items: the steps below are the concrete, intended path; they have not yet
been walked end-to-end on physical Windows hardware and that gap is not
closed by this story.

### 2.1 Prerequisites

- Windows 10 (build 19041+) or Windows 11, with virtualization enabled in
  firmware (most machines: on by default).
- An **x86_64/amd64 Windows host CPU**. WSL2 on an ARM-based Windows device
  (e.g. a Snapdragon laptop) runs an **arm64** Linux kernel/userspace, and
  Docker would need to emulate amd64 inside that arm64 VM to run this
  project's amd64-only image — the same unverified/slow emulation path as
  §1's Apple Silicon note. WSL2 on a standard x86_64 Windows PC needs no
  emulation at all: it's a real amd64 Linux VM, so the production image runs
  natively.

### 2.2 Setup steps

1. Install WSL2 + a Linux distro (Ubuntu recommended, matching the Proxmox
   path's own distro choice):
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
   Reboot when prompted; set a Unix username/password on first launch.
2. Install Docker: either
   - **Docker Desktop for Windows**, with *Settings → Resources → WSL
     Integration* enabled for the `Ubuntu-24.04` distro (simplest — Docker
     Desktop supplies the daemon; no extra steps inside the distro), or
   - **Docker Engine installed directly inside the WSL2 distro** (no Docker
     Desktop), following the same `get.docker.com` path
     `scripts/install.sh` already uses for bare Linux hosts.
3. Raise WSL2's resource ceiling to match this project's recommended host
   spec (`docs/requirements-and-model-matrix.md` §1.1: 4 vCPU / 8 GB RAM /
   40 GB disk). WSL2 defaults to roughly half the host's RAM and all
   logical CPUs, which is usually enough, but a resource-constrained laptop
   should still create/edit `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=8GB
   processors=4
   ```
   then `wsl --shutdown` and reopen the distro for it to take effect.
4. Clone the repo **inside the Linux filesystem** (e.g. `~/applicant`, i.e.
   under `/home/<user>/...` as seen from WSL2) — **not** under `/mnt/c/...`.
   Bind-mounted named volumes and the repo checkout both suffer materially
   worse I/O throughput when they live on the Windows-side 9p/DrvFs mount;
   the texlive/Camoufox/Chrome image layers are large enough (~2 GB, per
   `docker/Dockerfile`'s own sizing comment) that this is not a minor
   difference during `docker compose up --build`.
5. From inside the WSL2 distro's shell, run the same install path as any
   Linux host:
   ```bash
   git clone <repo-url> ~/applicant && cd ~/applicant
   bash scripts/install.sh --apply
   ```
6. Reach the UI from Windows at `http://localhost:<APP_PORT>` — Docker
   Desktop's WSL2 backend and a bare Docker-Engine-in-WSL2 install both
   forward `localhost` from Windows into the distro automatically (WSL2's
   built-in `localhost` relay), so no manual port-forwarding is normally
   required.

### 2.3 Known WSL2-specific gotchas

- **`.wslconfig` memory ceiling** (§2.2 step 3) is the single most common
  cause of an OOM-killed `api` container on WSL2 — check this first if the
  stack builds but the `api` service restarts under load.
- **Repo location** (§2.2 step 4): a checkout under `/mnt/c/...` will still
  work, just slowly, especially the first `--build` (the texlive layer
  alone is ~700 MB per the Dockerfile's comment) and any bind-mounted dev
  workflow. Prefer the native Linux filesystem path.
- **Docker Desktop WSL2 integration must be toggled on per-distro** — a
  fresh Docker Desktop install does not automatically enable it for a newly
  installed distro; `docker` inside the distro will otherwise report "command
  not found" or fail to reach the daemon.
- **Xvfb/headful Camoufox rendering** (the browser renders headful on a
  virtual display *inside* the container per the Dockerfile's comment) needs
  no host GPU or WSLg — it's a software virtual display entirely inside the
  Linux container, identical to any other Linux Docker host; this is not a
  WSL2-specific risk.
- **Windows Defender / antivirus** scanning the WSL2 virtual disk file
  (`ext4.vhdx`) can measurably slow container I/O; excluding
  `%LocalAppData%\Docker\wsl\data` (Docker Desktop) or the distro's own
  `.vhdx` (Docker-Engine-in-WSL2) from real-time scanning is a common fix
  reported in the wild, not something this project can configure for you.
- **The `takeover-desktop` profile and the Proxmox Windows CDP sandbox
  backend are unrelated to this WSL2 path** — those are a separate
  streamed-desktop container and a separate real Windows VM (respectively),
  not something WSL2 provides or is meant to replace. Don't conflate "I'm
  running Applicant from inside WSL2" with "I have the takeover/Windows
  sandbox path" — they're orthogonal deploy choices.
- **ARM-based Windows hosts**: see §2.1 — expect emulation, unverified, not
  recommended.

---

## 3. Other host-OS notes

- **Native Linux** (any distro with Docker Engine + Compose v2 on an
  amd64 CPU) is the primary, most-exercised target — it's what
  `scripts/install.sh`/`scripts/proxmox-deploy.sh` assume and what CI's
  `docker compose config` validates against.
- **macOS**: Docker Desktop for Mac runs Linux in a VM either way.
  - Intel Macs: native amd64, no caveats beyond the general host-spec
    numbers in `docs/requirements-and-model-matrix.md`.
  - Apple Silicon (M-series, arm64): same emulation caveat as §1/§2.1 —
    Docker Desktop *can* run an amd64 image under emulation, but this
    project has not verified that path, so treat it as unsupported for
    anything beyond casual/dev inspection, not a documented production
    target.
- **Proxmox** (`scripts/proxmox-deploy.sh`): provisions an amd64 Ubuntu
  24.04 cloud image directly — matches the amd64-only container image with
  no cross-arch step at all, and remains the most-proven deploy path
  (referenced throughout `docs/requirements-and-model-matrix.md`'s sizing
  numbers).

---

## Summary for an operator

1. **CPU:** amd64/x86_64 only, today. Don't attempt an arm64 build; run on
   an amd64 host or VM instead.
2. **Windows:** WSL2 on a standard (x86_64) Windows PC is a first-class,
   documented path (§2) — un-emulated, same amd64 image as native Linux.
   ARM-based Windows devices inherit the same emulation caveat as
   Apple Silicon.
3. **macOS:** Intel is native; Apple Silicon works only via unverified
   Docker Desktop emulation.
4. **Status honesty:** the WSL2 steps above are procedure, not a live
   pass — nobody has run them against a physical WSL2 box in this project's
   CI or this session's sandbox (which has no WSL host at all). Flip this
   note once someone does and records the result here.
