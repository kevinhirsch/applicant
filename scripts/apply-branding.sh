#!/usr/bin/env bash
set -euo pipefail

# AZ0-4/846: Branded-artifact overlay script
# Applies the a0-webui/ build-time overlay over the pristine framework webui.
#
# Usage: apply-branding.sh [target_dir]
#   target_dir: directory containing a full Agent Zero tree (default: workspace/../agent-zero sibling)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TARGET_DIR="${1:-$(dirname "$SCRIPT_DIR")/agent-zero}"
OVERLAY_DIR="$PROJECT_ROOT/a0-webui"

if [ ! -d "$TARGET_DIR" ]; then
  echo "Error: target directory does not exist: $TARGET_DIR"
  exit 1
fi

if [ ! -d "$OVERLAY_DIR" ]; then
  echo "Error: overlay directory does not exist: $OVERLAY_DIR"
  exit 1
fi

# Source brand configuration (for informational use)
source "$SCRIPT_DIR/../branding/string-map.env"

echo "Applying branded overlay '$APP_NAME' from $OVERLAY_DIR to $TARGET_DIR/webui"

# Recursively mirror the ENTIRE a0-webui/ overlay tree onto webui/, preserving
# directory structure. This means ANY core webui file can be durably overridden
# by placing a modified copy at a0-webui/<same-relative-path> (index.html,
# login.html, js/manifest.json, public/*.svg AND nested files such as
# components/welcome/welcome-screen.html). The base image is pinned to a fixed
# upstream release, so vendored core files do not drift. README.md is excluded.
# Supersedes the earlier explicit per-file copies (which this reproduces exactly
# for index.html / login.html / js/manifest.json / public/*.svg).
cp -a "$OVERLAY_DIR"/. "$TARGET_DIR/webui"/
rm -f "$TARGET_DIR/webui/README.md"

# AZ0-4/826: Apply string substitution to catch upstream component references
# that leak the upstream codename into the shipped artifact.  This pass runs
# after the overlay copies so that overlay-provided files (e.g. manifest.json)
# are not double-patched.  Only .html and .json files under webui/ are touched;
# node_modules/ is excluded.
echo "Applying string substitution: 'Agent Zero' -> '$APP_NAME', 'agent0ai' -> '$APP_SHORT_NAME'"
find "$TARGET_DIR/webui" -type f -name '*.html' ! -path '*/node_modules/*' -print0 | xargs -0 -r sed -i -e "s/Agent Zero/${APP_NAME}/g" -e "s/agent0ai/${APP_SHORT_NAME}/g"
find "$TARGET_DIR/webui" -type f -name '*.json' ! -path '*/node_modules/*' -print0 | xargs -0 -r sed -i -e "s/Agent Zero/${APP_NAME}/g" -e "s/agent0ai/${APP_SHORT_NAME}/g"
# .js display strings (welcome/settings Alpine stores etc.) leaked the upstream
# codename too (found by the visual monkey-crawl). Substitute ONLY the spaced
# display name "Agent Zero" -> APP_NAME here — deliberately NOT "agent0ai", which
# appears in functional identifiers/URLs in JS and must not be rewritten. Skip
# vendored libraries (vendor/, node_modules/).
find "$TARGET_DIR/webui" -type f -name '*.js' ! -path '*/node_modules/*' ! -path '*/vendor/*' -print0 | xargs -0 -r sed -i -e "s/Agent Zero/${APP_NAME}/g"

echo "Branding applied from overlay"
