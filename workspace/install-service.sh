#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/applicant-ui.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: applicant-ui.service not found in $SCRIPT_DIR"
  exit 1
fi

echo "Installing Applicant UI service..."
echo "Make sure you've edited applicant-ui.service with your username and paths first!"
echo ""

sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable applicant-ui
sudo systemctl start applicant-ui
sudo systemctl status applicant-ui
