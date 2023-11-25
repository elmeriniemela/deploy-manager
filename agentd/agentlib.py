import logging

_logger = logging.getLogger(__name__)

def register(func):
    def wraps(*args, **kwargs):
        _logger.info(f"Calling {func.__name__}.")
        return func(*args, **kwargs)
    wraps._rpc = True
    wraps.__name__ = func.__name__
    return wraps
