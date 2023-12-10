import logging
import subprocess
import socket
import psycopg2
import re
from jinja2 import Template
import os

_logger = logging.getLogger(__name__)

def register(func):
    def wraps(*args): #XML-RPC doesn't have a concept of 'keyword arguments'
        _logger.info(f"Call {func.__name__}{args}")
        return func(*args)
    wraps._rpc = True
    wraps.__name__ = func.__name__
    return wraps


def load_nginx_map(fname):
    mapping = {}
    with open(f'/etc/nginx/conf.d/{fname}') as fp:
        lines = fp.readlines()

    [(match, target)] = re.findall(r'map\s+(\$[\w]+)\s+(\$[\w]+)\s+{', lines[0])

    for line in lines[1:]:
        for key, value in re.findall(r'\s+([\w:\.]+)\s+([\w:\.]+);', line):
            mapping[key] = value

    return match, target, mapping

def store_nginx_map(fname, match, target, mapping):
    with open('templates/nginxmap.conf') as fp:
        template = Template(fp.read(), keep_trailing_newline=True)

    conf = template.render(mapping=mapping, match=match, target=target)
    with open(f'/etc/nginx/conf.d/{fname}', 'w') as fp:
        fp.write(conf)


def render_odoo_config(uid, pw):
    with open('templates/odoo.conf') as fp:
        template = Template(fp.read(), keep_trailing_newline=True)

    conf = template.render(uid=uid, pw=pw)
    save_odoo_config(conf, uid)
    return conf

def save_odoo_config(uid, conf):
    os.makedirs(f'/etc/odoo/{uid}', mode=0o755, exist_ok=True)
    with open(f'/etc/odoo/{uid}/odoo.conf', 'w') as fp:
        fp.write(conf)


def psql(queries):
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


class SubprocessError(Exception): pass

def execute(cmd):
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding='utf-8',
        )
    except subprocess.CalledProcessError as error:
        msg = error.stderr or error.stdout
        cmd = ' '.join(error.cmd)
        raise SubprocessError(f'{msg}\n\n{cmd}')

def validate(**kwargs):
    validators = {
        'hostname': is_valid_hostname,
        'uid': is_valid_uid,
        'http_port': is_valid_port,
        'gevent_port': is_valid_port,
    }
    missing = set(kwargs.keys()) - set(validators.keys())
    if missing:
        raise ValueError("Validator not found for %s" % missing)

    for key, value in kwargs.items():
        resp = validators[key](value)
        assert resp, "Validator for '%s' returned '%s'" % (key, resp)


def is_valid_port(port):
    assert isinstance(port, int), "Port should be an integer."
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        resp = sock.connect_ex(('127.0.0.1', port))
    finally:
        sock.close()
    if resp != 111:
        _logger.info("Port responed with %s.", resp)
        raise ValueError("Port %s is already in use." % port)
    return True

def is_valid_uid(uid):
    assert isinstance(uid, str), "UID should be a string"
    try:
        int(uid, 16)
    except ValueError:
        raise ValueError("Invalid UID, expected a hexadecimal number.")
    return True

def is_valid_hostname(hostname):
    assert isinstance(hostname, str), "Hostname should be a string."
    import re
    # https://stackoverflow.com/a/33214423
    if hostname[-1] == ".":
        # strip exactly one dot from the right, if present
        hostname = hostname[:-1]
    if len(hostname) > 253:
        raise ValueError("The hostname can't be longer than 253 characters.")

    labels = hostname.split(".")

    # the TLD must be not all-numeric
    if re.match(r"[0-9]+$", labels[-1]):
        raise ValueError("The top level domain must be not all-numeric.")

    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$")
    for label in labels:
        if not allowed.match(label):
            raise ValueError("Invalid characters in '%s'. Not allowed for a domain name." % label)

    return True
