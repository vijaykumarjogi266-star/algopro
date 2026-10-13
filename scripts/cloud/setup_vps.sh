#!/usr/bin/env bash
# Algo Lab — Oracle Cloud & Linux VPS Deployment & Supervision Setup
set -euo pipefail

echo "=========================================================="
echo "Algo Lab: Oracle Cloud Infrastructure (OCI) Setup"
echo "=========================================================="

sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git curl htop \
    build-essential libpq-dev iptables-persistent

# Restrict open ports — recommendation is to bind API/UI to localhost and use Nginx/Caddy TLS reverse proxy
echo "Note: Do not expose raw database or unauthenticated application ports directly to 0.0.0.0."
echo "Use Nginx/Caddy with TLS and configure ALGO_LAB_API_KEY."

# Copy systemd service unit
if [ -f scripts/cloud/algolab-paper.service ]; then
    sudo cp scripts/cloud/algolab-paper.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable algolab-paper.service
fi

echo "=========================================================="
echo "Setup complete! Next steps:"
echo "1. Configure .env with your generated secrets: cp .env.example .env"
echo "2. Generate ALGO_LAB_API_KEY, CIRCUIT_BREAKER_REARM_SECRET, and BROKER_CREDENTIAL_ENCRYPTION_KEY."
echo "3. Start paper trading service: sudo systemctl start algolab-paper"
echo "4. Check live logs: tail -f data/paper_trading_live.log"
echo "=========================================================="
