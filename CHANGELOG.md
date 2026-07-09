# Changelog

All notable changes to Applicant are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`):

- **MAJOR** — a break in the deploy contract (env vars, compose service names/ports, data-migration
  requirements) or a removal of a shipped capability.
- **MINOR** — a new user-facing capability, reachable end-to-end through the white-labeled front-door.
- **PATCH** — a fix, hardening pass, or internal change with no new front-door capability.

The single source of truth for the current version is the repo-root `VERSION` file (see
`docs/release-process.md` for how the three copies — `VERSION`, `pyproject.toml`, and
`src/applicant/version.py` — are kept in lockstep, and how to cut a release).

## [Unreleased]

### Added
- Release engineering (P3-5): versioned releases (`VERSION` + semver), this changelog, a
  version-consistency check (`scripts/ci/check_release_version.py`), and
  `.github/workflows/release.yml` — build, sign (cosign keyless/OIDC), and publish images to
  GHCR on a version tag, with stable/beta channel tags. See `docs/release-process.md` for the
  full process, the one-time GHCR/cosign setup, and the current live-signing gap.
- The engine's running version is now surfaced through the front-door: `GET
  /api/health/capabilities` (engine) → `GET /api/applicant/health/capabilities` (workspace proxy)
  → the Settings → System "Engine health" panel now shows "Engine vX.Y.Z".

## [0.1.0] - 2026-07-09

Baseline entry — the version already recorded in `pyproject.toml` / `src/applicant/version.py`
before this changelog existed. Prior history is not reconstructed here; see `git log` for the
full commit history. From this point forward, every version bump gets its own entry above.
