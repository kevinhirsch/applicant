# Integration Lane runner setup

The **Integration Lane** (`.github/workflows/ci-integration.yml`) runs Applicant's
real-dependency test suite (`@pytest.mark.integration`) against a live Postgres, a
real TeX toolchain, LibreOffice, a real browser stack, and (optionally) live job
boards. It runs on a **self-hosted GitHub Actions runner** and — unlike the per-PR
`ci.yml` lane — it needs heavy system dependencies that must be **pre-baked on the
runner host**, because the runner has no passwordless `sudo` inside a job. The lane
verifies these deps and fails fast with guidance if any is missing; it never installs
them at run time (that is also the speedup — no per-run `apt`).

This page is the runner-onboarding procedure: what the lane needs, the one-command
setup, how the runner user is detected, the manual fallback, and a verification
checklist.

## What the lane needs on the host

| Prerequisite | Why | Provided by |
|---|---|---|
| **Docker reachable without `sudo`** | The Postgres service container and the destroy/install drills call `docker` directly; the runner user must be in the `docker` group. | Docker Engine + `usermod -aG docker <runner-user>` (the "K9" fix) |
| **TeX (lualatex/xelatex + moderncv/fontspec/fontawesome5 + fonts)** | FR-RESUME-3/4 real résumé render (P2-10 LaTeX leg). | `texlive-latex-extra texlive-fonts-recommended texlive-fonts-extra texlive-luatex texlive-xetex fonts-open-sans fonts-font-awesome` |
| **LibreOffice Writer (`soffice`)** | P2-10 docx-fallback render path (`soffice --convert-to pdf`) — the same package `docker/Dockerfile` bakes into the deploy image. | `libreoffice-writer` |
| **Xvfb (`xvfb-run`)** | FR-PREFILL / FR-STEALTH browser tests need a virtual X display. | `xvfb` |
| **Warm TeX font cache** (optional, recommended) | The first `lualatex`/`xelatex` compile builds the luaotfload font database, which alone can exceed the per-test 60s timeout and flake the timed render tests. Priming it once keeps those tests warm. | `luaotfload-tool --update` (also warmed once per lane run by a workflow step) |

## One-command setup

On the runner host, as an admin:

```bash
sudo bash scripts/setup-integration-runner.sh
```

The script is **idempotent** — safe to re-run any time. It:

1. Requires root (re-run with `sudo` if not).
2. Detects the runner's systemd service and its user, adds that user to the
   `docker` group, and restarts the runner service so the change takes effect.
3. Installs all the system packages above via `apt-get`, echoing which lane
   prerequisite each package group satisfies.
4. Warms the TeX font cache once (best-effort).
5. Prints a verification block (Docker reachable as the runner user;
   `xelatex`/`lualatex`/`soffice`/`xvfb-run` found or missing).

## How the runner user is detected

Docker-without-`sudo` requires the runner's **service user** to be in the `docker`
group. The script finds it robustly:

1. Locate the runner systemd unit:
   `systemctl list-units --type=service --all 'actions.runner.*'`
   (falling back to `systemctl list-unit-files 'actions.runner.*.service'`), taking
   the first match into `SVC`.
2. Read its user: `systemctl show -p User --value "$SVC"`.
3. If that is empty, fall back to the owner of the running listener process:
   `ps -o user= -C Runner.Listener | head -1`.

On the reference host (`ubnthost01`) this user is `actions`.

Group membership only takes effect on the **next start** of the runner service, so
the script restarts the service (`systemctl restart "$SVC"`) after the `usermod`.
If the runner is not installed as a systemd service, the script warns and you must
restart the runner (or reboot) yourself so the group change is picked up.

## Manual fallback

If you prefer to provision by hand (or the runner is not up yet so the script can't
detect its user), run the equivalent commands as root:

```bash
# 1. Detect the runner service + user
SVC="$(systemctl list-units --type=service --all --no-legend 'actions.runner.*' \
        | awk '{print $1}' | head -1)"
RUNNER_USER="$(systemctl show -p User --value "$SVC")"
# fallback if the unit declared no User=:
[ -z "$RUNNER_USER" ] && RUNNER_USER="$(ps -o user= -C Runner.Listener | head -1)"

# 2. Docker without sudo (takes effect on the next runner start)
sudo usermod -aG docker "$RUNNER_USER"
sudo systemctl restart "$SVC"

# 3. System deps
sudo apt-get update
sudo apt-get install -y \
  texlive-latex-extra texlive-fonts-recommended texlive-fonts-extra \
  texlive-luatex texlive-xetex fonts-open-sans fonts-font-awesome \
  libreoffice-writer xvfb

# 4. Warm the TeX font cache (best-effort)
luaotfload-tool --update || true
```

## Verification checklist

After setup, confirm the host is ready:

- [ ] `sudo -u <runner-user> docker version` succeeds (runner user reaches the
      Docker socket — may need one more runner-service restart if you just added
      the group).
- [ ] `command -v xelatex lualatex` both resolve (TeX engines present).
- [ ] `command -v soffice` resolves (LibreOffice Writer present).
- [ ] `command -v xvfb-run` resolves (virtual X display available).
- [ ] The GitHub Actions runner is registered, started, and carries the
      `self-hosted` label.

Then trigger the lane via **workflow_dispatch** (Actions → *Integration Lane*), or
let the weekly Sunday 02:00 UTC schedule run it.

## Hosted fallback

If no self-hosted runner is available, the lane can be flipped to a GitHub-hosted
runner (which permits `sudo apt-get`): see the `HOSTED FALLBACK` note near the top
of `.github/workflows/ci-integration.yml`.
