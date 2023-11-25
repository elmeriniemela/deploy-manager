import logging
from agentlib import register
_logger = logging.getLogger(__name__)

@register
def test():
    print("test")