#!/bin/bash

set -e

if [ -e "/mnt/extra-addons/requirements.txt" ]; then
    pip3 install -r /mnt/extra-addons/requirements.txt
fi

exec odoo

exit 1
