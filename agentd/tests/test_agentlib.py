import datetime
import subprocess
import unittest
from unittest.mock import call, mock_open, patch

from agentd import agentlib


class RegisterTests(unittest.TestCase):
    def test_register_marks_function_as_rpc_and_forwards_arguments(self):
        def sample(a, b=None):
            return a, b

        wrapped = agentlib.register(sample)

        self.assertTrue(wrapped._rpc)
        self.assertEqual(wrapped.__name__, "sample")
        self.assertEqual(wrapped("value", b="keyword"), ("value", "keyword"))


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

        self.assertEqual(path, "/root/backups/1a2b/daily/dump.pgc")
        makedirs.assert_called_once_with(
            "/root/backups/1a2b/daily", mode=0o700, exist_ok=True
        )


class BackupListingTests(unittest.TestCase):
    def test_list_backups_returns_empty_list_when_backup_mount_is_absent(self):
        with patch("agentd.agentlib.backups_mounted", return_value=False):
            self.assertEqual(agentlib.list_backups("1a2b"), [])

    def test_list_backups_extracts_metadata_from_dump_paths(self):
        paths = [
            "/root/backups/1a2b/daily/2026-07-11T12-30-45.pgc",
            "/root/backups/1a2b/manual/2026-07-10T01-02-03.pgc",
        ]

        with patch("agentd.agentlib.backups_mounted", return_value=True):
            with patch("agentd.agentlib.glob.glob", return_value=paths) as glob:
                backups = agentlib.list_backups("1a2b")

        glob.assert_called_once_with("/root/backups/1a2b/*/*.pgc")
        self.assertEqual(
            backups,
            [
                {
                    "fname": "2026-07-11T12-30-45.pgc",
                    "timestamp": "2026-07-11 12:30:45",
                    "trigger": "daily",
                    "source": "awsbucket:odoobackup1",
                },
                {
                    "fname": "2026-07-10T01-02-03.pgc",
                    "timestamp": "2026-07-10 01:02:03",
                    "trigger": "manual",
                    "source": "awsbucket:odoobackup1",
                },
            ],
        )


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
        template_handle = mock_open(read_data=template).return_value
        output_handle = mock_open().return_value

        with patch("builtins.open") as opened:
            opened.side_effect = [template_handle, output_handle]
            agentlib.store_nginx_map(
                "http-ports.conf",
                "$http_host",
                "$odoo_http_port",
                {"example.test": "127.0.0.1:8069"},
            )

        self.assertEqual(
            opened.call_args_list,
            [
                call("templates/nginxmap.conf"),
                call("/etc/nginx/conf.d/http-ports.conf", "w"),
            ],
        )
        output_handle.write.assert_called_once_with(
            "map $http_host $odoo_http_port {\n"
            "    example.test 127.0.0.1:8069;\n"
            "}\n"
        )


if __name__ == "__main__":
    unittest.main()
