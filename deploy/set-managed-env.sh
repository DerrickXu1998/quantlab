#!/usr/bin/env bash
# QuantLab -- point an existing VM at managed Postgres + ClickHouse without
# running the full migrate-to-managed.sh copy.
#
# Use this ONLY when the managed databases already contain the data you need
# (for example, after migrating manually or when standing up a fresh VM against
# an already-populated managed warehouse). It updates /opt/quantlab/.env in
# place and backs up the previous version.
#
# Required environment:
#   QUANTLAB_DB_URL      e.g. postgresql://postgres@<host>:5432/postgres?sslmode=require
#   PGPASSWORD           the managed Postgres password
#   QUANTLAB_CH_URL      e.g. clickhouses://default@<host>:8443/quantlab
#   QUANTLAB_CH_PASSWORD the managed ClickHouse password
#   GCP_INSTANCE         the Compute Engine instance name
#   GCP_ZONE             the instance zone
#
# Example:
#   QUANTLAB_DB_URL=postgresql://postgres@... \
#   PGPASSWORD=... \
#   QUANTLAB_CH_URL=clickhouses://default@... \
#   QUANTLAB_CH_PASSWORD=... \
#   GCP_INSTANCE=quantlab-vm \
#   GCP_ZONE=europe-west2-c \
#   bash deploy/set-managed-env.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/quantlab}"

for var in QUANTLAB_DB_URL PGPASSWORD QUANTLAB_CH_URL QUANTLAB_CH_PASSWORD GCP_INSTANCE GCP_ZONE; do
  [ -n "${!var:-}" ] || { echo "ERROR: $var is not set" >&2; exit 1; }
done

# The deploy guard rejects these legacy in-compose host patterns.
case "$QUANTLAB_DB_URL" in
  *@postgres:* | *@postgres/*)
    echo "ERROR: QUANTLAB_DB_URL looks like the retired in-compose Postgres" >&2
    exit 1
    ;;
esac
case "$QUANTLAB_CH_URL" in
  *@clickhouse:* | *@clickhouse/*)
    echo "ERROR: QUANTLAB_CH_URL looks like the retired in-compose ClickHouse" >&2
    exit 1
    ;;
esac

echo "Updating $APP_DIR/.env on $GCP_INSTANCE ($GCP_ZONE)"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

# Run on the VM through IAP. The commands build a new .env from the old one,
# keeping every line except the four managed keys, then append the new values.
# sudo is required because /opt/quantlab/.env is root-readable (mode 0600).
gcloud compute ssh "$GCP_INSTANCE" \
  --zone "$GCP_ZONE" \
  --tunnel-through-iap \
  --quiet \
  --command "
    set -euo pipefail
    [ -d '$APP_DIR' ] || { echo 'ERROR: $APP_DIR does not exist' >&2; exit 1; }
    [ -f '$APP_DIR/.env' ] || { echo 'ERROR: $APP_DIR/.env is missing' >&2; exit 1; }

    sudo cp -p '$APP_DIR/.env' '$APP_DIR/.env.pre-managed-$STAMP'

    tmp=\"\$(sudo mktemp '$APP_DIR/.env.XXXXXX')\"
    # Drop the managed keys if they exist.
    sudo grep -v -E '^(QUANTLAB_DB_URL|PGPASSWORD|QUANTLAB_CH_URL|QUANTLAB_CH_PASSWORD)=' '$APP_DIR/.env' | sudo tee \"\$tmp\" >/dev/null || true

    {
      echo 'QUANTLAB_DB_URL=$QUANTLAB_DB_URL'
      echo 'PGPASSWORD=$PGPASSWORD'
      echo 'QUANTLAB_CH_URL=$QUANTLAB_CH_URL'
      echo 'QUANTLAB_CH_PASSWORD=$QUANTLAB_CH_PASSWORD'
    } | sudo tee -a \"\$tmp\" >/dev/null

    sudo chmod 600 \"\$tmp\"
    sudo mv \"\$tmp\" '$APP_DIR/.env'
    echo 'Backed up to $APP_DIR/.env.pre-managed-$STAMP'
    echo 'Managed DB settings written to $APP_DIR/.env'
  "

echo "Done. The next deploy (or a manual 'sudo systemctl restart quantlab') will use the managed databases."
