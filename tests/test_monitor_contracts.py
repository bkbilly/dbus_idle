import logging
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dbus_idle import IdleMonitor
from dbus_idle import __main__ as dbus_idle_main


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
                    "before_level=logging.getLogger().level; import dbus_idle; "
                    "after=len(logging.getLogger().handlers); "
                    "after_level=logging.getLogger().level; "
                    "print((before, before_level) == (after, after_level))"
                ),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "True")

    def test_library_debug_flag_emits_without_application_logging(self):
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from dbus_idle import IdleMonitor, logger; "
                    "IdleMonitor(debug=True); logger.debug('debug-visible')"
                ),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("DEBUG:dbus_idle:debug-visible", result.stderr)

    def test_library_debug_does_not_duplicate_after_application_logging(self):
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import logging; from dbus_idle import IdleMonitor, logger; "
                    "IdleMonitor(debug=True); logging.basicConfig(level=logging.DEBUG); "
                    "logger.debug('debug-once')"
                ),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stderr.count("debug-once"), 1)

    @patch("dbus_idle.logging.basicConfig")
    @patch.object(dbus_idle_main.IdleMonitor, "get_dbus_idle", return_value=0)
    def test_cli_debug_flag_configures_debug_logging(self, _get_idle, basic_config):
        with patch.object(sys, "argv", ["dbus-idle", "--debug"]):
            dbus_idle_main.main()

        basic_config.assert_called_once_with(level=logging.DEBUG)

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
