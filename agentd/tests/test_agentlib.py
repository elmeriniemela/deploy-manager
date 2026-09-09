import datetime
import json
import subprocess
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, mock_open, patch

from agentd import agentlib


class RegisterTests(unittest.TestCase):
    def test_register_marks_function_as_rpc_and_forwards_arguments(self):
        def sample(a, b=None):
            return a, b

        wrapped = agentlib.register(sample)

        self.assertTrue(wrapped._rpc)
        self.assertEqual(wrapped.__name__, "sample")
        self.assertEqual(wrapped("value", b="keyword"), ("value", "keyword"))

    def test_register_does_not_log_argument_values(self):
        with patch('agentd.agentlib._logger.debug') as debug:
            agentlib.register(lambda conf: None)('db_password=secret')
        self.assertNotIn('secret', str(debug.call_args_list))


class VersionTests(unittest.TestCase):
    def test_parse_version_orders_release_candidates_before_final(self):
        self.assertLess(agentlib.parse_version("2.4rc1"), agentlib.parse_version("2.4"))
        self.assertLess(agentlib.parse_version("2.4b1"), agentlib.parse_version("2.4rc1"))
        self.assertGreater(agentlib.parse_version("2.4.1"), agentlib.parse_version("2.4-1"))

    def test_parse_version_treats_empty_versions_as_default(self):
        self.assertEqual(agentlib.parse_version(None), agentlib.parse_version("0.1"))
        self.assertEqual(agentlib.parse_version(""), agentlib.parse_version("0.1"))


class PathTests(unittest.TestCase):
    def test_timestamp_filename_round_trip(self):
        ts = datetime.datetime(2026, 7, 11, 12, 30, 45)

        fname = agentlib.ts_to_fname(ts)

        self.assertEqual(fname, "2026-07-11T12-30-45.pgc")
        self.assertEqual(agentlib.fname_to_ts(fname), ts)

    def test_dump_path_can_create_parent_directories(self):
        with patch("agentd.agentlib.os.makedirs") as makedirs:
            path = agentlib.dump_path("1a2b", "daily", "dump.pgc", makedirs=True)

        self.assertEqual(path, "/srv/secure/backups/1a2b/daily/dump.pgc")
        makedirs.assert_called_once_with(
            "/srv/secure/backups/1a2b/daily", mode=0o700, exist_ok=True
        )

    def test_save_odoo_config_creates_directory_and_writes_file(self):
        output_handle = mock_open().return_value

        with patch("agentd.agentlib.os.makedirs") as makedirs:
            with patch("builtins.open", mock_open()) as opened:
                opened.return_value = output_handle
                agentlib.save_odoo_config("1a2b", "[options]\n")

        makedirs.assert_called_once_with("/etc/odoo/1a2b", mode=0o755, exist_ok=True)
        opened.assert_called_once_with("/etc/odoo/1a2b/odoo.conf", "w")
        output_handle.write.assert_called_once_with("[options]\n")

    def test_render_odoo_config_removes_core_odoo_module_before_rendering(self):
        template = "db_user={{ uid }}\ndb_password={{ pw }}\naddons={{ modules|join(',') }}\n"
        modules = ["odoo", "custom_addons"]

        with patch("builtins.open", mock_open(read_data=template)):
            with patch("agentd.agentlib.save_odoo_config") as save:
                conf = agentlib.render_odoo_config("1a2b", "secret", modules)

        self.assertEqual(conf, "db_user=1a2b\ndb_password=secret\naddons=custom_addons\n")
        self.assertEqual(modules, ["custom_addons"])
        save.assert_called_once_with("1a2b", conf)

    def test_render_odoo_config_allows_modules_without_core_odoo_entry(self):
        template = "addons={{ modules|join(',') }}\n"
        modules = ["custom_addons"]

        with patch("builtins.open", mock_open(read_data=template)):
            with patch("agentd.agentlib.save_odoo_config") as save:
                conf = agentlib.render_odoo_config("1a2b", "secret", modules)

        self.assertEqual(conf, "addons=custom_addons\n")
        self.assertEqual(modules, ["custom_addons"])
        save.assert_called_once_with("1a2b", conf)

    def test_ensure_backups_mounted_raises_when_mount_is_missing(self):
        with patch("agentd.agentlib.backups_mounted", return_value=False):
            with self.assertRaisesRegex(AssertionError, "Backup dir not mounted"):
                agentlib.ensure_backups_mounted()


class BackupListingTests(unittest.TestCase):
    def test_backups_mounted_checks_expected_mountpoint(self):
        with patch("agentd.agentlib.os.path.ismount", return_value=True) as ismount:
            self.assertTrue(agentlib.backups_mounted())

        ismount.assert_called_once_with("/srv/secure/backups")

    def test_list_backups_returns_empty_list_when_backup_mount_is_absent(self):
        with patch("agentd.agentlib.backups_mounted", return_value=False):
            self.assertEqual(agentlib.list_backups("1a2b"), [])

    def test_list_backups_extracts_metadata_from_dump_paths(self):
        paths = [
            "/srv/secure/backups/1a2b/daily/2026-07-11T12-30-45.pgc",
            "/srv/secure/backups/1a2b/manual/2026-07-10T01-02-03.pgc",
        ]

        with patch("agentd.agentlib.backups_mounted", return_value=True):
            with patch("agentd.agentlib.glob.glob", return_value=paths) as glob:
                backups = agentlib.list_backups("1a2b")

        glob.assert_called_once_with("/srv/secure/backups/1a2b/*/*.pgc")
        self.assertEqual(
            backups,
            [
                {
                    "fname": "2026-07-11T12-30-45.pgc",
                    "timestamp": "2026-07-11 12:30:45",
                    "trigger": "daily",
                    "source": "backup-crypt:",
                },
                {
                    "fname": "2026-07-10T01-02-03.pgc",
                    "timestamp": "2026-07-10 01:02:03",
                    "trigger": "manual",
                    "source": "backup-crypt:",
                },
            ],
        )

class InventoryTests(unittest.TestCase):
    def test_list_instances_skips_invalid_container_names_and_adds_inspect_data(self):
        inspected = [
            {"Name": "/1a2b", "Id": "container-1", "Config": {"Labels": {"odoo.version": "19.0"}}, "State": {"Running": True}},
            {"Name": "/not-hex", "Id": "container-2", "Config": {"Labels": {"odoo.version": "19.0"}}},
            {"Name": "/2b3c", "Id": "container-3", "Config": {"Labels": {"odoo.version": "20.0"}}},
            {"Name": "/3c4d", "Id": "container-4", "Config": {}},
        ]
        commands = [
            SimpleNamespace(stdout="container-1\ncontainer-2\ncontainer-3\ncontainer-4\n"),
            SimpleNamespace(stdout=json.dumps(inspected)),
        ]

        with patch("agentd.agentlib.execute", side_effect=commands) as execute:
            with patch("agentd.agentlib.list_backups", return_value=[{"fname": "dump.pgc"}]):
                instances = agentlib.list_instances()

        self.assertEqual(
            execute.call_args_list,
            [
                call([
                    "docker", "container", "ls", "--all", "--quiet", "--no-trunc",
                    "--filter", "label=odoo.version=19.0",
                ]),
                call([
                    "docker", "container", "inspect", "container-1", "container-2",
                    "container-3", "container-4",
                ]),
            ],
        )
        self.assertEqual(
            instances,
            [
                {
                    "uid": "1a2b",
                    "docker": {
                        "Names": ["/1a2b"],
                        "Id": "container-1",
                        "Labels": {"odoo.version": "19.0"},
                        "inspect": inspected[0],
                    },
                    "backups": [{"fname": "dump.pgc"}],
                }
            ],
        )

    def test_list_instances_avoids_inspect_when_no_containers_exist(self):
        with patch(
            "agentd.agentlib.execute",
            return_value=SimpleNamespace(stdout=""),
        ) as execute:
            self.assertEqual(agentlib.list_instances(), [])

        execute.assert_called_once()

    def test_list_postgres_converts_cursor_rows_to_dicts(self):
        cursor = MagicMock()
        descriptions = [
            [SimpleNamespace(name="datname")],
            [SimpleNamespace(name="usename")],
        ]

        def execute(query):
            cursor.description = descriptions.pop(0)

        cursor.execute.side_effect = execute
        cursor.fetchall.side_effect = [
            [("postgres",), ("1a2b",)],
            [("odoo",)],
        ]

        class PsqlContext:
            def __enter__(self):
                return cursor

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        with patch("agentd.agentlib.psql", return_value=PsqlContext()):
            result = agentlib.list_postgres()

        self.assertEqual(
            cursor.execute.call_args_list,
            [
                call("select * from pg_catalog.pg_database"),
                call("select * from pg_catalog.pg_user"),
            ],
        )
        self.assertEqual(
            result,
            {
                "users": [{"usename": "odoo"}],
                "databases": [{"datname": "postgres"}, {"datname": "1a2b"}],
            },
        )

    def test_list_modules_collects_git_metadata(self):
        execute_results = [
            SimpleNamespace(stdout="abc123\n"),
            SimpleNamespace(stdout="2026-07-11 12:00:00 +0000\n"),
            SimpleNamespace(stdout="19.0\n"),
            SimpleNamespace(stdout="git@example.test:repo.git\n"),
        ]

        with patch("agentd.agentlib.glob.glob", return_value=["src/custom_addons/.git"]):
            with patch("agentd.agentlib.execute", side_effect=execute_results) as execute:
                modules = agentlib.list_modules()

        self.assertEqual(
            modules,
            [
                {
                    "name": "custom_addons",
                    "commit": "abc123",
                    "commit_date": "2026-07-11 12:00:00 +0000",
                    "branch": "19.0",
                    "url": "git@example.test:repo.git",
                }
            ],
        )
        self.assertEqual(
            execute.call_args_list,
            [
                call("cd src/custom_addons && git rev-parse HEAD", shell=True),
                call(
                    "cd src/custom_addons && git log -1 --format=%cd --date=iso",
                    shell=True,
                ),
                call(
                    "cd src/custom_addons && git rev-parse --abbrev-ref HEAD",
                    shell=True,
                ),
                call("cd src/custom_addons && git remote get-url origin", shell=True),
            ],
        )

    def test_list_modules_skips_repositories_with_metadata_errors(self):
        with patch("agentd.agentlib.glob.glob", return_value=["src/broken/.git"]):
            with patch("agentd.agentlib.execute", side_effect=RuntimeError("boom")):
                with patch("agentd.agentlib._logger.exception") as logger_exception:
                    modules = agentlib.list_modules()

        self.assertEqual(modules, [])
        logger_exception.assert_called_once()


class PostgresTests(unittest.TestCase):
    def test_psql_opens_logging_connection_and_closes_resources(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor

        with patch("agentd.agentlib.psycopg2.connect", return_value=connection) as connect:
            with agentlib.psql(dbname="1a2b") as returned_cursor:
                self.assertIs(returned_cursor, cursor)

        connect.assert_called_once_with(
            dbname="1a2b",
            connection_factory=agentlib.LoggingConnection,
        )
        connection.initialize.assert_called_once_with(agentlib._logger)
        connection.set_session.assert_called_once_with(autocommit=True)
        connection.cursor.assert_called_once_with()
        cursor.close.assert_called_once_with()
        connection.close.assert_called_once_with()


class CommandTests(unittest.TestCase):
    def test_odoo_docker_run_builds_expected_container_command(self):
        cmd = agentlib.odoo_docker_run("1a2b", 8069, 8072)

        self.assertEqual(cmd[:2], ["docker", "run"])
        self.assertIn("--name", cmd)
        self.assertIn("1a2b", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("127.0.0.1:8069:8069", cmd)
        self.assertIn("[::1]:8072:8072", cmd)
        self.assertEqual(cmd[-1], "ghcr.io/elmeriniemela/odoo-src:19.0")
        self.assertEqual(cmd[cmd.index('--label') + 1], 'odoo.version=19.0')
        self.assertIn('/opt/19/src:/mnt:ro', cmd)

    def test_execute_wraps_subprocess_errors(self):
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["failing", "command"],
            stderr="failure details",
        )

        with patch("agentd.agentlib.subprocess.run", side_effect=error):
            with self.assertRaises(agentlib.SubprocessError) as raised:
                agentlib.execute(["failing", "command"])

        self.assertIn("failure details", str(raised.exception))
        self.assertIn("failing command", str(raised.exception))

    def test_execute_uses_text_output_defaults(self):
        completed = subprocess.CompletedProcess(["ok"], 0, stdout="done", stderr="")

        with patch("agentd.agentlib.subprocess.run", return_value=completed) as run:
            result = agentlib.execute(["ok"])

        self.assertIs(result, completed)
        run.assert_called_once_with(
            ["ok"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            encoding="utf-8",
        )


class ValidationTests(unittest.TestCase):
    def test_uid_validation_accepts_hexadecimal_strings(self):
        self.assertTrue(agentlib.is_valid_uid("1a2b"))

    def test_uid_validation_rejects_non_hex_strings(self):
        with self.assertRaisesRegex(ValueError, "hexadecimal"):
            agentlib.is_valid_uid("not-hex")

    def test_uid_validation_rejects_non_strings(self):
        with self.assertRaisesRegex(AssertionError, "UID should be a string"):
            agentlib.is_valid_uid(123)

    def test_validate_rejects_unknown_validator_names(self):
        with self.assertRaisesRegex(ValueError, "Validator not found"):
            agentlib.validate(unknown="value")

    def test_hostname_validation_accepts_normal_domains(self):
        self.assertTrue(agentlib.is_valid_hostnames(["odoo.example.com", "example.test."]))

    def test_hostname_validation_rejects_single_label_hosts(self):
        with self.assertRaisesRegex(ValueError, "at least one dot"):
            agentlib.is_valid_hostnames(["localhost"])

    def test_hostname_validation_rejects_numeric_tlds(self):
        with self.assertRaisesRegex(ValueError, "not all-numeric"):
            agentlib.is_valid_hostnames(["example.123"])

    def test_hostname_validation_rejects_non_lists(self):
        with self.assertRaisesRegex(AssertionError, "Hostnames should be a list"):
            agentlib.is_valid_hostnames("example.test")

    def test_hostname_validation_rejects_invalid_labels(self):
        with self.assertRaisesRegex(ValueError, "Invalid characters"):
            agentlib.is_valid_hostnames(["-bad.example"])

    def test_hostname_validation_rejects_overlong_names(self):
        hostname = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 62, "example"])

        with self.assertRaisesRegex(ValueError, "longer than 253"):
            agentlib.is_valid_hostnames([hostname])

    def test_module_validation_accepts_existing_module_directories(self):
        with patch("agentd.agentlib.os.path.isdir", return_value=True) as isdir:
            self.assertTrue(agentlib.is_valid_modules(["custom_addons"]))

        isdir.assert_called_once_with("src/custom_addons")

    def test_module_validation_rejects_non_lists_and_non_strings(self):
        with self.assertRaisesRegex(AssertionError, "Modules should be a list"):
            agentlib.is_valid_modules("custom_addons")

        with self.assertRaisesRegex(AssertionError, "Module should be a string"):
            agentlib.is_valid_modules([object()])

    def test_module_validation_rejects_missing_directories(self):
        with patch("agentd.agentlib.os.path.isdir", return_value=False):
            with self.assertRaisesRegex(AssertionError, "Module directory does not exist"):
                agentlib.is_valid_modules(["missing"])

    def test_port_validation_accepts_ports_without_listeners(self):
        sock = MagicMock()
        sock.connect_ex.return_value = 111

        with patch("agentd.agentlib.socket.socket", return_value=sock):
            self.assertTrue(agentlib.is_valid_port(8069))

        sock.connect_ex.assert_called_once_with(("127.0.0.1", 8069))
        sock.close.assert_called_once_with()

    def test_port_validation_rejects_non_integer_ports_and_open_ports(self):
        with self.assertRaisesRegex(AssertionError, "Port should be an integer"):
            agentlib.is_valid_port("8069")

        sock = MagicMock()
        sock.connect_ex.return_value = 0
        with patch("agentd.agentlib.socket.socket", return_value=sock):
            with self.assertRaisesRegex(ValueError, "already in use"):
                agentlib.is_valid_port(8069)


class NginxMapTests(unittest.TestCase):
    def test_load_nginx_map_parses_mapping_file(self):
        conf = (
            "map $http_host $odoo_http_port {\n"
            "    example.test 127.0.0.1:8069;\n"
            "    another.example 127.0.0.1:8070;\n"
            "}\n"
        )

        with patch("builtins.open", mock_open(read_data=conf)) as opened:
            match, target, mapping = agentlib.load_nginx_map("http-ports.conf")

        opened.assert_called_once_with("/etc/nginx/conf.d/http-ports.conf")
        self.assertEqual(match, "$http_host")
        self.assertEqual(target, "$odoo_http_port")
        self.assertEqual(
            mapping,
            {
                "example.test": "127.0.0.1:8069",
                "another.example": "127.0.0.1:8070",
            },
        )

    def test_store_nginx_map_renders_template_to_nginx_config(self):
        template = (
            "map {{ match }} {{ target }} {\n"
            "{%- for key, value in mapping.items() %}\n"
            "    {{ key }} {{ value }};\n"
            "{%- endfor %}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            # An absolute filename selects a disposable directory while still
            # exercising the real tempfile, chmod and atomic replacement.
            path = Path(directory) / 'http-ports.conf'
            with patch("builtins.open", mock_open(read_data=template)):
                agentlib.store_nginx_map(
                    str(path), "$http_host", "$odoo_http_port",
                    {"example.test": "127.0.0.1:8069"},
                )
            self.assertEqual(path.read_text(),
                "map $http_host $odoo_http_port {\n"
                "    example.test 127.0.0.1:8069;\n}\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__": # pragma: no cover
    unittest.main()
