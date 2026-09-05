# LUKS and Multi-Version Odoo Host Plan

## Summary

This plan targets a fresh Ubuntu server with an empty Hetzner Cloud Volume. The
Ubuntu root filesystem remains unencrypted so the server can boot normally and
accept SSH connections. Sensitive Odoo runtime state is stored on a manually
unlocked LUKS2 volume.

PostgreSQL, Docker, containerd, nginx, rclone, and the deployment agents must
remain stopped until the encrypted volume has been unlocked and its bind mounts
have been verified.

The server supports multiple Odoo versions through separate deploy-manager
clones and agents while sharing PostgreSQL, Docker, nginx, rclone, and the LUKS
volume. Release-specific values are hardcoded in each release branch.

Odoo 19 uses:

```text
Repository:       /opt/odoo19
Virtualenv:       /root/agent-venv19
Systemd service:  deploy-manager19.service
Agent backend:    127.0.0.1:8019
Public endpoint:  https://odoo19.eniemela.fi:9019
Container image:  ghcr.io/elmeriniemela/odoo-src:19.0
Container label:  odoo.version=19.0
```

When Odoo 20 is released, create a 20.0 branch and replace the relevant 19
values with 20. The resulting installation will use `/opt/odoo20`, ports 8020
and 9020, and a separate Odoo 20 agent that can run alongside Odoo 19.

## Storage layout

Create a LUKS2 container directly on the Hetzner Volume without a partition
table, format the decrypted mapper as ext4, and mount it at `/srv/secure`.

```text
Hetzner Volume
└── LUKS2 mapper: appdata
    └── ext4
        └── /srv/secure
            ├── postgresql
            ├── docker
            ├── containerd
            ├── odoo-config
            ├── rclone-config
            ├── rclone-cache
            ├── secrets
            └── logs
                ├── nginx
                └── postgresql
```

Bind-mount the encrypted directories to the conventional host paths:

```text
/srv/secure/postgresql      → /var/lib/postgresql
/srv/secure/docker          → /var/lib/docker
/srv/secure/containerd      → /var/lib/containerd
/srv/secure/odoo-config     → /etc/odoo
/srv/secure/rclone-config   → /root/.config/rclone
/srv/secure/rclone-cache    → /root/.cache/rclone
/srv/secure/logs/nginx      → /var/log/nginx
/srv/secure/logs/postgresql → /var/log/postgresql
```

Store `cloudflare.ini` under `/srv/secure/secrets` and configure the deployment
agent to read it from there. The rclone mount continues to use `/root/backups`,
but its configuration and VFS cache reside on the encrypted filesystem.

The following remain on the unencrypted root filesystem:

- Ubuntu and SSH configuration
- Deploy-manager and Odoo source under `/opt/odoo19`
- Nginx routing configuration
- TLS certificates and keys
- System logs unrelated to the Odoo application

Do not store customer data in `/tmp` or `/var/tmp`. Disable persistent swap so
that application memory cannot be written unencrypted to disk.

## One-time fresh-server bootstrap

Change `ubuntu-install.sh` into a one-time host bootstrap accepting the stable
Hetzner device path:

```bash
sudo ./ubuntu-install.sh /dev/disk/by-id/<hetzner-volume-id>
```

The script must perform the following steps in order:

1. Require root privileges and a `/dev/disk/by-id/...` argument.
2. Resolve and display the target device.
3. Refuse the root device, mounted or otherwise active devices, and devices
   containing unexpected signatures. It must never silently erase or reformat
   an existing filesystem.
4. Install `cryptsetup` before installing PostgreSQL or Docker.
5. If the device is blank, create a LUKS2 container using an interactively
   entered passphrase. Never save the passphrase on the server.
6. Open the volume as `/dev/mapper/appdata`.
7. Create an ext4 filesystem only when the mapper contains no filesystem.
   Re-running the script against the same valid LUKS/ext4 volume must not format
   it again.
8. Add an idempotent `/etc/crypttab` entry using the LUKS UUID and the `noauto`
   option.
9. Add idempotent `/etc/fstab` entries for `/srv/secure` and all bind mounts.
   They must use `noauto` and explicit dependencies on `/srv/secure`.
10. Mount `/srv/secure`, create the source and target directories with suitable
    ownership and permissions, and activate every bind mount.
11. Install and configure PostgreSQL, Docker, containerd, nginx, rclone, and the
    remaining host dependencies only after the encrypted mounts are active.
12. Install the systemd target, mount guards, unlock helper, and the hardcoded
    Odoo 19 release service.
13. Disable automatic boot activation of PostgreSQL, Docker, `docker.socket`,
    containerd, nginx, rclone, and the deployment agent.
14. Disable persistent swap and fail with a clear message if an unsupported
    swap configuration remains.

The script must use the existing LUKS volume safely when re-run. It must abort
instead of attempting to migrate or overwrite data; migration from an existing
unencrypted server is outside the scope of this plan.

### LUKS header backup

After formatting, create a mode-0600 header backup named with the LUKS UUID,
for example:

```text
/root/appdata-luks-header-<uuid>.img
```

The installer must prominently instruct the operator to copy this file to
offline storage, verify the copy, and delete the server copy. The header backup
and the passphrase must be stored separately. Losing both usable LUKS headers
and their backup makes the data unrecoverable.

## Manual boot and unlock behavior

Create a custom `odoo-app.target` that groups the protected services. It must
not be wanted by `multi-user.target` and therefore must not start during normal
boot.

Install `/usr/local/sbin/unlock-appdata` as a root-owned executable. It must be
idempotent and perform these operations:

1. Resolve the LUKS device from the `appdata` crypttab entry.
2. Run `cryptsetup open` interactively unless the mapper is already open.
3. Mount `/srv/secure` unless it is already mounted.
4. Verify that `/srv/secure` is backed by `/dev/mapper/appdata`.
5. Mount and verify every encrypted bind mount.
6. Start `odoo-app.target` only after all mount checks pass.

Normal reboot procedure:

```bash
ssh server
sudo unlock-appdata
```

Expected state before unlocking:

```text
Ubuntu and SSH running
LUKS mapper closed
/srv/secure not mounted
PostgreSQL stopped
Docker and containerd stopped
Nginx stopped
Rclone mount stopped
All deploy-manager agents stopped
```

Systemd drop-ins must use mount requirements and mount-point conditions for
PostgreSQL, Docker, containerd, nginx, rclone, and the deployment agents. Even
if a service is started directly or by a package upgrade, it must fail closed
instead of writing into an unencrypted directory hidden beneath a missing bind
mount.

Docker containers retain `--restart unless-stopped`; they restart normally when
Docker is started by `odoo-app.target` after unlocking.

## Odoo 19 release installation

Keep the one-time host bootstrap separate from a small release installer. The
bootstrap invokes the release installer for Odoo 19. On a server that is
already configured with LUKS, a future Odoo release runs only its release
installer.

The 19.0 branch hardcodes the release values. It must:

- Verify that it is running from `/opt/odoo19`.
- Create and populate `/root/agent-venv19`.
- Install `deploy-manager19.service` with working directory `/opt/odoo19`.
- Start the Python agent with `--interface 127.0.0.1 --port 8019`.
- Make the service wanted by `odoo-app.target`, not `multi-user.target`.
- Install a uniquely named nginx virtual host for
  `odoo19.eniemela.fi` listening with TLS on port 9019 and proxying to
  `127.0.0.1:8019`.
- Reuse the existing basic-auth file and wildcard certificate.
- Preserve shared nginx routing maps and configuration when another release is
  installed.

The public agent URL is therefore:

```text
https://odoo19.eniemela.fi:9019
```

DNS must point the hostname to the server, and the server and Hetzner firewalls
must permit TCP port 9019. Port 8019 remains loopback-only.

Update `update.sh`, module clone instructions, image commands, and scheduled
backup examples to use `/opt/odoo19`, `/root/agent-venv19`, and
`deploy-manager19.service`.

## Multi-version isolation

PostgreSQL, Docker, nginx, rclone, and the encrypted volume are shared between
Odoo versions. Instance UIDs, PostgreSQL database/role names, Docker volume
names, and assigned HTTP/gevent ports must therefore be globally unique.

Add the following label to every Odoo 19 container:

```text
odoo.version=19.0
```

The Odoo 19 agent must filter Docker discovery by this label. As a result:

- `status()` returns only Odoo 19 containers in `instances`.
- The Odoo 19 scheduled backup job backs up only Odoo 19 containers.
- A future Odoo 20 agent can use its own label without duplicating Odoo 19
  backups.

Keep XML-RPC method names and arguments unchanged. PostgreSQL status remains
host-wide because PostgreSQL has no equivalent version label and the shared
database cluster is intentional.

Container creation in the 19.0 branch must consistently use:

- Image `ghcr.io/elmeriniemela/odoo-src:19.0`
- Source mount `/opt/odoo19/src:/mnt:ro`
- Label `odoo.version=19.0`
- Manifest version prefix `19.0`

Existing unlabeled containers are not adopted because this plan targets a
fresh server.

## Shared nginx routing

All version agents update the same hostname-to-container-port maps. Protect the
complete read-modify-write-validation-reload operation with a shared file lock
under `/run/lock` so simultaneous agent requests cannot discard each other's
changes.

Write map files through a temporary file and atomically replace the destination.
Run `nginx -t` while holding the lock and reload nginx only when validation
succeeds.

Remove the static-file shortcut rooted at `/opt/deploy-manager/src`. It cannot
select the correct source tree when Odoo 19 and Odoo 20 coexist. Proxy static
requests through the hostname-selected Odoo container so each instance serves
assets from its own release and mounted modules.

## Secrets and logs

- Keep `/etc/odoo` on LUKS because generated configuration files contain
  PostgreSQL passwords.
- Keep the rclone configuration and VFS cache on LUKS because the configuration
  contains S3 credentials and the backup encryption password, while the cache
  may contain plaintext backup data.
- Keep the Cloudflare credential file on LUKS and update `ssl_wildcard()` to use
  its encrypted path.
- Keep nginx and PostgreSQL application logs on LUKS because URLs, client
  addresses, database names, queries, and errors may contain customer data.
- Do not log complete XML-RPC argument values. In particular, the `config()`
  call can contain a database password. Log the method name without its full
  arguments.
- Back up the rclone crypt password separately in an offline password manager.
  LUKS recovery alone is not sufficient to decrypt remote backups.

## Volume expansion

The volume has no partition table, so it can be expanded without rebuilding
the encryption layer.

After increasing the Hetzner Volume size, unlock and mount it normally, then
run:

```bash
sudo cryptsetup resize appdata
sudo resize2fs /dev/mapper/appdata
```

Verify the mapper and filesystem sizes with `lsblk` and `df` before returning
the server to normal operation.

## Validation and acceptance tests

### Automated checks

- Initialize the `agentd/cronsyl` submodule before running tests.
- Run the complete Python unit suite.
- Add tests for the Odoo 19 image, source path, Docker label, label-filtered
  discovery, encrypted secret paths, and concurrent nginx map preservation.
- Run `bash -n` on every setup, update, and helper script.
- Run `systemd-analyze verify` on the target, release service, mount units, and
  service drop-ins.
- Validate nginx configuration before installation and before every reload.
- Validate the README Mermaid diagram using the commands in `AGENTS.md`.

### Disposable-server acceptance test

1. Confirm that installation refuses the root disk, active devices, and
   nonblank non-LUKS devices.
2. Complete installation on an empty volume and verify all bind mounts resolve
   to `/dev/mapper/appdata`.
3. Reboot and verify SSH works while the mapper, mounts, and protected services
   remain inactive.
4. Enter a wrong passphrase and confirm that no protected service starts.
5. Run `unlock-appdata` with the correct passphrase and confirm all mounts and
   services start.
6. Verify that port 8019 listens only on loopback and that
   `https://odoo19.eniemela.fi:9019` returns the expected basic-auth challenge.
7. Create an Odoo 19 instance and verify its image, version label, source mount,
   database, encrypted Docker volume, backup, and hostname routing.
8. Run simulated Odoo 19 and Odoo 20 agents concurrently and verify that each
   sees and backs up only its labeled containers.
9. Update nginx maps concurrently from both agents and verify that neither
   version loses the other's routes.
10. Re-run the installers and confirm that the LUKS filesystem, persistent data,
    nginx maps, and existing release services are preserved.

## Assumptions and exclusions

- The target is a fresh Ubuntu server with a separate empty Hetzner Volume.
- Migrating an existing PostgreSQL cluster or Docker data directory is outside
  scope.
- One PostgreSQL cluster, Docker daemon, nginx instance, rclone remote, and LUKS
  volume are shared by all Odoo versions.
- Instance UIDs and ports are globally allocated and cannot be reused by
  another version.
- Release selection is intentionally hardcoded per Git branch; there is no
  runtime version argument or shared release configuration file.
- The LUKS passphrase, LUKS header backup, and rclone encryption password are
  stored securely off the server.
