import logging
import psycopg2
from psycopg2 import sql
import secrets
import subprocess
from jinja2 import Template
from agentlib import register
_logger = logging.getLogger(__name__)

@register
def test():
    print("test")


@register
def new_instance(name, uid, http_port, gevent_port):
    pw = secrets.token_hex(32)
    queries = [
        (sql.SQL("CREATE ROLE {uid} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT LOGIN ENCRYPTED PASSWORD %s").format(uid=sql.Identifier(uid)), (pw,)),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(uid)),),
    ]
    with psycopg2.connect(dbname='postgres') as conn:
        conn.set_session(autocommit=True) # CREATE DATABASE cannot be run inside a transaction block.
        conn.commit()
        with conn.cursor() as cur:
            for args in queries:
                cur.execute(*args)

    with open('odoo/odoo.conf') as fp:
        template = Template(fp.read())

    conf = template.render(uid=uid, pw=pw)
    with open(f'/etc/odoo/{uid}/odoo.conf', 'w') as fp:
        fp.write(conf)

    resp = subprocess.run(
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        encoding='utf-8',
    )
