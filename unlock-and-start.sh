#!/bin/bash

set -euxo pipefail

: "${HETZNER_VOL:?HETZNER_VOL is not set; start a root login shell first}"

cryptsetup open "$HETZNER_VOL" appdata
systemctl start srv-secure.mount
systemctl start var-lib-postgresql.mount
systemctl start var-lib-docker.mount
systemctl start var-lib-containerd.mount
systemctl start etc-odoo.mount
systemctl start var-log-nginx.mount
systemctl start var-log-postgresql.mount
systemctl start var-lib-nginx.mount
nginx -t
systemctl start odoo-app.target
