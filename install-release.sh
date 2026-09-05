#!/bin/bash

set -euo pipefail
cd "$(dirname "$0")"
[[ $EUID == 0 && $(pwd -P) == /opt/odoo19 ]] || { echo 'Run as root from /opt/odoo19.' >&2; exit 1; }
/usr/local/sbin/unlock-appdata --check

python3 -m venv /root/agent-venv19
/root/agent-venv19/bin/python -m pip install -r requirements.txt
install -m 0644 systemd/system/deploy-manager19.service /etc/systemd/system/
install -D -m 0644 logrotate/deploy-manager19 /etc/logrotate.d/deploy-manager19
install -d /etc/systemd/system/deploy-manager19.service.d
# Reuse the host guard; future release branches install only their own unit.
install -m 0644 /etc/systemd/system/docker.service.d/appdata.conf /etc/systemd/system/deploy-manager19.service.d/appdata.conf
systemctl daemon-reload
systemctl enable deploy-manager19.service

# First bootstrap installs the venv needed to obtain the wildcard certificate.
if [[ ! -f /etc/letsencrypt/live/eniemela.fi/fullchain.pem || ! -f /etc/letsencrypt/live/eniemela.fi/privkey.pem || ! -f /etc/nginx/.htpasswd ]]; then
    echo 'Services have not been started. Configure /root/.config/rclone/rclone.conf and /srv/secure/secrets/cloudflare.ini.'
    echo 'Create nginx basic auth and the wildcard certificate (README.md), then rerun ./install-release.sh and sudo unlock-appdata.'
    exit 0
fi

# Share the agents' routing lock, including the validation and reload.
exec 9>/run/lock/odoo-nginx.lock
flock 9
staging=$(mktemp -d /etc/nginx/.odoo19.XXXXXX)
trap 'rm -r -- "$staging"' EXIT
mkdir "$staging/sites-enabled"
cp -aL /etc/nginx/sites-enabled/. "$staging/sites-enabled/"
install -m 0644 nginx/sites-enabled/00_agent19.conf "$staging/00_agent19.conf"
ln -sfn "$staging/00_agent19.conf" "$staging/sites-enabled/00_agent19.conf"
if [[ ! -e /etc/nginx/sites-enabled/odoo.conf ]]; then
    install -m 0644 nginx/sites-enabled/odoo.conf "$staging/odoo.conf"
    ln -sfn "$staging/odoo.conf" "$staging/sites-enabled/odoo.conf"
fi
sed "s@include /etc/nginx/sites-enabled/\*;@include $staging/sites-enabled/*;@" /etc/nginx/nginx.conf > "$staging/nginx.conf"
nginx -t -c "$staging/nginx.conf"
install -d /etc/nginx/sites-available
install -m 0644 "$staging/00_agent19.conf" /etc/nginx/sites-available/00_agent19.conf
ln -sfn /etc/nginx/sites-available/00_agent19.conf /etc/nginx/sites-enabled/00_agent19.conf
if [[ -f "$staging/odoo.conf" ]]; then
    install -m 0644 "$staging/odoo.conf" /etc/nginx/sites-available/odoo.conf
    ln -sfn /etc/nginx/sites-available/odoo.conf /etc/nginx/sites-enabled/odoo.conf
fi
if systemctl is-active --quiet nginx; then
    systemctl reload nginx
fi
echo 'Odoo 19 installed. Run sudo unlock-appdata to start the application services.'
