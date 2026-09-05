# Shared by setup-appdata.sh and /usr/local/sbin/unlock-appdata.
appdata_mounts=(
    postgresql:/var/lib/postgresql
    docker:/var/lib/docker
    containerd:/var/lib/containerd
    odoo-config:/etc/odoo
    rclone-config:/root/.config/rclone
    rclone-cache:/root/.cache/rclone
    logs/nginx:/var/log/nginx
    logs/postgresql:/var/log/postgresql
    nginx-temp:/var/lib/nginx
)

fail() {
    echo "$*" >&2
    exit 1
}

appdata_guard() {
    # Requisite checks existing mounts without pulling in a locked LUKS device.
    local entry mounts=(srv-secure.mount)
    for entry in "${appdata_mounts[@]}"; do
        mounts+=("$(systemd-escape --path --suffix=mount "${entry#*:}")")
    done
    # Ubuntu's postgresql@ unit otherwise pulls its data mount in on startup.
    printf '[Unit]\nRequiresMountsFor=\nRequisite=%s\nAfter=%s\nPartOf=odoo-app.target\nConditionPathIsMountPoint=/srv/secure\n' "${mounts[*]}" "${mounts[*]}"
    if [[ "$1" != *.socket ]]; then
        printf '\n[Service]\nExecStartPre=+/usr/local/sbin/unlock-appdata --check\nEnvironment=TMPDIR=/srv/secure/tmp\n'
    fi
}

appdata_device() {
    local uuid
    uuid=$(awk '$1 == "appdata" {print $2; count++} END {if (count != 1) exit 1}' /etc/crypttab) || fail 'Expected one appdata entry in /etc/crypttab.'
    [[ "$uuid" == UUID=* ]] || fail 'appdata must use a LUKS UUID.'
    readlink -e "/dev/disk/by-uuid/${uuid#UUID=}"
}

check_mapper() {
    local device expected
    device=$(cryptsetup status appdata | awk '$1 == "device:" {print $2}')
    device=$(readlink -e "$device") || fail 'Cannot resolve the appdata backing device.'
    expected=$(appdata_device) || fail 'Cannot resolve the configured appdata device.'
    [[ -n "$device" && "$device" == "$expected" ]] || fail 'appdata is mapped to the wrong device.'
}

check_secure() {
    check_mapper
    mountpoint -q /srv/secure || fail '/srv/secure is not mounted.'
    [[ $(findmnt -nro MAJ:MIN -M /srv/secure) == "$(lsblk -dnro MAJ:MIN /dev/mapper/appdata)" ]] || fail '/srv/secure is not backed by appdata.'
    [[ $(findmnt -nro FSTYPE -M /srv/secure) == ext4 && $(findmnt -nro FSROOT -M /srv/secure) == / ]] || fail '/srv/secure must mount the root of the ext4 filesystem.'
}

check_bind() {
    local source=$1 target=$2 source_inode target_inode
    mountpoint -q "$target" || fail "$target is not mounted."
    source_inode=$(stat -c '%d:%i' "$source") || fail "Cannot inspect $source."
    target_inode=$(stat -c '%d:%i' "$target") || fail "Cannot inspect $target."
    [[ "$source_inode" == "$target_inode" ]] || fail "$target is not bound to $source."
}

check_appdata() {
    check_secure
    local entry
    for entry in "${appdata_mounts[@]}"; do
        check_bind "/srv/secure/${entry%%:*}" "${entry#*:}"
    done
    [[ -z $(swapon --show --noheadings) ]] || fail 'Disable swap before starting application services.'
}

mount_appdata() {
    check_mapper
    mountpoint -q /srv/secure || mount /srv/secure
    check_secure
    local entry target
    for entry in "${appdata_mounts[@]}"; do
        target=${entry#*:}
        mountpoint -q "$target" || mount "$target"
        check_bind "/srv/secure/${entry%%:*}" "$target"
    done
    check_appdata
}
