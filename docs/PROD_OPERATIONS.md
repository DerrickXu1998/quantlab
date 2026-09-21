# Production operations cheatsheet

Everything you need to operate the prod VM and keep its warehouse fresh.
Local dev commands (`make up`, `make ingest`, ...) are in the README — this file
is **prod only**.

- VM: `instance-20260920-123627` · zone `us-central1-a` · project `avid-glazing-444109-h6`
- Public API: `https://34.133.64.130.sslip.io` (Caddy terminates TLS; only 80/443 are open)
- Stack on the VM: `/opt/quantlab` with `docker-compose.prod.yml`
  (caddy → backend → postgres + clickhouse; databases bound to loopback, not public)

## 0. Setup once per shell

The Makefile defaults assume the VM is named `quantlab`; yours is not, so export
these (or rename the instance to `quantlab` and skip this):

```bash
export GCP_INSTANCE=instance-20260920-123627
export GCP_ZONE=us-central1-a
export PROD_URL=https://34.133.64.130.sslip.io   # so prod-health hits TLS, not the bare IP
```

## 1. gcloud commands worth knowing

```bash
# Shell on the VM (through IAP — no public port 22)
gcloud compute ssh $GCP_INSTANCE --zone $GCP_ZONE --tunnel-through-iap

# One-off command on the VM
gcloud compute ssh $GCP_INSTANCE --zone $GCP_ZONE --tunnel-through-iap --quiet --command "<cmd>"

# Instance info / external IP
gcloud compute instances describe $GCP_INSTANCE --zone $GCP_ZONE \
  --format='value(status,tags.items,networkInterfaces[0].accessConfigs[0].natIP)'

# Stop / start the VM (stops the compute bill; disk + IP still bill)
gcloud compute instances stop  $GCP_INSTANCE --zone $GCP_ZONE
gcloud compute instances start $GCP_INSTANCE --zone $GCP_ZONE

# Tunnel a database port to your laptop (dbs are loopback-only on the VM)
gcloud compute ssh $GCP_INSTANCE --zone $GCP_ZONE --tunnel-through-iap -- -L 5432:localhost:5432
# then: psql "postgresql://quantlab:<password from /opt/quantlab/.env>@localhost:5432/quantlab"
# (same pattern with -L 8123:localhost:8123 for ClickHouse HTTP)

# Copy files to/from the VM
gcloud compute scp ./symbols.txt $GCP_INSTANCE:/tmp/ --zone $GCP_ZONE --tunnel-through-iap
gcloud compute scp $GCP_INSTANCE:/tmp/prices.log ./ --zone $GCP_ZONE --tunnel-through-iap

# Serial/console log (boot issues)
gcloud compute instances get-serial-port-output $GCP_INSTANCE --zone $GCP_ZONE
```

On the VM itself, compose is always invoked as:

```bash
cd /opt/quantlab
sudo docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml <cmd>
```

## 2. Makefile prod wrappers (from your laptop)

```bash
make prod-health      # public health endpoint
make prod-check       # assert the API serves the warehouse, not the demo fallback
make prod-ps          # what is running
make prod-logs        # follow logs (SERVICE=backend to narrow)
make prod-coverage    # what's in the warehouse
make prod-restart     # restart the whole stack (systemd unit)
make prod-ssh         # interactive shell on the VM
```

## 3. Ingestion commands (prod)

All jobs are **idempotent and additive** — safe to re-run any time. Each runs as a
one-shot container and exits. Long jobs can be detached with `nohup` (see §5).

### 3.1 Prices (Yahoo; Stooq is bot-walled and just falls back)

```bash
# A few symbols
make prod-ingest SYMBOLS="AAPL.US MSFT.US SHEL.LON" START=2015-01-01

# Refresh recent history for everything (daily/weekly top-up)
make prod-ingest SYMBOLS="$(cat artifacts/ingest_universe.txt | tr '\n' ' ') AAPL.US MSFT.US NVDA.US" START=2026-09-01

# Full backfill (what was run to load prod)
make prod-ingest SYMBOLS="$(cat artifacts/ingest_universe.txt | tr '\n' ' ') AAPL.US MSFT.US NVDA.US" START=2010-01-01
```

### 3.2 Macro series

```bash
# BoE (keyless): GBPUSD.BOE, GBPEUR.BOE, BANKRATE.BOE, GILT10Y.BOE, M4GROWTH.BOE
gcloud compute ssh $GCP_INSTANCE --zone $GCP_ZONE --tunnel-through-iap --quiet --command \
  "cd /opt/quantlab && sudo docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml \
   --profile ingest run --rm ingest ingest-macro"

# FRED (needs FRED_API_KEY on the VM): VIX, UST 2y/10y, HY spread, real 10y, dollar index
# Same command with: ingest-macro --provider fred
# (status "partial" is expected: negative 2020-21 real yields are quarantined)
```

### 3.3 Identifiers

```bash
# OpenFIGI (keyless, ~25 req/min, resumable — run after any price ingest of new symbols)
... run --rm ingest map-identifiers

# SEC ticker -> CIK (needs SEC_USER_AGENT)
... run --rm ingest map-sec-tickers

# Companies House company numbers (needs COMPANIES_HOUSE_API_KEY)
... run --rm ingest map-ch-companies
```

(`... run --rm ingest` = the same ssh + compose prefix as in 3.2.)

### 3.4 Fundamentals

```bash
# SEC companyfacts, ~5.7M rows, ~60 min — run detached (see §5)
... run --rm ingest ingest-sec-fundamentals            # full
... run --rm ingest ingest-sec-fundamentals --limit 20 # pilot

# Companies House iXBRL — expect 0 facts for FTSE (PDF-only filings, known gap)
... run --rm ingest ingest-ch-fundamentals
```

### 3.5 Short data (both keyless)

```bash
# FINRA daily short volume (default: last 31 days; CDN history back to 2018)
... run --rm ingest ingest-finra-shorts
... run --rm ingest ingest-finra-shorts --start 2026-08-01 --end 2026-09-18

# FCA net short positions (run AFTER map-identifiers — it matches on OpenFIGI names)
... run --rm ingest ingest-fca-shorts
```

### 3.6 Universe snapshot + signals

```bash
# Archive current universe membership (survivorship-bias tracking; run daily-ish)
... run --rm ingest universe-snapshot liquid-500-ftse-core

# Recompute all signal rules from warehouse bars (drives the public API)
make prod-signals
```

## 4. Verify

```bash
make prod-health                                # signal_count should be large
make prod-check                                 # warehouse, not demo fallback
curl -s $PROD_URL/api/v1/instruments?limit=3
curl -s -X POST $PROD_URL/api/v1/runs -H 'content-type: application/json' \
  -d '{"model_name":"sma-crossover","symbols":["AAPL.US","MSFT.US","SHEL.LON"],"start_date":"2024-01-01","end_date":"2024-12-31"}'
curl -s $PROD_URL/api/v1/runs/<run_id>/performance
```

Query the stores directly (on the VM):

```bash
sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres \
  psql -U quantlab -d quantlab -c \
  "SELECT provider, count(*), count(DISTINCT instrument_id) FROM fundamentals GROUP BY provider"

sudo docker compose --env-file .env -f docker-compose.prod.yml exec -T clickhouse \
  clickhouse-client --query \
  "SELECT countDistinct(instrument_id), count(), min(ts), max(ts) FROM quantlab.price_bars_current"
```

## 5. Long jobs: detach so SSH can drop

An ingest dies with its SSH session. For anything over a few minutes, run it
under `nohup` on the VM and poll:

```bash
gcloud compute ssh $GCP_INSTANCE --zone $GCP_ZONE --tunnel-through-iap --quiet --command \
  "cd /opt/quantlab && nohup sudo docker compose --env-file .env --env-file .env.images \
   -f docker-compose.prod.yml --profile ingest run --rm ingest ingest-sec-fundamentals \
   > /tmp/sec_fund.log 2>&1 &"

# poll
gcloud compute ssh $GCP_INSTANCE --zone $GCP_ZONE --tunnel-through-iap --quiet \
  --command "tail -5 /tmp/sec_fund.log"
```

## 6. Suggested refresh cadence

| Job | When |
|---|---|
| `prod-ingest` (recent START) | daily, after US close |
| `ingest-finra-shorts` | daily, after 18:00 ET |
| `prod-signals` | after every price ingest |
| `ingest-macro` / `--provider fred` | weekly |
| `ingest-sec-fundamentals` | weekly during earnings season, monthly otherwise |
| `map-identifiers`, `map-sec-tickers`, `map-ch-companies` | after ingesting new symbols |
| `universe-snapshot` | daily (append-only archive) |
| `ingest-fca-shorts` | weekly (source file can be weeks stale — check freshness) |

## 7. Known prod quirks

- **Missing keys**: `FRED_API_KEY` / `SEC_USER_AGENT` / `COMPANIES_HOUSE_API_KEY` live in
  `/opt/quantlab/.env` on the VM. If a credentialed job exits with "set X_API_KEY", the
  value is empty there — edit with `sudo nano /opt/quantlab/.env` (no restart needed;
  one-shot ingests read it per run).
- **4 FTSE tickers 404 on Yahoo** (`AHT.LON`, `BDEV.LON`, `PHNX.LON`, `SMDS.LON`) —
  delisted/renamed; expected, not a bug.
- **Reject counts are normal**: Yahoo UK sub-penny ticks ("OHLC ordering violated"),
  negative rate prints ("non-positive price") — quarantined in `ingest_rejects`, never
  silently stored.
- **Rollback**: `sudo cp /opt/quantlab/.env.images.prev /opt/quantlab/.env.images && sudo systemctl restart quantlab`.
- VM scratch logs: `/tmp/prices.log`, `/tmp/openfigi.log`, `/tmp/sec_fund.log` — safe to delete.
