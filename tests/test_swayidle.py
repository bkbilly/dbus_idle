import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from dbus_idle import SwayIdleMonitor


class SwayIdleMonitorTests(unittest.TestCase):
    def setUp(self):
        self.process = Mock()
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        self.which = patch(
            "shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}",
        )
        self.run = patch(
            "dbus_idle.subprocess.run",
            return_value=Mock(stdout="123.456\n", returncode=0),
        )
        self.popen = patch("dbus_idle.subprocess.Popen", return_value=self.process)
        self.which.start()
        self.run_mock = self.run.start()
        self.popen_mock = self.popen.start()
        self.addCleanup(self.which.stop)
        self.addCleanup(self.run.stop)
        self.addCleanup(self.popen.stop)

    def make_monitor(self):
        monitor = SwayIdleMonitor()
        self.addCleanup(monitor.close)
        return monitor

    def test_discovers_swayidle_without_running_it(self):
        self.make_monitor()

        self.run_mock.assert_called_once_with(
            ["/usr/bin/date", "+%s.%N"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        command = self.popen_mock.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/swayidle")

    def test_each_monitor_has_a_private_state_file(self):
        first = self.make_monitor()
        second = self.make_monitor()

        self.assertNotEqual(first.output_file, second.output_file)
        self.assertTrue(os.path.exists(first.output_file))
        self.assertTrue(os.path.exists(second.output_file))

    def test_commands_replace_state_atomically(self):
        monitor = self.make_monitor()
        command = self.popen_mock.call_args.args[0]

        move = f"/usr/bin/mv {monitor.staging_file} {monitor.output_file}"
        self.assertIn(move, command[4])
        self.assertIn(move, command[6])
        self.assertTrue(command[4].startswith("umask 077;"))
        self.assertTrue(command[6].startswith("umask 077;"))

    def test_reports_elapsed_idle_time_in_milliseconds(self):
        monitor = self.make_monitor()
        with open(monitor.output_file, "w") as state_file:
            state_file.write("100.25")

        with patch("dbus_idle.time.time", return_value=102.0):
            self.assertEqual(monitor.get_dbus_idle(), 2750.0)

    def test_uses_second_precision_when_nanoseconds_are_unavailable(self):
        self.run_mock.return_value.stdout = "123.%N\n"

        self.make_monitor()

        command = self.popen_mock.call_args.args[0]
        self.assertIn("/usr/bin/date +%s >", command[4])

    def test_close_stops_process_and_removes_state(self):
        monitor = self.make_monitor()
        output_file = monitor.output_file
        staging_file = monitor.staging_file
        with open(staging_file, "w") as state_file:
            state_file.write("pending")

        monitor.close()
        monitor.close()

        self.process.terminate.assert_called_once_with()
        self.process.wait.assert_called_once_with(timeout=1)
        self.assertFalse(os.path.exists(output_file))
        self.assertFalse(os.path.exists(staging_file))

    def test_close_kills_a_process_that_ignores_terminate(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired("swayidle", 1), 0]
        monitor = self.make_monitor()

        monitor.close()

        self.process.kill.assert_called_once_with()
        self.assertEqual(self.process.wait.call_count, 2)

    def test_exited_process_is_rejected_and_cleaned_up(self):
        monitor = self.make_monitor()
        output_file = monitor.output_file
        self.process.poll.return_value = 7

        with self.assertRaisesRegex(RuntimeError, "status 7"):
            monitor.get_dbus_idle()

        self.assertFalse(os.path.exists(output_file))

    def test_invalid_state_stops_process_and_removes_state(self):
        monitor = self.make_monitor()
        output_file = monitor.output_file
        with open(output_file, "w") as state_file:
            state_file.write("not-a-timestamp")

        with self.assertRaises(ValueError):
            monitor.get_dbus_idle()

        self.process.terminate.assert_called_once_with()
        self.assertFalse(os.path.exists(output_file))

    def test_failed_start_removes_state_file(self):
        state_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
        state_path = state_file.name
        self.popen_mock.side_effect = OSError("cannot start")

        with patch("dbus_idle.tempfile.NamedTemporaryFile", return_value=state_file):
            with self.assertRaisesRegex(OSError, "cannot start"):
                SwayIdleMonitor()

        self.assertFalse(os.path.exists(state_path))

    def test_failed_date_probe_removes_state_file(self):
        state_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
        state_path = state_file.name
        self.run_mock.side_effect = OSError("date failed")

        with patch("dbus_idle.tempfile.NamedTemporaryFile", return_value=state_file):
            with self.assertRaisesRegex(OSError, "date failed"):
                SwayIdleMonitor()

        self.assertFalse(os.path.exists(state_path))


if __name__ == "__main__":
    unittest.main()
