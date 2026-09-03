import logging
from psycopg2 import sql
import secrets

from . import agentlib, cronsyl
import requests
import os
import glob
import time
import threading
import ast
import datetime
import tempfile
_logger = logging.getLogger(__name__)


@agentlib.register
def status():
    return {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        'instances': agentlib.list_instances(),
        'postgres': agentlib.list_postgres(),
        'agent': {
            'commit': agentlib.execute(['git', 'rev-parse', 'HEAD']).stdout.strip(),
            'commit_date': agentlib.execute(['git', 'log', '-1', '--format=%cd', '--date=iso']).stdout.strip(),
        },
        'modules': agentlib.list_modules(),
        'hardware': cronsyl.collect_hardware(('/',))
    }

@agentlib.register
def agent_pull(checkout):
    commands = [
        ['git', 'pull'],
        ['git', 'checkout', checkout],
        ['git', 'submodule', 'update', '--init'],
    ]
    for cmd in commands:
        agentlib.execute(cmd)

    return agentlib.execute(['git', 'rev-parse', 'HEAD']).stdout.strip()

@agentlib.register
def agent_diff(version_range, include=None, exclude=None):
    agentlib.execute(['git', 'fetch'])
    output = agentlib.execute(['git', 'diff', '--submodule=diff', version_range]).stdout

    exclude = exclude or ['*.po', '*.pot', '**/tests/*']
    if include or exclude:
        filter_cmd = ['filterdiff']
        for p in (include or []): filter_cmd.extend(['-i', p])
        for p in (exclude or []): filter_cmd.extend(['-x', p])

        with tempfile.TemporaryFile(mode='w') as fp:
            fp.write(output)
            fp.seek(0)
            output = agentlib.execute(filter_cmd, stdin=fp).stdout

    return output

@agentlib.register
def module_diff(module, version_range, include=None, exclude=None):
    agentlib.execute(['git', 'fetch'], cwd=f'src/{module}')
    output = agentlib.execute(['git', 'diff', '--submodule=diff', version_range], cwd=f'src/{module}').stdout
    exclude = exclude or ['*.po', '*.pot', '**/tests/*']
    if include or exclude:
        filter_cmd = ['filterdiff']
        for p in (include or []): filter_cmd.extend(['-i', p])
        for p in (exclude or []): filter_cmd.extend(['-x', p])

        with tempfile.TemporaryFile(mode='w') as fp:
            fp.write(output)
            fp.seek(0)
            output = agentlib.execute(filter_cmd, stdin=fp).stdout

    return output

@agentlib.register
def module_pull(module, checkout):
    commands = [
        ['git', 'pull'],
        ['git', 'checkout', checkout],
        ['git', 'submodule', 'update', '--init'],
    ]
    for cmd in commands:
        agentlib.execute(cmd, cwd=f'src/{module}')

    return agentlib.execute(['git', 'rev-parse', 'HEAD'], cwd=f'src/{module}').stdout.strip()

@agentlib.register
def backup(uid, trigger='manual'):
    _logger.info(f"Starting {trigger} backup for {uid}")
    agentlib.validate(uid=uid)
    fname = agentlib.ts_to_fname(datetime.datetime.now(datetime.timezone.utc))
    agentlib.execute(['pg_dump', '--no-owner', '-Fc', '-f', agentlib.dump_path(uid, trigger, fname, makedirs=True), uid])
    agentlib.execute([
        'rclone', 'copy',
        '--transfers=16',
        '--ignore-existing', # Odoo filestore checksums prohibit editing an existing filepath.
        f'/var/lib/docker/volumes/{uid}/_data/filestore/{uid}', f'backup-crypt:{uid}/filestore'
    ])
    agentlib.execute([
        'rclone', 'sync',
        '--transfers=16',
        '--ignore-existing', # Odoo filestore checksums prohibit editing an existing filepath.
        f'/var/lib/docker/volumes/{uid}/_data/filestore/{uid}', f'backup-crypt:{uid}/previous_filestore'
    ])
    _logger.info(f"Backup done: {trigger} backup for {uid}")
    return {
        'backups': agentlib.list_backups(uid),
    }

@agentlib.register
def fshealth(uid):
    agentlib.validate(uid=uid)
    fsproc = agentlib.execute(
        cmd=[
            'rclone', 'check',
            '--one-way',
            f'/var/lib/docker/volumes/{uid}/_data/filestore/{uid}', f'backup-crypt:{uid}/filestore'
        ],
        check=False,
    )
    return (fsproc.stderr or '').strip()


@agentlib.register
def restore(src_uid, dst_uid, trigger, backup_file):
    _restore(src_uid, dst_uid, trigger, backup_file)
    restart(dst_uid)

def _restore(src_uid, dst_uid, trigger, backup_file):
    agentlib.validate(uid=src_uid)
    agentlib.validate(uid=dst_uid)
    agentlib.ensure_backups_mounted()
    queries = [
        (sql.SQL("DROP DATABASE {uid}").format(uid=sql.Identifier(dst_uid)),),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(dst_uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(dst_uid)),),
    ]
    with agentlib.psql() as cur:
        for args in queries:
            cur.execute(*args)

    commands = [
        [
            'rclone', 'sync',
            '--transfers=16',
            '--ignore-existing', # Odoo filestore checksums prohibit editing an existing filepath.
            f'backup-crypt:{src_uid}/previous_filestore', f'/var/lib/docker/volumes/{dst_uid}/_data/filestore/{dst_uid}'
        ],
        ['chown', '1000:1000', '-R', f'/var/lib/docker/volumes/{dst_uid}/_data/filestore/{dst_uid}'], # TODO, better way to assign ownership to container user 'odoo'?
        ['pg_restore', '-Fc', '--no-owner', f'--role={dst_uid}', '-d', dst_uid, agentlib.dump_path(src_uid, trigger, backup_file)],
    ]
    for cmd in commands:
        agentlib.execute(cmd)


@agentlib.register
def oca_migrate(src_uid, dst_uid, trigger, backup_file):
    _restore(src_uid, dst_uid, trigger, backup_file)
    start(dst_uid) # docker exec requires that the cointainer is running.
    _logger.info(f"Wait for Odoo to be ready (orm_signaling_registry is created).")
    time.sleep(3)
    proc = agentlib.execute([
        'docker', 'exec', dst_uid, 'odoo',
        '--update=all',
        '--no-http',
        '--workers=0',
        '--stop-after-init',
        '--load=base,web,openupgrade_framework',
        '--upgrade-path=/mnt/OpenUpgrade/openupgrade_scripts/scripts',
    ])
    restart(dst_uid)
    return (proc.stderr or '').strip() or (proc.stdout or '').strip()


@agentlib.register
def upgrade(uid):
    agentlib.validate(uid=uid)
    codever = {}
    for fname in glob.glob('src/**/**/__manifest__.py'):
        with open(fname, 'rb') as manifest:
            d = ast.literal_eval(manifest.read().decode('latin1'))
            version = d.get('version', '0.0')
            module = os.path.basename(os.path.dirname(fname))
            if not version.startswith('19.0.'):
                version = '19.0.' + version
            codever[module] = version

    with agentlib.psql(dbname=uid) as cur:
        cur.execute("select name, latest_version from ir_module_module where state='installed'")
        dbver = {name: version for name, version in cur.fetchall()}

    upgrade = []
    for module, db in dbver.items():
        code = codever.get(module, '0.0')
        if agentlib.parse_version(code) > agentlib.parse_version(db):
            upgrade.append(module)

    if upgrade:
        joined_upgrade = ','.join(upgrade)
        with agentlib.psql() as cur:
            cur.execute(
                sql.SQL("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND usename = %s"), (uid, uid),
            )

        proc = agentlib.execute([
            'docker',
            'exec',
            uid,
            'odoo',
            f'--update={joined_upgrade}',
            '--no-http',
            '--workers=0',
            '--stop-after-init',
        ])
        return (proc.stderr or '').strip() or (proc.stdout or '').strip()
    return None


@agentlib.register
def ssl_cert(hostname):
    agentlib.validate(hostnames=[hostname])
    basecmd = ['certbot', 'certonly', '-n', '--expand', '--agree-tos', '-m=niemela.elmeri@gmail.com', f'-d={hostname}', '--standalone',]
    agentlib.execute(basecmd + ['--dry-run'])
    agentlib.execute(basecmd)


@agentlib.register
def ssl_wildcard():
    # https://www.bjornjohansen.com/wildcard-certificate-letsencrypt-cloudflare
    agentlib.execute([
        'certbot', 'certonly', '--dns-cloudflare',
        '--dns-cloudflare-credentials', '/root/cloudflare.ini',
        '-d', '*.eniemela.fi',
        '-d', 'eniemela.fi',
        '--expand',
        '--preferred-challenges', 'dns-01',
        '-n', '--agree-tos',
        '-m=niemela.elmeri@gmail.com',
        '--dns-cloudflare-propagation-seconds=120', '-vvv',
    ])

@agentlib.register
def ssl_renew():
    proc = agentlib.execute(['certbot', 'renew'])
    agentlib.execute(['systemctl', 'reload', 'nginx'])
    return '\n'.join([proc.stderr or '', proc.stdout or '']).strip()

@agentlib.register
def self_upgrade(uid, callback_url):
    agentlib.validate(uid=uid)

    def thread_worker():
        time.sleep(1)
        logs = upgrade(uid) or ''
        resp = requests.post(
            url=callback_url,
            timeout=15,
            json={
                'method': 'upgrade',
                'uid': uid,
                'logs': logs,
            }
        )
        _logger.info(resp.text)
        restart(uid)

        for tryno in range(1, 6):
            time.sleep(3)
            resp = requests.post(
                url=callback_url,
                timeout=15,
                json={
                    'method': 'restart',
                    'uid': uid,
                }
            )
            _logger.info(resp.text)
            if resp.status_code == 200:
                break
        else:
            _logger.error("Host not responding after restart.")
    threading.Thread(target=thread_worker).start()



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
def remove(uid, http_port, gevent_port):
    agentlib.validate(uid=uid, http_port=http_port, gevent_port=gevent_port)
    curstatus = status()
    existing_containers = {v['uid'] for v in curstatus['instances']}
    if uid in existing_containers:
        agentlib.execute(['docker', 'rm', uid])

    sync_urls(hostnames=[], http_port=http_port, gevent_port=gevent_port)

    existing_dbs = {v['datname'] for v in curstatus['postgres']['databases']}
    existing_users = {v['usename'] for v in curstatus['postgres']['users']}
    with agentlib.psql() as cur:
        if uid in existing_dbs:
            cur.execute(sql.SQL("DROP DATABASE {uid}").format(uid=sql.Identifier(uid)),)
        if uid in existing_users:
            cur.execute(sql.SQL("DROP USER {uid}").format(uid=sql.Identifier(uid)),)

    if os.path.isdir(f'/var/lib/docker/volumes/{uid}'):
        agentlib.execute(['docker', 'volume', 'rm', uid])

@agentlib.register
def rebuild(uid, http_port, gevent_port):
    agentlib.validate(uid=uid, http_port=http_port, gevent_port=gevent_port)
    commands = [
        ['docker', 'rm', uid],
        agentlib.odoo_docker_run(uid, http_port, gevent_port),
    ]
    for cmd in commands:
        agentlib.execute(cmd)


@agentlib.register
def config(uid, conf):
    agentlib.validate(uid=uid)
    agentlib.save_odoo_config(uid, conf)


@agentlib.register
def sync_urls(hostnames, http_port, gevent_port):
    agentlib.validate(hostnames=hostnames) # ports are not checked, as the instance may be running and ports binded.

    for port, fname in [(gevent_port, 'gevent-ports.conf'), (http_port, 'http-ports.conf')]:
        match, target, mapping = agentlib.load_nginx_map(fname)
        # Remove old ones
        mapping = {d: p for d, p in mapping.items() if int(p.split(':')[-1]) != int(port)}
        # Add new ones
        for hostname in hostnames:
            mapping[hostname] = f'127.0.0.1:{port}'

        agentlib.store_nginx_map(fname, match, target, mapping)

    agentlib.execute(['systemctl', 'reload', 'nginx'])


@agentlib.register
def reset(uid):
    agentlib.validate(uid=uid)
    queries = [
        (sql.SQL("DROP DATABASE {uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(uid)),),
    ]
    with agentlib.psql() as cur:
        for args in queries:
            cur.execute(*args)

    commands = [
        ['docker', 'start', uid],
        [
            'docker', 'exec', uid, 'odoo',
            '--init=base',
            '--no-http',
            '--workers=0',
            '--stop-after-init',
        ],
        ['docker', 'restart', uid],
    ]

    for cmd in commands:
        agentlib.execute(cmd)

    with agentlib.psql(dbname=uid) as cur:
        cur.execute(sql.SQL("UPDATE res_users SET password=%s WHERE login='admin'"), (uid,)) # Better than admin:admin, but desinged to be changed manually.


@agentlib.register
def create(uid, hostnames, http_port, gevent_port, modules):
    agentlib.validate(uid=uid, hostnames=hostnames, http_port=http_port, gevent_port=gevent_port, modules=modules)
    pw = secrets.token_hex(32)

    config = agentlib.render_odoo_config(uid, pw, modules)

    sync_urls(hostnames, http_port, gevent_port)

    queries = [
        (sql.SQL("CREATE ROLE {uid} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT LOGIN ENCRYPTED PASSWORD %s").format(uid=sql.Identifier(uid)), (pw,)),
        (sql.SQL("CREATE DATABASE {uid} WITH OWNER={uid}").format(uid=sql.Identifier(uid)),),
        (sql.SQL("REVOKE ALL ON DATABASE {uid} FROM public").format(uid=sql.Identifier(uid)),),
    ]
    with agentlib.psql() as cur:
        for args in queries:
            cur.execute(*args)

    agentlib.execute(agentlib.odoo_docker_run(uid, http_port, gevent_port))
    _logger.info(f"Wait for Odoo to be ready (base_registry_signaling is created).")
    time.sleep(3)
    # agentlib.execute(['docker', 'exec', uid, 'curl', '-L', 'localhost:8069'])
    commands = [
        [
            'docker', 'exec', uid, 'odoo',
            '--init=base',
            '--no-http',
            '--workers=0',
            '--stop-after-init',
        ],
        ['docker', 'restart', uid],
    ]

    for cmd in commands:
        agentlib.execute(cmd)

    with agentlib.psql(dbname=uid) as cur:
        cur.execute(sql.SQL("UPDATE res_users SET password=%s WHERE login='admin'"), (uid,)) # Better than admin:admin, but desinged to be changed manually.

    return config

if __name__ == "__main__":  # pragma: no cover
    functions = {}
    localdict = dict(locals())
    for name, obj in localdict.items():
        if getattr(obj, '_rpc', None):
            functions[name] = obj

    import argparse
    from pprint import pprint
    parser = argparse.ArgumentParser(description='API')
    parser.add_argument('function', help="API function to run.")
    parser.add_argument('args', metavar='arg', type=str, nargs='*', help='arguments for the function')
    args = parser.parse_args()
    func = functions[args.function]
    pprint(func(*args.args))
