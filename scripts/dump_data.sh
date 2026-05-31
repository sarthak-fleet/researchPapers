#!/usr/bin/env bash
# Dump ClickHouse data + sample web exports for transport to another machine.
#
# Output: ./researchpapers_data_${TIMESTAMP}.tar.gz containing
#   - clickhouse/  : a snapshot of the running CH data directory
#   - web_data/    : the JSON exports the Astro app reads
#
# Usage:
#   ./scripts/dump_data.sh                 # writes to repo root
#   ./scripts/dump_data.sh /path/to/dump   # writes to custom path
#
# On the target machine, see ./scripts/deploy.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$REPO_ROOT}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
DUMP_NAME="researchpapers_data_${TIMESTAMP}"
WORK_DIR=$(mktemp -d)

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

echo "==> Verifying CH is up..."
docker ps --format '{{.Names}}' | grep -q researchpapers_ch || {
  echo "ERROR: researchpapers_ch container is not running. Start it with: docker compose up -d clickhouse"
  exit 1
}

echo "==> Flushing ClickHouse buffers..."
docker exec researchpapers_ch clickhouse-client --user papers --password papers -d papers -q "SYSTEM FLUSH LOGS" >/dev/null
docker exec researchpapers_ch clickhouse-client --user papers --password papers -d papers -q "SYSTEM SYNC REPLICA papers" 2>/dev/null || true

echo "==> Dumping CH data (this can take a minute on a large volume)..."
mkdir -p "$WORK_DIR/clickhouse"
# Copy the live data dir out of the container, including format_schemas + metadata.
# CH allows hot copies for MergeTree as long as we don't touch parts being merged;
# fine for a one-shot snapshot.
docker exec researchpapers_ch sh -c 'tar -C /var/lib/clickhouse -cf - .' \
  | tar -C "$WORK_DIR/clickhouse" -xf -

echo "==> Copying web exports (JSON the Astro app reads)..."
mkdir -p "$WORK_DIR/web_data"
cp -R "$REPO_ROOT/web/public/data/." "$WORK_DIR/web_data/" 2>/dev/null || true

echo "==> Compressing..."
OUT_FILE="${OUT_DIR}/${DUMP_NAME}.tar.gz"
tar -C "$WORK_DIR" -czf "$OUT_FILE" .

SIZE=$(du -h "$OUT_FILE" | cut -f1)
echo ""
echo "Dump written: $OUT_FILE ($SIZE)"
echo "Transfer to target machine, then run:  ./scripts/deploy.sh $OUT_FILE"
