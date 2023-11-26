import logging
import socket
import os
import psycopg2
from psycopg2 import sql
import secrets
from jinja2 import Template
import agentlib
_logger = logging.getLogger(__name__)


@agentlib.register
def test():
    print("test")

@agentlib.register
def new_instance(name, uid, http_port, gevent_port):
    assert isinstance(name, str)
    assert isinstance(uid, str)
    assert isinstance(http_port, int)
    assert isinstance(gevent_port, int)
    assert agentlib.is_valid_hostname(name)
    try:
        int(uid, 16)
    except ValueError:
        raise ValueError("Invalid UID, expected a hexadecimal number.")

    for p in [http_port, gevent_port]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            resp = sock.connect_ex(('127.0.0.1', p))
        finally:
            sock.close()
        if resp != 111:
            _logger.info("Port responed with %s.", resp)
            raise ValueError("Port %s is already in use." % p)



    pw = secrets.token_hex(32)
    queries = [
        (sql.SQL("CREATE ROLE {uid} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT LOGIN ENCRYPTED PASSWORD %s").format(uid=sql.Identifier(uid)), (pw,)),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(uid)),),
    ]

    cur = conn = None
    try:
        conn = psycopg2.connect(dbname='postgres')
        conn.set_session(autocommit=True) # CREATE DATABASE cannot be run inside a transaction block.
        cur = conn.cursor()
        for args in queries:
            cur.execute(*args)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    with open('odoo/odoo.conf') as fp:
        template = Template(fp.read())

    conf = template.render(uid=uid, pw=pw)
    os.makedirs(f'/etc/odoo/{uid}', mode=0o755, exist_ok=True)
    with open(f'/etc/odoo/{uid}/odoo.conf', 'w') as fp:
        fp.write(conf)

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

