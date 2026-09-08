# LUKS application storage

The Ubuntu root filesystem remains unencrypted so the server can boot and
accept SSH connections. PostgreSQL data, Docker data, Odoo configuration,
rclone credentials and cache, and application logs live on a manually unlocked
LUKS2 Hetzner Volume.

The exact first-install commands are in [README.md](README.md). They are kept in
the documentation because choosing and formatting a block device should be a
deliberate operator action, not hidden in a Bash script.

## Storage layout

```text
Hetzner Volume
└── LUKS2 mapper: appdata
    └── ext4 mounted at /srv/secure
        ├── postgresql      → /var/lib/postgresql
        ├── docker          → /var/lib/docker
        ├── containerd      → /var/lib/containerd
        ├── odoo-config     → /etc/odoo
        ├── rclone-config   → /root/.config/rclone
        ├── rclone-cache    → /root/.cache/rclone
        ├── nginx-temp      → /var/lib/nginx
        ├── tmp
        ├── secrets
        └── logs
            ├── nginx      → /var/log/nginx
            └── postgresql → /var/log/postgresql
```

The mapper and every bind mount use `noauto` in `/etc/fstab`. PostgreSQL,
Docker, containerd, nginx, rclone, and the deployment agent are disabled at
boot. Their systemd drop-ins declare every mount unit as a `Requisite`, so a
direct service start fails while the encrypted storage is not mounted.

Do not store database dumps in `/tmp` or `/var/tmp`. The agent uses
`/srv/secure/tmp`, PostgreSQL uses `/srv/secure/tmp/postgresql`, and nginx uses
its encrypted `/var/lib/nginx` bind mount. Persistent swap is disabled so
application memory is not written to unencrypted disk.

## Normal boot procedure

Replace the device path with the stable path recorded during installation:

```bash
cryptsetup open /dev/disk/by-id/<hetzner-volume-id> appdata
mount /srv/secure
mount /var/lib/postgresql
mount /var/lib/docker
mount /var/lib/containerd
mount /etc/odoo
mount /root/.config/rclone
mount /root/.cache/rclone
mount /var/log/nginx
mount /var/log/postgresql
mount /var/lib/nginx
nginx -t
systemctl start odoo-app.target
```

Before unlocking, SSH should work while the mapper, mounts, and application
services remain inactive. A wrong passphrase leaves the mapper closed. If a
mount command fails, stop there and inspect the device and `/etc/fstab` rather
than starting services.

Useful inspection commands:

```bash
cryptsetup status appdata
lsblk -f
findmnt /srv/secure
findmnt /var/lib/postgresql
findmnt /var/lib/docker
swapon --show
systemctl status odoo-app.target
```

To mount the data for maintenance without starting services, stop after the
last `mount` command. To stop the application and lock the volume:

```bash
systemctl stop odoo-app.target
umount /var/lib/nginx
umount /var/log/postgresql
umount /var/log/nginx
umount /root/.cache/rclone
umount /root/.config/rclone
umount /etc/odoo
umount /var/lib/containerd
umount /var/lib/docker
umount /var/lib/postgresql
umount /srv/secure
cryptsetup close appdata
```

## Recovery material

The first-install procedure creates
`/root/appdata-luks-header-<uuid>.img`. Copy it to offline storage, verify the
copy, and delete the server copy. Keep the header backup and passphrase
separately. Losing both usable LUKS headers and their backup makes the data
unrecoverable.

The rclone `crypt` password also needs a separate offline backup. Recovering the
LUKS volume does not recover a lost backup-encryption password.

## Volume expansion

After expanding the Hetzner Volume, unlock and mount it normally, stop the
application services, and run:

```bash
cryptsetup resize appdata
resize2fs /dev/mapper/appdata
lsblk
df -h /srv/secure
```

## Fresh-server checks

Before relying on a new installation:

1. Reboot and confirm SSH works while the application services remain stopped.
2. Confirm a wrong passphrase starts no service.
3. Unlock with the correct passphrase and mount each entry.
4. Confirm `findmnt` shows every sensitive path backed by `/srv/secure` and
   `swapon --show` is empty.
5. Run `nginx -t`, start `odoo-app.target`, and confirm PostgreSQL, Docker,
   nginx, rclone, and `deploy-manager19.service` are active.
6. Confirm port 8019 listens only on loopback and the public port 9019 requires
   nginx basic authentication.
