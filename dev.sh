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

uv run --project backend uvicorn backend.main:app --reload --port 8000 &
(cd frontend && pnpm run dev) &
wait
