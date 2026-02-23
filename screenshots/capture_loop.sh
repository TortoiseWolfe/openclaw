#!/bin/bash
# Capture overlay screenshots every 30 seconds
# Usage: bash screenshots/capture_loop.sh
OVERLAY_URL="http://172.18.0.3:3100/game/overlay.html"
OUT_DIR="$(dirname "$0")/session-2026-02-23"
mkdir -p "$OUT_DIR"

N=1
while true; do
    TS=$(date +%Y%m%d-%H%M%S)
    # Get current act/scene from game state
    INFO=$(docker compose exec -T openclaw-gateway python3 -u -c "
import json
with open('/home/node/.openclaw/rpg/state/game-state.json') as f:
    s = json.load(f)
sess = s.get('session',{})
print(sess.get('act','?'), sess.get('scene','?'), sess.get('mode','?'), len(s.get('action_log',[])))
" 2>/dev/null | tail -1)
    echo "[$TS] #$N state: $INFO"
    N=$((N+1))
    sleep 30
done
