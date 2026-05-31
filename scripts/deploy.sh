#!/usr/bin/env bash
# Deploy the researchPapers backend on a fresh machine.
#
# Brings up ClickHouse via docker compose, restores a data dump if provided,
# applies UDF init SQL, and starts the FastAPI server.
#
# Usage:
#   ./scripts/deploy.sh                              # cold start, empty DB
#   ./scripts/deploy.sh /path/to/data.tar.gz         # restore from dump
#   API_HOST=0.0.0.0 API_PORT=8000 ./scripts/deploy.sh ...
#
# Prereqs on target machine:
#   - Docker (OrbStack, Docker Desktop, or vanilla Docker daemon)
#   - Python 3.11+ + uv (https://github.com/astral-sh/uv)
#   - ~1.5 GB free disk

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="${1:-}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"

cd "$REPO_ROOT"

echo "==> Verifying prerequisites..."
command -v docker >/dev/null || { echo "ERROR: docker not found"; exit 1; }
command -v uv >/dev/null || { echo "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
docker ps >/dev/null 2>&1 || { echo "ERROR: docker daemon not reachable"; exit 1; }

echo "==> Installing Python deps..."
uv sync --quiet

echo "==> Starting ClickHouse via docker compose..."
docker compose up -d clickhouse

echo "==> Waiting for ClickHouse..."
for i in {1..60}; do
  if curl -sf http://localhost:8123/ping >/dev/null 2>&1; then
    echo "    ready"
    break
  fi
  sleep 1
done

if [[ -n "$DUMP" ]]; then
  if [[ ! -f "$DUMP" ]]; then
    echo "ERROR: dump file not found: $DUMP"
    exit 1
  fi
  echo "==> Restoring data from $DUMP..."
  echo "    (stopping CH so we can replace the data dir cleanly)"
  docker compose stop clickhouse

  EXTRACT_DIR=$(mktemp -d)
  trap "rm -rf $EXTRACT_DIR" EXIT
  tar -xzf "$DUMP" -C "$EXTRACT_DIR"

  if [[ -d "$EXTRACT_DIR/clickhouse" ]]; then
    # Replace the docker volume contents. We mount the volume at startup; this
    # writes into the named volume via a one-shot container.
    docker run --rm \
      -v researchpapers_chdata:/var/lib/clickhouse \
      -v "$EXTRACT_DIR/clickhouse":/restore:ro \
      alpine sh -c "rm -rf /var/lib/clickhouse/* && cp -a /restore/. /var/lib/clickhouse/"
    echo "    CH data restored"
  fi

  if [[ -d "$EXTRACT_DIR/web_data" ]]; then
    mkdir -p "$REPO_ROOT/web/public/data"
    cp -R "$EXTRACT_DIR/web_data/." "$REPO_ROOT/web/public/data/"
    echo "    Web JSON exports restored"
  fi

  echo "==> Restarting ClickHouse..."
  docker compose up -d clickhouse
  for i in {1..60}; do
    if curl -sf http://localhost:8123/ping >/dev/null 2>&1; then break; fi
    sleep 1
  done
fi

echo "==> Applying SQL UDFs (effective_year / effective_date)..."
docker exec researchpapers_ch clickhouse-client --user papers --password papers -d papers --multiquery \
  < "$REPO_ROOT/clickhouse/init/02_functions.sql"

echo "==> Sanity check..."
COUNT=$(docker exec researchpapers_ch clickhouse-client --user papers --password papers -d papers -q "SELECT count() FROM papers" 2>/dev/null || echo "0")
echo "    papers in DB: $COUNT"

echo ""
echo "==> Starting API on http://${API_HOST}:${API_PORT}"
echo "    (Ctrl-C to stop)"
exec uv run papers api-serve --host "$API_HOST" --port "$API_PORT"
