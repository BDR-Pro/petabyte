#!/usr/bin/env bash
# Petabyte Linux node uninstaller — stops + removes the agent service and files.
set -e
echo "Stopping and removing the Petabyte agent..."
sudo systemctl disable --now petabyte-agent 2>/dev/null || true
sudo rm -f /etc/systemd/system/petabyte-agent.service
sudo systemctl daemon-reload 2>/dev/null || true
sudo rm -rf /opt/petabyte /etc/petabyte
echo "Uninstalled. Docker was left installed — remove it with your package manager"
echo "if you added it only for Petabyte:  sudo apt-get remove docker-ce"
