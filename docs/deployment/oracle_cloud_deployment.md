# Algo Lab — Oracle Cloud Infrastructure (OCI) Production Deployment Guide

This guide details the complete, step-by-step instructions to provision, configure, and operate **Algo Lab** on **Oracle Cloud Infrastructure (OCI)** (e.g. Always Free Ampere A1 ARM / AMD compute in the Mumbai or Hyderabad region).

---

## 1. OCI Compute Instance Provisioning

1. Log in to the **[Oracle Cloud Console](https://cloud.oracle.com/)**.
2. Select your home region: **India West (Mumbai - `ap-mumbai-1`)** or **India South (Hyderabad - `ap-hyderabad-1`)** for minimal latency to NSE servers.
3. Navigate to **Compute** → **Instances** → **Create Instance**:
   - **Name:** `algolab-production-01`
   - **Image:** `Canonical Ubuntu 22.04 LTS` or `Ubuntu 24.04 LTS`
   - **Shape:** 
     - *Recommended (Always Free):* **VM.Standard.A1.Flex** (Ampere ARM, 2 to 4 OCPU, 12GB to 24GB RAM).
     - *Alternative:* **VM.Standard.E2.1.Micro** (AMD, 1 OCPU, 1GB RAM) or paid E4/E5.
   - **Networking:** Primary VCN with Public Subnet.
   - **SSH Keys:** Paste your local public SSH key (`id_ed25519.pub` or `id_rsa.pub`).
   - **Boot Volume:** 50 GB or 100 GB.
4. Click **Create** and copy the **Public IP Address**.

---

## 2. VCN Security List & Ingress Rules

To access the API dashboard and Web UI:
1. In OCI Console, go to **Networking** → **Virtual Cloud Networks** → Select your VCN → **Security Lists**.
2. Click **Default Security List** → **Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port Range | Description |
| :--- | :---: | :---: | :--- |
| `0.0.0.0/0` | TCP | `22` | SSH Access |
| `0.0.0.0/0` | TCP | `8000` | Algo Lab FastAPI Backend |
| `0.0.0.0/0` | TCP | `3000` | Algo Lab Next.js Dashboard |

3. Open iptables on the Ubuntu instance:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 3000 -j ACCEPT
sudo netfilter-persistent save
```

---

## 3. Server Setup & Dependencies

Connect to your Oracle Cloud instance:
```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@<YOUR_OCI_PUBLIC_IP>
```

Run the automated setup commands:
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install build tools, Python, PostgreSQL, and Git
sudo apt install -y python3 python3-pip python3-venv git curl htop \
    build-essential libpq-dev iptables-persistent

# Install Docker & Docker Compose (optional for PostgreSQL container)
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu
```

---

## 4. Clone Repository & Setup Environment

```bash
# Clone the repository
git clone https://github.com/vijaykumarjogi266-star/algopro.git /home/ubuntu/algopro
cd /home/ubuntu/algopro

# Create Python Virtual Environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python Dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install pyotp yfinance

# Configure Environment Variables
cp .env.example .env
nano .env
```

Ensure `.env` contains your trading configuration:
```env
ENVIRONMENT=production
INITIAL_CAPITAL=10000.0
LEVERAGE=5.0
KITE_API_KEY=your_kite_api_key
KITE_API_SECRET=your_kite_api_secret
KITE_USER_ID=your_kite_user_id
KITE_PASSWORD=your_kite_password
KITE_TOTP_SECRET=your_base32_totp_secret
```

---

## 5. Configure Systemd Background Services

Algo Lab uses `systemd` to keep trading daemons running 24/7 with automatic restart on failures.

### A. Install Paper Trading Daemon Service:
```bash
sudo cp scripts/cloud/algolab-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable algolab-paper.service
sudo systemctl start algolab-paper.service
```

### B. Verify Status & Live Logs:
```bash
# Check service status
sudo systemctl status algolab-paper.service

# Stream live real-time trading logs
tail -f /home/ubuntu/algopro/data/paper_trading_live.log
```

---

## 6. Daily 08:30 AM IST Morning Token Renewal (Cron)

Kite Connect requires a fresh access token each morning. Add a cron job to authenticate before the 09:15 AM market open:

```bash
crontab -e
```
Add the following line (03:00 UTC = 08:30 IST):
```cron
0 3 * * 1-5 /home/ubuntu/algopro/.venv/bin/python3 /home/ubuntu/algopro/services/paper-engine/adapters/kite_auth.py >> /home/ubuntu/algopro/data/auth.log 2>&1
```

---

## 7. Useful Operational Commands on OCI

| Command | Action |
| :--- | :--- |
| `sudo systemctl restart algolab-paper` | Restart trading daemon |
| `sudo systemctl stop algolab-paper` | Gracefully shut down daemon (executes 15:15 IST flush) |
| `journalctl -u algolab-paper -f` | View systemd logs |
| `python3 test_dry_run_institutional.py` | Run complete end-to-end self-test on server |
