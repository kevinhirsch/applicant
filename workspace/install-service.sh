#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/firehouse-ui.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: firehouse-ui.service not found in $SCRIPT_DIR"
  exit 1
fi

echo "Installing Firehouse UI service..."
echo "Make sure you've edited firehouse-ui.service with your username and paths first!"
echo ""

sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable firehouse-ui
sudo systemctl start firehouse-ui
sudo systemctl status firehouse-ui
