#!/bin/bash

set -e

git pull
git submodule update
systemctl restart odoo-agent.service

exit 1
