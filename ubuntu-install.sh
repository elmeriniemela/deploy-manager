#!/bin/bash

set -euxo pipefail
cd /opt/odoo19

# One-time Ubuntu 24.04 host install. Prepare and mount the encrypted storage
# first by following README.md.
systemctl mask --runtime postgresql.service postgresql@.service docker.service docker.socket containerd.service nginx.service rclone-mount.service

install -d /etc/systemd/system/postgresql@.service.d
install -d /etc/systemd/system/docker.service.d
install -d /etc/systemd/system/docker.socket.d
install -d /etc/systemd/system/containerd.service.d
install -d /etc/systemd/system/nginx.service.d
install -d /etc/systemd/system/rclone-mount.service.d
install -d /etc/systemd/system/deploy-manager19.service.d
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/postgresql@.service.d/appdata-mounts.conf
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/docker.service.d/appdata-mounts.conf
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/docker.socket.d/appdata-mounts.conf
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/containerd.service.d/appdata-mounts.conf
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/nginx.service.d/appdata-mounts.conf
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/rclone-mount.service.d/appdata-mounts.conf
install -m 0644 systemd/system/appdata-mounts.conf /etc/systemd/system/deploy-manager19.service.d/appdata-mounts.conf
systemctl daemon-reload

apt update
apt install -y postgresql nginx ca-certificates curl gnupg vim tmux patchutils fuse3 python3-pip python3-venv unattended-upgrades apache2-utils rsync rclone

# Docker: https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
install -m 0644 apt/docker.sources /etc/apt/sources.list.d/docker.sources
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

install -m 0644 systemd/system/odoo-app.target systemd/system/rclone-mount.service systemd/system/deploy-manager19.service /etc/systemd/system/
install -D -m 0644 systemd/system/docker.service.d/override.conf /etc/systemd/system/docker.service.d/override.conf
install -m 0644 systemd/system/docker.service.d/postgresql.conf /etc/systemd/system/docker.service.d/postgresql.conf
install -m 0644 systemd/system/postgresql@.service.d/tmp.conf /etc/systemd/system/postgresql@.service.d/tmp.conf
install -D -m 0644 logrotate/deploy-manager19 /etc/logrotate.d/deploy-manager19

install -d -o postgres -g postgres -m 0700 /srv/secure/tmp/postgresql
rsync -av postgres/ /etc/postgresql/16/main/
chown postgres:adm /var/log/postgresql
chmod 0750 /var/log/postgresql

chown www-data:adm /var/log/nginx
chmod 0755 /var/log/nginx
chown www-data:adm /var/lib/nginx
chmod 0755 /var/lib/nginx
rsync -av nginx/conf.d/ /etc/nginx/conf.d/
install -m 0644 nginx/nginx.conf /etc/nginx/nginx.conf
install -d /etc/nginx/sites-available
install -m 0644 nginx/sites-enabled/00_agent19.conf /etc/nginx/sites-available/00_agent19.conf
install -m 0644 nginx/sites-enabled/odoo.conf /etc/nginx/sites-available/odoo.conf

install -d -m 0700 /root/backups
install -D -m 0600 rclone.conf /root/.config/rclone/rclone.conf
install -D -m 0600 cloudflare.ini /srv/secure/secrets/cloudflare.ini
install -m 0644 sshd/harden.conf /etc/ssh/sshd_config.d/harden.conf
systemctl reload ssh

install -d /etc/apt/apt.conf.d
install -m 0644 apt/apt.conf.d/20auto-upgrades apt/apt.conf.d/50unattended-upgrades /etc/apt/apt.conf.d/

python3 -m venv /root/agent-venv19
/root/agent-venv19/bin/python -m pip install -r requirements.txt

systemctl unmask --runtime postgresql.service postgresql@.service docker.service docker.socket containerd.service nginx.service rclone-mount.service
systemctl disable postgresql.service postgresql@16-main.service docker.service docker.socket containerd.service nginx.service rclone-mount.service deploy-manager19.service
systemctl enable deploy-manager19.service
systemctl daemon-reload
systemctl restart unattended-upgrades
