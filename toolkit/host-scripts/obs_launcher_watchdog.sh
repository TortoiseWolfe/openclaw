#!/usr/bin/env bash
# Watchdog for obs_launcher.py — restarts on crash, idempotent.
# Called by start-openclaw.sh or manually.
# Logs to ~/.openclaw/obs-launcher-watchdog.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="$SCRIPT_DIR/obs_launcher.py"
PORT="${OBS_LAUNCHER_PORT:-8100}"
LOG_DIR="${HOME}/.openclaw"
LOG_FILE="$LOG_DIR/obs-launcher-watchdog.log"
PID_FILE="/tmp/obs-launcher.pid"

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# Check if already running via PID file — verify with health check
if [[ -f "$PID_FILE" ]]; then
    old_pid=$(cat "$PID_FILE")
    if kill -0 "$old_pid" 2>/dev/null; then
        if curl -sf --max-time 5 "http://localhost:${PORT}/health" >/dev/null 2>&1; then
            log "Already running (PID $old_pid, healthy)"
            exit 0
        fi
        # Process alive but unhealthy — kill it
        log "PID $old_pid alive but /health failed — killing"
        kill "$old_pid" 2>/dev/null || true
        sleep 2
        kill -9 "$old_pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# Safety net: if port is bound, health-check before assuming it's alive
if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    if curl -sf --max-time 5 "http://localhost:${PORT}/health" >/dev/null 2>&1; then
        log "Launcher healthy on port $PORT"
        exit 0
    fi
    # Port bound but unhealthy — kill the stale process
    stale_pid=$(ss -tlnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | head -1)
    if [[ -n "$stale_pid" ]]; then
        log "Killing stale launcher PID $stale_pid (port $PORT bound but /health failed)"
        kill "$stale_pid" 2>/dev/null || true
        sleep 2
        kill -9 "$stale_pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

log "Starting obs_launcher.py on port $PORT"

# Restart loop: if obs_launcher exits, wait 5s and restart
_run_loop() {
    while true; do
        python3 "$LAUNCHER" --port "$PORT" \
            --log-file "$LOG_DIR/obs-launcher.log" &
        LAUNCHER_PID=$!
        echo "$LAUNCHER_PID" > "$PID_FILE"
        log "Launched PID $LAUNCHER_PID"

        wait "$LAUNCHER_PID" || true
        EXIT_CODE=$?
        log "obs_launcher exited (code=$EXIT_CODE), restarting in 5s..."
        rm -f "$PID_FILE"
        sleep 5
    done
}

_run_loop &
WATCHDOG_PID=$!
log "Watchdog loop PID $WATCHDOG_PID"
disown "$WATCHDOG_PID"
