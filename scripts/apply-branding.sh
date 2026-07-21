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

# Copy SVG assets from the overlay public dir
if [ -d "$OVERLAY_DIR/public" ]; then
  mkdir -p "$TARGET_DIR/webui/public"
  cp "$OVERLAY_DIR/public/"*.svg "$TARGET_DIR/webui/public/"
fi

# Copy branded HTML files (index.html, login.html) from the overlay
if [ -f "$OVERLAY_DIR/index.html" ]; then
  cp "$OVERLAY_DIR/index.html" "$TARGET_DIR/webui/index.html"
fi
if [ -f "$OVERLAY_DIR/login.html" ]; then
  cp "$OVERLAY_DIR/login.html" "$TARGET_DIR/webui/login.html"
fi

# Copy branded PWA manifest
if [ -f "$OVERLAY_DIR/js/manifest.json" ]; then
  mkdir -p "$TARGET_DIR/webui/js"
  cp "$OVERLAY_DIR/js/manifest.json" "$TARGET_DIR/webui/js/manifest.json"
fi

# AZ0-4/826: Apply string substitution to catch upstream component references
# that leak the upstream codename into the shipped artifact.  This pass runs
# after the overlay copies so that overlay-provided files (e.g. manifest.json)
# are not double-patched.  Only .html and .json files under webui/ are touched;
# node_modules/ is excluded.
echo "Applying string substitution: 'Agent Zero' -> '$APP_NAME', 'agent0ai' -> '$APP_SHORT_NAME'"
find "$TARGET_DIR/webui" -type f -name '*.html' ! -path '*/node_modules/*' -print0 | xargs -0 -r sed -i -e "s/Agent Zero/${APP_NAME}/g" -e "s/agent0ai/${APP_SHORT_NAME}/g"
find "$TARGET_DIR/webui" -type f -name '*.json' ! -path '*/node_modules/*' -print0 | xargs -0 -r sed -i -e "s/Agent Zero/${APP_NAME}/g" -e "s/agent0ai/${APP_SHORT_NAME}/g"

echo "Branding applied from overlay"
