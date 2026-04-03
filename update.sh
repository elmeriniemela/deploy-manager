#!/bin/bash

set -e

git pull
git submodule update
systemctl restart deploy-manager.service

exit 1
