import datetime
import unittest
from unittest.mock import call, patch

from agentd import backup


REAL_DATE = datetime.date


def fake_today(year, month, day):
    class FakeDate(REAL_DATE):
        @classmethod
        def today(cls):
            return cls(year, month, day)

    return FakeDate


class ScheduledBackupTests(unittest.TestCase):
    def test_create_scheduled_backups_selects_trigger_from_current_date(self):
        cases = [
            ((2026, 7, 1), "quarterly"),
            ((2026, 8, 1), "monthly"),
            ((2026, 7, 13), "weekly"),
            ((2026, 7, 14), "daily"),
        ]

        for date_args, expected_trigger in cases:
            with self.subTest(date=date_args):
                with patch("agentd.backup.datetime.date", fake_today(*date_args)):
                    with patch(
                        "agentd.backup.agentlib.list_instances",
                        return_value=[{"uid": "1a2b"}],
                    ):
                        with patch("agentd.backup.api.backup") as api_backup:
                            with patch("agentd.backup.glob.glob", return_value=[]):
                                backup.create_scheduled_backups()

                api_backup.assert_called_once_with("1a2b", trigger=expected_trigger)

    def test_create_scheduled_backups_removes_all_but_three_latest_dumps(self):
        paths = [
            "/root/backups/1a2b/daily/2026-07-11T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-10T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-09T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-08T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-07T00-00-00.pgc",
        ]

        with patch("agentd.backup.datetime.date", fake_today(2026, 7, 14)):
            with patch(
                "agentd.backup.agentlib.list_instances",
                return_value=[{"uid": "1a2b"}],
            ):
                with patch("agentd.backup.api.backup"):
                    with patch("agentd.backup.glob.glob", return_value=list(reversed(paths))):
                        with patch("agentd.backup.os.remove") as remove:
                            backup.create_scheduled_backups()

        self.assertEqual(
            remove.call_args_list,
            [
                call("/root/backups/1a2b/daily/2026-07-08T00-00-00.pgc"),
                call("/root/backups/1a2b/daily/2026-07-07T00-00-00.pgc"),
            ],
        )

    def test_dry_run_does_not_create_or_remove_backups(self):
        paths = [
            "/root/backups/1a2b/daily/2026-07-11T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-10T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-09T00-00-00.pgc",
            "/root/backups/1a2b/daily/2026-07-08T00-00-00.pgc",
        ]

        with patch("agentd.backup.datetime.date", fake_today(2026, 7, 14)):
            with patch(
                "agentd.backup.agentlib.list_instances",
                return_value=[{"uid": "1a2b"}],
            ):
                with patch("agentd.backup.api.backup") as api_backup:
                    with patch("agentd.backup.glob.glob", return_value=paths):
                        with patch("agentd.backup.os.remove") as remove:
                            backup.create_scheduled_backups(dryrun=True)

        api_backup.assert_not_called()
        remove.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
