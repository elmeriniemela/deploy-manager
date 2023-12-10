import logging
from psycopg2 import sql
import secrets
import agentlib
import requests
_logger = logging.getLogger(__name__)


@agentlib.register
def status():
    return requests.get(
        url='http://127.0.0.1:2375/containers/json',
        params={'all': True},
    ).json()

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
    agentlib.execute(['docker', 'volume', 'rm', uid])
    commands = [
        ['docker', 'volume', 'rm', uid],
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
