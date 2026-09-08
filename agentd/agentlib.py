import logging
import subprocess
import socket
import psycopg2
import re
import requests
from jinja2 import Template
import os
import glob
from contextlib import contextmanager
from psycopg2.extras import LoggingConnection
import datetime
import fcntl
import tempfile

_logger = logging.getLogger(__name__)

def register(func):
    def wraps(*args, **kwargs): #XML-RPC doesn't have a concept of 'keyword arguments'
        _logger.debug("Call %s", func.__name__)
        return func(*args, **kwargs)
    wraps._rpc = True
    wraps.__name__ = func.__name__
    return wraps


def _parse_version_parts(s):
    component_re = re.compile(r'(\d+ | [a-z]+ | \.| -)', re.VERBOSE)
    replace = {'pre':'c', 'preview':'c','-':'final-','_':'final-','rc':'c','dev':'@','saas':'','~':''}.get
    for part in component_re.split(s):
        part = replace(part,part)
        if not part or part=='.':
            continue
        if part[:1] in '0123456789':
            yield part.zfill(8)    # pad for numeric comparison
        else:
            yield '*'+part

    yield '*final'  # ensure that alpha/beta/candidate are before final

def parse_version(s):
    """Convert a version string to a chronologically-sortable key

    This is a rough cross between distutils' StrictVersion and LooseVersion;
    if you give it versions that would work with StrictVersion, then it behaves
    the same; otherwise it acts like a slightly-smarter LooseVersion. It is
    *possible* to create pathological version coding schemes that will fool
    this parser, but they should be very rare in practice.

    The returned value will be a tuple of strings.  Numeric portions of the
    version are padded to 8 digits so they will compare numerically, but
    without relying on how numbers compare relative to strings.  Dots are
    dropped, but dashes are retained.  Trailing zeros between alpha segments
    or dashes are suppressed, so that e.g. "2.4.0" is considered the same as
    "2.4". Alphanumeric parts are lower-cased.

    The algorithm assumes that strings like "-" and any alpha string that
    alphabetically follows "final"  represents a "patch level".  So, "2.4-1"
    is assumed to be a branch or patch of "2.4", and therefore "2.4.1" is
    considered newer than "2.4-1", which in turn is newer than "2.4".

    Strings like "a", "b", "c", "alpha", "beta", "candidate" and so on (that
    come before "final" alphabetically) are assumed to be pre-release versions,
    so that the version "2.4" is considered newer than "2.4a1".

    Finally, to handle miscellaneous cases, the strings "pre", "preview", and
    "rc" are treated as if they were "c", i.e. as though they were release
    candidates, and therefore are not as new as a version string that does not
    contain them.
    """
    parts = []
    for part in _parse_version_parts((s or '0.1').lower()):
        if part.startswith('*'):
            if part<'*final':   # remove '-' before a prerelease tag
                while parts and parts[-1]=='*final-': parts.pop()
            # remove trailing zeros from each series of numeric parts
            while parts and parts[-1]=='00000000':
                parts.pop()
        parts.append(part)
    return tuple(parts)

def load_nginx_map(fname):
    mapping = {}
    with open(os.path.join('/etc/nginx/conf.d', fname)) as fp:
        lines = fp.readlines()

    [(match, target)] = re.findall(r'map\s+(\$[\w]+)\s+(\$[\w]+)\s+{', lines[0])

    for line in lines[1:]:
        for key, value in re.findall(r'\s+([\w:\.-]+)\s+([\w:\.-]+);', line):
            mapping[key] = value

    return match, target, mapping

def store_nginx_map(fname, match, target, mapping):
    with open('templates/nginxmap.conf') as fp:
        template = Template(fp.read(), keep_trailing_newline=True)

    conf = template.render(mapping=mapping, match=match, target=target)
    path = os.path.join('/etc/nginx/conf.d', fname)
    with tempfile.NamedTemporaryFile(mode='w', dir=os.path.dirname(path), delete=False) as fp:
        try:
            fp.write(conf)
            fp.flush()
            os.fchmod(fp.fileno(), 0o644)
            os.replace(fp.name, path)
        finally:
            if os.path.exists(fp.name):
                os.unlink(fp.name)


@contextmanager
def nginx_lock():
    # A separate open per call also serializes threads in one agent process.
    with open('/run/lock/odoo-nginx.lock', 'a') as fp:
        fcntl.flock(fp, fcntl.LOCK_EX)
        yield


def render_odoo_config(uid, pw, modules):
    with open('templates/odoo.conf') as fp:
        template = Template(fp.read(), keep_trailing_newline=True)

    try:
        modules.remove('odoo')
    except ValueError:
        pass

    conf = template.render(uid=uid, pw=pw, modules=modules)
    save_odoo_config(uid, conf)
    return conf

def save_odoo_config(uid, conf):
    os.makedirs(f'/etc/odoo/{uid}', mode=0o755, exist_ok=True)
    with open(f'/etc/odoo/{uid}/odoo.conf', 'w') as fp:
        fp.write(conf)

def backups_mounted():
    return os.path.ismount('/srv/secure/backups')

def ensure_backups_mounted():
    assert backups_mounted(), "Backup dir not mounted. Something wrong with rclone-mount.service.."

def fname_to_ts(fname):
    return datetime.datetime.strptime(fname, '%Y-%m-%dT%H-%M-%S.pgc')

def ts_to_fname(ts):
    return f"{ts.strftime('%Y-%m-%dT%H-%M-%S')}.pgc"

def dump_path(uid, trigger, fname, makedirs=False):
    dirs = f'/srv/secure/backups/{uid}/{trigger}'
    if makedirs:
        os.makedirs(dirs, mode=0o700, exist_ok=True)
    return f'{dirs}/{fname}'

def rclone_command(command, *args):
    return ['rclone', command, '--config', '/srv/secure/rclone-config/rclone.conf', *args]

def odoo_docker_run(uid, http_port, gevent_port):
    return [
        'docker', 'run',
        '--log-driver=loki',
        '--log-opt', 'loki-url=https://loki.eniemela.fi:3110/loki/api/v1/push',
        '--log-opt', 'loki-retries=5',
        '--log-opt', 'loki-max-backoff=3s',
        '--log-opt', 'loki-timeout=5s',
        '--log-opt', 'loki-tls-insecure-skip-verify=true',
        '--log-opt', 'keep-file=true',
        '--log-opt', 'loki-batch-size=400',
        '--label', 'odoo.version=19.0',
        '-v', '/opt/19/src:/mnt:ro',
        '-v', f'/var/run/postgresql/:/var/run/postgresql/',
        '-v', f'/etc/odoo/{uid}:/etc/odoo:ro',
        '-v', f'{uid}:/var/lib/odoo',
        '-p', f'127.0.0.1:{http_port}:8069',
        '-p', f'[::1]:{http_port}:8069',
        '-p', f'127.0.0.1:{gevent_port}:8072',
        '-p', f'[::1]:{gevent_port}:8072',
        '--restart', 'unless-stopped',
        '--name', uid,
        '-t', '-d', 'ghcr.io/elmeriniemela/odoo-src:19.0',
    ]

def list_backups(uid):
    backups = []
    if not backups_mounted():
        return backups

    for path in glob.glob(dump_path(uid, '*', '*.pgc')):
        fname = os.path.basename(path)
        backups.append({
            'fname': fname,
            'timestamp': fname_to_ts(fname).strftime('%Y-%m-%d %H:%M:%S'), # Odoo DEFAULT_SERVER_DATETIME_FORMAT
            'trigger': os.path.basename(os.path.dirname(path)),
            'source': 'backup-crypt:',
        })
    return backups

def list_instances():
    instances = []
    docker_ps_a = requests.get(
        url='http://127.0.0.1:2375/containers/json',
        params={'all': True},
    ).json()

    for container in docker_ps_a:
        if container.get('Labels', {}).get('odoo.version') != '19.0':
            continue
        uid = container['Names'][0].lstrip('/')
        try:
            validate(uid=uid)
        except ValueError:
            continue

        cid = container['Id']
        container['inspect'] = requests.get(url=f'http://127.0.0.1:2375/containers/{cid}/json').json()

        instances.append({
            'uid': uid,
            'docker': container,
            'backups': list_backups(uid),
        })
    return instances

def list_postgres():
    with psql() as cur:
        cur.execute("select * from pg_catalog.pg_database")
        pg_databases = [{d.name: row[i] for i, d in enumerate(cur.description)} for row in cur.fetchall()]
        cur.execute("select * from pg_catalog.pg_user")
        pg_users = [{d.name: row[i] for i, d in enumerate(cur.description)} for row in cur.fetchall()]

    return {
        'users': pg_users,
        'databases': pg_databases,
    }

def list_modules():
    modules = []
    for fname in glob.glob('src/**/.git'):
        dirname = os.path.dirname(fname)
        mod = {
            'name': os.path.basename(dirname),
        }
        try:
            mod['commit'] = execute(f'cd {dirname} && git rev-parse HEAD', shell=True).stdout.strip()
            mod['commit_date'] = execute(f'cd {dirname} && git log -1 --format=%cd --date=iso', shell=True).stdout.strip()
            mod['branch'] = execute(f'cd {dirname} && git rev-parse --abbrev-ref HEAD', shell=True).stdout.strip()
            mod['url'] = execute(f'cd {dirname} && git remote get-url origin', shell=True).stdout.strip()
        except Exception as error:
            _logger.exception(error)
            continue

        modules.append(mod)

    return modules


@contextmanager
def psql(dbname='postgres'):
    cur = conn = None
    try:
        conn = psycopg2.connect(dbname=dbname, connection_factory=LoggingConnection)
        conn.initialize(_logger)
        conn.set_session(autocommit=True) # CREATE DATABASE cannot be run inside a transaction block.
        cur = conn.cursor()
        yield cur
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


class SubprocessError(Exception): pass

def execute(cmd, **kwargs):
    try:
        _logger.debug(cmd)
        defaults = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding='utf-8',
        )
        defaults.update(kwargs)
        return subprocess.run(cmd, **defaults)
    except subprocess.CalledProcessError as error:
        msg = error.stderr or error.stdout
        cmd = ' '.join(error.cmd)
        raise SubprocessError(f'{msg}\n\n{cmd}')

def validate(**kwargs):
    validators = {
        'hostnames': is_valid_hostnames,
        'uid': is_valid_uid,
        'http_port': is_valid_port,
        'gevent_port': is_valid_port,
        'modules': is_valid_modules
    }
    missing = set(kwargs.keys()) - set(validators.keys())
    if missing:
        raise ValueError("Validator not found for %s" % missing)

    for key, value in kwargs.items():
        resp = validators[key](value)
        assert resp, "Validator for '%s' returned '%s'" % (key, resp)

def is_valid_modules(modules):
    assert isinstance(modules, list), f"Modules should be a list not {type(modules)}"
    for mod in modules:
        assert isinstance(mod, str), f"Module should be a string not {type(mod)}"
        assert os.path.isdir(f'src/{mod}'), f"Module directory does not exist"
    return True


def is_valid_port(port):
    assert isinstance(port, int), "Port should be an integer."
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        resp = sock.connect_ex(('127.0.0.1', port))
    finally:
        sock.close()
    if resp != 111:
        _logger.debug("Port responed with %s.", resp)
        raise ValueError("Port %s is already in use." % port)
    return True

def is_valid_uid(uid):
    assert isinstance(uid, str), "UID should be a string"
    try:
        int(uid, 16)
    except ValueError:
        raise ValueError("Invalid UID, expected a hexadecimal number.")
    return True

def is_valid_hostnames(hostnames):
    assert isinstance(hostnames, list), f"Hostnames should be a list not {type(hostnames)}"
    for hostname in hostnames:
        assert isinstance(hostname, str), "Hostname should be a string."
        import re
        # https://stackoverflow.com/a/33214423
        if hostname[-1] == ".":
            # strip exactly one dot from the right, if present
            hostname = hostname[:-1]
        if len(hostname) > 253:
            raise ValueError("The hostname can't be longer than 253 characters.")

        labels = hostname.split(".")
        if len(labels) < 2:
            raise ValueError("There should be at least one dot in the domain name.")

        # the TLD must be not all-numeric
        if re.match(r"[0-9]+$", labels[-1]):
            raise ValueError("The top level domain must be not all-numeric.")

        allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$")
        for label in labels:
            if not allowed.match(label):
                raise ValueError("Invalid characters in '%s'. Not allowed for a domain name." % label)

    return True
