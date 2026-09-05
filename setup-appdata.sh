#!/bin/bash

set -euo pipefail
cd "$(dirname "$0")"
source ./appdata.sh

[[ $EUID == 0 && $# == 1 && $1 == /dev/disk/by-id/* ]] || fail 'Usage: sudo ./setup-appdata.sh /dev/disk/by-id/<volume>'
device=$(readlink -e "$1")
[[ -b "$device" && $(lsblk -dnro TYPE "$device") == disk ]] || fail 'Supply a whole, unpartitioned volume.'
echo "Application data volume: $1 ($device)"

# Reject the boot disk even when / is inside a partition or device mapper.
root_device=$(findmnt -nro MAJ:MIN /)
root_ancestors=$(lsblk -snro MAJ:MIN "/dev/block/$root_device")
[[ -n "$root_ancestors" ]] || fail 'Cannot identify the root disk.'
if grep -Fxq "$(lsblk -dnro MAJ:MIN "$device")" <<< "$root_ancestors"; then
    fail 'Refusing the root disk.'
fi

apt update
apt install -y cryptsetup

signature=$(wipefs --no-act --noheadings --output TYPE "$device" | sort -u | xargs)
case "$signature" in
    '')
        [[ $(lsblk -nrpo NAME "$device" | wc -l) == 1 ]] || fail 'Volume has partitions or active holders.'
        [[ -z $(lsblk -nro MOUNTPOINTS "$device" | xargs) ]] || fail 'Volume is mounted or used as swap.'
        [[ ! -e /dev/mapper/appdata ]] || fail 'appdata already exists.'
        if [[ -f /etc/crypttab ]] && grep -qE '^appdata[[:space:]]' /etc/crypttab; then
            fail 'appdata is already configured; refusing a different volume.'
        fi
        ;;
    crypto_LUKS)
        cryptsetup isLuks --type luks2 "$device" || fail 'Expected LUKS2.'
        [[ "$device" == "$(appdata_device)" ]] || fail 'Existing LUKS volume is not the configured appdata device.'
        while read -r child; do
            [[ "$child" == "$device" || "$child" == /dev/mapper/appdata ]] || fail "Unexpected active device: $child"
        done < <(lsblk -nrpo NAME "$device")
        if [[ -e /dev/mapper/appdata ]]; then
            check_mapper
            while read -r target; do
                [[ -z "$target" ]] && continue
                allowed=false
                [[ "$target" == /srv/secure ]] && allowed=true
                for entry in "${appdata_mounts[@]}"; do
                    [[ "$target" == "${entry#*:}" ]] && allowed=true
                done
                "$allowed" || fail "Unexpected mount on appdata: $target"
            done < <(lsblk -nro MOUNTPOINTS /dev/mapper/appdata)
        fi
        ;;
    *) fail "Refusing volume with existing signatures: $signature" ;;
esac

# Never hide pre-existing plaintext data beneath a bind mount.
for entry in "${appdata_mounts[@]}"; do
    target=${entry#*:}
    [[ ! -L "$target" ]] || fail "Refusing symlink: $target"
    if mountpoint -q "$target"; then
        check_secure
        check_bind "/srv/secure/${entry%%:*}" "$target"
    elif [[ -d "$target" && -n $(find "$target" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
        fail "$target is not empty. Existing-server migration is not supported."
    fi
done
if mountpoint -q /srv/secure; then
    check_secure
elif [[ -d /srv/secure && -n $(find /srv/secure -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    fail '/srv/secure is not empty.'
fi
[[ ! -L /srv/secure ]] || fail 'Refusing /srv/secure symlink.'

if [[ -z "$signature" ]]; then
    # cryptsetup retains its interactive destructive-operation confirmation.
    cryptsetup luksFormat --type luks2 "$device"
    uuid=$(cryptsetup luksUUID "$device")
    printf 'appdata UUID=%s none luks,noauto\n' "$uuid" >> /etc/crypttab
    (umask 077; cryptsetup luksHeaderBackup "$device" --header-backup-file "/root/appdata-luks-header-$uuid.img")
    echo "Copy /root/appdata-luks-header-$uuid.img offline, verify it, then delete the server copy. Store the passphrase separately."
    udevadm trigger --action=change --name-match="$device"
    udevadm settle
fi
cryptsetup status appdata >/dev/null || cryptsetup open "$device" appdata
check_mapper
signature=$(wipefs --no-act --noheadings --output TYPE /dev/mapper/appdata | sort -u | xargs)
case "$signature" in
    '') mkfs.ext4 /dev/mapper/appdata ;;
    ext4) ;;
    *) fail "Expected ext4, found: $signature" ;;
esac

# Disable fstab swap persistently. Native swap units/generators must be removed
# by the operator; silently leaving them configured could expose customer data.
swapoff --all
sed -i '/^[^#].*[[:space:]]swap[[:space:]]/s/^/# Disabled for LUKS appdata: /' /etc/fstab
systemctl daemon-reload
[[ -z $(systemctl list-unit-files --type=swap --state=enabled,generated --no-legend) ]] || fail 'Disable native swap units or swap generators, then re-run setup.'
systemctl mask swap.target

fstab_entry() {
    local source=$1 target=$2 type=$3 options=$4 pass=$5 existing
    existing=$(awk -v target="$target" '$2 == target {print}' /etc/fstab)
    if [[ -n "$existing" ]]; then
        [[ "$existing" == "$source $target $type $options 0 $pass" ]] || fail "Conflicting fstab entry for $target."
    else
        printf '%s %s %s %s 0 %s\n' "$source" "$target" "$type" "$options" "$pass" >> /etc/fstab
    fi
}

install -d /srv/secure
fstab_entry /dev/mapper/appdata /srv/secure ext4 noauto 2
systemctl daemon-reload
mountpoint -q /srv/secure || mount /srv/secure
check_secure
for entry in "${appdata_mounts[@]}"; do
    source_dir=/srv/secure/${entry%%:*}
    target=${entry#*:}
    mkdir -p "$source_dir" "$target"
    fstab_entry "$source_dir" "$target" none noauto,bind,x-systemd.requires=srv-secure.mount 0
done
install -d -m 0700 /srv/secure/secrets /srv/secure/rclone-config /srv/secure/rclone-cache
install -d -m 0711 /srv/secure/tmp
systemctl daemon-reload
mount_appdata
install -D -m 0644 appdata.sh /usr/local/lib/odoo-appdata.sh
install -m 0755 unlock-appdata /usr/local/sbin/unlock-appdata
