#!/bin/bash

set -e

apt update
apt install postgresql nginx ca-certificates curl gnupg vim tmux patchutils fuse3 python3-pip python3-venv

systemctl enable nginx --now
systemctl enable postgresql --now

# https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

curl https://rclone.org/install.sh | sudo bash

python3 -m venv /root/agent-venv
/root/agent-venv/bin/python -m pip install -r requirements.txt

cp systemd/system/odoo-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable odoo-agent.service --now

exit 1
