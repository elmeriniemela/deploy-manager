#!/bin/bash

set -euo pipefail
cd "$(dirname "$0")"
source ./appdata.sh

[[ $EUID == 0 && $(pwd -P) == /opt/odoo19 ]] || fail 'Run as root from /opt/odoo19.'
for service in postgresql docker containerd nginx rclone-mount odoo-app.target; do
    if systemctl is-active --quiet "$service"; then
        fail "$service is active. Stop application services before running the host bootstrap."
    fi
done
bash ./setup-appdata.sh "$@"

# Package post-install scripts must not start services before configuration.
# Leave these runtime masks in place on failure; a successful rerun removes them.
services=(postgresql.service postgresql@.service docker.service docker.socket containerd.service nginx.service rclone-mount.service)
systemctl mask --runtime "${services[@]}"
# Install guards before packages: even a reboot during setup must fail closed.
for service in "${services[@]}" deploy-manager19.service; do
    mkdir -p "/etc/systemd/system/$service.d"
    appdata_guard "$service" > "/etc/systemd/system/$service.d/appdata.conf"
done
systemctl daemon-reload
apt install -y postgresql nginx ca-certificates curl gnupg vim tmux patchutils fuse3 python3-pip python3-venv unattended-upgrades apache2-utils rsync rclone

# https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

install -m 0644 systemd/system/odoo-app.target systemd/system/rclone-mount.service /etc/systemd/system/
install -D -m 0644 systemd/system/docker.service.d/override.conf /etc/systemd/system/docker.service.d/override.conf

# PostgreSQL needs a writable temporary directory owned by its own user.
install -d -o postgres -g postgres -m 0700 /srv/secure/tmp/postgresql
printf '[Service]\nEnvironment=TMPDIR=/srv/secure/tmp/postgresql\n' > /etc/systemd/system/postgresql@.service.d/tmp.conf

# Debian/Ubuntu cluster generators can enable PostgreSQL independently of the
# umbrella service. Start clusters explicitly from our manual target instead.
for pgconf in /etc/postgresql/*/main; do
    pgversion=${pgconf#/etc/postgresql/}
    pgversion=${pgversion%/main}
    rsync -av postgres/ "$pgconf/"
    printf 'manual\n' > "$pgconf/start.conf"
    systemctl add-wants odoo-app.target "postgresql@$pgversion-main.service"
    mkdir -p /etc/systemd/system/docker.service.d
    printf '[Unit]\nRequires=postgresql@%s-main.service\nAfter=postgresql@%s-main.service\n' "$pgversion" "$pgversion" > /etc/systemd/system/docker.service.d/postgresql.conf
done
chown postgres:adm /var/log/postgresql
chmod 0750 /var/log/postgresql
chown www-data:adm /var/log/nginx
chmod 0755 /var/log/nginx
chown www-data:adm /var/lib/nginx
chmod 0755 /var/lib/nginx

# Copy shared routing maps only on first install. A second release must never
# overwrite hostnames that the running agents have already registered.
rsync -av --ignore-existing nginx/conf.d/ /etc/nginx/conf.d/
install -m 0644 nginx/nginx.conf /etc/nginx/nginx.conf
install -d -m 0700 /root/backups
[[ -f /root/.config/rclone/rclone.conf ]] || install -m 0600 rclone.conf /root/.config/rclone/rclone.conf
[[ -f /srv/secure/secrets/cloudflare.ini ]] || install -m 0600 cloudflare.ini /srv/secure/secrets/cloudflare.ini
cp sshd/harden.conf /etc/ssh/sshd_config.d/harden.conf
systemctl reload ssh

mkdir -p /etc/apt/apt.conf.d/
cp apt/apt.conf.d/* /etc/apt/apt.conf.d/
systemctl restart unattended-upgrades

systemctl unmask --runtime "${services[@]}"
systemctl disable "${services[@]}"
systemctl daemon-reload
bash ./install-release.sh
