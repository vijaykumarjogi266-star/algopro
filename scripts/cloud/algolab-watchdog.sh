#!/usr/bin/env bash
# Algo Lab Autonomous 30-Day Watchdog & Self-Healing Monitor
# Runs periodically to ensure 100% uptime and zero-human-intervention stability.

set -euo pipefail

PROJECT_DIR="/home/ubuntu/algopro"
DATA_DIR="${PROJECT_DIR}/data"
LOG_FILE="${DATA_DIR}/paper_trading_live.log"
WATCHDOG_LOG="${DATA_DIR}/watchdog.log"
SERVICE_NAME="algolab-paper.service"

mkdir -p "${DATA_DIR}"

log_alert() {
    local msg="$1"
    local ts
    ts=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
    echo "[${ts}] [WATCHDOG] ${msg}" | tee -a "${WATCHDOG_LOG}"
}

# 1. Check Service Status
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    log_alert "WARNING: ${SERVICE_NAME} is DOWN! Initiating autonomous restart..."
    sudo systemctl restart "${SERVICE_NAME}"
    sleep 3
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log_alert "RECOVERY: ${SERVICE_NAME} successfully recovered and is now ACTIVE."
    else
        log_alert "CRITICAL: ${SERVICE_NAME} failed to restart! Inspecting journalctl..."
        journalctl -u "${SERVICE_NAME}" -n 20 --no-pager >> "${WATCHDOG_LOG}"
    fi
fi

# 2. Check Process Freeze during Trading Hours (09:15 - 15:30 IST / 03:45 - 10:00 UTC)
# Only check on weekdays (1-5 in date +%u)
DAY_OF_WEEK=$(date -u +%u)
UTC_HOUR=$(date -u +%H)
UTC_MIN=$(date -u +%M)
UTC_TOTAL_MIN=$((10#$UTC_HOUR * 60 + 10#$UTC_MIN))

# 03:45 UTC = 225 mins; 10:00 UTC = 600 mins
if [ "${DAY_OF_WEEK}" -le 5 ] && [ "${UTC_TOTAL_MIN}" -ge 225 ] && [ "${UTC_TOTAL_MIN}" -le 600 ]; then
    if [ -f "${LOG_FILE}" ]; then
        LAST_MOD=$(stat -c %Y "${LOG_FILE}")
        NOW=$(date +%s)
        DIFF=$((NOW - LAST_MOD))
        if [ "${DIFF}" -gt 300 ]; then
            log_alert "WARNING: Process freeze detected. Log stagnant for ${DIFF}s during active trading. Restarting daemon..."
            sudo systemctl restart "${SERVICE_NAME}"
            log_alert "RECOVERY: Daemon restarted following stagnation."
        fi
    fi
fi

# 3. Database Health & Integrity Check
DB_FILE="${DATA_DIR}/paper_trading.db"
if [ -f "${DB_FILE}" ]; then
    INTEGRITY=$("${PROJECT_DIR}/.venv/bin/python" -c "import sqlite3; conn = sqlite3.connect('${DB_FILE}'); cur = conn.cursor(); cur.execute('PRAGMA integrity_check;'); res = cur.fetchone()[0]; conn.close(); print(res)" 2>/dev/null || echo "ERROR")
    if [ "${INTEGRITY}" != "ok" ]; then
        log_alert "CRITICAL: Database integrity check failed (${INTEGRITY}). Checking backups..."
        LATEST_BACKUP=$(ls -t "${DATA_DIR}/backups/"paper_trading_*.db 2>/dev/null | head -n 1 || true)
        if [ -n "${LATEST_BACKUP}" ]; then
            log_alert "RECOVERY: Restoring database from backup: ${LATEST_BACKUP}"
            cp "${LATEST_BACKUP}" "${DB_FILE}"
            sudo systemctl restart "${SERVICE_NAME}"
        fi
    fi
fi

# 4. Log Rotation Check (> 50MB)
if [ -f "${LOG_FILE}" ]; then
    FILESIZE=$(stat -c %s "${LOG_FILE}")
    if [ "${FILESIZE}" -gt 52428800 ]; then
        log_alert "MAINTENANCE: Log file reached 50MB. Rotating..."
        mv "${LOG_FILE}" "${LOG_FILE}.old"
        touch "${LOG_FILE}"
        chmod 664 "${LOG_FILE}"
    fi
fi

exit 0
