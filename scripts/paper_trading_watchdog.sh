#!/bin/bash
# Autonomous Paper Trading Watchdog
# Ensures the intraday paper trader daemon is always running during trading sessions.

WORKSPACE_DIR="/opt/ai-builder/workspaces/TASK-INTRA-SCAN-01/algolab"
PID_FILE="$WORKSPACE_DIR/logs/paper_trader.pid"
LOG_FILE="$WORKSPACE_DIR/logs/autonomous_paper_trader.log"
PYTHON_BIN="$WORKSPACE_DIR/.venv/bin/python"
SCRIPT="$WORKSPACE_DIR/scripts/run_autonomous_paper_trader.py"

cd "$WORKSPACE_DIR" || exit 1

# Check if process is running via pgrep or PID file
RUNNING_PID=$(pgrep -f "run_autonomous_paper_trader.py" | head -n 1)
if [ -n "$RUNNING_PID" ]; then
    echo "$RUNNING_PID" > "$PID_FILE"
    exit 0 # Already running normally
fi

# Not running; launch process in background
nohup "$PYTHON_BIN" "$SCRIPT" --capital 10000.0 --leverage 5.0 --interval 5.0 >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PID_FILE"
echo "[$(date)] Started Autonomous Paper Trader with PID $NEW_PID" >> "$WORKSPACE_DIR/logs/watchdog.log"
