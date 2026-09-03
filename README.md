# Deployment Manager for Odoo images

## Abstract
This project automates self-hosted Odoo deployments on a Linux host. It provides a custom Odoo Docker image, host bootstrap scripts (Docker/PostgreSQL/nginx/systemd), and an XML-RPC deployment manager for instance lifecycle tasks such as create/reset/restart/upgrade, hostname-to-port routing updates, and SSL certificate management. It also handles client-side encrypted database and filestore backup/restore workflows using `pg_dump`/`pg_restore` and `rclone` (with zero-knowledge `crypt` overlay), with scheduled retention cleanup.

The XML-RPC API can be used from an Odoo instance to do self upgrades of Odoo source code.

## System architecture
```mermaid
flowchart LR
    GHCR["GHCR odoo-src image"]
    User["Users and Browsers"]
    DNS["DNS and Hostname"]
    Nginx["NGINX routing and SSL"]
    Odoo["Odoo instances"]
    PG["PostgreSQL databases"]
    FS["Filestore volumes"]
    DeployManager["Deployment Manager"]
    Backup["Backups"]
    Rclone["rclone crypt to S3 storage"]
    Monitoring["Prometheus Grafana Loki"]
    Metrics["System metrics"]
    Logs["Logging (promtail)"]
    Modules["Odoo modules"]

    GHCR --> Docker
    Docker --> Odoo
    Modules -->|self upgrades| Odoo

    User --> DNS
    DNS --> Nginx
    Nginx -->|hostname -> port| Odoo
    Odoo --> PG
    Odoo --> FS
    Odoo -->|cloudflare api| DNS
    Odoo --> DeployManager

    Backup --> PG
    Backup --> FS

    DeployManager --> Docker
    DeployManager --> Nginx
    DeployManager --> Backup
    DeployManager -->|git| Modules
    Backup --> Rclone

    Docker --> Metrics
    Docker --> Logs

    Metrics --> Monitoring
    Logs --> Monitoring


    subgraph OdooHost["Linux VPS - Odoo"]
        Docker
        Odoo
        PG
        FS
        DeployManager
        Modules
        Nginx
        Backup
        Metrics
        Logs
    end


    subgraph MonHost["Linux VPS - Monitoring"]
      Monitoring
    end


```

* XML-RPC deployment-manager for running remote commands
    * Deploy and manage Odoo containers.
    * Git operations to allow an Odoo application that updates itself.
    * Manage custom NGINX/SSL configurations for the Odoo containers.
* Custom docker image with odoo source install + custom pip packages.
    * Packages: https://github.com/elmeriniemela/deploy-manager/pkgs/container/odoo-src
    * Github container registry: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
    * Python packages from here: https://github.com/odoo/odoo/blob/19.0/debian/control
        * Saved to apt.txt
        * Print missing: while read -r x; do grep -q "$x" Dockerfile || echo "$x"; done < ./apt.txt
* Odoo Modules:
    * Allow self updates of Odoo source code
    * Custom modules https://github.com/elmeriniemela/tabularium
* CI pipeline with Github actions:
    * Actions defined here at `src/tabularium/.github/workflows/test.yml`
    * Depends on the docker container image defined by this repository.
    * Documentation: https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions
* Monitoring
    * One monitoring server where multiple Odoo servers can send diagnostics and logging data.
    * prometheus+grafana+loki: https://github.com/elmeriniemela/grafana-loki
    * Import dashboards: https://grafana.com/grafana/dashboards/1860-node-exporter-full/


## Installation

#### Prerequisite
* `scp .gitconfig agent19.eniemela.fi:`
* `cd .ssh && ssh-keygen -f id_ecdsa -t ecdsa -b 521`
* `cat id_ecdsa.pub`
* go to github / settings / SSH keys / Add 'Odoo 19.0 Hetzner Server key'
    * https://github.com/settings/keys

#### Installation
* `git clone -b 19.0 --recurse-submodules --shallow-submodules https://github.com/elmeriniemela/deploy-manager.git /opt/deploy-manager`
* `cd /opt/deploy-manager`
* `./ubuntu-install.sh`
* `vim /root/.config/rclone/rclone.conf`
* `vim /root/cloudflare.ini`
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
* `python -m agentd.api ssl_wildcard`
* `systemctl restart nginx`

#### Promtail setup (TODO: deprecated, migrate to Alloy)
* Promtail is an agent which ships the contents of local logs to a private Grafana Loki instance: https://grafana.com/docs/loki/latest/send-data/promtail/
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

#### Prometheus node exporter monitoring:
* Prometheus exporter for hardware and OS metrics exposed by *NIX kernels, written in Go with pluggable metric collectors: https://github.com/prometheus/node_exporter
* docker run -d \
    --net="host" \
    --pid="host" \
    -v "/:/host:ro,rslave" \
    --restart unless-stopped \
    quay.io/prometheus/node-exporter:latest \
    --path.rootfs=/host

#### Creating a personal github access token (READ only):
* https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token
* Go to Settings / Developer / New personal access token (classic) / Add 'Odoo 19.0 Hetzner Server key' + add repo and write:packages
    * https://github.com/settings/tokens/new
* `docker login ghcr.io -u elmeriniemela`

#### Building the image
* `docker build -t ghcr.io/elmeriniemela/odoo-src:19.0 /opt/deploy-manager`
* https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#building-container-images
* `docker push ghcr.io/elmeriniemela/odoo-src:19.0`


#### Backup setup (Client-Side Encrypted S3 Backups):
* All database dumps and Odoo filestores are encrypted client-side via rclone's `crypt` backend before upload to AWS S3.
* Create a dedicated S3 bucket in AWS: `odoo-backups-crypt` (e.g. in `eu-north-1`).
* Generate an obscured password for rclone config:
  * `rclone obscure 'YourStrongSecretPassphrase'`
* In `/root/.config/rclone/rclone.conf`, add the `[backup-crypt]` section:
  ```ini
  [backup-crypt]
  type = crypt
  remote = awsbucket:odoo-backups-crypt
  filename_encryption = off
  directory_name_encryption = false
  password = <output from rclone obscure>
  ```
  *(Important: Back up this passphrase in an offline password manager. If lost, encrypted backups cannot be recovered!)*
* Mount the encrypted remote:
  * `systemctl restart rclone-mount.service`
* Scheduled cron:
  * `crontab -e`
  * `30 00 * * * cd /opt/deploy-manager && /root/agent-venv/bin/python -m agentd.backup`

##### Copying existing unencrypted backups to the new encrypted bucket:
If you have existing plaintext backups in `odoobackup1` and wish to copy them into the new encrypted bucket:
1. Copy into the encrypted remote (reads unencrypted files, encrypts locally, writes to `odoo-backups-crypt`):
   * `rclone copy awsbucket:odoobackup1 backup-crypt: --progress --transfers=16`
2. Verify the files through `/root/backups` or `rclone ls backup-crypt:`
3. Once verified, the old unencrypted bucket `odoobackup1` can be kept as a fallback or purged:
   * `rclone purge awsbucket:odoobackup1`

##### Decrypting a single file without rclone:
To manually decrypt a downloaded file without rclone (using only Python and `pip install pynacl`):
* `python3 docs/decrypt.py <encrypted_file> <decrypted_file> <password>`

#### Clone modules
* `cd /opt/deploy-manager/src`
* `git clone -b 19.0 git@github.com:elmeriniemela/tabularium.git`
* `git clone -b 19.0 --depth=1 --single-branch git@github.com:odoo/odoo.git`
* `git clone -b 19.0 --depth=1 --single-branch git@github.com:OCA/OpenUpgrade.git`


## Other notes

#### Pulling the image
* `docker pull ghcr.io/elmeriniemela/odoo-src:19.0`

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
    --name eniemela_16 -ti ghcr.io/elmeriniemela/odoo-src:19.0
* sudo docker restart eniemela_16 && sudo docker attach eniemela_16
* sudo docker exec -it -u root eniemela_16 bash
* sudo docker restart eniemela_16 && sudo docker exec -it -u root eniemela_16 odoo -u investment_portfolio --http-port=9999 --stop-after-init && sudo docker restart eniemela_16 && sudo docker attach eniemela_16

### Local mermaid-cli installation for AGENTS.md verification of the diagram:
* `sudo pacman -S nodejs npm`
* `sudo npm install -g @mermaid-js/mermaid-cli`
* `npx puppeteer browsers install chrome-headless-shell@131.0.6778.204`. NOTE: mmdc pins to a specific version, adapt if needed.
* See AGENTS.md for usage.

### Tests
* `python3 -m unittest discover -s agentd/tests -t .`
* `coverage run -m unittest discover -s agentd/tests -t . && coverage report -m`

#### Random notes
* Docker logs
* Docker volumes: `ls /var/lib/docker/volumes`
* Delete everything: `docker system prune -a --volumes`
* Remote access: https://docs.docker.com/config/daemon/remote-access/
* Docker API: https://docs.docker.com/engine/api/latest/
* Login as root: `docker exec -it -u root <uid> bash`
