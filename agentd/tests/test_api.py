import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

from agentd import api


class AgentGitTests(unittest.TestCase):
    def test_agent_pull_runs_update_commands_and_returns_current_commit(self):
        execute_results = [
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout="abc123\n"),
        ]

        with patch("agentd.api.agentlib.execute", side_effect=execute_results) as execute:
            commit = api.agent_pull("main")

        self.assertEqual(commit, "abc123")
        self.assertEqual(
            execute.call_args_list,
            [
                call(["git", "pull"]),
                call(["git", "checkout", "main"]),
                call(["git", "submodule", "update", "--init"]),
                call(["git", "rev-parse", "HEAD"]),
            ],
        )

    def test_agent_diff_fetches_diff_and_filters_default_exclusions(self):
        execute_results = [
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout="raw diff"),
            SimpleNamespace(stdout="filtered diff"),
        ]

        with patch("agentd.api.agentlib.execute", side_effect=execute_results) as execute:
            diff = api.agent_diff("HEAD~1..HEAD")

        self.assertEqual(diff, "filtered diff")
        self.assertEqual(execute.call_args_list[0], call(["git", "fetch"]))
        self.assertEqual(
            execute.call_args_list[1],
            call(["git", "diff", "--submodule=diff", "HEAD~1..HEAD"]),
        )
        filter_call = execute.call_args_list[2]
        self.assertEqual(
            filter_call.args[0],
            ["filterdiff", "-x", "*.po", "-x", "*.pot", "-x", "**/tests/*"],
        )
        self.assertIn("stdin", filter_call.kwargs)

    def test_module_pull_runs_commands_inside_requested_module(self):
        execute_results = [
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout="def456\n"),
        ]

        with patch("agentd.api.agentlib.execute", side_effect=execute_results) as execute:
            commit = api.module_pull("custom_addons", "19.0")

        self.assertEqual(commit, "def456")
        self.assertEqual(
            execute.call_args_list,
            [
                call(["git", "pull"], cwd="src/custom_addons"),
                call(["git", "checkout", "19.0"], cwd="src/custom_addons"),
                call(
                    ["git", "submodule", "update", "--init"],
                    cwd="src/custom_addons",
                ),
                call(["git", "rev-parse", "HEAD"], cwd="src/custom_addons"),
            ],
        )


class BackupTests(unittest.TestCase):
    def test_backup_dumps_database_and_syncs_filestore(self):
        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.ts_to_fname", return_value="dump.pgc"):
                with patch(
                    "agentd.api.agentlib.dump_path", return_value="/tmp/dump.pgc"
                ) as dump_path:
                    with patch("agentd.api.agentlib.execute") as execute:
                        with patch(
                            "agentd.api.agentlib.list_backups",
                            return_value=[{"fname": "dump.pgc"}],
                        ):
                            result = api.backup("1a2b", trigger="manual")

        validate.assert_called_once_with(uid="1a2b")
        dump_path.assert_called_once_with("1a2b", "manual", "dump.pgc", makedirs=True)
        self.assertEqual(result, {"backups": [{"fname": "dump.pgc"}]})
        self.assertEqual(
            execute.call_args_list,
            [
                call(["pg_dump", "--no-owner", "-Fc", "-f", "/tmp/dump.pgc", "1a2b"]),
                call(
                    [
                        "rclone",
                        "copy",
                        "--transfers=16",
                        "--ignore-existing",
                        "/var/lib/docker/volumes/1a2b/_data/filestore/1a2b",
                        "awsbucket:odoobackup1/1a2b/filestore",
                    ]
                ),
                call(
                    [
                        "rclone",
                        "sync",
                        "--transfers=16",
                        "--ignore-existing",
                        "/var/lib/docker/volumes/1a2b/_data/filestore/1a2b",
                        "awsbucket:odoobackup1/1a2b/previous_filestore",
                    ]
                ),
            ],
        )

    def test_fshealth_runs_one_way_rclone_check_and_returns_stderr(self):
        with patch("agentd.api.agentlib.validate") as validate:
            with patch(
                "agentd.api.agentlib.execute",
                return_value=SimpleNamespace(stderr="  mismatch\n", stdout=""),
            ) as execute:
                result = api.fshealth("1a2b")

        validate.assert_called_once_with(uid="1a2b")
        self.assertEqual(result, "mismatch")
        execute.assert_called_once_with(
            cmd=[
                "rclone",
                "check",
                "--one-way",
                "/var/lib/docker/volumes/1a2b/_data/filestore/1a2b",
                "awsbucket:odoobackup1/1a2b/filestore",
            ],
            check=False,
        )


class InstanceCommandTests(unittest.TestCase):
    def test_restart_start_and_stop_validate_uid_and_call_docker(self):
        cases = [
            (api.restart, ["docker", "restart", "1a2b"]),
            (api.start, ["docker", "start", "1a2b"]),
            (api.stop, ["docker", "stop", "1a2b"]),
        ]

        for func, expected_cmd in cases:
            with self.subTest(func=func.__name__):
                with patch("agentd.api.agentlib.validate") as validate:
                    with patch("agentd.api.agentlib.execute") as execute:
                        func("1a2b")

                validate.assert_called_once_with(uid="1a2b")
                execute.assert_called_once_with(expected_cmd)

    def test_rebuild_removes_and_recreates_container(self):
        docker_run = ["docker", "run", "--name", "1a2b"]

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.odoo_docker_run", return_value=docker_run):
                with patch("agentd.api.agentlib.execute") as execute:
                    api.rebuild("1a2b", 8069, 8072)

        validate.assert_called_once_with(uid="1a2b", http_port=8069, gevent_port=8072)
        self.assertEqual(
            execute.call_args_list,
            [
                call(["docker", "rm", "1a2b"]),
                call(docker_run),
            ],
        )


class UrlSyncTests(unittest.TestCase):
    def test_sync_urls_replaces_existing_port_mappings_and_reloads_nginx(self):
        load_results = [
            (
                "$host",
                "$gevent_target",
                {
                    "old-gevent.example": "127.0.0.1:8072",
                    "keep-gevent.example": "127.0.0.1:9001",
                },
            ),
            (
                "$host",
                "$http_target",
                {
                    "old-http.example": "127.0.0.1:8069",
                    "keep-http.example": "127.0.0.1:9000",
                },
            ),
        ]

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.load_nginx_map", side_effect=load_results):
                with patch("agentd.api.agentlib.store_nginx_map") as store:
                    with patch("agentd.api.agentlib.execute") as execute:
                        api.sync_urls(["new.example"], 8069, 8072)

        validate.assert_called_once_with(hostnames=["new.example"])
        self.assertEqual(
            store.call_args_list,
            [
                call(
                    "gevent-ports.conf",
                    "$host",
                    "$gevent_target",
                    {
                        "keep-gevent.example": "127.0.0.1:9001",
                        "new.example": "127.0.0.1:8072",
                    },
                ),
                call(
                    "http-ports.conf",
                    "$host",
                    "$http_target",
                    {
                        "keep-http.example": "127.0.0.1:9000",
                        "new.example": "127.0.0.1:8069",
                    },
                ),
            ],
        )
        execute.assert_called_once_with(["systemctl", "reload", "nginx"])


if __name__ == "__main__":
    unittest.main()
