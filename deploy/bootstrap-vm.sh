#!/usr/bin/env bash
# QuantLab -- one-time preparation of the Compute Engine VM that runs the stack.
#
# Run this once, on the VM, as a user with sudo:
#
#     gcloud compute ssh quantlab --zone <zone> --tunnel-through-iap
#     curl -fsSL https://raw.githubusercontent.com/DerrickXu1998/quantlab/main/deploy/bootstrap-vm.sh -o bootstrap.sh
#     sudo AR_REGION=europe-west2 bash bootstrap.sh
#
# It is idempotent: re-running it after a change to this script upgrades the
# host in place and leaves /opt/quantlab/.env (your passwords and API keys)
# untouched. Deploys do not run it -- GitHub Actions only ships images and
# restarts Compose.
#
# What it leaves behind:
#   /opt/quantlab/                  compose file, Caddyfile, .env, .env.images
#   docker + compose v2             from Docker's own apt repository
#   Artifact Registry credentials   via the VM's attached service account
#   quantlab.service                systemd unit, so the stack survives reboot
#   2 GiB swap                      headroom for ingest peaks on an 8 GiB box
#   unattended-upgrades             security patches without a human

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/quantlab}"
AR_REGION="${AR_REGION:-}"
DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-$(id -un)}}"

log() { printf '\n=== %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "run as root (sudo bash $0)"
[ -n "$AR_REGION" ] || fail "set AR_REGION to your Artifact Registry region, e.g. AR_REGION=europe-west2"

# ---------------------------------------------------------------------------
# Docker Engine + Compose v2, from Docker's repository rather than Debian's.
# Debian's docker.io package has no compose plugin, which is the only thing
# this host actually needs.
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
	log "installing Docker Engine and the Compose plugin"
	apt-get update -qq
	apt-get install -y -qq ca-certificates curl gnupg
	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/debian/gpg |
		gpg --dearmor -o /etc/apt/keyrings/docker.gpg
	chmod a+r /etc/apt/keyrings/docker.gpg
	printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian %s stable\n' \
		"$(dpkg --print-architecture)" "$(. /etc/os-release && echo "$VERSION_CODENAME")" \
		>/etc/apt/sources.list.d/docker.list
	apt-get update -qq
	apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
		docker-buildx-plugin docker-compose-plugin
else
	log "Docker already installed ($(docker --version))"
fi

systemctl enable --now docker

# Convenience for whoever runs this: `docker ps` without sudo on the next login.
# The deploy workflow does not rely on it -- it arrives as a fresh OS Login user
# (sa_<numeric-id>) that no bootstrap run can know the name of in advance, so it
# uses sudo instead, which roles/compute.osAdminLogin grants it.
if [ -n "$DEPLOY_USER" ] && [ "$DEPLOY_USER" != "root" ]; then
	usermod -aG docker "$DEPLOY_USER" || true
	log "added $DEPLOY_USER to the docker group"
fi

# ---------------------------------------------------------------------------
# Artifact Registry credentials. The VM's attached service account already
# carries roles/artifactregistry.reader; this only teaches the Docker CLI to
# present its token. Configured for root and for the deploying user, because
# whichever of them runs `docker compose pull` needs it.
# ---------------------------------------------------------------------------
log "configuring Docker for ${AR_REGION}-docker.pkg.dev"
command -v gcloud >/dev/null 2>&1 || fail "gcloud not found -- use a Google-provided Debian image, or install the SDK"
gcloud auth configure-docker "${AR_REGION}-docker.pkg.dev" --quiet
if [ "$DEPLOY_USER" != "root" ]; then
	sudo -u "$DEPLOY_USER" gcloud auth configure-docker "${AR_REGION}-docker.pkg.dev" --quiet
fi

# ---------------------------------------------------------------------------
# Swap. 8 GiB with no swap means an ingest run that briefly overshoots gets a
# container OOM-killed mid-write. 2 GiB of slow memory is a better outcome than
# a half-applied batch; the Compose memory limits still cap each service.
# ---------------------------------------------------------------------------
if ! swapon --show | grep -q .; then
	log "creating 2 GiB swap"
	fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
	# Prefer reclaiming page cache to swapping out a running service.
	sysctl -w vm.swappiness=10
	grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >>/etc/sysctl.conf
else
	log "swap already present"
fi

# ---------------------------------------------------------------------------
# Kernel limits ClickHouse needs. The container asks for 262144 open files via
# ulimits, which the host must actually be able to grant.
# ---------------------------------------------------------------------------
cat >/etc/sysctl.d/99-quantlab.conf <<'SYSCTL'
# ClickHouse keeps many small files open per part.
fs.file-max = 1048576
# ClickHouse maps data files; the default is too low for a growing bars table.
vm.max_map_count = 262144
SYSCTL
sysctl -p /etc/sysctl.d/99-quantlab.conf >/dev/null

# ---------------------------------------------------------------------------
# Application directory and the environment file. Generated once, with random
# passwords, and never regenerated -- rewriting it would orphan the Postgres and
# ClickHouse volumes, which keep the credentials from their first initialisation.
# ---------------------------------------------------------------------------
mkdir -p "$APP_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

if [ ! -f "$APP_DIR/.env" ]; then
	log "generating $APP_DIR/.env with random database passwords"
	pg_pw="$(openssl rand -hex 24)"
	ch_pw="$(openssl rand -hex 24)"
	cat >"$APP_DIR/.env" <<ENVFILE
# Generated by bootstrap-vm.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).
# The passwords below are baked into the Postgres and ClickHouse data volumes on
# first start. Changing them here alone will NOT change them in the databases.

QUANTLAB_SITE_ADDRESS=:80
QUANTLAB_ACME_EMAIL=

QUANTLAB_PG_USER=quantlab
QUANTLAB_PG_PASSWORD=${pg_pw}
QUANTLAB_CH_USER=quantlab
QUANTLAB_CH_PASSWORD=${ch_pw}

QUANTLAB_DB_URL=postgresql://quantlab:${pg_pw}@postgres:5432/quantlab
QUANTLAB_CH_URL=clickhouse://quantlab:${ch_pw}@clickhouse:8123/quantlab

# REQUIRED -- the stack will not start until this is set, and empty counts as
# missing. The SPA is on Vercel, so every browser call to this API is
# cross-origin; unset, the API answers curl fine and the app sees only CORS
# errors. Exact origins, comma-separated, no wildcards, no trailing slash.
QUANTLAB_CORS_ORIGINS=

QUANTLAB_USER_AGENT=quantlab/0.1 (research)
SEC_USER_AGENT=
FRED_API_KEY=
COMPANIES_HOUSE_API_KEY=
ENVFILE
	chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/.env"
	chmod 600 "$APP_DIR/.env"
else
	log "$APP_DIR/.env already exists -- left untouched"
fi

# Placeholder so `docker compose --env-file .env --env-file .env.images` works
# before the first deploy has written real tags.
if [ ! -f "$APP_DIR/.env.images" ]; then
	cat >"$APP_DIR/.env.images" <<'IMAGES'
# Written by .github/workflows/deploy.yml on every deploy. Do not edit by hand.
# Two images: the SPA is served by Vercel, so no frontend image runs here.
QUANTLAB_BACKEND_IMAGE=
QUANTLAB_INGEST_IMAGE=
IMAGES
	chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/.env.images"
fi

# ---------------------------------------------------------------------------
# systemd unit. Compose's `restart: unless-stopped` brings containers back after
# a crash but relies on the Docker daemon starting them at boot; a unit makes
# "the stack is up after a reboot" an explicit, checkable property, and gives
# `systemctl status quantlab` as the one place to look.
# ---------------------------------------------------------------------------
log "installing the quantlab systemd unit"
cat >/etc/systemd/system/quantlab.service <<UNIT
[Unit]
Description=QuantLab stack (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/docker compose --env-file ${APP_DIR}/.env --env-file ${APP_DIR}/.env.images -f ${APP_DIR}/docker-compose.prod.yml up -d --remove-orphans
ExecStop=/usr/bin/docker compose --env-file ${APP_DIR}/.env --env-file ${APP_DIR}/.env.images -f ${APP_DIR}/docker-compose.prod.yml down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable quantlab.service

# ---------------------------------------------------------------------------
# Housekeeping. A weekly image prune keeps the boot disk from filling with
# superseded image layers -- every deploy pulls three new ones.
# ---------------------------------------------------------------------------
cat >/etc/cron.weekly/quantlab-docker-prune <<'CRON'
#!/bin/sh
# Remove images not referenced by a running container and older than a week.
# Keeps the previous deploy's images around long enough to roll back to them.
/usr/bin/docker image prune -af --filter "until=168h" >/dev/null 2>&1
CRON
chmod +x /etc/cron.weekly/quantlab-docker-prune

log "enabling unattended security upgrades"
apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

cat <<DONE

Bootstrap complete.

  app dir : ${APP_DIR}
  env     : ${APP_DIR}/.env          (random DB passwords; add your API keys)
  registry: ${AR_REGION}-docker.pkg.dev

Next:
  1. REQUIRED: set QUANTLAB_CORS_ORIGINS in ${APP_DIR}/.env to your Vercel
     origin (e.g. https://your-project.vercel.app). The stack will not start
     without it. This VM serves the API only -- the SPA is on Vercel, so every
     browser call is cross-origin and an empty allow-list blocks all of them.
  2. REQUIRED for a working app: point a DNS record at this VM and set
     QUANTLAB_SITE_ADDRESS to that hostname. Vercel serves the SPA over HTTPS
     and a browser will not let an HTTPS page call an HTTP API, so the plain-HTTP
     default is only good for curling the box from itself.
  3. Add your ingest API keys to ${APP_DIR}/.env  (SEC_USER_AGENT, FRED_API_KEY, ...)
  4. In Vercel, set VITE_API_BASE_URL to https://<that-hostname>/api/v1 so the
     SPA calls this VM instead of its own origin.
  5. Push to main, or run the "deploy" workflow by hand. It copies the compose
     file here, writes ${APP_DIR}/.env.images, and starts the stack.

DONE
