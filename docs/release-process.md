# Release process (P3-5 — Release engineering)

The single answer to "how do we cut a release, and what does an operator actually get." Companion
files: `VERSION` (source of truth), `CHANGELOG.md` (Keep a Changelog), `.github/workflows/release.yml`
(build/sign/publish), `scripts/ci/check_release_version.py` (consistency gate).

## 1. Versioning scheme

Semantic Versioning (`MAJOR.MINOR.PATCH`, optional `-prerelease` suffix — e.g. `1.4.0`,
`1.5.0-beta.1`, `1.5.0-rc.2`):

- **MAJOR** — a break in the deploy contract (env vars, compose service names/ports, a required data
  migration) or the removal of a shipped capability.
- **MINOR** — a new user-facing capability, reachable end-to-end through the white-labeled front-door
  (per this repo's reachability principle — an engine-only feature is not a MINOR bump on its own).
- **PATCH** — a fix, hardening pass, or internal change with no new front-door capability.

## 2. The three copies that must agree

The current version is recorded in three places, and they must always match exactly:

| File | What it's for |
|---|---|
| `VERSION` (repo root) | The single source of truth. The release workflow reads this and refuses to publish if it doesn't match the tag being released. |
| `pyproject.toml` → `[project].version` | What `uv`/pip see as the installed package version. |
| `src/applicant/version.py` → `__version__` | What the *running* app reports — `FastAPI(..., version=__version__)`, `/healthz`, and (new in this story) `GET /api/health/capabilities` → the front-door proxy → the Settings → System "Engine health" panel, which now shows "Engine vX.Y.Z". |

`scripts/ci/check_release_version.py` enforces all three agree, that `VERSION` is valid semver, and
that `CHANGELOG.md` has a `## [X.Y.Z]` heading for the current version. It's wrapped as a hermetic
pytest module (`tests/unit/test_release_engineering.py`) so a mismatch fails the default (non-integration)
test suite — not just an extra CI step someone can forget to add. Run it directly with:

```bash
python3 scripts/ci/check_release_version.py
```

## 3. Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): an `## [Unreleased]`
section at the top collects changes as they land on `main`, and cutting a release means renaming that
section's heading to `## [X.Y.Z] - YYYY-MM-DD` and opening a fresh empty `## [Unreleased]` above it.

## 4. Cutting a release (the steps, in order)

1. On `main`, bump the version in lockstep:
   - `VERSION` → the new version string (no `v` prefix, no trailing content but a newline).
   - `pyproject.toml` → `[project].version`.
   - `src/applicant/version.py` → `__version__`.
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` (summarizing what
   actually shipped) and add a fresh empty `## [Unreleased]` above it.
3. Run `python3 scripts/ci/check_release_version.py` locally (or just let CI's hermetic suite catch
   it — `tests/unit/test_release_engineering.py` runs it on every PR).
4. Open the version-bump PR, get it merged (squash-merged, per this repo's PR convention).
5. Tag the merged commit on `main` and push the tag:
   ```bash
   git tag vX.Y.Z            # stable, e.g. v1.4.0
   # or: git tag vX.Y.Z-beta.1   # beta/pre-release, e.g. v1.5.0-beta.1
   git push origin vX.Y.Z
   ```
6. Pushing the tag fires `.github/workflows/release.yml`, which builds, pushes, and signs both
   shipped images (see §5/§6 below). Watch the Actions run; its Job Summary lists the exact image
   refs published.

## 5. Stable vs beta channels

The tag text is the single source of truth for which channel an image lands in — decided by one
`if` in `.github/workflows/release.yml`'s "Resolve the release tag, version, and channel" step:

- **No `-suffix`** (`vX.Y.Z`, e.g. `v1.4.0`) → **stable** channel.
- **Any `-suffix`** (`vX.Y.Z-beta.N`, `vX.Y.Z-rc.N`, anything) → **beta** channel.

Every release publishes two tags per image: the exact immutable version (`:1.4.0`) and the moving
channel tag (`:stable` or `:beta`). **Only a stable release also moves `:latest`** — a beta build
never touches `:latest`, so nobody lands on a pre-release image by pulling the default tag.

Published images (GHCR, once the one-time setup in §6 is done and a real tag has been pushed):

```text
ghcr.io/<owner>/applicant-api:<version>   ghcr.io/<owner>/applicant-api:stable|beta   ghcr.io/<owner>/applicant-api:latest (stable only)
ghcr.io/<owner>/applicant-ui:<version>    ghcr.io/<owner>/applicant-ui:stable|beta    ghcr.io/<owner>/applicant-ui:latest (stable only)
```

### How `scripts/update.sh` picks a channel today

`docker/docker-compose.prod.yml` builds both images **locally from source** (`pull_policy: build`) —
it does not pull from GHCR. `scripts/update.sh` syncs the source checkout before that local build, so
the channel an operator tracks is really "which git ref does the source sync land on":

- `APPLICANT_CHANNEL=stable` (the default) syncs `APPLICANT_BRANCH` (default `main`) — the branch a
  stable version tag is always cut from.
- `APPLICANT_CHANNEL=beta` syncs a `beta` branch by default (maintain one if you want a rolling
  beta-tester deploy target; otherwise pin an exact pre-release tag instead — see below).
- Setting `APPLICANT_BRANCH` directly to an exact release tag (e.g. `APPLICANT_BRANCH=v1.4.0` or
  `v1.5.0-beta.1`) pins the update to that **specific released commit** instead of a moving branch —
  `update.sh` fetches and resets to the tag ref (not `origin/<branch>`, since tags aren't
  remote-tracking branches). This is the recommended way to test an exact beta build without
  maintaining a long-lived `beta` branch.

The GHCR images are for anyone who wants to run the published, signed images directly (e.g. a bare
`docker run` or a separate compose file pointed at `ghcr.io/...`) instead of the source-build flow
`scripts/update.sh` automates. Fully switching the shipped compose stack to pull prebuilt GHCR images
by default is a larger, separate change (deploy-model shift, not merely release tooling) and is not
part of this story.

## 6. One-time setup a maintainer must do (before the first real tag push)

This workflow was authored and syntax-checked in a development environment with **no GHCR push
access, no Sigstore/cosign OIDC context, and no ability to actually execute a GitHub Actions run**.
It is syntactically valid and correctly gated (see the hermetic pins in
`tests/unit/test_release_engineering.py`), but **it has not yet been exercised end-to-end against
real credentials** — no image has actually been pushed or signed by it yet. Before relying on it:

1. **GHCR write access.** The workflow authenticates with the automatic `GITHUB_TOKEN` (no new
   secret needed) and requests `packages: write` — confirm the repo's Settings → Actions → General →
   "Workflow permissions" allows this (or that the org's package-creation policy allows Actions to
   publish new `ghcr.io/<owner>/applicant-*` packages the first time).
2. **Package visibility.** GHCR packages default to **private** on first publish tied to a private
   repo. If this is meant to be a public distribution channel, set the packages
   (`applicant-api`, `applicant-ui`) to public in the org/user Packages settings after the first push.
3. **Cosign keyless signing needs no key setup** — it uses the job's own OIDC token against
   Sigstore's public Fulcio CA (`id-token: write`, already requested in the workflow). Nothing to
   provision, but the FIRST run is the first real proof it works — watch it.
4. **First test run:** push a throwaway pre-release tag (e.g. `v0.1.0-rc.1`) or use the
   `workflow_dispatch` manual trigger with an existing tag, confirm the Actions run goes green, then
   verify the image is both pullable and correctly signed:
   ```bash
   cosign verify \
     --certificate-identity-regexp 'https://github.com/<owner>/<repo>/.*' \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     ghcr.io/<owner>/applicant-api:0.1.0-rc.1
   ```
5. Only after that first green, verified run should this doc's "signed images on GHCR" claim be
   treated as proven rather than aspirational — flip the honest gap note in
   `docs/backlog/road-to-market.md`'s P3-5 entry once it happens.

## 7. Reachability of the version number

Per this repo's reachability principle, the version isn't only a build artifact — it's visible in the
white-labeled front-door: Settings → System → "Engine health" now shows "Engine vX.Y.Z" (sourced from
`GET /api/health/capabilities` on the engine, proxied verbatim by
`workspace/routes/applicant_health_routes.py`, rendered by `workspace/static/js/applicantHealth.js`).
