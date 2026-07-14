#!/bin/bash
# TradingDesk cold-start script
#
# Usage:
#   ./dev.sh          # normal start — skips rebuild if image is unchanged
#   ./dev.sh --build  # force rebuild (use after Python/Dockerfile changes)
#
# To pre-fetch SEC EDGAR 13F cache (run once, in a second terminal):
#   node scripts/prefetch-edgar.mjs

set -e

BUILD_FLAG=""
if [[ "$*" == *"--build"* ]]; then
  BUILD_FLAG="--build"
fi

# ── 1. Go to project root ─────────────────────────────────────────────────────
cd "$(dirname "$0")"
echo "📂  $(pwd)"

# ── 2. Start Docker Desktop if not already running ───────────────────────────
if ! docker info > /dev/null 2>&1; then
  echo "🐳  Starting Docker Desktop..."
  open -a Docker

  echo -n "   Waiting for Docker daemon"
  until docker info > /dev/null 2>&1; do
    echo -n "."
    sleep 2
  done
  echo " ready!"
else
  echo "🐳  Docker already running"
fi

# ── 3. Start desk-server (rebuild only if --build passed) ────────────────────
if [[ -n "$BUILD_FLAG" ]]; then
  echo "🔨  Building and starting desk-server..."
else
  echo "🚀  Starting desk-server (no rebuild)..."
fi
docker compose up $BUILD_FLAG -d desk-server

# ── 4. Start web frontend ─────────────────────────────────────────────────────
echo "🌐  Starting web frontend at http://localhost:3000"
cd web && npm run dev
