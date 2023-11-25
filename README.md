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
* `git clone -b 17.0 git@github.com:elmeriniemela/odoo-agent.git /opt/odoo-agent`
* `apt update`
* `apt install postgresql nginx ca-certificates curl gnupg`
* `su - postgres -c "createuser -s root"`
* `systemctl enable nginx --now`
* `systemctl enable postgresql --now`
* `install -m 0755 -d /etc/apt/keyrings`
* `curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg`
* `chmod a+r /etc/apt/keyrings/docker.gpg`
* `echo "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null`
* `apt update`
* `apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`
* `cd docker`
* `docker build -t odoo:17.0 .`
* ``

#### DB setup:
* `CREATE DATABASE kni;`
* `CREATE USER kni WITH ENCRYPTED PASSWORD 'kni';`
* `ALTER DATABASE kni OWNER TO kni;`
* docker run --name kni -t odoo:17.0 \
    -v /opt/odoo-agent/src:/mnt:ro \
    -v /etc/odoo/kni:/etc/odoo:ro \
    -v kni:/var/lib/odoo \
    -v /var/run/postgresql/:/var/run/postgresql/ \
    -p 127.0.0.1:8017:8069 \
    -p [::1]:8017:8069 \
    -p 127.0.0.1:9017:8072 \
    -p [::1]:9017:8072


#### Random notes
* Docker logs
* Docker volumes: `ls /var/lib/docker/volumes`
* Delete everything: `docker system prune -a --volumes`