# Deploying QuantLab

The work is split in two. **Vercel** builds and serves the SPA from `frontend/`.
One `e2-standard-2` Compute Engine VM runs **the API and its datastores**.
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
                                     -> postgres   (catalog)
                                     -> clickhouse (bars)
                                  [migrate + ingest run from the ingest image]
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

Postgres and ClickHouse are bound to `127.0.0.1` and are not reachable from the
internet at all.

## Why this shape

| Decision | Reason |
|---|---|
| SPA on Vercel, not on the VM | Vercel already builds `frontend/` from this repository on every push. Shipping a second copy in a container would be two builds and two deploys of one artefact. The cost is CORS and a mandatory domain — see above. |
| The ingest image still ships | It is not only the data loader: the `migrate` service runs from it, and the backend will not start until that container has exited successfully. Dropping it would stop the API booting. |
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
| Artifact Registry (2 images, ~2–4 GB after the cleanup policy; first 0.5 GB free) | <$1 |
| Daily snapshots, 14-day retention (incremental) | ~$1–3 |
| GitHub Actions (public repo, or within the free private minutes) | $0 |
| Vercel (hobby tier, serving the SPA) | $0 |
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

### 3. Domain, HTTPS and CORS — before the first deploy

Unlike a same-origin deployment, these are not optional polish; the stack will
not start without the allow-list, and the browser will not talk to it without
TLS. Point an A record at the VM's external IP (`make prod-ip`), then:

```bash
sudo sed -i 's/^QUANTLAB_SITE_ADDRESS=.*/QUANTLAB_SITE_ADDRESS=api.example.com/' /opt/quantlab/.env
sudo sed -i 's/^QUANTLAB_ACME_EMAIL=.*/QUANTLAB_ACME_EMAIL=you@example.com/'     /opt/quantlab/.env
sudo sed -i 's|^QUANTLAB_CORS_ORIGINS=.*|QUANTLAB_CORS_ORIGINS=https://your-project.vercel.app|' /opt/quantlab/.env
```

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
sudo docker compose --env-file .env --env-file .env.images -f docker-compose.prod.yml \
  --profile ingest run --rm ingest ingest AAPL.US MSFT.US HSBA.LON --start 2015-01-01
```

Or, from your laptop, the wrappers in the Makefile:

```bash
make prod-ingest SYMBOLS="AAPL.US MSFT.US" START=2015-01-01
make prod-signals
make prod-coverage
```

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
| API works in curl, SPA shows no data | CORS. The browser console will say the origin is not allowed. `QUANTLAB_CORS_ORIGINS` must list the SPA's exact origin — scheme included, no trailing slash, no wildcard. A Vercel preview URL will not match your production entry. |
| Browser blocks the API call as "mixed content" | The SPA is on HTTPS and `QUANTLAB_SITE_ADDRESS` is still `:80`. Set a real hostname and point `VITE_API_BASE_URL` at `https://`. |
| Stack refuses to start, `required variable QUANTLAB_CORS_ORIGINS` | Working as intended — the API is useless to the SPA without it, so it fails loudly rather than serving something the browser will reject. |
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
