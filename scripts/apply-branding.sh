#!/usr/bin/env bash
set -euo pipefail

# AZ0-4: Branded-artifact overlay script
# Usage: apply-branding.sh [target_dir]
#   target_dir: directory containing a full Agent Zero tree (default: agent-zero sibling)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${1:-$(dirname "$SCRIPT_DIR")/agent-zero}"

if [ ! -d "$TARGET_DIR" ]; then
  echo "Error: target directory does not exist: $TARGET_DIR"
  exit 1
fi

# Source brand configuration
source "$SCRIPT_DIR/../branding/string-map.env"

echo "Applying branding for '$APP_NAME' to $TARGET_DIR"

# --- Copy SVG assets -----------------------------------------------------------
mkdir -p "$TARGET_DIR/webui/public"
cp branding/public/*.svg "$TARGET_DIR/webui/public/"

# --- Replace HTML titles -------------------------------------------------------
for f in "$TARGET_DIR/webui/index.html" "$TARGET_DIR/webui/login.html"; do
  if [ -f "$f" ]; then
    sed -i "s|<title>Agent Zero</title>|<title>$APP_NAME</title>|g" "$f"
  fi
done

# --- Replace login strings -----------------------------------------------------
if [ -f "$TARGET_DIR/webui/login.html" ]; then
  sed -i "s|alt=\"Agent Zero Logo\"|alt=\"$APP_NAME Logo\"|g" "$TARGET_DIR/webui/login.html"
  sed -i "s|<h2>Agent Zero</h2>|<h2>$APP_NAME</h2>|g" "$TARGET_DIR/webui/login.html"
fi

# --- Replace PWA manifest ------------------------------------------------------
if [ -f "$TARGET_DIR/webui/manifest.json" ]; then
  sed -i "s|\"name\": \"Agent Zero\"|\"name\": \"$APP_NAME\"|g" "$TARGET_DIR/webui/manifest.json"
  sed -i "s|\"short_name\": \"Agent Zero\"|\"short_name\": \"$APP_SHORT_NAME\"|g" "$TARGET_DIR/webui/manifest.json"
fi

echo "Branding applied"
