#!/bin/bash

set -euxo pipefail
cd /opt/19

# One-time Ubuntu 24.04 host install. Create and open the LUKS volume and add its
# UUID to /etc/crypttab first by following README.md.
systemctl mask swap.target
echo '/dev/mapper/appdata /srv/secure ext4 noauto 0 2' >> /etc/fstab
echo '/srv/secure/postgresql /var/lib/postgresql none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/docker /var/lib/docker none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/containerd /var/lib/containerd none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/odoo-config /etc/odoo none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/logs/nginx /var/log/nginx none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/logs/postgresql /var/log/postgresql none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/nginx-temp /var/lib/nginx none noauto,bind 0 0' >> /etc/fstab
systemctl daemon-reload

install -d /srv/secure
mount /srv/secure
install -d /srv/secure/postgresql /srv/secure/docker /srv/secure/containerd /srv/secure/odoo-config
install -d /srv/secure/logs/nginx /srv/secure/logs/postgresql /srv/secure/nginx-temp
install -d -m 0700 /srv/secure/rclone-config /srv/secure/rclone-cache /srv/secure/backups /srv/secure/secrets
install -d -m 0711 /srv/secure/tmp
install -d /var/lib/postgresql /var/lib/docker /var/lib/containerd /etc/odoo
install -d /var/log/nginx /var/log/postgresql /var/lib/nginx
mount /var/lib/postgresql
mount /var/lib/docker
mount /var/lib/containerd
mount /etc/odoo
mount /var/log/nginx
mount /var/log/postgresql
mount /var/lib/nginx

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

install -d -m 0700 /srv/secure/backups
install -m 0600 rclone.conf /srv/secure/rclone-config/rclone.conf
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
