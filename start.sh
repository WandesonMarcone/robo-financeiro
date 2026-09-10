#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Backend Flask (API). Preview exposes the frontend port.
cd "$ROOT"
API_ENABLED="${API_ENABLED:-true}" \
API_CORS_ORIGINS="${API_CORS_ORIGINS:-http://localhost:3000}" \
PORT="${PORT:-10000}" \
python main.py &
BACKEND_PID=$!

# Frontend Next.js (exposed preview)
cd "$ROOT/frontend"
npm run dev

trap 'kill $BACKEND_PID' EXIT
