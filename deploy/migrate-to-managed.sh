#!/usr/bin/env bash
# QuantLab -- one-time move from the VM's own Postgres and ClickHouse containers
# to the managed services (ClickHouse Cloud for bars, managed Postgres for the
# catalog).
#
# Runs ON the VM, as root, while the old stack is still up -- it reads from the
# running containers. Deploy the version without those containers only AFTER
# this has succeeded; remote-deploy.sh refuses to deploy until it has.
#
#   1. Put the managed services' settings in /opt/quantlab/.env.managed (mode 600):
#
#        QUANTLAB_DB_URL=postgresql://postgres@<pg-host>:5432/postgres?sslmode=require
#        PGPASSWORD=<postgres password>
#        QUANTLAB_CH_URL=clickhouses://default@<service>.clickhouse.cloud:8443/quantlab
#        QUANTLAB_CH_PASSWORD=<clickhouse password>
#
#   2. sudo bash migrate-to-managed.sh
#
# What it does, in order, stopping at the first failure:
#   - checks both targets answer, and refuses a target that already has tables
#     (FORCE=1 overrides -- only for re-running after a failed attempt);
#   - pauses the API, so no run is written half-way through the copy (it is
#     started again on any exit, success or not);
#   - Postgres: pg_dump from the container, pg_restore into the managed server;
#   - ClickHouse: recreates each table from its own DDL, streams its rows across
#     in Native format;
#   - compares every table's row count, source against target;
#   - only if all of them match: rewrites the four settings in .env (the old
#     file is kept as .env.pre-managed-<time>) and deletes .env.managed.
#
# Nothing is deleted from the old containers or their volumes. The Postgres dump
# is kept in /opt/quantlab/backups.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/quantlab}"
MANAGED_ENV="$APP_DIR/.env.managed"
BACKUP_DIR="$APP_DIR/backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PG_IMAGE="postgres:17-alpine"
# ClickHouse Cloud's native protocol is TLS on 9440. Overridable only so the
# whole script can be rehearsed against a plain local server first.
CH_NATIVE_PORT="${CH_NATIVE_PORT:-9440}"
CH_SECURE="${CH_SECURE:-1}"

log() { printf '\n==> %s\n' "$*"; }
fail() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

[ -w "$APP_DIR" ] || fail "cannot write $APP_DIR -- run with sudo"
[ -f "$MANAGED_ENV" ] || fail "$MANAGED_ENV is missing -- see the header of this script"

# --- targets -------------------------------------------------------------------
# Read the four keys literally rather than sourcing the file: a generated
# password may contain characters a shell would interpret.
setting() { sed -n "s/^$1=//p" "$MANAGED_ENV" | head -1; }
TARGET_DB_URL="$(setting QUANTLAB_DB_URL)"
TARGET_PGPASSWORD="$(setting PGPASSWORD)"
TARGET_CH_URL="$(setting QUANTLAB_CH_URL)"
TARGET_CH_PASSWORD="$(setting QUANTLAB_CH_PASSWORD)"
for name in TARGET_DB_URL TARGET_PGPASSWORD TARGET_CH_URL TARGET_CH_PASSWORD; do
	[ -n "${!name}" ] || fail "${name#TARGET_} is empty in $MANAGED_ENV"
done

# clickhouses://user@host[:port]/db -- the password is QUANTLAB_CH_PASSWORD.
re='^clickhouses?://([^:@/]+)(:[^@]*)?@([^:/?]+)(:[0-9]+)?/([A-Za-z0-9_]+)'
[[ "$TARGET_CH_URL" =~ $re ]] ||
	fail "QUANTLAB_CH_URL must look like clickhouses://default@<host>:8443/quantlab"
TARGET_CH_USER="${BASH_REMATCH[1]}"
TARGET_CH_HOST="${BASH_REMATCH[3]}"
TARGET_CH_DB="${BASH_REMATCH[5]}"

# --- sources: the running containers -------------------------------------------
container() {
	docker ps -q \
		--filter "label=com.docker.compose.project=quantlab" \
		--filter "label=com.docker.compose.service=$1" | head -1
}
PG_C="$(container postgres)"
CH_C="$(container clickhouse)"
BACKEND_C="$(container backend)"
[ -n "$PG_C" ] || fail "no running quantlab postgres container -- this copies FROM it, so run it before deploying the managed stack"
[ -n "$CH_C" ] || fail "no running quantlab clickhouse container"

# Credentials from the containers' own environment, not .env: they were fixed
# when the volumes were initialised and are what the servers actually accept.
SRC_PG_USER="$(docker exec "$PG_C" printenv POSTGRES_USER)"
SRC_PG_DB="$(docker exec "$PG_C" printenv POSTGRES_DB)"
SRC_CH_USER="$(docker exec "$CH_C" printenv CLICKHOUSE_USER)"
SRC_CH_PASSWORD="$(docker exec "$CH_C" printenv CLICKHOUSE_PASSWORD)"
SRC_CH_DB="$(docker exec "$CH_C" printenv CLICKHOUSE_DB)"

# Clients. Both ClickHouse ends run the client inside the source container (it
# ships one); the managed end is the secure native port, 9440.
src_psql() { docker exec -i "$PG_C" psql -v ON_ERROR_STOP=1 -U "$SRC_PG_USER" -d "$SRC_PG_DB" -Atq "$@"; }
tgt_psql() {
	docker run --rm -i -e PGPASSWORD="$TARGET_PGPASSWORD" "$PG_IMAGE" \
		psql -v ON_ERROR_STOP=1 "$TARGET_DB_URL" -Atq "$@"
}
src_ch() { docker exec -i "$CH_C" clickhouse-client --user "$SRC_CH_USER" --password "$SRC_CH_PASSWORD" "$@"; }
tgt_ch_tls=()
[ "$CH_SECURE" = "1" ] && tgt_ch_tls=(--secure)
tgt_ch() {
	docker exec -i "$CH_C" clickhouse-client --host "$TARGET_CH_HOST" --port "$CH_NATIVE_PORT" "${tgt_ch_tls[@]}" \
		--user "$TARGET_CH_USER" --password "$TARGET_CH_PASSWORD" "$@"
}

# --- preflight ------------------------------------------------------------------
log "checking the managed Postgres"
docker pull --quiet "$PG_IMAGE" >/dev/null
tgt_version="$(tgt_psql -c 'SHOW server_version_num')" || fail "cannot connect to the managed Postgres -- check QUANTLAB_DB_URL, PGPASSWORD and the service's IP allow-list"
src_version="$(src_psql -c 'SHOW server_version_num')"
printf 'source Postgres %s, target Postgres %s\n' "$src_version" "$tgt_version"
# A dump made by pg_dump 17 sets options (transaction_timeout) that older
# servers reject, so the target must be at least as new as the source.
[ "${tgt_version:0:2}" -ge "${src_version:0:2}" ] ||
	fail "the managed Postgres is older than the source ($tgt_version < $src_version); a dump cannot be restored into it"
tgt_tables="$(tgt_psql -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
if [ "$tgt_tables" != "0" ] && [ "${FORCE:-0}" != "1" ]; then
	fail "the managed Postgres already has $tgt_tables tables in public. Refusing to restore over them (FORCE=1 to override)."
fi

# The schema uses extensions (btree_gist, for exclusion constraints); a managed
# server that does not offer one fails the restore half-way, so check first.
for ext in $(src_psql -c "SELECT extname FROM pg_extension WHERE extname <> 'plpgsql' ORDER BY 1"); do
	[ "$(tgt_psql -c "SELECT count(*) FROM pg_available_extensions WHERE name = '$ext'")" = "1" ] ||
		fail "the managed Postgres does not offer the $ext extension, which the schema needs"
	printf 'extension %s: available\n' "$ext"
done

log "checking ClickHouse Cloud"
tgt_ch -q 'SELECT version()' >/dev/null ||
	fail "cannot connect to ClickHouse Cloud on $TARGET_CH_HOST:$CH_NATIVE_PORT -- check QUANTLAB_CH_URL, QUANTLAB_CH_PASSWORD and the service's IP allow-list"
tgt_ch_tables="$(tgt_ch -q "SELECT count() FROM system.tables WHERE database = '$TARGET_CH_DB'")"
if [ "$tgt_ch_tables" != "0" ] && [ "${FORCE:-0}" != "1" ]; then
	fail "ClickHouse Cloud already has $tgt_ch_tables tables in $TARGET_CH_DB. Refusing to copy over them (FORCE=1 to override)."
fi

# A foreign key the source marks as valid can still have been violated -- a
# bulk load or a test that bypassed triggers leaves rows pointing at nothing.
# pg_restore re-checks every constraint and would stop half-way on them, so
# find them now, before anything is paused or copied.
log "checking the source's foreign keys"
orphans="$(src_psql 2>&1 <<'SQL'
DO $$
DECLARE r record; n bigint;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS child, c.confrelid::regclass AS parent,
           (SELECT string_agg('ch.' || quote_ident(a.attname), ',' ORDER BY k.ord)
              FROM unnest(c.conkey) WITH ORDINALITY k(n, ord)
              JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n) AS ccols,
           (SELECT string_agg('p.' || quote_ident(a.attname), ',' ORDER BY k.ord)
              FROM unnest(c.confkey) WITH ORDINALITY k(n, ord)
              JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.n) AS pcols
      FROM pg_constraint c
     WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
  LOOP
    EXECUTE format(
      'SELECT count(*) FROM %s ch WHERE (%s) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM %s p WHERE (%s) = (%s))',
      r.child, r.ccols, r.parent, r.pcols, r.ccols) INTO n;
    IF n > 0 THEN RAISE NOTICE 'ORPHAN % % % rows point at missing % rows', r.conname, r.child, n, r.parent; END IF;
  END LOOP;
END $$;
SQL
)" || true
orphans="$(printf '%s\n' "$orphans" | grep 'ORPHAN' || true)"
[ -z "$orphans" ] || fail "the source Postgres has rows that break its own foreign keys, which pg_restore will refuse:
$orphans
Delete or repair them in the source first."

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
need_kb=$(($(src_psql -c "SELECT pg_database_size(current_database())") / 1024))
free_kb="$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
[ "$free_kb" -gt "$need_kb" ] ||
	fail "not enough disk for the dump: ${free_kb} KiB free, the database is ${need_kb} KiB"

# --- pause the API ----------------------------------------------------------------
if [ -n "$BACKEND_C" ]; then
	log "pausing the API for the copy"
	docker stop "$BACKEND_C" >/dev/null
	trap 'log "starting the API again"; docker start "$BACKEND_C" >/dev/null || true' EXIT
fi

# --- Postgres -------------------------------------------------------------------
dump="$BACKUP_DIR/postgres-$STAMP.dump"
log "dumping Postgres to $dump"
docker exec "$PG_C" pg_dump -U "$SRC_PG_USER" -d "$SRC_PG_DB" -Fc --no-owner --no-acl >"$dump"
chmod 600 "$dump"
ls -lh "$dump"

log "restoring into the managed Postgres (the largest table takes a while)"
docker run --rm -e PGPASSWORD="$TARGET_PGPASSWORD" -v "$BACKUP_DIR:/backups:ro" "$PG_IMAGE" \
	pg_restore --no-owner --no-acl --exit-on-error --jobs 4 \
	--dbname "$TARGET_DB_URL" "/backups/$(basename "$dump")"

# --- ClickHouse -----------------------------------------------------------------
log "copying ClickHouse $SRC_CH_DB -> $TARGET_CH_DB"
tgt_ch -q "CREATE DATABASE IF NOT EXISTS $TARGET_CH_DB"
# Tables before views: a view's DDL names the table it reads.
mapfile -t ch_tables < <(src_ch -q "SELECT name FROM system.tables WHERE database = '$SRC_CH_DB' ORDER BY engine LIKE '%View', name")
for table in "${ch_tables[@]}"; do
	ddl="$(src_ch -q "SHOW CREATE TABLE $SRC_CH_DB.$table FORMAT TSVRaw" </dev/null)"
	ddl="${ddl//$SRC_CH_DB./$TARGET_CH_DB.}"
	tgt_ch -q "$ddl" </dev/null
	engine="$(src_ch -q "SELECT engine FROM system.tables WHERE database = '$SRC_CH_DB' AND name = '$table'" </dev/null)"
	case "$engine" in
	*View) printf '  %s: view created\n' "$table" ;;
	*)
		# Rows leave in sort order -- one instrument's whole history together --
		# so one block spans ~200 monthly partitions, past the default cap of
		# 100 per insert block. Lift it for the copy only.
		src_ch -q "SELECT * FROM $SRC_CH_DB.$table FORMAT Native" </dev/null |
			tgt_ch --max_partitions_per_insert_block=0 -q "INSERT INTO $TARGET_CH_DB.$table FORMAT Native"
		printf '  %s: copied\n' "$table"
		;;
	esac
done

# --- verify -----------------------------------------------------------------------
log "comparing row counts"
# Lists read into arrays first, and every client below given /dev/null as
# stdin: `docker exec -i` / `docker run -i` read stdin, and inside a
# `while read` loop they would swallow the rest of the list -- comparing one
# table and reporting success.
mapfile -t pg_tables < <(src_psql -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1")
mapfile -t ch_data_tables < <(src_ch -q "SELECT name FROM system.tables WHERE database = '$SRC_CH_DB' AND engine NOT LIKE '%View' ORDER BY name")
[ "${#pg_tables[@]}" -gt 0 ] || fail "found no Postgres tables to compare"
[ "${#ch_data_tables[@]}" -gt 0 ] || fail "found no ClickHouse tables to compare"
mismatch=0
compare() {
	local system="$1" table="$2" a="$3" b="$4" mark=ok
	if [ "$a" != "$b" ]; then
		mark=MISMATCH
		mismatch=1
	fi
	printf '  %-10s %-24s %12s %12s  %s\n' "$system" "$table" "$a" "$b" "$mark"
}
for table in "${pg_tables[@]}"; do
	compare postgres "$table" \
		"$(src_psql -c "SELECT count(*) FROM public.\"$table\"" </dev/null)" \
		"$(tgt_psql -c "SELECT count(*) FROM public.\"$table\"" </dev/null)"
done
for table in "${ch_data_tables[@]}"; do
	compare clickhouse "$table" \
		"$(src_ch -q "SELECT count() FROM $SRC_CH_DB.$table" </dev/null)" \
		"$(tgt_ch -q "SELECT count() FROM $TARGET_CH_DB.$table" </dev/null)"
done
printf '  %d Postgres and %d ClickHouse tables compared\n' "${#pg_tables[@]}" "${#ch_data_tables[@]}"
[ "$mismatch" -eq 0 ] || fail "row counts differ -- .env was NOT changed; the stack still uses the containers"

# --- switch .env ------------------------------------------------------------------
log "switching $APP_DIR/.env to the managed services"
cp -p "$APP_DIR/.env" "$APP_DIR/.env.pre-managed-$STAMP"
set_setting() {
	local key="$1" value="$2" tmp
	tmp="$(mktemp "$APP_DIR/.env.XXXXXX")"
	grep -v "^$key=" "$APP_DIR/.env" >"$tmp" || true
	printf '%s=%s\n' "$key" "$value" >>"$tmp"
	chmod 600 "$tmp"
	mv "$tmp" "$APP_DIR/.env"
}
set_setting QUANTLAB_DB_URL "$TARGET_DB_URL"
set_setting PGPASSWORD "$TARGET_PGPASSWORD"
set_setting QUANTLAB_CH_URL "$TARGET_CH_URL"
set_setting QUANTLAB_CH_PASSWORD "$TARGET_CH_PASSWORD"
rm -f "$MANAGED_ENV"

cat <<DONE

Done. Every table matched, and .env now points at the managed services.
  - Previous .env:  $APP_DIR/.env.pre-managed-$STAMP
  - Postgres dump:  $dump

The API was started again on its OLD configuration (still reading the
containers). The next deploy -- merging the change that removes the database
containers -- switches it to the managed services.
DONE
