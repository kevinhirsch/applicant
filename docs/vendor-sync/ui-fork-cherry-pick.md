# UI Fork Cherry-Pick Workflow

This document describes how an upstream change to the **framework webui**
(`/a0/webui`) is deliberately ported into the **branded overlay** (`a0-webui/`).

## Purpose

The `a0-webui/` directory is a **build-time overlay** applied over the pristine
`/a0/webui` subtree. It holds only the branded/divergent files (never the full
copy), so every file in `a0-webui/` represents a **deliberate divergence**.
Cherry-picking an upstream change into this overlay keeps the divergence
managed, legible, and updatable — not a frozen fork.

## When to cherry-pick

- The upstream `/a0/webui` receives a **bug fix, security patch, or feature**
  that affects a file you have overridden in `a0-webui/`.
- You want to **adopt the upstream change** while keeping your branding intact.

## Workflow

### 1. Apply the upstream change to the pristine subtree

Pull the upstream framework update so `/a0/webui` has the new version:

```bash
cd /a0/usr/projects/applicant
# Update the framework submodule / subtree
# (method depends on how the framework is vendored)
```

### 2. Port the relevant diff into the overlay

```bash
cd /a0/usr/projects/applicant-wt846

# Generate the diff between the old and new upstream file
git diff <old-ref>..<new-ref> -- /a0/webui/index.html > /tmp/upstream.patch

# Apply the relevant hunk(s) to the branded copy
patch a0-webui/index.html <(cat /tmp/upstream.patch | grep -v 'Agent Zero')
# ^--- Grep-filter demo only — do this manually to avoid breaking branding
```

**Best practice:** Port the diff **by hand** to preserve branded strings.
Use `git diff --no-color` for clean patches.

### 3. Verify the branded file

```bash
# Check that branded strings survived
head -5 a0-webui/login.html         # Should say "Applicant" not "Agent Zero"
grep -c 'Agent Zero' a0-webui/*.html # Should be 0

# Run the overlay coherence test
.venv/bin/pytest tests/unit/test_ui_fork_overlay.py -v
```

### 4. Commit with an audit trail

```bash
git add a0-webui/<changed-file>
git commit -m "feat(ui): cherry-pick <upstream-hash> into a0-webui overlay

Upstream: <org>/a0@<sha>
File: <path>
What changed: <description>
Refs: #846"
```

## How the build applies the overlay

At container build time, `scripts/apply-branding.sh` copies every file from
`a0-webui/` onto the target `/a0/webui` tree:

```
apply-branding.sh  →  cp a0-webui/<path> → target/webui/<path>
```

The pristine `/a0/webui` is never modified at source — the overlay shadows
it by file-level replacement *at the build stage*.

## Adding a new overlay file

1. Place the branded file in `a0-webui/` under the matching relative path.
2. Add the copy command to `scripts/apply-branding.sh`.
3. Update this document with the new file's purpose and any cherry-pick
   considerations.

## Overlay file inventory

| File in a0-webui/ | Upstream source | Divergence |
|---|---|---|
| `index.html` | `/a0/webui/index.html` | `<title>` branded |
| `login.html` | `/a0/webui/login.html` | `<title>`, alt, `<h2>` branded |
| `js/manifest.json` | `/a0/webui/js/manifest.json` | `name`, `short_name` branded |
| `public/favicon.svg` | `/a0/webui/public/favicon.svg` | Custom SVG |
| `public/favicon_round.svg` | *(not in upstream)* | Custom SVG |
| `public/icon.svg` | `/a0/webui/public/icon.svg` | Custom SVG |
| `public/icon-maskable.svg` | `/a0/webui/public/icon-maskable.svg` | Custom SVG |
