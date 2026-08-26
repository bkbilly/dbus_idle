import subprocess
import unittest
from unittest.mock import Mock, patch

from dbus_idle import XprintidleIdleMonitor


class XprintidleMonitorTests(unittest.TestCase):
    @patch("shutil.which", return_value=None)
    @patch("dbus_idle.subprocess.run")
    def test_missing_executable_does_not_spawn_which(self, run, which):
        with self.assertRaises(AttributeError):
            XprintidleIdleMonitor()

        which.assert_called_once_with("xprintidle")
        run.assert_not_called()

    @patch("dbus_idle.subprocess.run")
    @patch("shutil.which", return_value="/custom/bin/xprintidle")
    def test_runs_the_executable_found_during_discovery(self, which, run):
        run.return_value = Mock(returncode=0, stdout=b"123\n")
        monitor = XprintidleIdleMonitor()

        self.assertEqual(monitor.get_dbus_idle(), 123.0)
        run.assert_called_once_with(
            ["/custom/bin/xprintidle"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        which.assert_called_once_with("xprintidle")


if __name__ == "__main__":
    unittest.main()
