#!/usr/bin/env bash
# Algo Lab — Cloud VPS Deployment & Supervision Setup
set -euo pipefail

echo "=========================================================="
echo "Algo Lab: Institutional Cloud VPS Provisioning Setup"
echo "=========================================================="

sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git curl htop

# Copy systemd service unit
sudo cp scripts/cloud/algolab-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable algolab-paper.service

echo "Provisioning complete. To start the daemon on VPS:"
echo "  sudo systemctl start algolab-paper.service"
echo "  sudo systemctl status algolab-paper.service"
