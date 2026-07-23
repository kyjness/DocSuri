#!/usr/bin/env bash
# DocSuri solo-local dev — one command for the whole stack (solo-local-migration.md §5).
#
#   ./dev.sh          # docker deps up + backend(:8000) + frontend(:3000)
#   Ctrl+C            # stops backend+frontend together (docker containers stay up)
#   docker compose -f backend/docker-compose.yml down   # stop the containers too
set -euo pipefail
cd "$(dirname "$0")"

docker compose -f backend/docker-compose.yml up -d

set -a; source .env; set +a

# Kill the whole process group on exit so Ctrl+C stops both servers.
trap 'kill 0' EXIT INT TERM

start_backend() {
  # Mirror backend output to a log file so a silent worker crash leaves evidence.
  mkdir -p .dev-logs
  # Watch only backend code — watching the repo root makes the watcher see its own
  # log file under .dev-logs/ (feedback spam) and the whole frontend tree.
  uv run --project backend uvicorn backend.main:app --reload --port 8000 \
    --reload-dir backend --reload-dir shared/python 2>&1 \
    | tee ".dev-logs/backend-$(date +%Y%m%d-%H%M%S).log" &
}

# Port taken (e.g. by a previous run): keep it only if it actually answers.
# A dead --reload worker leaves the watcher holding the port while every request
# hangs — that watcher also ignores SIGTERM, so use SIGKILL on its process group.
if ss -tln | grep -q ':8000 '; then
  if curl -sf -o /dev/null --max-time 3 http://localhost:8000/openapi.json; then
    echo "[dev.sh] healthy backend already on 8000 — skipping backend"
  else
    echo "[dev.sh] port 8000 held by an unresponsive backend — replacing it"
    stale_pid=$(ss -tlnp | grep ':8000 ' | grep -oP 'pid=\K[0-9]+' | head -1)
    if [ -n "${stale_pid:-}" ]; then
      kill -9 -- -"$(ps -o pgid= -p "$stale_pid" | tr -d ' ')" 2>/dev/null || kill -9 "$stale_pid"
      sleep 1
    fi
    start_backend
  fi
else
  start_backend
fi

if ss -tln | grep -q ':3000 '; then
  echo "[dev.sh] port 3000 already in use — skipping frontend"
else
  (cd frontend && pnpm run dev) &
fi

wait
