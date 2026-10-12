#!/bin/bash
# Send SIGTERM for graceful shutdown and state commit
pkill -15 -f run_live_paper_daemon.py 2>/dev/null || true
sleep 1

# Release Termux wake-lock if available
if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock
    echo "Termux wake-lock released."
fi

echo "Live Paper Trading Daemon gracefully stopped."
