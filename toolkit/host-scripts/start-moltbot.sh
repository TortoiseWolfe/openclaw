#!/usr/bin/env bash
# Auto-start moltbot Docker services after WSL2 reboot.
# Idempotent — skips steps already done. Safe to run multiple times.
#
# Triggered by:
#   1. @reboot cron entry (primary — no terminal needed)
#   2. .bashrc hook (fallback — if cron misses)
# Logs to ~/.moltbot/startup.log

set -euo pipefail

REPO_DIR="$HOME/repos/moltbot"
LOG_DIR="$HOME/.moltbot"
LOG_FILE="$LOG_DIR/startup.log"
LOCK_FILE="/tmp/moltbot-starting.lock"
REQUIRED_MODELS=("qwen3:14b")

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# Atomic lock using flock — prevents race between @reboot cron and .bashrc
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 0  # Another instance holds the lock
fi
trap 'rm -f "$LOCK_FILE"' EXIT

log "=== moltbot startup ==="

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
if ! docker image inspect moltbot:local &>/dev/null; then
  log "Building moltbot:local image..."
  docker build -t moltbot:local . >> "$LOG_FILE" 2>&1
  log "Image built"
else
  log "Image moltbot:local exists"
fi

# 3. Start services
log "Starting services..."
docker compose up -d >> "$LOG_FILE" 2>&1
log "Compose up done"

# 4. Wait for Ollama to be responsive (longer wait for fresh containers)
log "Waiting for Ollama..."
for i in $(seq 1 300); do
  if docker compose exec -T ollama curl -sf http://localhost:11434/api/tags &>/dev/null; then
    break
  fi
  sleep 2
done
if ! docker compose exec -T ollama curl -sf http://localhost:11434/api/tags &>/dev/null; then
  log "WARNING: Ollama not responding after 10 min — models may not be available"
else
  log "Ollama ready"

  # 5. Pull missing models
  existing=$(docker compose exec -T ollama ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' || true)
  for model in "${REQUIRED_MODELS[@]}"; do
    if echo "$existing" | grep -q "^${model}"; then
      log "Model $model present"
    else
      log "Pulling $model (this may take several minutes)..."
      docker compose exec -T ollama ollama pull "$model" >> "$LOG_FILE" 2>&1
      log "Model $model pulled"
    fi
  done

  # 6. Create ctx8k Modelfile variants (num_ctx=8192 for VRAM efficiency on RTX 3060)
  for model in "${REQUIRED_MODELS[@]}"; do
    variant="${model}-ctx8k"
    if echo "$existing" | grep -q "^${variant}"; then
      log "Variant $variant present"
    else
      log "Creating $variant (num_ctx=8192)..."
      docker compose exec -T moltbot-gateway curl -sf http://ollama:11434/api/create \
        -X POST -H 'Content-Type: application/json' \
        -d "{\"model\":\"${variant}\",\"from\":\"${model}\",\"params\":{\"num_ctx\":8192}}" \
        >> "$LOG_FILE" 2>&1
      log "Variant $variant created"
    fi
  done
fi

# 7. Summary
running=$(docker compose ps --format '{{.Name}} {{.State}}' 2>/dev/null | grep -c running || true)
log "Startup complete — $running services running"
