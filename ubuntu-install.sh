#!/bin/bash

set -e

apt update
apt install postgresql nginx ca-certificates curl gnupg vim tmux patchutils fuse3 python3-pip python3-venv unattended-upgrades

systemctl enable nginx --now
systemctl enable postgresql --now

# https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt update
apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

curl https://rclone.org/install.sh | sudo bash

python3 -m venv /root/agent-venv
/root/agent-venv/bin/python -m pip install -r requirements.txt

cp systemd/system/deploy-manager.service /etc/systemd/system/
cp systemd/system/rclone-mount.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable deploy-manager.service --now
systemctl enable rclone-mount.service --now

rsync -avz postgres/ /etc/postgresql/*/main
rsync -avz nginx/ /etc/nginx

mkdir -p /root/backups
mkdir -p /root/.config/rclone/
cp rclone.conf /root/.config/rclone/rclone.conf
chmod 0600 /root/.config/rclone/rclone.conf
cp cloudflare.ini /root/cloudflare.ini
chmod 0600 /root/cloudflare.ini
cp sshd/harden.conf /etc/ssh/sshd_config.d/harden.conf
systemctl reload ssh

mkdir -p /etc/apt/apt.conf.d/
cp apt/apt.conf.d/* /etc/apt/apt.conf.d/
systemctl restart unattended-upgrades

exit 0
