#!/bin/bash

set -euxo pipefail

# Run once on a fresh host. Re-running this file duplicates /etc/fstab entries.
echo '/dev/mapper/appdata /srv/secure ext4 noauto 0 2' >> /etc/fstab
echo '/srv/secure/postgresql /var/lib/postgresql none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/docker /var/lib/docker none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/containerd /var/lib/containerd none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/odoo-config /etc/odoo none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/logs/nginx /var/log/nginx none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/logs/postgresql /var/log/postgresql none noauto,bind 0 0' >> /etc/fstab
echo '/srv/secure/nginx-temp /var/lib/nginx none noauto,bind 0 0' >> /etc/fstab
systemctl daemon-reload
