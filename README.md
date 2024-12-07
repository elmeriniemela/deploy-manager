### Odoo Docker

#### Architecture:
* Custom docker image with odoo source install + custom pip packages.
    * https://github.com/odoo/odoo/blob/17.0/debian/control
    * https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
* CI pipeline with Github actions:
    * Actions defined here at `src/odoo_addons/.github/workflows/test.yml`
    * Depends on the docker container image available at https://github.com/elmeriniemela/odoo-ci
    * Based on https://github.com/oca/oca-ci/pkgs/container/oca-ci%2Fpy3.10-odoo17.0
    * Documentation: https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions

* XML-RPC agent for running remote commands
* Monitoring prometheus
    * [grafana loki: DONE!](https://github.com/elmeriniemela/grafana-loki)
    * Import dashboards: https://grafana.com/grafana/dashboards/1860-node-exporter-full/
    *

#### Creating a personal github access token (READ only):
* https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token
* `docker login ghcr.io -u elmeriniemela`

#### Installation
* `git clone -b 17.0 --recurse-submodules --shallow-submodules https://github.com/elmeriniemela/odoo-agent.git /opt/odoo-agent`
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

#### Promtail setup
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


#### Pulling the image
* `docker pull ghcr.io/elmeriniemela/odoo-src:17.0`

#### DB setup:
* `su - postgres -c "createuser -s root"`
* https://wiki.postgresql.org/wiki/Shared_Database_Hosting
* https://wiki.postgresql.org/images/d/d1/Managing_rights_in_postgresql.pdf

#### Backup setup:
* `crontab -e`
* `30 00 * * * cd /opt/odoo-agent && ./agentd/backup.py`

#### New DB
* `createdb 618b4082e2d7`
* `psql postgres -c "CREATE USER 618b4082e2d7 WITH ENCRYPTED PASSWORD '618b4082e2d7'"`
* `psql postgres -c "ALTER DATABASE 618b4082e2d7 OWNER TO 618b4082e2d7"`
* `psql postgres -c "REVOKE CONNECT ON DATABASE 618b4082e2d7 FROM PUBLIC"`
* docker run \
    --log-driver=loki \
    --log-opt loki-url="https://loki.eniemela.fi:3110/loki/api/v1/push" \
    --log-opt loki-retries=5 \
    --log-opt loki-max-backoff=3s \
    --log-opt loki-timeout=5s \
    --log-opt loki-tls-insecure-skip-verify=true \
    --log-opt keep-file=true \
    --log-opt loki-batch-size=400 \
    -v /opt/odoo-agent/src:/mnt:ro \
    -v /var/run/postgresql/:/var/run/postgresql/ \
    -v /etc/odoo/618b4082e2d7:/etc/odoo:ro \
    -v 618b4082e2d7:/var/lib/odoo \
    -p 127.0.0.1:49152:8069 \
    -p [::1]:49152:8069 \
    -p 127.0.0.1:49153:8072 \
    -p [::1]:49153:8072 \
    --restart unless-stopped \
    --name 618b4082e2d7 -t -d ghcr.io/elmeriniemela/odoo-src:17.0


### Local setup
* sudo docker run \
    -v /home/elmeri/Work/16:/mnt:ro \
    -v /var/run/postgresql:/var/run/postgresql \
    -v /home/elmeri/Work/16/own-docker.conf:/etc/odoo/odoo.conf:ro \
    -v /home/elmeri/.local/share/Odoo:/var/lib/odoo \
    -p 127.0.0.1:8016:8069 \
    -p 127.0.0.1:9016:8072 \
    --name eniemela_16 -ti ghcr.io/elmeriniemela/odoo-src:17.0
* sudo docker restart eniemela_16 && sudo docker attach eniemela_16
* sudo docker exec -it -u root eniemela_16 bash
* sudo docker restart eniemela_16 && sudo docker exec -it -u root eniemela_16 odoo -u investment_portfolio --http-port=9999 --stop-after-init && sudo docker restart eniemela_16 && sudo docker attach eniemela_16

#### Building the image
* `docker build -t ghcr.io/elmeriniemela/odoo-src:17.0 /opt/odoo-agent`
* https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#building-container-images
* `sudo docker push ghcr.io/elmeriniemela/odoo-src:17.0`


#### Random notes
* Docker logs
* Docker volumes: `ls /var/lib/docker/volumes`
* Delete everything: `docker system prune -a --volumes`
* Remote access: https://docs.docker.com/config/daemon/remote-access/
* Docker API: https://docs.docker.com/engine/api/latest/
* Login as root: `docker exec -it -u root <uid> bash`
