#!/usr/bin/env bash
# Back up the NavigIQ database and prove the backup restores.
#
#   scripts/backup_restore_check.sh                 # uses the navigiq_db container
#   DB_CONTAINER=navigiq_db DB_USER=navigiq_user DB_NAME=navigiq scripts/backup_restore_check.sh
#
# 1. pg_dump (custom format) of the live database into data/artifacts/backups/
# 2. restore it into a scratch database inside the same container
# 3. compare row counts of the tables that matter, and check PostGIS/pgvector
# 4. drop the scratch database
# The live database is only read. Exit code is non-zero if anything differs.
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-navigiq_db}"
DB_USER="${DB_USER:-navigiq_user}"
DB_NAME="${DB_NAME:-navigiq}"
SCRATCH="${DB_NAME}_restore_check"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/data/artifacts/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="navigiq-$STAMP.dump"
mkdir -p "$OUT_DIR"

psql() { docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -v ON_ERROR_STOP=1 -At "$@"; }

echo "== backup $DB_NAME -> $OUT_DIR/$FILE"
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc -f "/tmp/$FILE"
# Git Bash on Windows: container paths must not be rewritten (MSYS_NO_PATHCONV=1)
# but the host path must be a Windows path for docker cp.
HOST_OUT="$(cygpath -w "$OUT_DIR" 2>/dev/null || echo "$OUT_DIR")"
docker cp "$DB_CONTAINER:/tmp/$FILE" "$HOST_OUT/$FILE"
ls -lh "$OUT_DIR/$FILE" | awk '{print "   size:", $5}'

echo "== restore into $SCRATCH"
psql -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null
psql -d postgres -c "CREATE DATABASE $SCRATCH" >/dev/null
docker exec "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$SCRATCH" --no-owner "/tmp/$FILE"

TABLES="pois poi_opening_hours poi_aliases places \"user\" user_preferences saved_pois itineraries itinerary_versions itinerary_stops knowledge_documents knowledge_chunks conversations messages alembic_version"
status=0
printf "   %-22s %10s %10s\n" table live restored
for t in $TABLES; do
  live=$(psql -d "$DB_NAME" -c "SELECT count(*) FROM $t" 2>/dev/null || echo "n/a")
  restored=$(psql -d "$SCRATCH" -c "SELECT count(*) FROM $t" 2>/dev/null || echo "n/a")
  mark=""; [ "$live" != "$restored" ] && { mark="  <-- differs"; status=1; }
  printf "   %-22s %10s %10s%s\n" "$t" "$live" "$restored" "$mark"
done

echo "== spatial and vector data survive the round trip"
psql -d "$SCRATCH" -c "SELECT 'postgis ' || postgis_lib_version()"
psql -d "$SCRATCH" -c "SELECT 'pgvector ' || extversion FROM pg_extension WHERE extname = 'vector'"
psql -d "$SCRATCH" -c "SELECT 'geometries valid: ' || bool_and(ST_IsValid(geom::geometry)) FROM pois"
psql -d "$SCRATCH" -c "SELECT 'embeddings: ' || count(*) FROM knowledge_chunks WHERE embedding IS NOT NULL" || true

psql -d postgres -c "DROP DATABASE $SCRATCH" >/dev/null
docker exec "$DB_CONTAINER" rm -f "/tmp/$FILE"
[ $status -eq 0 ] && echo "== OK: backup restores with identical row counts" || echo "== FAILED: counts differ"
exit $status
