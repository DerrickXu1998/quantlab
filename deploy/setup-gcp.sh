#!/usr/bin/env bash
# QuantLab -- one-time GCP setup for the "VM + Artifact Registry + GitHub Actions"
# deployment. Run it once from your laptop or Cloud Shell, as a project owner:
#
#     PROJECT_ID=my-project ZONE=europe-west2-c bash deploy/setup-gcp.sh
#
# It is idempotent -- every step is skipped or updated if it already exists, so
# re-run it after changing a variable rather than unpicking things by hand.
#
# It creates, in this order:
#   1. the APIs the pipeline calls
#   2. an Artifact Registry Docker repository for the three images
#   3. a service account for the VM, allowed to PULL images
#   4. a service account for GitHub Actions, allowed to PUSH images and to SSH
#   5. a Workload Identity Federation pool, so Actions authenticates with a
#      short-lived OIDC token and there is no JSON key anywhere to leak
#   6. firewall rules: 80/443 from anywhere, SSH only through IAP
#
# It does NOT create the VM -- you already have one. It will attach the VM
# service account and the network tag to it, which is a stop/start.

set -euo pipefail

# --- what you must set --------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-}"
ZONE="${ZONE:-}"

# --- what you can leave alone -------------------------------------------------
INSTANCE="${INSTANCE:-quantlab}"
# deploy/docker-compose.prod.yml sizes the stack for 8 GiB. Changing this
# without retuning those limits will get containers OOM-killed.
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-2}"
REGION="${REGION:-${ZONE%-*}}"          # europe-west2-c -> europe-west2
AR_REPO="${AR_REPO:-quantlab}"
GITHUB_REPO="${GITHUB_REPO:-DerrickXu1998/quantlab}"
POOL_ID="${POOL_ID:-github}"
PROVIDER_ID="${PROVIDER_ID:-github-oidc}"
VM_SA_ID="${VM_SA_ID:-quantlab-vm}"
DEPLOYER_SA_ID="${DEPLOYER_SA_ID:-quantlab-deployer}"
NETWORK_TAG="${NETWORK_TAG:-quantlab}"
STATIC_IP_NAME="${STATIC_IP_NAME:-quantlab-api}"

log() { printf '\n=== %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
# Most `gcloud ... create` calls fail with ALREADY_EXISTS on a re-run. That is
# the idempotent outcome, not an error -- but a genuine failure must still stop
# the script, so only that one message is swallowed.
ok_if_exists() {
	local out
	if ! out="$("$@" 2>&1)"; then
		printf '%s\n' "$out" | grep -qiE 'already exists|ALREADY_EXISTS' || { printf '%s\n' "$out" >&2; return 1; }
		printf '  (already exists)\n'
	else
		printf '%s\n' "$out"
	fi
}

command -v gcloud >/dev/null 2>&1 || fail "gcloud not found -- https://cloud.google.com/sdk/docs/install"
[ -n "$PROJECT_ID" ] || fail "set PROJECT_ID"
[ -n "$ZONE" ] || fail "set ZONE (e.g. ZONE=europe-west2-c)"

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
VM_SA="${VM_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
DEPLOYER_SA="${DEPLOYER_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"

log "project ${PROJECT_ID} (#${PROJECT_NUMBER}), zone ${ZONE}, region ${REGION}"

# --- 1. APIs ------------------------------------------------------------------
log "enabling APIs"
gcloud services enable \
	artifactregistry.googleapis.com \
	compute.googleapis.com \
	iamcredentials.googleapis.com \
	iap.googleapis.com \
	sts.googleapis.com

# --- 2. Artifact Registry -----------------------------------------------------
log "Artifact Registry repository ${AR_REPO} in ${REGION}"
ok_if_exists gcloud artifacts repositories create "$AR_REPO" \
	--repository-format=docker \
	--location="$REGION" \
	--description="QuantLab container images"

# Superseded image versions are pure cost. Keep the 10 most recent of each image
# and delete untagged layers after a week; rollback targets stay, history does not.
log "applying a cleanup policy to the repository"
policy="$(mktemp)"
cat >"$policy" <<'JSON'
[
  {
    "name": "keep-recent-tagged",
    "action": {"type": "Keep"},
    "mostRecentVersions": {"keepCount": 10}
  },
  {
    "name": "delete-untagged-after-7d",
    "action": {"type": "Delete"},
    "condition": {"tagState": "untagged", "olderThan": "7d"}
  }
]
JSON
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" \
	--location="$REGION" --policy="$policy" --no-dry-run
rm -f "$policy"

# --- 3. VM service account (pull only) ---------------------------------------
log "VM service account ${VM_SA}"
ok_if_exists gcloud iam service-accounts create "$VM_SA_ID" \
	--display-name="QuantLab VM"

# Scoped to the one repository, not the whole project: the VM has no reason to
# read any other image.
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
	--location="$REGION" \
	--member="serviceAccount:${VM_SA}" \
	--role=roles/artifactregistry.reader \
	--condition=None >/dev/null
# So the VM can write its own logs and metrics, which is how you debug it later.
for role in roles/logging.logWriter roles/monitoring.metricWriter; do
	gcloud projects add-iam-policy-binding "$PROJECT_ID" \
		--member="serviceAccount:${VM_SA}" --role="$role" --condition=None >/dev/null
done

# --- 4. Deployer service account (push + SSH) --------------------------------
log "deployer service account ${DEPLOYER_SA}"
ok_if_exists gcloud iam service-accounts create "$DEPLOYER_SA_ID" \
	--display-name="QuantLab GitHub Actions deployer"

gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
	--location="$REGION" \
	--member="serviceAccount:${DEPLOYER_SA}" \
	--role=roles/artifactregistry.writer \
	--condition=None >/dev/null

# osAdminLogin, not osLogin: the deploy step writes into /opt and drives Docker,
# both of which need sudo on the VM. iap.tunnelResourceAccessor is what lets it
# reach port 22 without the VM having an SSH port open to the internet.
for role in roles/compute.osAdminLogin roles/iap.tunnelResourceAccessor roles/compute.viewer; do
	gcloud projects add-iam-policy-binding "$PROJECT_ID" \
		--member="serviceAccount:${DEPLOYER_SA}" --role="$role" --condition=None >/dev/null
done

# actAs on the INSTANCE's service account. Easy to assume this is only needed to
# create a VM with a service account attached, but `gcloud compute ssh` requires
# it too: connecting to an instance means borrowing the identity it runs as.
# Without it the deploy authenticates fine, reaches IAP, and is refused at the
# door with "User does not have iam.serviceAccounts.actAs permission" -- after
# the images have already been built and pushed.
#
# Granted on the VM account specifically rather than project-wide, so the
# deployer can impersonate this one identity and no other.
gcloud iam service-accounts add-iam-policy-binding "$VM_SA" \
	--member="serviceAccount:${DEPLOYER_SA}" \
	--role=roles/iam.serviceAccountUser >/dev/null

# --- 5. Workload Identity Federation -----------------------------------------
log "workload identity pool ${POOL_ID}"
ok_if_exists gcloud iam workload-identity-pools create "$POOL_ID" \
	--location=global --display-name="GitHub Actions"

log "OIDC provider ${PROVIDER_ID} for ${GITHUB_REPO}"
# The attribute condition is the security boundary. Without it, ANY GitHub
# repository in the world could mint a token for this pool and push images here.
ok_if_exists gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
	--location=global \
	--workload-identity-pool="$POOL_ID" \
	--display-name="GitHub OIDC" \
	--issuer-uri="https://token.actions.githubusercontent.com" \
	--attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
	--attribute-condition="assertion.repository=='${GITHUB_REPO}'"

# Only workflows in that repository may impersonate the deployer.
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
	--role=roles/iam.workloadIdentityUser \
	--member="principalSet://iam.googleapis.com/${POOL_RESOURCE}/attribute.repository/${GITHUB_REPO}" >/dev/null

# --- 6. Firewall --------------------------------------------------------------
log "firewall rules"
ok_if_exists gcloud compute firewall-rules create "quantlab-allow-http" \
	--direction=INGRESS --action=ALLOW --rules=tcp:80,tcp:443 \
	--target-tags="$NETWORK_TAG" --source-ranges=0.0.0.0/0 \
	--description="QuantLab public web traffic"

# 35.235.240.0/20 is IAP's forwarding range and the only source that should ever
# reach port 22. Delete any default-allow-ssh rule once this is in place.
ok_if_exists gcloud compute firewall-rules create "quantlab-allow-ssh-iap" \
	--direction=INGRESS --action=ALLOW --rules=tcp:22 \
	--target-tags="$NETWORK_TAG" --source-ranges=35.235.240.0/20 \
	--description="SSH via Identity-Aware Proxy only"

# --- 7. Attach the service account and tag to the existing VM ----------------
if gcloud compute instances describe "$INSTANCE" --zone "$ZONE" >/dev/null 2>&1; then
	log "configuring instance ${INSTANCE}"

	# Reserve the external IP BEFORE anything stops the instance. A default VM
	# gets an *ephemeral* address, which is released on stop and replaced on
	# start -- so the resize below would silently move the API to a new IP and
	# break the DNS record pointing at it. Promoting the address it already has
	# keeps the current value and costs the same as any other static IP.
	current_ip="$(gcloud compute instances describe "$INSTANCE" --zone "$ZONE" \
		--format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || true)"
	ip_kind="$(gcloud compute addresses list --filter="address=${current_ip}" \
		--format='value(addressType)' 2>/dev/null | head -1)"

	if [ -n "$current_ip" ] && [ -z "$ip_kind" ]; then
		log "reserving ${current_ip} as a static address (it is currently ephemeral)"
		ok_if_exists gcloud compute addresses create "${STATIC_IP_NAME}" \
			--addresses="$current_ip" --region="$REGION" \
			--description="QuantLab API, promoted from ephemeral"
	else
		printf '  external IP %s is already reserved (%s)\n' "${current_ip:-none}" "${ip_kind:-unknown}"
	fi

	# Not disks[0]: an instance with a data disk attached may list it first, and
	# measuring the wrong disk would be silently useless.
	#
	# `describe` has no --filter (that is a `list` flag, and passing it here is a
	# usage error, not an empty result), so the boot flag is selected after the
	# fact. || true because this is advisory: a failure here must not abort a
	# setup run that has already created real resources.
	BOOT_DISK_NAME="$(gcloud compute instances describe "$INSTANCE" --zone "$ZONE" \
		--flatten="disks[]" \
		--format="value(disks.boot, disks.source.basename())" 2>/dev/null |
		awk -F'\t' '$1 == "True" { print $2; exit }' || true)"

	# OS Login is what makes the deployer SA's IAM roles grant SSH access;
	# without it the VM expects keys in project metadata instead.
	gcloud compute instances add-metadata "$INSTANCE" --zone "$ZONE" \
		--metadata=enable-oslogin=TRUE >/dev/null

	gcloud compute instances add-tags "$INSTANCE" --zone "$ZONE" \
		--tags="$NETWORK_TAG" >/dev/null

	current_sa="$(gcloud compute instances describe "$INSTANCE" --zone "$ZONE" \
		--format='value(serviceAccounts[0].email)')"
	current_type="$(gcloud compute instances describe "$INSTANCE" --zone "$ZONE" \
		--format='value(machineType.basename())')"

	# Both of these need the instance TERMINATED, so they share one stop/start
	# rather than costing two. Nothing is lost: disks and their data persist.
	needs_stop="no"
	[ "$current_sa" != "$VM_SA" ] && needs_stop="yes"
	[ "$current_type" != "$MACHINE_TYPE" ] && needs_stop="yes"

	if [ "$needs_stop" = "yes" ]; then
		log "stopping ${INSTANCE} to reconfigure it"
		gcloud compute instances stop "$INSTANCE" --zone "$ZONE"

		if [ "$current_type" != "$MACHINE_TYPE" ]; then
			# The stock scopes leave cloud-platform disabled, and access scopes
			# gate API calls independently of IAM: without this the VM cannot
			# pull from Artifact Registry however many roles its account holds.
			log "resizing ${current_type} -> ${MACHINE_TYPE}"
			gcloud compute instances set-machine-type "$INSTANCE" --zone "$ZONE" \
				--machine-type="$MACHINE_TYPE"
		fi

		if [ "$current_sa" != "$VM_SA" ]; then
			log "attaching ${VM_SA}"
			gcloud compute instances set-service-account "$INSTANCE" --zone "$ZONE" \
				--service-account="$VM_SA" \
				--scopes=https://www.googleapis.com/auth/cloud-platform
		fi

		gcloud compute instances start "$INSTANCE" --zone "$ZONE"
	else
		printf '  already %s with %s attached\n' "$MACHINE_TYPE" "$VM_SA"
	fi

	# The compose memory limits assume 8 GiB. Warn rather than fail: someone may
	# have deliberately chosen a smaller box and retuned them.
	case "$MACHINE_TYPE" in
		e2-standard-2 | e2-standard-4 | e2-standard-8 | n2-standard-*) ;;
		*) printf '\n  WARNING: deploy/docker-compose.prod.yml sizes the stack for 8 GiB.\n           %s may not have that; retune the limits or the stack will be OOM-killed.\n' "$MACHINE_TYPE" ;;
	esac

	# A 30 GiB boot disk fills quickly: three image versions, ClickHouse parts
	# and its logs all live there unless something else is mounted.
	boot_gb="$(gcloud compute disks describe "$BOOT_DISK_NAME" --zone "$ZONE" \
		--format='value(sizeGb)' 2>/dev/null || echo "")"
	if [ -n "$boot_gb" ] && [ "$boot_gb" -lt 50 ]; then
		printf '\n  NOTE: the boot disk is %sGB. ClickHouse data, Postgres and every pulled\n        image share it. Grow it, or mount a data disk at /var/lib/docker.\n' "$boot_gb"
	fi
else
	log "instance ${INSTANCE} not found in ${ZONE} -- skipping instance configuration"
	cat <<CREATE

If you need to create it:

  gcloud compute instances create ${INSTANCE} \\
    --zone=${ZONE} --machine-type=e2-standard-2 \\
    --image-family=debian-12 --image-project=debian-cloud \\
    --boot-disk-size=100GB --boot-disk-type=pd-balanced \\
    --service-account=${VM_SA} \\
    --scopes=https://www.googleapis.com/auth/cloud-platform \\
    --tags=${NETWORK_TAG} --metadata=enable-oslogin=TRUE

CREATE
fi

# --- 8. Disk snapshots --------------------------------------------------------
# The honest weak point of a single-VM deployment: one disk holds the ClickHouse
# bars, the Postgres catalog and the TLS certificates, and nothing replicates it.
# Snapshots are incremental and cost cents a month at this size -- far and away
# the cheapest risk reduction available here.
log "daily snapshot schedule"
ok_if_exists gcloud compute resource-policies create snapshot-schedule quantlab-daily \
	--region="$REGION" \
	--max-retention-days=14 \
	--daily-schedule --start-time=03:00 \
	--on-source-disk-delete=apply-retention-policy \
	--description="QuantLab boot disk, daily at 03:00 UTC, kept 14 days"

if gcloud compute instances describe "$INSTANCE" --zone "$ZONE" >/dev/null 2>&1; then
	# Every attached disk, not just the boot one: a data disk holding the
	# ClickHouse volume is the disk you would most regret losing.
	DISKS="$(gcloud compute instances describe "$INSTANCE" --zone "$ZONE" \
		--flatten="disks[]" --format="value(disks.source.basename())" 2>/dev/null)"
	for disk in $DISKS; do
		[ -n "$disk" ] || continue
		# Attaching a policy that is already attached is an error, not a no-op.
		if gcloud compute disks describe "$disk" --zone "$ZONE" \
			--format='value(resourcePolicies)' 2>/dev/null | grep -q quantlab-daily; then
			printf '  already attached to disk %s\n' "$disk"
		else
			gcloud compute disks add-resource-policies "$disk" --zone "$ZONE" \
				--resource-policies=quantlab-daily >/dev/null 2>&1 &&
				printf '  attached to disk %s\n' "$disk" ||
				printf '  could not attach to disk %s (it may already have a schedule)\n' "$disk"
		fi
	done
fi

# --- What to paste into GitHub ------------------------------------------------
PROVIDER_RESOURCE="${POOL_RESOURCE}/providers/${PROVIDER_ID}"
EXTERNAL_IP="$(gcloud compute instances describe "$INSTANCE" --zone "$ZONE" \
	--format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || true)"

cat <<SUMMARY

================================================================================
Setup complete. Add these as repository VARIABLES (not secrets -- none of them
are sensitive, and Workload Identity Federation means there is no key to store):

  gh variable set GCP_PROJECT_ID            --body '${PROJECT_ID}'
  gh variable set GCP_REGION                --body '${REGION}'
  gh variable set GCP_ZONE                  --body '${ZONE}'
  gh variable set GCP_INSTANCE              --body '${INSTANCE}'
  gh variable set GCP_AR_REPO               --body '${AR_REPO}'
  gh variable set GCP_SERVICE_ACCOUNT       --body '${DEPLOYER_SA}'
  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --body '${PROVIDER_RESOURCE}'

Then, on the VM:

  gcloud compute ssh ${INSTANCE} --zone ${ZONE} --tunnel-through-iap
  sudo AR_REGION=${REGION} bash /path/to/deploy/bootstrap-vm.sh

$( [ -n "$EXTERNAL_IP" ] && printf 'The VM is at http://%s/ once the first deploy lands.' "$EXTERNAL_IP" )
================================================================================

SUMMARY
