import logging

_logger = logging.getLogger(__name__)

def register(func):
    def wraps(*args): #XML-RPC doesn't have a concept of 'keyword arguments'
        _logger.info(f"Call {func.__name__}({args})")
        return func(*args)
    wraps._rpc = True
    wraps.__name__ = func.__name__
    return wraps
