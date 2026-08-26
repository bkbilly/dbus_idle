import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dbus_idle import DBusIdleMonitor
from jeepney.low_level import HeaderFields, MessageType


class DBusIdleMonitorTests(unittest.TestCase):
    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_closes_connection_when_service_discovery_fails(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = RuntimeError("DBus failure")
        open_connection.return_value = connection

        with self.assertRaises(RuntimeError):
            DBusIdleMonitor()

        connection.close.assert_called_once_with()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_closes_connection_when_no_idle_service_is_available(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.return_value = SimpleNamespace(
            body=[["org.freedesktop.DBus"]]
        )
        open_connection.return_value = connection

        with self.assertRaises(AttributeError):
            DBusIdleMonitor()

        connection.close.assert_called_once_with()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_closes_connection_when_idle_query_fails(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(body=[["org.gnome.Mutter.IdleMonitor"]]),
            SimpleNamespace(body=[123]),
            RuntimeError("DBus failure"),
        ]
        open_connection.return_value = connection
        monitor = DBusIdleMonitor()

        self.assertEqual(monitor.get_dbus_idle(), 123.0)

        with self.assertRaises(RuntimeError):
            monitor.get_dbus_idle()

        connection.close.assert_called_once_with()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_closes_connection_on_dbus_error_reply(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(body=[["org.freedesktop.ScreenSaver"]]),
            SimpleNamespace(
                body=["GetSessionIdleTime is not supported on this platform"],
                header=SimpleNamespace(message_type=MessageType.error),
            ),
        ]
        open_connection.return_value = connection

        with self.assertRaisesRegex(RuntimeError, "not supported"):
            DBusIdleMonitor()

        connection.close.assert_called_once_with()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_closes_supported_service_connection_once(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(body=[["org.gnome.Mutter.IdleMonitor"]]),
            SimpleNamespace(body=[123]),
        ]
        open_connection.return_value = connection

        monitor = DBusIdleMonitor()

        connection.close.assert_not_called()
        self.assertIsNotNone(monitor.idle_msg)
        monitor.close()
        monitor.close()
        connection.close.assert_called_once_with()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            monitor.get_dbus_idle()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_uses_freedesktop_screensaver_for_kde_x11(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(body=[["org.freedesktop.ScreenSaver"]]),
            SimpleNamespace(body=[42]),
        ]
        open_connection.return_value = connection
        monitor = DBusIdleMonitor(idle_threshold=60_000)

        self.assertEqual(monitor.idle_threshold, 60_000)
        self.assertEqual(
            monitor.idle_msg.header.fields[HeaderFields.member],
            "GetSessionIdleTime",
        )
        self.assertEqual(monitor.get_dbus_idle(), 42_000.0)
        monitor.close()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_prefers_gnome_idle_monitor_over_screensaver(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(
                body=[
                    [
                        "org.freedesktop.ScreenSaver",
                        "org.gnome.Mutter.IdleMonitor",
                    ]
                ]
            ),
            SimpleNamespace(body=[123]),
        ]
        open_connection.return_value = connection
        monitor = DBusIdleMonitor()

        self.assertEqual(
            monitor.idle_msg.header.fields[HeaderFields.member],
            "GetIdletime",
        )
        self.assertEqual(monitor.idle_scale, 1.0)
        self.assertEqual(monitor.get_dbus_idle(), 123.0)
        monitor.close()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_ignores_unrelated_idle_monitor_service(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.return_value = SimpleNamespace(
            body=[["com.example.IdleMonitorHelper"]]
        )
        open_connection.return_value = connection

        with self.assertRaises(AttributeError):
            DBusIdleMonitor()

        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
