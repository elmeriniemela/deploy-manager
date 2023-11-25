#!/bin/bash

set -e

# if [ -e "/mnt/extra-addons/requirements.txt" ]; then
#     pip3 install -r /mnt/extra-addons/requirements.txt
# fi

if [ -e "/usr/bin/odoo" ]; then
    exec odoo
else
    echo "Mount missing, sleep for 6000 seconds.."
    /usr/bin/sleep 6000
fi

exit 1
