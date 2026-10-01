#!/usr/bin/env bash
# QuantLab -- one-time move from the managed services (ClickHouse Cloud for
# bars, managed Postgres for the catalog) back to Postgres and ClickHouse
# containers on this VM, with their data on the separate data disk.
#
# Runs ON the VM, as root, while the managed stack is still serving. Nothing in
# the managed services is modified or deleted: they stay as the rollback.
#
#   1. Mount the data disk:     sudo bash prepare-data-disk.sh /dev/disk/by-id/google-<disk>
#   2. Put the NEW local settings in /opt/quantlab/.env.selfhost (mode 600):
#
#        QUANTLAB_DATA_DIR=/mnt/disks/quantlab
#        QUANTLAB_PG_USER=quantlab
#        QUANTLAB_PG_PASSWORD=<openssl rand -hex 24>
#        QUANTLAB_CH_USER=quantlab
#        QUANTLAB_CH_PASSWORD=<openssl rand -hex 24>
#        QUANTLAB_DB_URL=postgresql://quantlab@postgres:5432/quantlab
#        QUANTLAB_CH_URL=clickhouse://quantlab@clickhouse:8123/quantlab
#
#   3. Copy the new docker-compose.prod.yml, clickhouse-limits.xml and
#      clickhouse-users.xml into
#      STAGE_DIR (default /opt/quantlab/selfhost-staging), then:
#
#        sudo bash migrate-to-selfhost.sh            # bulk copy + cutover
#        sudo PHASE=bulk bash migrate-to-selfhost.sh  # bulk ClickHouse copy only
#
# What it does, in order, stopping at the first failure:
#   - starts the local postgres and clickhouse containers (only those);
#   - ClickHouse, with the API still serving: creates the schema (the repo's
#     own migration -- Cloud's Shared*MergeTree DDL does not run outside
#     Cloud -- plus any views the source has), copies schema_migrations, then
#     copies price_bars ONE MONTHLY PARTITION AT A TIME. Each month is checked
#     against the source by row count and a content hash, both taken with
#     FINAL so neither side's background merges can make equal data look
#     different; a month that does not match is dropped and copied again.
#     Re-running skips months that still match, so the slow bulk copy can run
#     hours before the cutover and the cutover only re-copies what changed;
#   - pauses the API (started again on any exit), so nothing is written to the
#     catalog half-way through its copy;
#   - Postgres: pg_dump from the managed server (excluding provider-specific
#     extensions the stock image does not have), pg_restore into the local one;
#   - compares every Postgres table's row count, source against target;
#   - only if everything matched: rewrites .env (the old file is kept as
#     .env.pre-selfhost-<time>, with the managed credentials in it), installs
#     the staged compose file and brings the whole stack up on it.
#
# Rollback, before anything new is written to the local databases: restore
# .env.pre-selfhost-<time> as .env, put the previous compose file back
# (docker-compose.prod.yml.pre-selfhost-<time>) and `docker compose up -d`.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/quantlab}"
STAGE_DIR="${STAGE_DIR:-$APP_DIR/selfhost-staging}"
SELFHOST_ENV="$APP_DIR/.env.selfhost"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
PHASE="${PHASE:-all}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PG_IMAGE="postgres:18-alpine"
CH_IMAGE="clickhouse/clickhouse-server:24.8-alpine"
# Extensions the managed provider installs that a stock Postgres does not ship.
SKIP_EXTENSIONS="${SKIP_EXTENSIONS:-pg_stat_ch}"

log() { printf '\n[%s] ==> %s\n' "$(date -u +%T)" "$*"; }
fail() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

[ -w "$APP_DIR" ] || fail "cannot write $APP_DIR -- run with sudo"
[ -f "$SELFHOST_ENV" ] || fail "$SELFHOST_ENV is missing -- see the header of this script"
[ -f "$STAGE_DIR/docker-compose.prod.yml" ] || fail "no staged compose file in $STAGE_DIR"
for f in clickhouse-limits.xml clickhouse-users.xml; do
	[ -f "$STAGE_DIR/$f" ] || fail "no staged $f in $STAGE_DIR"
done

# Settings are read literally, never sourced: a password may hold characters a
# shell would interpret.
from() { sed -n "s/^$2=//p" "$1" | head -1; }
SRC_DB_URL="$(from "$APP_DIR/.env" QUANTLAB_DB_URL)"
SRC_PGPASSWORD="$(from "$APP_DIR/.env" PGPASSWORD)"
SRC_CH_URL="$(from "$APP_DIR/.env" QUANTLAB_CH_URL)"
SRC_CH_PASSWORD="$(from "$APP_DIR/.env" QUANTLAB_CH_PASSWORD)"
case "$SRC_CH_URL" in
*@clickhouse:* | *@clickhouse/*) fail ".env already points at the local clickhouse -- nothing to migrate" ;;
esac
re='^clickhouses?://([^:@/]+)(:[^@]*)?@([^:/?]+)(:[0-9]+)?/([A-Za-z0-9_]+)'
[[ "$SRC_CH_URL" =~ $re ]] || fail "QUANTLAB_CH_URL in .env is not a ClickHouse URL"
SRC_CH_USER="${BASH_REMATCH[1]}"
SRC_CH_HOST="${BASH_REMATCH[3]}"
SRC_CH_DB="${BASH_REMATCH[5]}"

DATA_DIR="$(from "$SELFHOST_ENV" QUANTLAB_DATA_DIR)"
DATA_DIR="${DATA_DIR:-/mnt/disks/quantlab}"
DST_PG_USER="$(from "$SELFHOST_ENV" QUANTLAB_PG_USER)"
DST_CH_USER="$(from "$SELFHOST_ENV" QUANTLAB_CH_USER)"
DST_CH_PASSWORD="$(from "$SELFHOST_ENV" QUANTLAB_CH_PASSWORD)"
for name in DST_PG_USER DST_CH_USER DST_CH_PASSWORD; do
	[ -n "${!name}" ] || fail "${name#DST_} is empty in $SELFHOST_ENV"
done
mountpoint -q "$DATA_DIR" || fail "$DATA_DIR is not mounted -- run prepare-data-disk.sh first"

compose() {
	docker compose -p quantlab --env-file "$APP_DIR/.env" --env-file "$APP_DIR/.env.images" \
		--env-file "$SELFHOST_ENV" -f "$STAGE_DIR/docker-compose.prod.yml" "$@"
}
container() {
	docker ps -q --filter "label=com.docker.compose.project=quantlab" \
		--filter "label=com.docker.compose.service=$1" | head -1
}

# Every client gets /dev/null as stdin unless it is the receiving end of a
# pipe: `docker run -i` / `docker exec -i` read stdin, and in a loop they would
# swallow the rest of the list.
src_ch() {
	docker run --rm -i "$CH_IMAGE" clickhouse-client --host "$SRC_CH_HOST" --port 9440 --secure \
		--user "$SRC_CH_USER" --password "$SRC_CH_PASSWORD" "$@"
}
src_psql() {
	docker run --rm -i -e PGPASSWORD="$SRC_PGPASSWORD" "$PG_IMAGE" \
		psql -v ON_ERROR_STOP=1 "$SRC_DB_URL" -Atq "$@"
}

# --- local containers ------------------------------------------------------------
log "starting the local postgres and clickhouse (only those)"
docker pull -q "$PG_IMAGE" >/dev/null
docker pull -q "$CH_IMAGE" >/dev/null
compose up -d --no-deps postgres clickhouse
for _ in $(seq 1 60); do
	pg_c="$(container postgres)"
	ch_c="$(container clickhouse)"
	if [ -n "$pg_c" ] && [ -n "$ch_c" ] &&
		[ "$(docker inspect -f '{{.State.Health.Status}}' "$pg_c")" = healthy ] &&
		[ "$(docker inspect -f '{{.State.Health.Status}}' "$ch_c")" = healthy ]; then
		break
	fi
	sleep 3
done
PG_C="$(container postgres)"
CH_C="$(container clickhouse)"
[ "$(docker inspect -f '{{.State.Health.Status}}' "$CH_C")" = healthy ] || fail "local clickhouse is not healthy"
[ "$(docker inspect -f '{{.State.Health.Status}}' "$PG_C")" = healthy ] || fail "local postgres is not healthy"
dst_ch() { docker exec -i "$CH_C" clickhouse-client --user "$DST_CH_USER" --password "$DST_CH_PASSWORD" --database quantlab "$@"; }
dst_psql() { docker exec -i "$PG_C" psql -v ON_ERROR_STOP=1 -U "$DST_PG_USER" -d quantlab -Atq "$@"; }

# --- ClickHouse ------------------------------------------------------------------
log "ClickHouse: schema"
src_ch -q 'SELECT 1' </dev/null >/dev/null ||
	fail "cannot reach ClickHouse Cloud at $SRC_CH_HOST:9440 -- check the service's IP allow-list"
# The table from the repo's own migration (stock ReplacingMergeTree); its
# checksum is what the source recorded, so `migrate` later finds it applied.
docker run --rm --entrypoint sh "$(from "$APP_DIR/.env.images" QUANTLAB_INGEST_IMAGE)" \
	-c 'cat "$(python -c "import importlib; print(importlib.import_module(\"quantlab.store.migrate\").CH_MIGRATIONS_DIR)")"/*.sql' |
	dst_ch --multiquery
# Views: plain SELECTs, portable as the source wrote them. Views over views
# are created in dependency order by retrying the ones whose source is missing.
mapfile -t views < <(src_ch -q "SELECT name FROM system.tables WHERE database = '$SRC_CH_DB' AND engine = 'View' ORDER BY name" </dev/null)
for _ in 1 2 3; do
	for view in "${views[@]}"; do
		ddl="$(src_ch -q "SHOW CREATE TABLE $SRC_CH_DB.$view FORMAT TSVRaw" </dev/null)"
		ddl="${ddl/CREATE VIEW/CREATE VIEW IF NOT EXISTS}"
		ddl="${ddl//$SRC_CH_DB./quantlab.}"
		dst_ch -q "$ddl" </dev/null 2>/dev/null || true
	done
done
for view in "${views[@]}"; do
	[ "$(dst_ch -q "EXISTS TABLE $view" </dev/null)" = 1 ] || fail "could not create view $view locally"
done
dst_ch -q "TRUNCATE TABLE IF EXISTS schema_migrations" </dev/null
src_ch -q "SELECT version, checksum, applied_at FROM $SRC_CH_DB.schema_migrations FINAL FORMAT Native" </dev/null |
	dst_ch -q "INSERT INTO schema_migrations (version, checksum, applied_at) FORMAT Native"
printf '  migrations: %s\n' "$(dst_ch -q "SELECT arrayStringConcat(groupArray(version), ' ') FROM (SELECT version FROM schema_migrations FINAL ORDER BY version)" </dev/null)"

log "ClickHouse: price_bars, one monthly partition at a time"
SIG="count(), sum(cityHash64(instrument_id, frequency, ts, open, high, low, close, volume, adj_close, currency, source, run_id))"
mapfile -t parts < <(src_ch -q "SELECT DISTINCT partition FROM system.parts WHERE active AND database = '$SRC_CH_DB' AND table = 'price_bars' ORDER BY partition" </dev/null)
[ "${#parts[@]}" -gt 0 ] || fail "the source has no price_bars partitions"
copied=0
for p in "${parts[@]}"; do
	want="$(src_ch -q "SELECT $SIG FROM $SRC_CH_DB.price_bars FINAL WHERE toYYYYMM(ts) = $p FORMAT TSV" </dev/null)"
	got="$(dst_ch -q "SELECT $SIG FROM price_bars FINAL WHERE toYYYYMM(ts) = $p FORMAT TSV" </dev/null)"
	[ "$want" = "$got" ] && continue
	ok=0
	for attempt in 1 2 3; do
		dst_ch -q "ALTER TABLE price_bars DROP PARTITION $p" </dev/null 2>/dev/null || true
		src_ch -q "SELECT * FROM $SRC_CH_DB.price_bars WHERE toYYYYMM(ts) = $p FORMAT Native" </dev/null |
			dst_ch -q "INSERT INTO price_bars FORMAT Native"
		got="$(dst_ch -q "SELECT $SIG FROM price_bars FINAL WHERE toYYYYMM(ts) = $p FORMAT TSV" </dev/null)"
		if [ "$want" = "$got" ]; then
			ok=1
			break
		fi
		printf '  %s attempt %d: source [%s] local [%s]\n' "$p" "$attempt" "$want" "$got"
	done
	[ "$ok" = 1 ] || fail "partition $p did not match after 3 attempts"
	copied=$((copied + 1))
	printf '  %s: %s rows\n' "$p" "${got%%[[:space:]]*}"
done
# A month the source no longer has must not survive locally either.
extra="$(dst_ch -q "SELECT DISTINCT partition FROM system.parts WHERE active AND database = 'quantlab' AND table = 'price_bars' AND partition NOT IN ('$(
	IFS=,
	printf '%s' "${parts[*]}" | sed "s/,/','/g"
)')" </dev/null)"
[ -z "$extra" ] || fail "local price_bars has partitions the source does not: $extra"
printf '  %d partitions verified, %d (re)copied this run\n' "${#parts[@]}" "$copied"

# A partition copied in several insert blocks lands as several parts, and
# FINAL (which every read goes through, via price_bars_current) must merge
# them at query time. Right after a bulk copy that pushed a whole-table FINAL
# past the 2 GiB server cap. Merge each month to one part now, a month at a
# time so no single merge is large.
log "ClickHouse: merging each partition to a single part"
mapfile -t multi < <(dst_ch -q "SELECT partition FROM system.parts WHERE active AND database = 'quantlab' AND table = 'price_bars' GROUP BY partition HAVING count() > 1 ORDER BY partition" </dev/null)
for p in "${multi[@]}"; do
	dst_ch -q "OPTIMIZE TABLE price_bars PARTITION $p FINAL" </dev/null
done
printf '  %d partitions merged\n' "${#multi[@]}"

[ "$PHASE" = bulk ] && {
	log "bulk phase done; run again without PHASE=bulk to cut over"
	exit 0
}

# --- Postgres --------------------------------------------------------------------
log "Postgres: preflight"
src_version="$(src_psql -c 'SHOW server_version_num' </dev/null)"
dst_version="$(dst_psql -c 'SHOW server_version_num' </dev/null)"
printf '  managed %s, local %s\n' "$src_version" "$dst_version"
[ "${dst_version:0:2}" -ge "${src_version:0:2}" ] ||
	fail "local Postgres is older than the managed one; its dump cannot be restored"
dst_tables="$(dst_psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" </dev/null)"
if [ "$dst_tables" != 0 ] && [ "${FORCE:-0}" != 1 ]; then
	fail "the local Postgres already has $dst_tables tables. Refusing to restore over them (FORCE=1 drops and recreates its public schema)."
fi
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

BACKEND_C="$(container backend)"
if [ -n "$BACKEND_C" ]; then
	log "pausing the API for the catalog copy"
	docker stop "$BACKEND_C" >/dev/null
	trap 'log "starting the API again on its previous configuration"; docker start "$BACKEND_C" >/dev/null || true' EXIT
fi

dump="$BACKUP_DIR/managed-postgres-$STAMP.dump"
log "Postgres: dumping the managed catalog to $dump"
exclude=()
for ext in $SKIP_EXTENSIONS; do exclude+=(--exclude-extension "$ext"); done
docker run --rm -e PGPASSWORD="$SRC_PGPASSWORD" -v "$BACKUP_DIR:/backups" "$PG_IMAGE" \
	pg_dump "$SRC_DB_URL" -Fc --no-owner --no-acl "${exclude[@]}" -f "/backups/$(basename "$dump")"
chmod 600 "$dump"
ls -lh "$dump"

if [ "$dst_tables" != 0 ]; then
	dst_psql -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' </dev/null
fi
log "Postgres: restoring into the local server"
docker exec -i "$PG_C" pg_restore -U "$DST_PG_USER" -d quantlab --no-owner --no-acl --exit-on-error <"$dump"

log "Postgres: comparing row counts"
mapfile -t pg_tables < <(src_psql -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1" </dev/null)
[ "${#pg_tables[@]}" -gt 0 ] || fail "found no Postgres tables to compare"
mismatch=0
for table in "${pg_tables[@]}"; do
	a="$(src_psql -c "SELECT count(*) FROM public.\"$table\"" </dev/null)"
	b="$(dst_psql -c "SELECT count(*) FROM public.\"$table\"" </dev/null)"
	mark=ok
	if [ "$a" != "$b" ]; then
		mark=MISMATCH
		mismatch=1
	fi
	printf '  %-24s %12s %12s  %s\n' "$table" "$a" "$b" "$mark"
done
[ "$mismatch" = 0 ] || fail "Postgres row counts differ -- .env was NOT changed; the API restarts on the managed services"

# --- switch ------------------------------------------------------------------------
log "switching .env and the compose file to the self-hosted datastores"
cp -p "$APP_DIR/.env" "$APP_DIR/.env.pre-selfhost-$STAMP"
cp -p "$APP_DIR/docker-compose.prod.yml" "$APP_DIR/docker-compose.prod.yml.pre-selfhost-$STAMP"
tmp="$(mktemp "$APP_DIR/.env.XXXXXX")"
# Drop every setting .env.selfhost replaces, plus PGPASSWORD: the compose file
# now derives the clients' password from QUANTLAB_PG_PASSWORD.
keys="$(sed -n 's/^\([A-Z_]*\)=.*/\1/p' "$SELFHOST_ENV" | paste -sd'|' -)"
grep -Ev "^(${keys}|PGPASSWORD)=" "$APP_DIR/.env" >"$tmp" || true
{
	printf '\n# Self-hosted datastores since %s (deploy/migrate-to-selfhost.sh).\n' "$STAMP"
	printf '# The managed services settings are in .env.pre-selfhost-%s.\n' "$STAMP"
	grep -E '^[A-Z_]+=' "$SELFHOST_ENV"
} >>"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$APP_DIR/.env"
install -o root -g root -m 0644 "$STAGE_DIR/docker-compose.prod.yml" "$APP_DIR/docker-compose.prod.yml"
for f in clickhouse-limits.xml clickhouse-users.xml; do
	install -o root -g root -m 0644 "$STAGE_DIR/$f" "$APP_DIR/$f"
done

trap - EXIT
log "bringing the stack up on the self-hosted datastores"
cd "$APP_DIR"
docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml up -d --remove-orphans
for _ in $(seq 1 60); do
	b="$(container backend)"
	[ -n "$b" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$b")" = healthy ] && break
	sleep 5
done
b="$(container backend)"
[ -n "$b" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$b")" = healthy ] ||
	fail "the backend did not become healthy on the new datastores -- see 'docker compose logs backend migrate'. Roll back with .env.pre-selfhost-$STAMP."
docker exec "$b" python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://localhost:8000/api/v1/health')))"

cat <<DONE

Done. Every ClickHouse partition and Postgres table matched, and the stack now
runs on the self-hosted datastores in $DATA_DIR.
  - Previous .env (managed credentials): $APP_DIR/.env.pre-selfhost-$STAMP
  - Previous compose file:               $APP_DIR/docker-compose.prod.yml.pre-selfhost-$STAMP
  - Managed Postgres dump:               $dump
The managed services were not modified. Keep them until the local copy is
trusted, then delete them from their consoles.
DONE
