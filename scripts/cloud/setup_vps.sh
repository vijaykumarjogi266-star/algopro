#!/usr/bin/env bash
# Algo Lab — Oracle Cloud & Linux VPS Deployment & Supervision Setup
set -euo pipefail

echo "=========================================================="
echo "Algo Lab: Oracle Cloud Infrastructure (OCI) Setup"
echo "=========================================================="

sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git curl htop \
    build-essential libpq-dev iptables-persistent

# Open Oracle Cloud OS Firewall Ports 8000 and 3000 if iptables present
if command -v iptables >/dev/null 2>&1; then
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT || true
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 3000 -j ACCEPT || true
    if command -v netfilter-persistent >/dev/null 2>&1; then
        sudo netfilter-persistent save || true
    fi
fi

# Copy systemd service unit
if [ -f scripts/cloud/algolab-paper.service ]; then
    sudo cp scripts/cloud/algolab-paper.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable algolab-paper.service
fi

echo "=========================================================="
echo "Setup complete! Next steps:"
echo "1. Configure .env with your credentials: cp .env.example .env"
echo "2. Start paper trading service: sudo systemctl start algolab-paper"
echo "3. Check live logs: tail -f data/paper_trading_live.log"
echo "=========================================================="
