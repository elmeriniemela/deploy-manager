
import socketserver
import xmlrpc.server
import argparse
import pathlib
import logging
import sys
import api
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)


class AgentServer(socketserver.ThreadingMixIn, xmlrpc.server.SimpleXMLRPCServer):
    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Agent Server')
    parser.add_argument("--interface", dest="interface", type=str, default='localhost')
    parser.add_argument("--port", dest="port", type=int, default=8000)
    parser.add_argument("--logfile", dest="logfile", type=pathlib.Path)
    args = parser.parse_args()

    _logger = logging.getLogger("run")

    with AgentServer((args.interface, args.port), allow_none=True) as server:
        _logger.info(f"AgentServer serving at {args.interface}:{args.port}")

        for obj in api.__dict__.values():
            if getattr(obj, '_rpc', None):
                server.register_function(obj)

        _logger.info(f'Available functions: {list(server.funcs.keys())}')
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            _logger.info("Keyboard interrupt received, exiting.")
            sys.exit(0)
