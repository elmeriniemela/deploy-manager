#!/bin/bash

set -euxo pipefail
cd /opt/19

# Ubuntu 26.04 host configuration. Create and open the LUKS volume and add its
# UUID to /etc/crypttab first by following README.md. This script is rerunnable.
ensure_line() {
    grep -qxF "$1" "$2" || printf '%s\n' "$1" >> "$2"
}

systemctl mask swap.target

ensure_line '/dev/mapper/appdata /srv/secure ext4 noauto 0 2' /etc/fstab
ensure_line '/srv/secure/postgresql /var/lib/postgresql none noauto,bind 0 0' /etc/fstab
ensure_line '/srv/secure/docker /var/lib/docker none noauto,bind 0 0' /etc/fstab
ensure_line '/srv/secure/containerd /var/lib/containerd none noauto,bind 0 0' /etc/fstab
ensure_line '/srv/secure/odoo-config /etc/odoo none noauto,bind 0 0' /etc/fstab
ensure_line '/srv/secure/logs/nginx /var/log/nginx none noauto,bind 0 0' /etc/fstab
ensure_line '/srv/secure/logs/postgresql /var/log/postgresql none noauto,bind 0 0' /etc/fstab
ensure_line '/srv/secure/nginx-temp /var/lib/nginx none noauto,bind 0 0' /etc/fstab

install -d /srv/secure
systemctl daemon-reload
systemctl start srv-secure.mount
install -d /srv/secure/postgresql /srv/secure/docker /srv/secure/containerd /srv/secure/odoo-config
install -d /srv/secure/logs/nginx /srv/secure/logs/postgresql /srv/secure/nginx-temp
install -d -m 0700 /srv/secure/rclone-config /srv/secure/rclone-cache /srv/secure/backups /srv/secure/secrets
install -d -m 0711 /srv/secure/tmp
install -d /var/lib/postgresql /var/lib/docker /var/lib/containerd /etc/odoo
install -d /var/log/nginx /var/log/postgresql /var/lib/nginx
systemctl start var-lib-postgresql.mount var-lib-docker.mount var-lib-containerd.mount
systemctl start etc-odoo.mount var-log-nginx.mount var-log-postgresql.mount var-lib-nginx.mount

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
apt install -y postgresql nginx ca-certificates curl gnupg git patchutils fuse3 cron unattended-upgrades apache2-utils rsync rclone
apt install -y python3 python3-psycopg2 python3-requests python3-jinja2 certbot python3-certbot-dns-cloudflare

# Docker: https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
install -m 0644 apt/docker.sources /etc/apt/sources.list.d/docker.sources
apt update
apt install -y docker-ce docker-ce-cli containerd.io

install -m 0644 systemd/system/odoo-app.target systemd/system/rclone-mount.service systemd/system/deploy-manager19.service /etc/systemd/system/
install -m 0644 systemd/system/docker.service.d/postgresql-dependency.conf /etc/systemd/system/docker.service.d/postgresql-dependency.conf
install -m 0644 systemd/system/postgresql@.service.d/tmp.conf /etc/systemd/system/postgresql@.service.d/tmp.conf
install -D -m 0644 logrotate/deploy-manager19 /etc/logrotate.d/deploy-manager19
install -D -m 0644 cron/deploy-manager19 /etc/cron.d/deploy-manager19

install -d -o postgres -g postgres -m 0700 /srv/secure/tmp/postgresql
rsync -av postgres/ /etc/postgresql/18/main/
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
ln -sfn /etc/nginx/sites-available/00_agent19.conf /etc/nginx/sites-enabled/00_agent19.conf
ln -sfn /etc/nginx/sites-available/odoo.conf /etc/nginx/sites-enabled/odoo.conf

# Permit only the rclone filesystem mounted at the encrypted backup path.
grep -qF '<local/fusermount3>' /etc/apparmor.d/fusermount3
install -D -m 0644 apparmor/local/fusermount3 /etc/apparmor.d/local/fusermount3
apparmor_parser -r /etc/apparmor.d/fusermount3

cp --update=none rclone.conf /srv/secure/rclone-config/rclone.conf
chmod 0600 /srv/secure/rclone-config/rclone.conf
cp --update=none cloudflare.ini /srv/secure/secrets/cloudflare.ini
chmod 0600 /srv/secure/secrets/cloudflare.ini
install -m 0644 sshd/harden.conf /etc/ssh/sshd_config.d/harden.conf
systemctl reload ssh

install -d /etc/apt/apt.conf.d
install -m 0644 apt/apt.conf.d/20auto-upgrades apt/apt.conf.d/60deploy-manager /etc/apt/apt.conf.d/

if [ ! -d src/tabularium/.git ]; then
    git clone -b 19.0 https://github.com/elmeriniemela/tabularium.git src/tabularium
fi
if [ ! -d src/odoo/.git ]; then
    git clone -b 19.0 --depth=1 --single-branch https://github.com/odoo/odoo.git src/odoo
fi
if [ ! -d src/OpenUpgrade/.git ]; then
    git clone -b 19.0 --depth=1 --single-branch https://github.com/OCA/OpenUpgrade.git src/OpenUpgrade
fi

systemctl unmask --runtime postgresql.service postgresql@.service docker.service docker.socket containerd.service nginx.service rclone-mount.service
systemctl daemon-reload
/usr/bin/python3 -c 'import jinja2, psycopg2, requests'
systemctl disable postgresql.service postgresql@18-main.service docker.service docker.socket containerd.service nginx.service rclone-mount.service
systemctl enable deploy-manager19.service

# PostgreSQL must have the peer-authenticated administrative role before the
# deployment manager can receive requests.
systemctl start postgresql@18-main.service
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'root'" | grep -qx 1; then
    runuser -u postgres -- createuser --superuser root
fi

# Monitoring is part of the required host setup. Odoo containers use the Loki
# log driver, while Promtail ships host logs and node-exporter exposes metrics.
systemctl start docker.service
if ! docker plugin inspect loki >/dev/null 2>&1; then
    docker plugin install grafana/loki-docker-driver --alias loki --grant-all-permissions
fi
if [ "$(docker plugin inspect --format '{{.Enabled}}' loki)" != true ]; then
    docker plugin enable loki
fi
if ! docker container inspect promtail >/dev/null 2>&1; then
    docker run -d \
        --name promtail \
        --restart unless-stopped \
        -v /opt/19/promtail:/etc/promtail:ro \
        -v /var/log:/var/log:ro \
        grafana/promtail:latest \
        -config.file=/etc/promtail/config.yml
else
    docker update --restart unless-stopped promtail
    docker restart promtail
fi
if ! docker container inspect node-exporter >/dev/null 2>&1; then
    docker run -d \
        --name node-exporter \
        --net=host \
        --pid=host \
        --restart unless-stopped \
        -v /:/host:ro,rslave \
        quay.io/prometheus/node-exporter:latest \
        --path.rootfs=/host
else
    docker update --restart unless-stopped node-exporter
    if [ "$(docker container inspect --format '{{.State.Running}}' node-exporter)" != true ]; then
        docker start node-exporter
    fi
fi

test "$(docker plugin inspect --format '{{.Enabled}}' loki)" = true
test "$(docker container inspect --format '{{.State.Running}}' promtail)" = true
test "$(docker container inspect --format '{{.State.Running}}' node-exporter)" = true
systemctl restart unattended-upgrades
