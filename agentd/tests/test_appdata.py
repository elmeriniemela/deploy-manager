import subprocess
import unittest
from pathlib import Path


class AppdataTests(unittest.TestCase):
    """Exercise fail-closed checks without root, real mounts or disk writes."""

    def check(self, override='', command='check_appdata'):
        script = '''
set -euo pipefail
source ./appdata.sh
appdata_device() { echo /dev/test-volume; }
cryptsetup() { echo 'device: /dev/test-volume'; }
readlink() { echo "${@: -1}"; }
mountpoint() { return 0; }
findmnt() {
    case "$2" in
        MAJ:MIN) echo 253:0 ;;
        FSTYPE) echo ext4 ;;
        FSROOT) echo / ;;
    esac
}
lsblk() { echo 253:0; }
stat() { echo 100:200; }
swapon() { :; }
mount() { echo unexpected-mount; exit 99; }
'''
        return subprocess.run(
            ['bash', '-c', script + override + '\n' + command],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True,
        )

    def test_accepts_verified_mounts_and_repeated_mount_request(self):
        for command in ('check_appdata', 'mount_appdata'):
            result = self.check(command=command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('unexpected-mount', result.stdout)

    def test_rejects_missing_or_wrong_mounts_and_swap(self):
        cases = [
            ('cryptsetup() { echo "device: /dev/other"; }', 'wrong device'),
            ('mountpoint() { return 1; }', '/srv/secure is not mounted'),
            ('lsblk() { echo 8:1; }', 'not backed by appdata'),
            ('mountpoint() { [[ "$2" != /var/lib/docker ]]; }', '/var/lib/docker is not mounted'),
            ('stat() { echo "$3"; }', 'not bound to'),
            ('stat() { return 1; }', 'Cannot inspect'),
            ('readlink() { return 1; }', 'Cannot resolve'),
            ('swapon() { echo /swapfile; }', 'Disable swap'),
        ]
        for override, message in cases:
            with self.subTest(message=message):
                result = self.check(override)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
