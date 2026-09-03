import datetime
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from agentd import api


@contextmanager
def cursor_context(cursor):
    yield cursor


def manifest_context(read_data):
    handle = MagicMock()
    handle.__enter__.return_value.read.return_value = read_data
    return handle


class ImmediateThread:
    def __init__(self, target):
        self.target = target

    def start(self):
        self.target()


class StatusTests(unittest.TestCase):
    def test_status_collects_agent_postgres_module_and_hardware_state(self):
        now = datetime.datetime(2026, 7, 11, 12, 30, tzinfo=datetime.timezone.utc)
        execute_results = [
            SimpleNamespace(stdout="abc123\n"),
            SimpleNamespace(stdout="2026-07-11 12:00:00 +0000\n"),
        ]

        with patch("agentd.api.datetime.datetime") as datetime_class:
            datetime_class.now.return_value = now
            with patch("agentd.api.agentlib.list_instances", return_value=[{"uid": "1a2b"}]):
                with patch(
                    "agentd.api.agentlib.list_postgres",
                    return_value={"databases": [], "users": []},
                ):
                    with patch(
                        "agentd.api.agentlib.execute", side_effect=execute_results
                    ) as execute:
                        with patch(
                            "agentd.api.agentlib.list_modules",
                            return_value=[{"name": "custom_addons"}],
                        ):
                            with patch(
                                "agentd.api.cronsyl.collect_hardware",
                                return_value={"load": 0.1},
                            ) as collect_hardware:
                                result = api.status()

        self.assertEqual(result["timestamp"], "2026-07-11 12:30:00")
        self.assertEqual(result["instances"], [{"uid": "1a2b"}])
        self.assertEqual(result["postgres"], {"databases": [], "users": []})
        self.assertEqual(
            result["agent"],
            {
                "commit": "abc123",
                "commit_date": "2026-07-11 12:00:00 +0000",
            },
        )
        self.assertEqual(result["modules"], [{"name": "custom_addons"}])
        self.assertEqual(result["hardware"], {"load": 0.1})
        self.assertEqual(
            execute.call_args_list,
            [
                call(["git", "rev-parse", "HEAD"]),
                call(["git", "log", "-1", "--format=%cd", "--date=iso"]),
            ],
        )
        collect_hardware.assert_called_once_with(("/",))


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

    def test_module_diff_fetches_diff_inside_module_and_filters_patterns(self):
        execute_results = [
            SimpleNamespace(stdout=""),
            SimpleNamespace(stdout="raw diff"),
            SimpleNamespace(stdout="filtered diff"),
        ]

        with patch("agentd.api.agentlib.execute", side_effect=execute_results) as execute:
            diff = api.module_diff(
                "custom_addons",
                "HEAD~1..HEAD",
                include=["*.py"],
                exclude=["*.po"],
            )

        self.assertEqual(diff, "filtered diff")
        self.assertEqual(
            execute.call_args_list[0],
            call(["git", "fetch"], cwd="src/custom_addons"),
        )
        self.assertEqual(
            execute.call_args_list[1],
            call(
                ["git", "diff", "--submodule=diff", "HEAD~1..HEAD"],
                cwd="src/custom_addons",
            ),
        )
        filter_call = execute.call_args_list[2]
        self.assertEqual(filter_call.args[0], ["filterdiff", "-i", "*.py", "-x", "*.po"])
        self.assertIn("stdin", filter_call.kwargs)


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
                        "backup-crypt:1a2b/filestore",
                    ]
                ),
                call(
                    [
                        "rclone",
                        "sync",
                        "--transfers=16",
                        "--ignore-existing",
                        "/var/lib/docker/volumes/1a2b/_data/filestore/1a2b",
                        "backup-crypt:1a2b/previous_filestore",
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
                "backup-crypt:1a2b/filestore",
            ],
            check=False,
        )


class RestoreTests(unittest.TestCase):
    def test_restore_runs_database_and_filestore_restore_then_restarts_destination(self):
        with patch("agentd.api._restore") as restore:
            with patch("agentd.api.restart") as restart:
                api.restore("1a2b", "2b3c", "daily", "dump.pgc")

        restore.assert_called_once_with("1a2b", "2b3c", "daily", "dump.pgc")
        restart.assert_called_once_with("2b3c")

    def test_restore_helper_recreates_database_and_restores_dump(self):
        cursor = MagicMock()

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.ensure_backups_mounted") as ensure_mounted:
                with patch("agentd.api.agentlib.psql", return_value=cursor_context(cursor)):
                    with patch(
                        "agentd.api.agentlib.dump_path", return_value="/backups/dump.pgc"
                    ) as dump_path:
                        with patch("agentd.api.agentlib.execute") as execute:
                            api._restore("1a2b", "2b3c", "daily", "dump.pgc")

        self.assertEqual(
            validate.call_args_list,
            [
                call(uid="1a2b"),
                call(uid="2b3c"),
            ],
        )
        ensure_mounted.assert_called_once_with()
        self.assertEqual(cursor.execute.call_count, 3)
        dump_path.assert_called_once_with("1a2b", "daily", "dump.pgc")
        self.assertEqual(
            execute.call_args_list,
            [
                call(
                    [
                        "rclone",
                        "sync",
                        "--transfers=16",
                        "--ignore-existing",
                        "backup-crypt:1a2b/previous_filestore",
                        "/var/lib/docker/volumes/2b3c/_data/filestore/2b3c",
                    ]
                ),
                call(
                    [
                        "chown",
                        "1000:1000",
                        "-R",
                        "/var/lib/docker/volumes/2b3c/_data/filestore/2b3c",
                    ]
                ),
                call(
                    [
                        "pg_restore",
                        "-Fc",
                        "--no-owner",
                        "--role=2b3c",
                        "-d",
                        "2b3c",
                        "/backups/dump.pgc",
                    ]
                ),
            ],
        )

    def test_oca_migrate_restores_runs_openupgrade_and_restarts(self):
        with patch("agentd.api._restore") as restore:
            with patch("agentd.api.start") as start:
                with patch("agentd.api.time.sleep") as sleep:
                    with patch(
                        "agentd.api.agentlib.execute",
                        return_value=SimpleNamespace(stderr=" migration log\n", stdout=""),
                    ) as execute:
                        with patch("agentd.api.restart") as restart:
                            result = api.oca_migrate("1a2b", "2b3c", "daily", "dump.pgc")

        self.assertEqual(result, "migration log")
        restore.assert_called_once_with("1a2b", "2b3c", "daily", "dump.pgc")
        start.assert_called_once_with("2b3c")
        sleep.assert_called_once_with(3)
        execute.assert_called_once_with(
            [
                "docker",
                "exec",
                "2b3c",
                "odoo",
                "--update=all",
                "--no-http",
                "--workers=0",
                "--stop-after-init",
                "--load=base,web,openupgrade_framework",
                "--upgrade-path=/mnt/OpenUpgrade/openupgrade_scripts/scripts",
            ]
        )
        restart.assert_called_once_with("2b3c")


class UpgradeTests(unittest.TestCase):
    def test_upgrade_runs_odoo_update_for_modules_with_newer_code_versions(self):
        db_cursor = MagicMock()
        db_cursor.fetchall.return_value = [
            ("sale", "19.0.1.0"),
            ("stock", "19.0.1.0"),
            ("base", "19.0.1.0"),
        ]
        terminate_cursor = MagicMock()
        manifests = [
            manifest_context(b"{'version': '2.0'}"),
            manifest_context(b"{'version': '19.0.1.0'}"),
        ]

        with patch("agentd.api.agentlib.validate") as validate:
            with patch(
                "agentd.api.glob.glob",
                return_value=[
                    "src/addons/sale/__manifest__.py",
                    "src/addons/stock/__manifest__.py",
                ],
            ):
                with patch("builtins.open", side_effect=manifests):
                    with patch("agentd.api.agentlib.psql") as psql:
                        psql.side_effect = [
                            cursor_context(db_cursor),
                            cursor_context(terminate_cursor),
                        ]
                        with patch(
                            "agentd.api.agentlib.execute",
                            return_value=SimpleNamespace(stderr="", stdout=" upgraded\n"),
                        ) as execute:
                            result = api.upgrade("1a2b")

        self.assertEqual(result, "upgraded")
        validate.assert_called_once_with(uid="1a2b")
        db_cursor.execute.assert_called_once_with(
            "select name, latest_version from ir_module_module where state='installed'"
        )
        terminate_cursor.execute.assert_called_once()
        execute.assert_called_once_with(
            [
                "docker",
                "exec",
                "1a2b",
                "odoo",
                "--update=sale",
                "--no-http",
                "--workers=0",
                "--stop-after-init",
            ]
        )
        self.assertEqual(psql.call_args_list, [call(dbname="1a2b"), call()])

    def test_upgrade_returns_none_when_database_versions_are_current(self):
        db_cursor = MagicMock()
        db_cursor.fetchall.return_value = [("sale", "19.0.2.0")]

        with patch("agentd.api.agentlib.validate"):
            with patch(
                "agentd.api.glob.glob",
                return_value=["src/addons/sale/__manifest__.py"],
            ):
                with patch("builtins.open", side_effect=[manifest_context(b"{'version': '2.0'}")]):
                    with patch(
                        "agentd.api.agentlib.psql",
                        return_value=cursor_context(db_cursor),
                    ) as psql:
                        with patch("agentd.api.agentlib.execute") as execute:
                            result = api.upgrade("1a2b")

        self.assertIsNone(result)
        psql.assert_called_once_with(dbname="1a2b")
        execute.assert_not_called()


class CertificateTests(unittest.TestCase):
    def test_ssl_cert_validates_hostname_and_runs_dry_run_before_real_request(self):
        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.execute") as execute:
                api.ssl_cert("odoo.example.com")

        basecmd = [
            "certbot",
            "certonly",
            "-n",
            "--expand",
            "--agree-tos",
            "-m=niemela.elmeri@gmail.com",
            "-d=odoo.example.com",
            "--standalone",
        ]
        validate.assert_called_once_with(hostnames=["odoo.example.com"])
        self.assertEqual(
            execute.call_args_list,
            [
                call(basecmd + ["--dry-run"]),
                call(basecmd),
            ],
        )

    def test_ssl_wildcard_runs_cloudflare_certbot_command(self):
        with patch("agentd.api.agentlib.execute") as execute:
            api.ssl_wildcard()

        execute.assert_called_once()
        command = execute.call_args.args[0]
        self.assertEqual(command[:4], ["certbot", "certonly", "--dns-cloudflare", "--dns-cloudflare-credentials"])
        self.assertIn("-d", command)
        self.assertIn("*.eniemela.fi", command)
        self.assertIn("--dns-cloudflare-propagation-seconds=120", command)

    def test_ssl_renew_reloads_nginx_and_returns_combined_output(self):
        with patch(
            "agentd.api.agentlib.execute",
            side_effect=[
                SimpleNamespace(stderr="renew stderr", stdout="renew stdout"),
                SimpleNamespace(stderr="", stdout=""),
            ],
        ) as execute:
            result = api.ssl_renew()

        self.assertEqual(result, "renew stderr\nrenew stdout")
        self.assertEqual(
            execute.call_args_list,
            [
                call(["certbot", "renew"]),
                call(["systemctl", "reload", "nginx"]),
            ],
        )


class SelfUpgradeTests(unittest.TestCase):
    def test_self_upgrade_posts_upgrade_logs_then_restart_notifications(self):
        responses = [
            SimpleNamespace(text="upgrade accepted", status_code=202),
            SimpleNamespace(text="not ready", status_code=503),
            SimpleNamespace(text="ready", status_code=200),
        ]

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.threading.Thread", ImmediateThread):
                with patch("agentd.api.time.sleep") as sleep:
                    with patch("agentd.api.upgrade", return_value="upgrade logs") as upgrade:
                        with patch("agentd.api.restart") as restart:
                            with patch(
                                "agentd.api.requests.post", side_effect=responses
                            ) as post:
                                api.self_upgrade("1a2b", "https://callback.test")

        validate.assert_called_once_with(uid="1a2b")
        self.assertEqual(sleep.call_args_list, [call(1), call(3), call(3)])
        upgrade.assert_called_once_with("1a2b")
        restart.assert_called_once_with("1a2b")
        self.assertEqual(
            post.call_args_list,
            [
                call(
                    url="https://callback.test",
                    timeout=15,
                    json={
                        "method": "upgrade",
                        "uid": "1a2b",
                        "logs": "upgrade logs",
                    },
                ),
                call(
                    url="https://callback.test",
                    timeout=15,
                    json={
                        "method": "restart",
                        "uid": "1a2b",
                    },
                ),
                call(
                    url="https://callback.test",
                    timeout=15,
                    json={
                        "method": "restart",
                        "uid": "1a2b",
                    },
                ),
            ],
        )

    def test_self_upgrade_logs_error_when_restart_callback_never_recovers(self):
        responses = [SimpleNamespace(text="not ready", status_code=503)] * 6

        with patch("agentd.api.agentlib.validate"):
            with patch("agentd.api.threading.Thread", ImmediateThread):
                with patch("agentd.api.time.sleep"):
                    with patch("agentd.api.upgrade", return_value=None):
                        with patch("agentd.api.restart"):
                            with patch("agentd.api.requests.post", side_effect=responses) as post:
                                with patch("agentd.api._logger.error") as logger_error:
                                    api.self_upgrade("1a2b", "https://callback.test")

        self.assertEqual(post.call_count, 6)
        logger_error.assert_called_once_with("Host not responding after restart.")


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

    def test_remove_uses_status_postgres_shape_and_removes_existing_resources(self):
        cursor = MagicMock()
        curstatus = {
            "instances": [{"uid": "1a2b"}],
            "postgres": {
                "databases": [{"datname": "1a2b"}],
                "users": [{"usename": "1a2b"}],
            },
        }

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.status", return_value=curstatus):
                with patch("agentd.api.sync_urls") as sync_urls:
                    with patch("agentd.api.agentlib.psql", return_value=cursor_context(cursor)):
                        with patch("agentd.api.os.path.isdir", return_value=True):
                            with patch("agentd.api.agentlib.execute") as execute:
                                api.remove("1a2b", 8069, 8072)

        validate.assert_called_once_with(uid="1a2b", http_port=8069, gevent_port=8072)
        sync_urls.assert_called_once_with(
            hostnames=[],
            http_port=8069,
            gevent_port=8072,
        )
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(
            execute.call_args_list,
            [
                call(["docker", "rm", "1a2b"]),
                call(["docker", "volume", "rm", "1a2b"]),
            ],
        )

    def test_config_validates_uid_and_saves_odoo_config(self):
        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.save_odoo_config") as save:
                api.config("1a2b", "[options]\n")

        validate.assert_called_once_with(uid="1a2b")
        save.assert_called_once_with("1a2b", "[options]\n")

    def test_reset_recreates_database_initializes_base_and_sets_admin_password(self):
        postgres_cursor = MagicMock()
        db_cursor = MagicMock()

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.agentlib.psql") as psql:
                psql.side_effect = [
                    cursor_context(postgres_cursor),
                    cursor_context(db_cursor),
                ]
                with patch("agentd.api.agentlib.execute") as execute:
                    api.reset("1a2b")

        validate.assert_called_once_with(uid="1a2b")
        self.assertEqual(psql.call_args_list, [call(), call(dbname="1a2b")])
        self.assertEqual(postgres_cursor.execute.call_count, 3)
        self.assertEqual(
            execute.call_args_list,
            [
                call(["docker", "start", "1a2b"]),
                call(
                    [
                        "docker",
                        "exec",
                        "1a2b",
                        "odoo",
                        "--init=base",
                        "--no-http",
                        "--workers=0",
                        "--stop-after-init",
                    ]
                ),
                call(["docker", "restart", "1a2b"]),
            ],
        )
        db_cursor.execute.assert_called_once()

    def test_create_configures_urls_database_container_and_admin_password(self):
        postgres_cursor = MagicMock()
        db_cursor = MagicMock()
        docker_run = ["docker", "run", "--name", "1a2b"]

        with patch("agentd.api.agentlib.validate") as validate:
            with patch("agentd.api.secrets.token_hex", return_value="secret") as token_hex:
                with patch(
                    "agentd.api.agentlib.render_odoo_config", return_value="[options]\n"
                ) as render_config:
                    with patch("agentd.api.sync_urls") as sync_urls:
                        with patch("agentd.api.agentlib.psql") as psql:
                            psql.side_effect = [
                                cursor_context(postgres_cursor),
                                cursor_context(db_cursor),
                            ]
                            with patch(
                                "agentd.api.agentlib.odoo_docker_run",
                                return_value=docker_run,
                            ) as odoo_docker_run:
                                with patch("agentd.api.time.sleep") as sleep:
                                    with patch("agentd.api.agentlib.execute") as execute:
                                        result = api.create(
                                            "1a2b",
                                            ["odoo.example.com"],
                                            8069,
                                            8072,
                                            ["custom_addons"],
                                        )

        self.assertEqual(result, "[options]\n")
        validate.assert_called_once_with(
            uid="1a2b",
            hostnames=["odoo.example.com"],
            http_port=8069,
            gevent_port=8072,
            modules=["custom_addons"],
        )
        token_hex.assert_called_once_with(32)
        render_config.assert_called_once_with("1a2b", "secret", ["custom_addons"])
        sync_urls.assert_called_once_with(["odoo.example.com"], 8069, 8072)
        self.assertEqual(psql.call_args_list, [call(), call(dbname="1a2b")])
        self.assertEqual(postgres_cursor.execute.call_count, 3)
        odoo_docker_run.assert_called_once_with("1a2b", 8069, 8072)
        sleep.assert_called_once_with(3)
        self.assertEqual(
            execute.call_args_list,
            [
                call(docker_run),
                call(
                    [
                        "docker",
                        "exec",
                        "1a2b",
                        "odoo",
                        "--init=base",
                        "--no-http",
                        "--workers=0",
                        "--stop-after-init",
                    ]
                ),
                call(["docker", "restart", "1a2b"]),
            ],
        )
        db_cursor.execute.assert_called_once()


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


if __name__ == "__main__": # pragma: no cover
    unittest.main()
