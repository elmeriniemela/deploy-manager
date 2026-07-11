import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agentd import run


def rpc_function():  # pragma: no cover
    return "ok"


rpc_function._rpc = True


def hidden_function():  # pragma: no cover
    return "hidden"


class FakeServer:
    def __init__(self, address, allow_none=False, interrupt=False):
        self.address = address
        self.allow_none = allow_none
        self.interrupt = interrupt
        self.funcs = {}
        self.shutdown_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def register_function(self, func):
        self.funcs[func.__name__] = func

    def serve_forever(self):
        if self.interrupt:
            raise KeyboardInterrupt

    def shutdown(self):
        self.shutdown_called = True


class MainTests(unittest.TestCase):
    def test_main_registers_rpc_functions_and_returns_failure_when_server_exits(self):
        created_servers = []

        def server_factory(*args, **kwargs):
            server = FakeServer(*args, **kwargs)
            created_servers.append(server)
            return server

        fake_api = SimpleNamespace(rpc_function=rpc_function, hidden_function=hidden_function)

        with patch("agentd.run.api", fake_api):
            with patch("agentd.run.AgentServer", side_effect=server_factory):
                result = run.main(["--interface", "127.0.0.1", "--port", "9001"])

        self.assertEqual(result, 1)
        server = created_servers[0]
        self.assertEqual(server.address, ("127.0.0.1", 9001))
        self.assertTrue(server.allow_none)
        self.assertIn("rpc_function", server.funcs)
        self.assertIn("agent_restart", server.funcs)
        self.assertNotIn("hidden_function", server.funcs)

        server.funcs["agent_restart"]()
        self.assertTrue(server.shutdown_called)

    def test_main_returns_zero_on_keyboard_interrupt(self):
        def server_factory(*args, **kwargs):
            return FakeServer(*args, interrupt=True, **kwargs)

        with patch("agentd.run.api", SimpleNamespace()):
            with patch("agentd.run.AgentServer", side_effect=server_factory):
                result = run.main([])

        self.assertEqual(result, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
