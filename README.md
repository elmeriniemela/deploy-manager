# Deployment manager for Odoo images

## Abstract
This project automates self-hosted Odoo deployments on a Linux host. It provides a custom Odoo Docker image, host bootstrap scripts (Docker/PostgreSQL/nginx/systemd), and an XML-RPC agent for instance lifecycle tasks such as create/reset/restart/upgrade, hostname-to-port routing updates, and SSL certificate management. It also handles database and filestore backup/restore workflows using `pg_dump`/`pg_restore` and `rclone`, with scheduled retention cleanup.

## Installation

#### Architecture:
* Custom docker image with odoo source install + custom pip packages.
    * https://github.com/odoo/odoo/blob/18.0/debian/control
    * https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
* CI pipeline with Github actions:
    * Actions defined here at `src/odoo_addons/.github/workflows/test.yml`
    * Depends on the docker container image available at https://github.com/elmeriniemela/odoo-ci
    * Based on https://github.com/oca/oca-ci/pkgs/container/oca-ci%2Fpy3.10-odoo18.0
    * Documentation: https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions

* XML-RPC agent for running remote commands
* Monitoring prometheus
    * [grafana loki: DONE!](https://github.com/elmeriniemela/grafana-loki)
    * Import dashboards: https://grafana.com/grafana/dashboards/1860-node-exporter-full/
    *

#### Creating a personal github access token (READ only):
* https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token
* Go to Settings / Developer / New personal access token (classic) / Add 'Odoo 18.0 Hetzner Server key' + add repo and write:packages
* `docker login ghcr.io -u elmeriniemela`

#### Prerequisite
* `scp .gitconfig agent18.eniemela.fi:`
* `cd .ssh && ssh-keygen -f id_ecdsa -t ecdsa -b 521`
* `cat id_ecdsa.pub`
* go to github / settings / SSH keys / Add 'Odoo 18.0 Hetzner Server key'
* `mkdir -p /root/.config/rclone/`
* `cp rclone.conf /root/.config/rclone/rclone.conf`
* `vim /root/.config/rclone/rclone.conf`
* `cp cloudflare.ini /root/cloudflare.ini`
* `vim /root/cloudflare.ini`

#### Installation
* `git clone -b 18.0 --recurse-submodules --shallow-submodules https://github.com/elmeriniemela/deploy-manager.git /opt/odoo-agent`
* `cd /opt/odoo-agent`
* `./ubuntu-install.sh`
* `systemctl edit docker.service`
```
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://127.0.0.1:2375 --containerd=/run/containerd/containerd.sock
```
* `systemctl daemon-reload`
* `systemctl restart docker.service`
* `systemctl restart postgresql`
* `su - postgres -c "createuser -s root"`
* `source /root/agent-venv/bin/activate`
* `python agentd/api.py ssl_wildcard`
* `systemctl restart nginx`

#### Promtail setup
* Attach new server to the same private network as "monitoring" in hetzner cloud.
* docker run \
    -v ./promtail:/etc/promtail \
    -v /var/log:/var/log \
    --restart unless-stopped \
    --name promtail -d \
    grafana/promtail:latest -config.file=/etc/promtail/config.yml

* https://grafana.com/docs/loki/latest/send-data/docker-driver/
* https://grafana.com/docs/loki/latest/send-data/docker-driver/configuration/
* `docker plugin install grafana/loki-docker-driver --alias loki --grant-all-permissions`

#### Prometheus note exporter monitoring:
* docker run -d \
    --net="host" \
    --pid="host" \
    -v "/:/host:ro,rslave" \
    --restart unless-stopped \
    quay.io/prometheus/node-exporter:latest \
    --path.rootfs=/host

#### Building the image
* `docker build -t ghcr.io/elmeriniemela/odoo-src:18.0 /opt/odoo-agent`
* https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#building-container-images
* `sudo docker push ghcr.io/elmeriniemela/odoo-src:18.0`


#### Backup setup:
* `crontab -e`
* `30 00 * * * cd /opt/odoo-agent && /root/agent-venv/bin/python ./agentd/backup.py`


## Other notes

#### Pulling the image
* `docker pull ghcr.io/elmeriniemela/odoo-src:18.0`

#### DB isolation:
* https://wiki.postgresql.org/wiki/Shared_Database_Hosting
* https://wiki.postgresql.org/images/d/d1/Managing_rights_in_postgresql.pdf

### Local setup
* sudo docker run \
    -v /home/elmeri/Odoo/src/16:/mnt:ro \
    -v /var/run/postgresql:/var/run/postgresql \
    -v /home/elmeri/Odoo/src/16/own-docker.conf:/etc/odoo/odoo.conf:ro \
    -v /home/elmeri/.local/share/Odoo:/var/lib/odoo \
    -p 127.0.0.1:8016:8069 \
    -p 127.0.0.1:9016:8072 \
    --name eniemela_16 -ti ghcr.io/elmeriniemela/odoo-src:18.0
* sudo docker restart eniemela_16 && sudo docker attach eniemela_16
* sudo docker exec -it -u root eniemela_16 bash
* sudo docker restart eniemela_16 && sudo docker exec -it -u root eniemela_16 odoo -u investment_portfolio --http-port=9999 --stop-after-init && sudo docker restart eniemela_16 && sudo docker attach eniemela_16

#### Random notes
* Docker logs
* Docker volumes: `ls /var/lib/docker/volumes`
* Delete everything: `docker system prune -a --volumes`
* Remote access: https://docs.docker.com/config/daemon/remote-access/
* Docker API: https://docs.docker.com/engine/api/latest/
* Login as root: `docker exec -it -u root <uid> bash`
