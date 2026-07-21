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

echo "Branding applied from overlay"
