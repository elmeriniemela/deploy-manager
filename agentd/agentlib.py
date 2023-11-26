import logging
import subprocess

_logger = logging.getLogger(__name__)

def register(func):
    def wraps(*args): #XML-RPC doesn't have a concept of 'keyword arguments'
        _logger.info(f"Call {func.__name__}({args})")
        return func(*args)
    wraps._rpc = True
    wraps.__name__ = func.__name__
    return wraps


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

def is_valid_hostname(hostname):
    import re
    # https://stackoverflow.com/a/33214423
    if hostname[-1] == ".":
        # strip exactly one dot from the right, if present
        hostname = hostname[:-1]
    if len(hostname) > 253:
        return False

    labels = hostname.split(".")

    # the TLD must be not all-numeric
    if re.match(r"[0-9]+$", labels[-1]):
        return False

    allowed = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)$")
    return all(allowed.match(label) for label in labels)