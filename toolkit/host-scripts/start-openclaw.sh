#!/usr/bin/env bash
# Auto-start openclaw Docker services after WSL2 reboot.
# Idempotent — skips steps already done. Safe to run multiple times.
#
# Triggered by:
#   1. @reboot cron entry (primary — no terminal needed)
#   2. .bashrc hook (fallback — if cron misses)
# Logs to ~/.openclaw/startup.log

set -euo pipefail

REPO_DIR="$HOME/repos/openclaw"
LOG_DIR="$HOME/.openclaw"
LOG_FILE="$LOG_DIR/startup.log"
LOCK_FILE="/tmp/openclaw-starting.lock"
REQUIRED_MODELS=("qwen3:8b" "llama3-groq-tool-use:8b" "llama3.1:8b")

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# Atomic lock using flock — prevents race between @reboot cron and .bashrc
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 0  # Another instance holds the lock
fi
trap 'rm -f "$LOCK_FILE"' EXIT

log "=== openclaw startup ==="

# 1. Wait for Docker Desktop to be ready (auto-starts on Windows boot)
if ! docker info &>/dev/null; then
  log "Waiting for Docker Desktop..."
  for i in $(seq 1 90); do
    docker info &>/dev/null && break
    sleep 1
  done
  if ! docker info &>/dev/null; then
    log "ERROR: Docker not available after 90s"
    exit 1
  fi
  log "Docker ready"
else
  log "Docker already available"
fi

cd "$REPO_DIR"

# 2. Build image if missing
if ! docker image inspect openclaw:local &>/dev/null; then
  log "Building openclaw:local image..."
  docker build -t openclaw:local . >> "$LOG_FILE" 2>&1
  log "Image built"
else
  log "Image openclaw:local exists"
fi

# 3. Start services
log "Starting services..."
docker compose up -d >> "$LOG_FILE" 2>&1
log "Compose up done"

# 3b. Start OBS launcher watchdog (host-side HTTP bridge — independent of Ollama)
WATCHDOG="$REPO_DIR/toolkit/host-scripts/obs_launcher_watchdog.sh"
if [[ -x "$WATCHDOG" ]]; then
    log "Starting OBS launcher watchdog..."
    bash "$WATCHDOG"
    log "OBS launcher watchdog started"
else
    log "WARNING: obs_launcher_watchdog.sh not found or not executable"
fi

# 4. Wait for Ollama to be responsive (longer wait for fresh containers)
log "Waiting for Ollama..."
for i in $(seq 1 300); do
  if docker compose exec -T ollama ollama list &>/dev/null; then
    break
  fi
  sleep 2
done
if ! docker compose exec -T ollama ollama list &>/dev/null; then
  log "WARNING: Ollama not responding after 10 min — models may not be available"
else
  log "Ollama ready"

  # 5. Pull base models and create 16K context variants
  for base in "${REQUIRED_MODELS[@]}"; do
    variant="${base}-ctx16k"
    if docker compose exec -T ollama ollama show "$variant" &>/dev/null; then
      log "Model $variant present"
    else
      log "Pulling $base (this may take several minutes)..."
      docker compose exec -T ollama ollama pull "$base" >> "$LOG_FILE" 2>&1
      log "Creating $variant (16K context)..."
      docker compose exec -T ollama bash -c "printf 'FROM %s\nPARAMETER num_ctx 16384\n' '$base' > /tmp/Modelfile && ollama create '$variant' -f /tmp/Modelfile" >> "$LOG_FILE" 2>&1
      log "Model $variant ready"
    fi
  done
fi

# 7. Summary
running=$(docker compose ps --format '{{.Name}} {{.State}}' 2>/dev/null | grep -c running || true)
log "Startup complete — $running services running"
