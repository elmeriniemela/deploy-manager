import logging
from psycopg2 import sql
import secrets
import agentlib
import requests
import os
import datetime
_logger = logging.getLogger(__name__)


@agentlib.register
def status():
    status = []
    docker_ps_a = requests.get(
        url='http://127.0.0.1:2375/containers/json',
        params={'all': True},
    ).json()
    for container in docker_ps_a:
        uid = container['Names'][0].lstrip('/')
        status.append({
            'uid': uid,
            'docker': container,
            'backups': agentlib.list_backups(uid),
        })

    return status


@agentlib.register
def backup(uid):
    agentlib.validate(uid=uid)
    os.makedirs(f'/root/storagebox/{uid}', mode=0o700, exist_ok=True)
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S')
    commands = [
        ['rclone', 'sync', f'/var/lib/docker/volumes/{uid}/_data/filestore/{uid}', f'storagebox:{uid}/filestore'],
        ['rclone', 'mount', 'storagebox:', '/root/storagebox', '--daemon', '--vfs-cache-mode', 'full'],
        ['pg_dump', '-Fc', '-f', f'/root/storagebox/{uid}/{now}.pgc', uid],
    ]
    for cmd in commands:
        agentlib.execute(cmd)

    return agentlib.list_backups(uid)

@agentlib.register
def restore(src_uid, dst_uid, backup_file):
    agentlib.validate(uid=src_uid)
    agentlib.validate(uid=dst_uid)
    queries = [
        (sql.SQL("DROP DATABASE {uid}").format(uid=sql.Identifier(dst_uid)),),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(dst_uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(dst_uid)),),
    ]
    agentlib.psql(queries)
    commands = [
        ['rclone', 'copy', f'storagebox:{src_uid}/filestore', f'/var/lib/docker/volumes/{dst_uid}/_data/filestore/{dst_uid}'],
        ['chown', '1000:1000', '-R', f'/var/lib/docker/volumes/{dst_uid}/_data/filestore/{dst_uid}'], # TODO, better way to assign ownership to container user 'odoo'?
        ['rclone', 'mount', 'storagebox:', '/root/storagebox', '--daemon', '--vfs-cache-mode', 'full'],
        ['pg_restore', '-Fc', '--no-owner', f'--role={dst_uid}', '-d', dst_uid, f'/root/storagebox/{src_uid}/{backup_file}'],
        ['docker', 'restart', dst_uid],
    ]
    for cmd in commands:
        agentlib.execute(cmd)



@agentlib.register
def restart(uid):
    agentlib.validate(uid=uid)
    agentlib.execute(['docker', 'restart', uid])

@agentlib.register
def start(uid):
    agentlib.validate(uid=uid)
    agentlib.execute(['docker', 'start', uid])

@agentlib.register
def stop(uid):
    agentlib.validate(uid=uid)
    agentlib.execute(['docker', 'stop', uid])

@agentlib.register
def remove(uid, hostname):
    agentlib.validate(uid=uid, hostname=hostname)
    agentlib.execute(['docker', 'rm', uid])

    for fname in ['gevent-ports.conf', 'http-ports.conf']:
        match, target, mapping = agentlib.load_nginx_map(fname)
        mapping.pop(hostname)
        agentlib.store_nginx_map(fname, match, target, mapping)
    agentlib.execute(['systemctl', 'reload', 'nginx'])

    queries = [
        (sql.SQL("DROP DATABASE {uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("DROP USER {uid}").format(uid=sql.Identifier(uid)),),
    ]
    agentlib.psql(queries)

    agentlib.execute(['docker', 'volume', 'rm', uid])

@agentlib.register
def rebuild(uid, http_port, gevent_port):
    agentlib.validate(uid=uid, http_port=http_port, gevent_port=gevent_port)
    commands = [
        ['docker', 'rm', uid],
        [
            'docker', 'run',
            '-v', f'/opt/odoo-agent/src:/mnt:ro',
            '-v', f'/var/run/postgresql/:/var/run/postgresql/',
            '-v', f'/etc/odoo/{uid}:/etc/odoo:ro',
            '-v', f'{uid}:/var/lib/odoo',
            '-p', f'127.0.0.1:{http_port}:8069',
            '-p', f'[::1]:{http_port}:8069',
            '-p', f'127.0.0.1:{gevent_port}:8072',
            '-p', f'[::1]:{gevent_port}:8072',
            '--restart', 'unless-stopped',
            '--name', uid,
            '-t', '-d', 'odoo-src:16.0',
        ],
        ['docker', 'restart', uid],
    ]
    for cmd in commands:
        agentlib.execute(cmd)


@agentlib.register
def config(uid, conf):
    agentlib.validate(uid=uid)
    agentlib.save_odoo_config(uid, conf)


@agentlib.register
def reset(uid):
    agentlib.validate(uid=uid)
    queries = [
        (sql.SQL("DROP DATABASE {uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(uid)),),
    ]
    agentlib.psql(queries)
    commands = [
        ['docker', 'start', uid],
        [
            'docker', 'exec', '-it', uid, 'odoo',
            '--init=base',
            '--http-port=9999',
            '--stop-after-init',
        ],
        ['docker', 'restart', uid],
    ]

    for cmd in commands:
        agentlib.execute(cmd)


@agentlib.register
def create(uid, hostname, http_port, gevent_port):
    agentlib.validate(uid=uid, hostname=hostname, http_port=http_port, gevent_port=gevent_port)
    pw = secrets.token_hex(32)

    config = agentlib.render_odoo_config(uid, pw)

    for port, fname in [(gevent_port, 'gevent-ports.conf'), (http_port, 'http-ports.conf')]:
        match, target, mapping = agentlib.load_nginx_map(fname)
        mapping[hostname] = f'127.0.0.1:{port}'
        agentlib.store_nginx_map(fname, match, target, mapping)

    agentlib.execute(['systemctl', 'reload', 'nginx'])


    queries = [
        (sql.SQL("CREATE ROLE {uid} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT LOGIN ENCRYPTED PASSWORD %s").format(uid=sql.Identifier(uid)), (pw,)),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(uid)),),
    ]
    agentlib.psql(queries)

    commands = [
        [
            'docker', 'run',
            '-v', f'/opt/odoo-agent/src:/mnt:ro',
            '-v', f'/var/run/postgresql/:/var/run/postgresql/',
            '-v', f'/etc/odoo/{uid}:/etc/odoo:ro',
            '-v', f'{uid}:/var/lib/odoo',
            '-p', f'127.0.0.1:{http_port}:8069',
            '-p', f'[::1]:{http_port}:8069',
            '-p', f'127.0.0.1:{gevent_port}:8072',
            '-p', f'[::1]:{gevent_port}:8072',
            '--restart', 'unless-stopped',
            '--name', uid,
            '-t', '-d', 'odoo-src:16.0',
        ],
        [
            'docker', 'exec', '-it', uid, 'odoo',
            '--init=base',
            '--http-port=9999',
            '--stop-after-init',
        ],
        ['docker', 'restart', uid],
    ]

    for cmd in commands:
        agentlib.execute(cmd)

    return config
