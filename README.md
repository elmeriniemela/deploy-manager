### Odoo Docker

#### TODO:
* Custom docker image with odoo source install + custom pip packages.
    * https://github.com/odoo/odoo/blob/17.0/debian/control
    * https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
* CI pipeline with Github actions / Jenkinks
    * https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions
    * https://github.com/OCA/oca-ci
    * https://github.com/OCA/oca-github-bot
    * https://github.com/OCA/interface-github
* XML-RPC agent for running remote commands
* Monitoring system with logs (Zabbix or something else?)

#### Installation
* `git clone -b 17.0 git@github.com:elmeriniemela/odoo-agent.git /opt/17.0/odoo-agent`
* `cd /opt/17.0/odoo-agent`
* `git submodule update --init`
* `./install.sh`


#### Building the image
* `cd docker`
* `docker build -t odoo-src:17.0 /opt/17.0/odoo-agent/docker`

#### DB setup:
* `su - postgres -c "createuser -s root"`
* `psql postgres`
* `CREATE DATABASE kni;`
* `CREATE USER kni WITH ENCRYPTED PASSWORD 'kni';`
* `ALTER DATABASE kni OWNER TO kni;`
* docker run \
    -v /opt/17.0/odoo-agent/src:/mnt:ro \
    -v /etc/odoo/kni:/etc/odoo:ro \
    -v kni:/var/lib/odoo \
    -v /var/run/postgresql/:/var/run/postgresql/ \
    -p 127.0.0.1:49152:8069 \
    -p [::1]:49152:8069 \
    -p 127.0.0.1:49153:8072 \
    -p [::1]:49153:8072 \
    --name kni -t odoo-src:17.0

#### Random notes
* Docker logs
* Docker volumes: `ls /var/lib/docker/volumes`
* Delete everything: `docker system prune -a --volumes`