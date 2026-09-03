# Odoo Server Setup Plan

## 1. Base server
- Create a fresh Ubuntu LTS Hetzner Cloud server.
- Attach a separate Hetzner Cloud Volume for application data.
- Keep the Ubuntu root filesystem unencrypted so the server can boot and SSH normally.

## 2. Encrypt the data volume
- Install `cryptsetup`.
- Create a LUKS2 container directly on the Hetzner Volume.
- Format the decrypted device as `ext4`.
- Mount it at `/srv/secure`.
- Keep the LUKS passphrase off the server.
- Back up the LUKS header securely.

Layout:

```text
Hetzner Volume
└── LUKS2
    └── ext4
        └── /srv/secure
```

## 3. Put application data on the encrypted filesystem

Create:

```text
/srv/secure/postgresql
/srv/secure/docker
/srv/secure/containerd
```

Bind-mount them to the standard Ubuntu/Docker locations:

```text
/srv/secure/postgresql  → /var/lib/postgresql
/srv/secure/docker      → /var/lib/docker
/srv/secure/containerd  → /var/lib/containerd
```

This allows PostgreSQL, Docker and Odoo to use their normal configuration while all persistent application data resides on LUKS.

## 4. Configure boot behavior
Do not automatically unlock the LUKS volume.

After reboot:

```text
Ubuntu boots
↓
network + SSH start
↓
encrypted volume remains locked
↓
PostgreSQL/Docker remain stopped
```

Disable automatic startup of:

```text
postgresql
docker
docker.socket
containerd
```

Add systemd mount-point checks so these services cannot accidentally write data to the unencrypted root filesystem.

## 5. Install PostgreSQL and Docker
With the encrypted filesystem mounted and bind mounts active:

- Install PostgreSQL using Ubuntu packages.
- Install Docker Engine from Docker's repository.
- Install Docker Compose.
- Deploy Odoo normally using Docker Compose.

No custom PostgreSQL `data_directory` or Docker `data-root` configuration should be necessary.

## 6. Manual startup after reboot
Create a root-owned helper such as:

```text
/usr/local/sbin/unlock-appdata
```

It should:

1. Run `cryptsetup open` and request the LUKS passphrase.
2. Mount `/srv/secure`.
3. Mount the PostgreSQL/Docker/containerd bind mounts.
4. Start containerd.
5. Start Docker.
6. Start PostgreSQL.
7. Start Odoo if it is not automatically started by Docker.

Normal reboot procedure:

```bash
ssh server
sudo unlock-appdata
```

## 7. Additional encrypted-data considerations
- Disable swap or configure encrypted swap.
- Avoid storing customer data in unencrypted `/tmp` or `/var/tmp`.
- Review PostgreSQL, Odoo, Docker and reverse-proxy logs for user data.
- Either minimize sensitive logging or move relevant logs onto encrypted storage.

## 8. Volume expansion
Use:

```text
Hetzner Volume
→ LUKS
→ ext4
```

without a partition table.

When additional space is needed:

```bash
# Increase Volume size in Hetzner first
sudo cryptsetup resize appdata
sudo resize2fs /dev/mapper/appdata
```

The volume can therefore be expanded later without rebuilding or re-encrypting the existing data.