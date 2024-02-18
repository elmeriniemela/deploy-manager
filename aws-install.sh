#!/bin/bash
set -e
mkdir -p /root/backups
yum update
yum install postgresql15 postgresql15-server
/usr/bin/postgresql-setup --initdb
cp postgres/pg_hba.conf /var/lib/pgsql/data/pg_hba.conf
mkdir /var/lib/pgsql/data/conf.d -p
cp postgres/pgtune.conf /var/lib/pgsql/data/conf.d/
systemctl enable postgresql --now

yum install nginx tmux
yum install certbot python3-certbot-nginx
yum install docker
yum install python3-psycopg2
yum install patchutils # filterdiff
yum install fuse3 # required for rclone mount
curl https://rclone.org/install.sh | sudo bash

cp -r nginx/* /etc/nginx/

systemctl enable nginx --now

cp systemd/system/odoo-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable odoo-agent.service --now

exit 0
