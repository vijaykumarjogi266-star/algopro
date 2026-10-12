#!/bin/bash
unset ANDROID_DATA ANDROID_ROOT
cd /data/data/com.termux/files/home/algopro
# Check if already running
if pgrep -f run_live_paper_daemon.py > /dev/null; then
    echo "Live paper daemon is already running (PID: $(pgrep -f run_live_paper_daemon.py))."
    exit 0
fi

nohup python3 run_live_paper_daemon.py >> data/paper_trading_live.log 2>&1 &
PID=$!
echo "Live Paper Trading Daemon successfully started in background with PID: $PID"
