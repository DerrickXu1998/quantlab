# Deploying QuantLab

One `e2-standard-2` Compute Engine VM runs the whole stack. GitHub Actions builds
the three images, pushes them to Artifact Registry, and restarts Compose on the
VM over an IAP SSH tunnel. The pipeline itself costs nothing; the VM is the bill.

```
  git push main
        |
        v
  GitHub Actions ---- build ----> Artifact Registry (europe-west2-docker.pkg.dev)
        |                                    |
        | OIDC -> Workload Identity          | docker pull (VM service account)
        | (no service-account key)           v
        +------- ssh via IAP ------->  e2-standard-2 VM
                                        caddy :80/:443
                                          -> frontend (nginx, SPA + /api proxy)
                                            -> backend (uvicorn, 2 workers)
                                               -> postgres   (catalog)
                                               -> clickhouse (bars)
```

Everything is same-origin behind Caddy, so `QUANTLAB_CORS_ORIGINS` stays empty —
CORS never engages. Postgres and ClickHouse are bound to `127.0.0.1` and are not
reachable from the internet at all.

## Why this shape

| Decision | Reason |
|---|---|
| One VM, not Cloud Run | ClickHouse and Postgres want persistent local disk and a long-lived process. Cloud Run gives neither, and managed equivalents (Cloud SQL + ClickHouse Cloud) cost several times the VM on their own. |
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
| 100 GB `pd-balanced` boot disk | ~$10 |
| Static external IP, attached | ~$3 |
| Egress (modest personal traffic) | ~$2–5 |
| Artifact Registry (~3–5 GB after the cleanup policy; first 0.5 GB free) | <$1 |
| Daily snapshots, 14-day retention (incremental) | ~$1–3 |
| GitHub Actions (public repo, or within the free private minutes) | $0 |
| **Total** | **~$65–70** |

The levers, cheapest effort first:

- **A 1-year committed use discount** on the VM is the big one — roughly a third
  off the compute line, taking the total to about $45/month. It commits you for
  a year, so make it once the shape has settled.
- **Shrink the disk.** 100 GB is generous for compressed bars; `make coverage`
  reports what the warehouse actually occupies. The disk cannot be shrunk after
  creation, only grown, so size it deliberately the first time.
- **Stop the VM when idle.** You stop paying for compute; the disk and IP still
  bill. Good for a research box you use in bursts, useless for a public demo.

## First-time setup

### 1. GCP side (once, from your laptop or Cloud Shell)

```bash
PROJECT_ID=your-project ZONE=europe-west2-c bash deploy/setup-gcp.sh
```

This enables the APIs, creates the Artifact Registry repository with a cleanup
policy, creates both service accounts, wires up Workload Identity Federation
scoped to `DerrickXu1998/quantlab`, opens 80/443, restricts SSH to IAP, attaches
the service account and network tag to your existing VM, and sets up daily
snapshots. It is idempotent — re-run it after changing anything.

It finishes by printing the `gh variable set` commands to run. They are
repository **variables**, not secrets: none of the values are sensitive.

### 2. VM side (once, on the VM)

```bash
gcloud compute ssh quantlab --zone europe-west2-c --tunnel-through-iap
# on the VM:
git clone https://github.com/DerrickXu1998/quantlab.git /tmp/quantlab
sudo AR_REGION=europe-west2 bash /tmp/quantlab/deploy/bootstrap-vm.sh
```

Installs Docker and Compose v2, points Docker at Artifact Registry, creates
2 GiB of swap and the kernel limits ClickHouse needs, generates
`/opt/quantlab/.env` with **random database passwords**, installs the
`quantlab.service` systemd unit so the stack survives a reboot, and enables
unattended security upgrades.

Then add your ingest API keys (all free — see [DATA_SOURCES.md](DATA_SOURCES.md)):

```bash
sudo nano /opt/quantlab/.env     # SEC_USER_AGENT, FRED_API_KEY, COMPANIES_HOUSE_API_KEY
```

> `/opt/quantlab/.env` holds the only copy of the generated database passwords,
> and they are baked into the Postgres and ClickHouse volumes on first start.
> Changing them in the file alone will not change them in the databases.

### 3. Deploy

Push to `main`, or run the **deploy** workflow manually. It runs CI, builds and
pushes three images, copies the compose file and Caddyfile to the VM, applies
migrations, restarts the stack, and verifies the app from outside.

### 4. Load data

Ingest reaches the network and is never part of a deploy. From the VM:

```bash
cd /opt/quantlab
sudo docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml \
  --profile ingest run --rm ingest ingest AAPL.US MSFT.US HSBA.LON --start 2015-01-01
```

Or, from your laptop, the wrappers in the Makefile:

```bash
make prod-ingest SYMBOLS="AAPL.US MSFT.US" START=2015-01-01
make prod-signals
make prod-coverage
```

### 5. HTTPS

Until DNS points at the VM, the stack serves plain HTTP at `http://<VM-IP>/`.
Once an A record resolves to the VM:

```bash
sudo sed -i 's/^QUANTLAB_SITE_ADDRESS=.*/QUANTLAB_SITE_ADDRESS=quantlab.example.com/' /opt/quantlab/.env
sudo sed -i 's/^QUANTLAB_ACME_EMAIL=.*/QUANTLAB_ACME_EMAIL=you@example.com/' /opt/quantlab/.env
sudo systemctl restart quantlab
```

Caddy provisions a Let's Encrypt certificate on the first request and renews it
unattended. Set the hostname *only* after DNS resolves — ACME failures are
rate-limited.

## Day-to-day

```bash
make prod-ssh        # shell on the VM, through IAP
make prod-ps         # what is running
make prod-logs       # follow logs (SERVICE=backend to narrow)
make prod-health     # hit the public health endpoint
make prod-check      # assert the API serves the warehouse, not the demo fallback
```

**Rollback** to the previous images, without a rebuild:

```bash
cd /opt/quantlab
sudo cp .env.images.prev .env.images
sudo systemctl restart quantlab
```

**Reach a database** without exposing it. The ports are bound to loopback on the
VM, so tunnel to them:

```bash
gcloud compute ssh quantlab --zone europe-west2-c --tunnel-through-iap -- -L 5432:localhost:5432
psql "postgresql://quantlab:<password-from-/opt/quantlab/.env>@localhost:5432/quantlab"
```

## When something is wrong

| Symptom | Where to look |
|---|---|
| Deploy fails at "waiting for the backend healthcheck" | `make prod-logs SERVICE=backend`. A failed migration shows in the `migrate` service; the old backend is still serving, so the site is up. |
| Deploy passes, site unreachable from outside | The firewall rule or the instance's network tag. `gcloud compute instances describe <vm> --format='value(tags.items)'` should list `quantlab`. |
| API serves data that looks plausible but fictitious | It fell back to the synthetic SQLite demo because `QUANTLAB_DB_URL` or `QUANTLAB_CH_URL` is unset or wrong. `remote-deploy.sh` hard-fails on this, and `make prod-check` re-checks it any time. |
| A container is killed mid-query | Memory. The Compose limits and `clickhouse-limits.xml` size the stack for 8 GB; a query that needs more now fails with `MEMORY_LIMIT_EXCEEDED` instead of taking the host down. Widen the ClickHouse limit only if you also grow the VM. |
| Disk filling | `docker system df`. The weekly prune keeps a week of superseded images; ClickHouse `system.query_log` is capped at 14 days. |
| Certificate not issued | DNS must resolve to the VM *before* `QUANTLAB_SITE_ADDRESS` is set. `make prod-logs SERVICE=caddy`. |
| Deploy blocked by frontend tests timing out | CI runs vitest with `--maxWorkers=2`. Unbounded, twenty parallel jsdom environments starve each other and six `findBy*` queries time out — a contention artefact, not a defect. The underlying reliance on wall-clock timeouts is still worth fixing in the tests. |

## Growing out of this

The stack is a single Compose file, so the next step up is deliberately dull:
change the machine type (`gcloud compute instances set-machine-type`, requires a
stop/start) and raise the memory limits in `deploy/docker-compose.prod.yml`
together. Splitting ClickHouse onto its own VM, or moving to ClickHouse Cloud, is
a change to two URLs in `/opt/quantlab/.env` — the backend already talks to both
stores over the network and does not care where they live.
