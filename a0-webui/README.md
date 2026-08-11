# a0-webui — Branded UI Overlay

This directory is the **build-time overlay** applied over the pristine framework
webui (`/a0/webui`) at container build or deployment time. It holds only the
**divergent/branded files** — never the full framework webui.

## What goes here

| File | Purpose |
|------|---------|
| `index.html` | Branded main UI entry (title, meta) |
| `login.html` | Branded login page (title, logo alt, heading) |
| `js/manifest.json` | Branded PWA manifest (name, short_name) |
| `public/*.svg` | Custom favicon and app icons |

## How the overlay works

The `scripts/apply-branding.sh` script copies files from `a0-webui/` onto the
target `/a0/webui` tree at build time. The pristine framework webui is never
touched — the overlay shadows it by file-level replacement.

## Adding a new branded file

1. Place the branded version in `a0-webui/` under the same relative path as
   its counterpart in `/a0/webui`.
2. Add the copy to `scripts/apply-branding.sh`.
3. Update the cherry-pick doc (`docs/vendor-sync/ui-fork-cherry-pick.md`)
   if the file is a deliberate divergence from an upstream file.

## Cherry-picking upstream changes

When the upstream framework webui updates a file you have overridden:

1. Rebase the upstream change into `/a0/webui/` as normal.
2. Port the relevant diff into the branded version in `a0-webui/`.
3. Update the cherry-pick doc with the upstream commit ref and what was adapted.

See `docs/vendor-sync/ui-fork-cherry-pick.md` for the full workflow.
