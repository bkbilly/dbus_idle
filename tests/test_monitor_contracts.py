import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from dbus_idle import IdleMonitor


class MonitorContractTests(unittest.TestCase):
    def test_default_idle_threshold_is_120_seconds_in_milliseconds(self):
        monitor = IdleMonitor()
        monitor.get_dbus_idle = Mock(return_value=119_999)
        self.assertFalse(monitor.is_idle())
        monitor.get_dbus_idle.return_value = 120_001
        self.assertTrue(monitor.is_idle())

    def test_import_does_not_configure_root_logger(self):
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import logging; before=len(logging.getLogger().handlers); "
                    "import dbus_idle; after=len(logging.getLogger().handlers); "
                    "print(before, after)"
                ),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "0 0")

    def test_missing_backend_warning_has_no_fake_traceback(self):
        monitor = IdleMonitor()
        monitor.subclasses = []

        with self.assertLogs("dbus_idle", level="WARNING") as logs:
            self.assertIsNone(monitor.get_dbus_idle())

        self.assertEqual(
            logs.output,
            ["WARNING:dbus_idle:Could not find any working monitor to get idle time."],
        )

    def test_cli_help_uses_milliseconds(self):
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from dbus_idle.__main__ import main; main()",
                "--help",
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Get idle time in milliseconds", result.stdout)
        self.assertNotIn("Get idle time in seconds", result.stdout)


if __name__ == "__main__":
    unittest.main()
