#!/usr/bin/env bash
# QuantLab -- format (once) and mount the VM's data disk for Postgres and
# ClickHouse. Runs ON the VM, as root. Idempotent: safe to re-run, and it never
# formats a disk that already holds anything.
#
#   sudo bash prepare-data-disk.sh /dev/disk/by-id/google-<device-name>
#
# The databases' data lives on this separate persistent disk, not the 30 GB
# boot disk: the boot disk is mostly container images, and a database that
# fills it takes every service down at once. A separate disk can also be grown,
# snapshotted and re-attached to a rebuilt VM on its own.
#
# What it does:
#   - a disk already labelled quantlab-data is just mounted;
#   - a disk with NO filesystem signature and an all-zero first MiB is
#     formatted ext4, labelled quantlab-data;
#   - anything else is refused -- a signature, a partition table, or non-zero
#     bytes mean the disk is someone's data, and this script will not guess;
#   - mounts it at MOUNT_POINT (default /mnt/disks/quantlab) via /etc/fstab, by
#     label, with `nofail` so a detached disk cannot stop the VM from booting
#     (remote-deploy.sh then refuses to deploy against the missing mount);
#   - creates postgres/ and clickhouse/ under it.

set -euo pipefail

DEVICE="${1:?usage: prepare-data-disk.sh /dev/disk/by-id/google-<device-name>}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/disks/quantlab}"
LABEL=quantlab-data

log() { printf '==> %s\n' "$*"; }
fail() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

[ "$(id -u)" = 0 ] || fail "run as root (sudo)"
[ -b "$DEVICE" ] || fail "$DEVICE is not a block device"
real="$(readlink -f "$DEVICE")"
# The boot disk holds / -- refuse it, and anything partitioned, outright.
findmnt -rno SOURCE / | grep -q "^$real" && fail "$DEVICE is the boot disk"
[ -z "$(lsblk -nro NAME "$real" | tail -n +2)" ] || fail "$DEVICE has partitions -- not a blank data disk"

current_label="$(blkid -s LABEL -o value "$real" 2>/dev/null || true)"
if [ "$current_label" = "$LABEL" ]; then
	log "$DEVICE is already formatted as $LABEL"
elif [ -n "$(blkid -p "$real" 2>/dev/null || true)" ]; then
	fail "$DEVICE carries a filesystem or other signature ($(blkid -p "$real")). Refusing to format it."
elif [ "$(head -c 1048576 "$real" | tr -d '\0' | wc -c)" != "0" ]; then
	fail "$DEVICE has no signature but its first MiB is not empty. Refusing to format it."
else
	log "formatting $DEVICE as ext4 ($LABEL)"
	# lazy_* defer zeroing to the background: a 100 GB disk formats in seconds.
	mkfs.ext4 -q -L "$LABEL" -m 0 -E lazy_itable_init=1,lazy_journal_init=1,discard "$real"
fi

mkdir -p "$MOUNT_POINT"
if ! grep -q "^LABEL=$LABEL " /etc/fstab; then
	log "adding $MOUNT_POINT to /etc/fstab"
	cp -p /etc/fstab "/etc/fstab.pre-quantlab-data-$(date -u +%Y%m%dT%H%M%SZ)"
	printf 'LABEL=%s %s ext4 defaults,discard,nofail 0 2\n' "$LABEL" "$MOUNT_POINT" >>/etc/fstab
fi
mountpoint -q "$MOUNT_POINT" || mount "$MOUNT_POINT"
mountpoint -q "$MOUNT_POINT" || fail "$MOUNT_POINT did not mount"

mkdir -p "$MOUNT_POINT/postgres" "$MOUNT_POINT/clickhouse"
df -h "$MOUNT_POINT"
log "data disk ready at $MOUNT_POINT"
