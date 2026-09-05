#!/bin/bash

set -e

cd /opt/odoo19
git pull
git submodule update
systemctl restart deploy-manager19.service

exit 0
