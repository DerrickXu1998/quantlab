# Deploying QuantLab

The work is split in two. **Vercel** builds and serves the SPA from `frontend/`.
One `e2-standard-2` Compute Engine VM runs **the API and its datastores** —
bars in ClickHouse, the catalog in Postgres, both as containers whose data lives
on the VM's separate 100 GB persistent data disk.
GitHub Actions builds two images, pushes them to Artifact Registry, and restarts
Compose on the VM over an IAP SSH tunnel. Both pipelines cost nothing; the VM is
the bill.

```
  push to main
        |
        +---> Vercel ------ build frontend/ ------> SPA (public HTTPS)
        |                                             |
        v                                             | fetch(VITE_API_BASE_URL)
  GitHub Actions -- build --> Artifact Registry        |
        |                          |                   |
        | OIDC -> Workload         | docker pull       |
        | Identity (no key)        v                   v
        +--- ssh via IAP --->  e2-standard-2 VM
                                caddy :80/:443  (TLS, the only public port)
                                  -> backend (uvicorn, 2 workers)
                                  [migrate + ingest run from the ingest image]
                                  -> postgres 18      (catalog)  \  data on the
                                  -> clickhouse 24.8  (bars)     /  data disk,
                                                                   /mnt/disks/quantlab
```

Two consequences follow from the split, and both are load-bearing:

- **`QUANTLAB_CORS_ORIGINS` is required.** Every browser call is now
  cross-origin. Leave it empty and the API answers `curl` perfectly while the
  real app sees nothing but CORS errors — invisible from the server side, which
  is why the stack refuses to start without it.
- **A real hostname is required, not the VM's IP.** Vercel serves the SPA over
  HTTPS, and a browser will not let an HTTPS page call an HTTP API. No
  certificate authority issues for a bare IP, so plain HTTP is only good for
  curling the box from itself.

The databases run on the VM but are never published: their ports bind to
`127.0.0.1` only. Their settings live in `/opt/quantlab/.env`
(`QUANTLAB_PG_USER` / `QUANTLAB_PG_PASSWORD`, `QUANTLAB_CH_USER` /
`QUANTLAB_CH_PASSWORD`, and `QUANTLAB_DB_URL` / `QUANTLAB_CH_URL` naming the
in-compose hosts `postgres` and `clickhouse`). The passwords are baked into the
data directories on first start; changing them in `.env` alone does not change
them in the databases.

## Why this shape

| Decision | Reason |
|---|---|
| SPA on Vercel, not on the VM | Vercel already builds `frontend/` from this repository on every push. Shipping a second copy in a container would be two builds and two deploys of one artefact. The cost is CORS and a mandatory domain — see above. |
| The ingest image still ships | It is not only the data loader: the `migrate` service runs from it, and the backend will not start until that container has exited successfully. Dropping it would stop the API booting. |
| Databases in containers on the VM, not managed services | Tried managed (ClickHouse Cloud + managed Postgres, September 2026) and moved back in October: the services sat in London while the VM is in Iowa, so every query paid a transatlantic round trip, and the bills outgrew the VM. On the box, queries are local and the cost is the disk. The price is that backups, upgrades and disk growth are ours — see "Data disk" below. |
| Data on a separate persistent disk, not the boot disk | The 30 GB boot disk is mostly container images; a database that filled it would take every service down at once. The data disk can be grown, snapshotted and re-attached to a rebuilt VM on its own. `remote-deploy.sh` refuses to deploy unless it is mounted, because the databases would otherwise initialise empty on the boot disk. |
| Artifact Registry, not Docker Hub | The VM authenticates with its own service account. No registry credentials exist on the host to leak or rotate. |
| Workload Identity Federation, not a JSON key | Actions exchanges GitHub's OIDC token for a short-lived Google credential. There is no key in repository secrets because there is no key. |
| SSH through IAP, not a public port 22 | The firewall admits only IAP's `35.235.240.0/20` range. |
| Images tagged `:<sha>` | Every deploy is pinned to an exact commit, and rollback is a tag swap rather than a rebuild. |

## What it costs

Order-of-magnitude, at `us-central1` list prices, for a VM that runs all month.
**Check the [pricing calculator](https://cloud.google.com/products/calculator) for
your region** — European and Asian regions run roughly 10–20% higher.

| Line | Monthly |
|---|---|
| `e2-standard-2` (2 vCPU, 8 GB), on-demand, 730 h | ~$49 |
| 30 GB `pd-balanced` boot disk | ~$3 |
| 100 GB `pd-balanced` data disk (Postgres + ClickHouse) | ~$10 |
| Static external IP, attached | ~$3 |
| Egress (modest personal traffic) | ~$2–5 |
| Artifact Registry (2 images, ~2–4 GB after the cleanup policy; first 0.5 GB free) | <$1 |
| Daily snapshots, 14-day retention (incremental) | ~$1–3 |
| GitHub Actions (public repo, or within the free private minutes) | $0 |
| Vercel (hobby tier, serving the SPA) | $0 |
| **Total** | **~$65–70** |

The levers, cheapest effort first:

- **A 1-year committed use discount** on the VM is the big one — roughly a third
  off the compute line, taking the total to about $45/month. It commits you for
  a year, so make it once the shape has settled.
- **Right-size the data disk.** 100 GB is generous: the whole warehouse
  (476M bars, 6.4 GB compressed, plus a <1 GB catalog) used ~7 GB in October
  2026. A disk cannot be shrunk after creation, only grown — online, in
  seconds — so starting smaller is the cheap direction.
- **Stop the VM when idle.** You stop paying for compute; the disk and IP still
  bill. Good for a research box you use in bursts, useless for a public demo.

## First-time setup

### 1. GCP side (once, from your laptop or Cloud Shell)

No `gcloud` installed? [Cloud Shell](https://shell.cloud.google.com) has it,
already authenticated as you, with nothing to install:

```bash
git clone https://github.com/DerrickXu1998/quantlab.git && cd quantlab
PROJECT_ID=your-project ZONE=europe-west2-c bash deploy/setup-gcp.sh
```

This enables the APIs, creates the Artifact Registry repository with a cleanup
policy, creates both service accounts, wires up Workload Identity Federation
scoped to `DerrickXu1998/quantlab`, opens 80/443, restricts SSH to IAP, attaches
the service account and network tag to your existing VM, and sets up daily
snapshots. It is idempotent — re-run it after changing anything.

It finishes by printing the `gh variable set` commands to run. They are
repository **variables**, not secrets: none of the values are sensitive.

> **There is no service-account key to create, store or paste anywhere.** The
> pipeline authenticates by federating the OIDC token GitHub mints for this
> repository, which Google exchanges for a credential that expires in minutes.
> That is the entire point of the Workload Identity Federation setup: nothing to
> rotate, nothing to leak, nothing to hand to anyone.
>
> If `google-github-actions/auth` reports *"must specify exactly one of
> workload_identity_provider or credentials_json"*, it is not asking for a key.
> It means `vars.GCP_WORKLOAD_IDENTITY_PROVIDER` interpolated to an empty string
> because the variable is unset — i.e. this step has not been run yet. The
> `repository is configured` preflight job reports that in plain terms before
> the build starts.

### 2. VM side (once, on the VM)

```bash
gcloud compute ssh quantlab --zone europe-west2-c --tunnel-through-iap
# on the VM:
git clone https://github.com/DerrickXu1998/quantlab.git /tmp/quantlab
sudo AR_REGION=europe-west2 bash /tmp/quantlab/deploy/bootstrap-vm.sh
```

Installs Docker and Compose v2, points Docker at Artifact Registry, creates
2 GiB of swap, formats and mounts the data disk (`DATA_DISK=/dev/disk/by-id/google-<name>`,
via `prepare-data-disk.sh`), generates `/opt/quantlab/.env` with random
database passwords, installs the `quantlab.service` systemd unit so the stack
survives a reboot, and enables unattended security upgrades.

Then add your ingest API keys (all free — see [DATA_SOURCES.md](DATA_SOURCES.md)):

```bash
sudo nano /opt/quantlab/.env
#   SEC_USER_AGENT, FRED_API_KEY, COMPANIES_HOUSE_API_KEY
```

The generated database passwords are baked into the data directories on the
first start; do not change them afterwards. Bootstrap marks a freshly prepared
data disk as allowed one deploy while empty; after that first deploy succeeds,
every later one refuses an empty data disk.

### 3. Domain, HTTPS and CORS — before the first deploy

Unlike a same-origin deployment, these are not optional polish; the stack will
not start without the allow-list, and the browser will not talk to it without
TLS. Point an A record at the VM's external IP (`make prod-ip`), then:

```bash
sudo sed -i 's/^QUANTLAB_SITE_ADDRESS=.*/QUANTLAB_SITE_ADDRESS=api.example.com/' /opt/quantlab/.env
sudo sed -i 's|^QUANTLAB_CORS_ORIGINS=.*|QUANTLAB_CORS_ORIGINS=https://your-project.vercel.app|' /opt/quantlab/.env
```

**No domain of your own?** A wildcard DNS resolver gives you a real, publicly
resolvable hostname for any IP, and Let's Encrypt issues certificates for it:

```bash
sudo sed -i 's/^QUANTLAB_SITE_ADDRESS=.*/QUANTLAB_SITE_ADDRESS=34.133.64.130.sslip.io/' /opt/quantlab/.env
```

That is enough for a working HTTPS API today. It depends on a third party
resolving the name, so move to a domain you control before anything depends on
it — the change is one line here and one environment variable in Vercel.

ACME registration e-mail lives in `deploy/Caddyfile`, not in `.env`. There is no
default: Let's Encrypt treats it as optional, and a placeholder like
`admin@localhost` is not deliverable, so issuance would fail outright.

Set the hostname *only* after DNS resolves to the VM — ACME failures are
rate-limited, and Caddy provisions the certificate on the first request.

Then, in the Vercel project's environment variables:

```
VITE_API_BASE_URL = https://api.example.com/api/v1
```

Without it the SPA defaults to `/api/v1` — its own origin — and calls Vercel
instead of the VM.

> **Vercel preview deployments get a unique URL each.** `resolve_cors_origins()`
> is an exact allow-list with no wildcard, deliberately, so previews cannot call
> this API unless you add each one. Use a stable production domain here. If you
> need previews working against the real API, that needs `allow_origin_regex` in
> `backend/src/quantlab/api/app.py` — a change to security-relevant code and its
> tests, not a config tweak.

### 4. Deploy

Push to `main`, or run the **deploy** workflow manually. It runs CI, builds and
pushes the backend and ingest images, copies the compose file and Caddyfile to
the VM, applies migrations, restarts the stack, and verifies the API from
outside. Vercel deploys the SPA off the same push, independently.

### 5. Load data

Ingest reaches the network and is never part of a deploy. From the VM:

```bash
cd /opt/quantlab
# Data loading is not part of this repo any more: it runs from
# quantlab-data-pipeline, on your machine, over an IAP tunnel to these databases.
```

From a [quantlab-data-pipeline](https://github.com/DerrickXu1998/quantlab-data-pipeline) checkout:

```bash
make tunnel                                                     # keep open
make quantlab-data TARGET=prod ARGS="ingest AAPL.US MSFT.US --start 2015-01-01"
make ingest-fred TARGET=prod                                    # VIX, HY spread, yields
```

Then, from this repo, recompute signals: `make prod-signals`.

## Day-to-day

```bash
make prod-ssh        # shell on the VM, through IAP
make prod-ps         # what is running
make prod-logs       # follow logs (SERVICE=backend to narrow)
make prod-health     # hit the public health endpoint
make prod-check      # assert the API serves the warehouse, not the demo fallback
```

Once the API has a hostname, tell those two targets about it — Caddy serves only
the configured name, so a probe at the bare IP gets a 404:

```bash
export PROD_URL=https://api.example.com
```

**Rollback** to the previous images, without a rebuild:

```bash
cd /opt/quantlab
sudo cp .env.images.prev .env.images
sudo systemctl restart quantlab
```

**Reach a database.** From a shell on the VM (`make prod-ssh`); the ports are
loopback-only, so there is nothing to reach from outside:

```bash
cd /opt/quantlab
sudo docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml \
  exec postgres psql -U quantlab -d quantlab
sudo docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml \
  exec clickhouse clickhouse-client --user quantlab --password "$(sudo sed -n 's/^QUANTLAB_CH_PASSWORD=//p' .env)" -d quantlab
```

## Data disk

Postgres and ClickHouse keep their data under `/mnt/disks/quantlab`
(`QUANTLAB_DATA_DIR`), a separate 100 GB `pd-balanced` persistent disk mounted
by label from `/etc/fstab` with `nofail`. `deploy/prepare-data-disk.sh` formats
it (only if it is blank — it refuses any disk carrying a signature or data) and
mounts it; it is safe to re-run.

```bash
sudo bash deploy/prepare-data-disk.sh /dev/disk/by-id/google-<disk-device-name>
```

Two guards keep a missing disk from turning into an empty warehouse:
`remote-deploy.sh` refuses to deploy unless the mount point is a mounted
filesystem and both `postgres/` and `clickhouse/` under it hold data (a
brand-new install sets `QUANTLAB_ALLOW_EMPTY_DATA=1` once), and `nofail` lets
the VM boot without it rather than hang.

**Backups are ours now.** Snapshot the data disk on a schedule — a GCE snapshot
schedule on the disk is the least moving parts:

```bash
gcloud compute resource-policies create snapshot-schedule quantlab-data-daily \
  --region <region> --daily-schedule --start-time 03:00 --max-retention-days 14
gcloud compute disks add-resource-policies <data-disk> --zone <zone> \
  --resource-policies quantlab-data-daily
```

A crash-consistent snapshot of a running ClickHouse and Postgres restores like a
power cut: both recover from their own write-ahead state. For a logical copy as
well, `pg_dump` the catalog into `/opt/quantlab/backups`.

**Growing the disk** is online: `gcloud compute disks resize <data-disk> --size
200GB`, then `sudo resize2fs /dev/disk/by-id/google-<disk-device-name>`.

## Moving an existing VM back from the managed databases

From September to October 2026 the datastores were managed services
(ClickHouse Cloud + ClickHouse's managed Postgres, both in London). A VM still
pointing at them is moved back by `deploy/migrate-to-selfhost.sh`, once, while
the managed stack is still serving. It never modifies the managed services, so
they remain the rollback.

1. Mount the data disk: `sudo bash prepare-data-disk.sh /dev/disk/by-id/google-<disk>`.
2. Put the new local settings in `/opt/quantlab/.env.selfhost` (mode 600) — the
   seven lines in the script's header, with fresh passwords from
   `openssl rand -hex 24`.
3. Copy this branch's `docker-compose.prod.yml`, `clickhouse-limits.xml` and
   `clickhouse-users.xml` into
   `/opt/quantlab/selfhost-staging/`.
4. Optionally run the slow part early, with the API still serving:
   `sudo PHASE=bulk bash migrate-to-selfhost.sh`. It starts only the local
   `postgres` and `clickhouse`, creates the ClickHouse schema (from the repo's
   migration: Cloud's `Shared*MergeTree` DDL does not run elsewhere) plus any
   views the source has, and copies `price_bars` **one monthly partition at a
   time**, checking each against the source by row count and a content hash,
   both under `FINAL`. A month that does not match is dropped and copied again. Each month is then merged
   to a single part (`OPTIMIZE ... PARTITION ... FINAL`): every read goes
   through `FINAL`, and over a freshly copied, unmerged table it exceeds the
   2 GiB server memory cap.
5. Cut over: `sudo bash migrate-to-selfhost.sh`. It re-checks every month
   (re-copying only what changed), pauses the API, `pg_dump`s the managed
   catalog (excluding the provider-only `pg_stat_ch` extension) and restores it
   into Postgres 18, compares every table's row count, and only if all match
   rewrites `.env` (keeping `.env.pre-selfhost-<time>`, which holds the managed
   credentials), installs the new compose file and brings the stack up.
6. Merge the branch, so the next CI deploy ships the same compose file.

**Do not merge anything else to `main` during steps 4–5.** The managed-era
`remote-deploy.sh` runs its compose file with `--remove-orphans`, which removes
the new `postgres` / `clickhouse` containers as orphans. Their data survives on
the data disk, and the script can simply be run again, but the copy is
interrupted.

**Rolling back**, before anything new has been written locally: restore
`.env.pre-selfhost-<time>` as `.env` and `docker-compose.prod.yml.pre-selfhost-<time>`
as `docker-compose.prod.yml`, then `sudo docker compose ... up -d`. Writes made
after the cutover are not in the managed services.

The boot-disk volumes `quantlab_quantlab-chdata` / `quantlab_quantlab-pgdata`
are from the first self-hosted era and stale since September; nothing mounts
them. Remove them to free ~7 GB of the boot disk:
`sudo docker volume rm quantlab_quantlab-chdata quantlab_quantlab-pgdata`.

## When something is wrong

| Symptom | Where to look |
|---|---|
| Deploy fails at "waiting for the backend healthcheck" | `make prod-logs SERVICE=backend`. A failed migration shows in the `migrate` service; the old backend is still serving, so the site is up. |
| `auth failed: must specify exactly one of "workload_identity_provider" or "credentials_json"` | The repository variables are unset, so the action received an empty string. It is **not** asking for a service-account key — there isn't one. Run `deploy/setup-gcp.sh` and set the variables it prints. |
| Deploy passes, site unreachable from outside | The firewall rule or the instance's network tag. `gcloud compute instances describe <vm> --format='value(tags.items)'` should list `quantlab`. |
| API works in curl, SPA shows no data | CORS. The browser console will say the origin is not allowed. `QUANTLAB_CORS_ORIGINS` must list the SPA's exact origin — scheme included, no trailing slash, no wildcard. A Vercel preview URL will not match your production entry. |
| Browser blocks the API call as "mixed content" | The SPA is on HTTPS and `QUANTLAB_SITE_ADDRESS` is still `:80`. Set a real hostname and point `VITE_API_BASE_URL` at `https://`. |
| Stack refuses to start, `required variable QUANTLAB_CORS_ORIGINS` | Working as intended — the API is useless to the SPA without it, so it fails loudly rather than serving something the browser will reject. |
| API serves data that looks plausible but fictitious | It fell back to the synthetic SQLite demo because `QUANTLAB_DB_URL` or `QUANTLAB_CH_URL` is unset or wrong. `remote-deploy.sh` hard-fails on this, and `make prod-check` re-checks it any time. |
| Deploy refuses: "does not point at the in-compose postgres/clickhouse" | `.env` still names a managed service. Run `deploy/migrate-to-selfhost.sh` (see above). |
| Deploy refuses: "is not a mounted filesystem" or "is empty" | The data disk is missing or unmounted. `lsblk`, `sudo mount /mnt/disks/quantlab`; a new VM runs `deploy/prepare-data-disk.sh`. Never bypass this with an empty directory on the boot disk — the databases would initialise empty. |
| `migrate` fails with authentication errors | `QUANTLAB_PG_PASSWORD` / `QUANTLAB_CH_PASSWORD` in `.env` no longer match what the data directories were initialised with. Restore the old values; changing a password means changing it inside the database too. |
| ClickHouse query fails with `MEMORY_LIMIT_EXCEEDED` | Working as intended: `clickhouse-limits.xml` caps a query at 1.5 GiB so one wide scan cannot OOM the 8 GiB host. Narrow the query, or raise the limit together with the container's memory limit. |
| Disk filling | `docker system df`. The weekly prune keeps a week of superseded images. |
| Certificate not issued | DNS must resolve to the VM *before* `QUANTLAB_SITE_ADDRESS` is set. `make prod-logs SERVICE=caddy`. |
| Deploy blocked by frontend tests timing out | CI runs vitest with `--maxWorkers=2`. Unbounded, twenty parallel jsdom environments starve each other and six `findBy*` queries time out — a contention artefact, not a defect. The underlying reliance on wall-clock timeouts is still worth fixing in the tests. |

## Growing out of this

The stack is a single Compose file, so the next step up is deliberately dull:
change the machine type (`gcloud compute instances set-machine-type`, requires a
stop/start) and raise the memory limits in `deploy/docker-compose.prod.yml`
together. Splitting ClickHouse onto its own VM is a change to one URL in
`/opt/quantlab/.env` — the backend already talks to both stores over the
network and does not care where they live. (Managed services were tried and
reverted; see "Moving an existing VM back from the managed databases".)
