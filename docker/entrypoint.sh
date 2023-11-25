#!/bin/bash

set -e

pip3 install -r /mnt/extra-addons/requirements.txt

exec odoo

exit 1
