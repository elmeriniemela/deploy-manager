# LUKS application storage

The Ubuntu root filesystem remains unencrypted so the server can boot and
accept SSH connections. PostgreSQL data, Docker data, Odoo configuration,
rclone credentials and cache, and application logs live on a manually unlocked
LUKS2 Hetzner Volume.

The exact first-install commands are in [README.md](README.md). They are kept in
the documentation because choosing and formatting a block device should be a
deliberate operator action, not hidden in a Bash script.

The initial format may use a verified kernel device name such as `/dev/sdb`.
Identify it by matching the `MODEL`, `SERIAL`, and `SIZE` from `lsblk` with the
Hetzner Console. Once LUKS exists, `/etc/crypttab` stores its stable UUID; do not
persist `/dev/sdb`, because kernel device names can change.

## Storage layout

```text
Hetzner Volume
└── LUKS2 mapper: appdata
    └── ext4 mounted at /srv/secure
        ├── postgresql      → /var/lib/postgresql
        ├── docker          → /var/lib/docker
        ├── containerd      → /var/lib/containerd
        ├── odoo-config     → /etc/odoo
        ├── rclone-config
        ├── rclone-cache
        ├── backups         (rclone mountpoint)
        ├── nginx-temp      → /var/lib/nginx
        ├── tmp
        ├── secrets
        └── logs
            ├── nginx      → /var/log/nginx
            └── postgresql → /var/log/postgresql
```

The mapper and every bind mount use `noauto` in `/etc/fstab`. PostgreSQL,
Docker, containerd, nginx, rclone, and the deployment agent are disabled at
boot. Their systemd drop-ins use `RequiresMountsFor` so systemd starts the bind
mounts on demand and fails the service if a required mount cannot be started.

Rclone reads its configuration from `/srv/secure/rclone-config/rclone.conf`,
uses `/srv/secure/rclone-cache`, and mounts the decrypted backup view at
`/srv/secure/backups`.

Do not store database dumps in `/tmp` or `/var/tmp`. The agent uses
`/srv/secure/tmp`, PostgreSQL uses `/srv/secure/tmp/postgresql`, and nginx uses
its encrypted `/var/lib/nginx` bind mount. Persistent swap is disabled so
application memory is not written to unencrypted disk.

## Normal boot procedure

The generated `systemd-cryptsetup@appdata.service` reads the stable device UUID
from `/etc/crypttab`. From a root login shell, run:

```bash
systemctl start systemd-cryptsetup@appdata.service
systemctl start odoo-app.target
```

Before unlocking, SSH should work while the mapper, mounts, and application
services remain inactive. A wrong passphrase leaves the mapper closed. If a
mount unit fails, stop there and inspect the device and `/etc/fstab` rather
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

To mount the data for maintenance without starting services, start the encrypted
volume and mount units directly:

```bash
systemctl start systemd-cryptsetup@appdata.service
systemctl start srv-secure.mount var-lib-postgresql.mount var-lib-docker.mount var-lib-containerd.mount etc-odoo.mount var-log-nginx.mount var-log-postgresql.mount var-lib-nginx.mount
```

To stop the application and lock the volume:

```bash
systemctl stop odoo-app.target
umount /var/lib/nginx
umount /var/log/postgresql
umount /var/log/nginx
umount /etc/odoo
umount /var/lib/containerd
umount /var/lib/docker
umount /var/lib/postgresql
umount /srv/secure
systemctl stop systemd-cryptsetup@appdata.service
```

## Recovery material

The passphrase does not encrypt the data directly. It unlocks a protected copy
of the random volume-encryption key stored in a LUKS keyslot:

```text
Passphrase
    ↓ unlocks
LUKS header and keyslot
    ↓ reveals
Volume-encryption key
    ↓ decrypts
Data on the volume
```

`cryptsetup luksHeaderBackup` creates a binary copy of the LUKS metadata and
keyslot area. This includes the UUID, encryption parameters, keyslot information,
and encrypted copies of the volume key. It does not contain the passphrase in
plaintext, application files, or a complete image of the volume.

If the live header or its keyslots are damaged, the encrypted data may still be
physically present but impossible to decrypt. A header backup can restore the
information needed to unlock it:

```bash
cryptsetup luksHeaderRestore "/dev/disk/by-uuid/<luks-uuid>" --header-backup-file "/offline/path/appdata-luks-header-<uuid>.img"
```

Do not run `luksHeaderRestore` during normal operation. It overwrites the current
header; during recovery, preserve the damaged current header before attempting a
restore. A header backup also does not replace ordinary application-data backups.

The first-install procedure creates
`/root/appdata-luks-header-<uuid>.img`. The header backup alone cannot decrypt
the volume, but the backup together with a passphrase valid when it was created
can—even if that passphrase was later changed or removed from the live header.
Create a new header backup after intentional keyslot changes, and securely
destroy old copies if a removed passphrase must no longer work. Losing both the
usable live header and every header backup makes the data unrecoverable.

### Encrypting the header backup

GPG prompts for the password. Encrypt the header before transferring it:

```bash
HEADER_NAME="appdata-luks-header-$LUKS_UUID.img"
gpg --symmetric "/root/$HEADER_NAME"
```

Decrypt it when needed:

```bash
gpg --output "/root/$HEADER_NAME" --decrypt "/offline/path/$HEADER_NAME.gpg"
```

Transfer only the `.gpg` file and remove the plaintext server copy after the
backup is stored safely. Keep the GPG password separately.

See the official [`luksHeaderBackup` manual](https://man7.org/linux/man-pages/man8/cryptsetup-luksheaderbackup.8.html)
for the recovery and security warnings.

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
