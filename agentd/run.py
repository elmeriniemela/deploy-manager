import argparse
import logging
import pathlib
import socketserver
import sys
import xmlrpc.server

from . import api

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)


class AgentServer(socketserver.ThreadingMixIn, xmlrpc.server.SimpleXMLRPCServer):
    pass


def main(argv=None):
    parser = argparse.ArgumentParser(description='Agent Server')
    parser.add_argument("--interface", dest="interface", type=str, default='localhost')
    parser.add_argument("--port", dest="port", type=int, default=8000)
    parser.add_argument("--logfile", dest="logfile", type=pathlib.Path)
    args = parser.parse_args(argv)

    _logger = logging.getLogger("run")

    with AgentServer((args.interface, args.port), allow_none=True) as server:
        _logger.info(f"AgentServer serving at {args.interface}:{args.port}")

        for obj in api.__dict__.values():
            if getattr(obj, '_rpc', None):
                server.register_function(obj)

        def agent_restart():
            _logger.info("Restarting agent..")
            server.shutdown()

        server.register_function(agent_restart)

        _logger.info(f'Available functions: {list(server.funcs.keys())}')
        try:
            server.serve_forever()
            return 1 # If the loop ended, its considered a failure -> systemd will restart.
        except KeyboardInterrupt:
            _logger.info("Keyboard interrupt received, exiting.")
            return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
