import sys
import unittest
from enum import Enum, auto
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dbus_idle import DBusIdleMonitor

try:
    from jeepney.low_level import HeaderFields, MessageType
except ModuleNotFoundError:
    class HeaderFields(Enum):
        member = auto()

    class MessageType(Enum):
        error = auto()

    class DBusAddress:
        def __init__(self, object_path, **kwargs):
            self.object_path = object_path
            self.kwargs = kwargs

    def new_method_call(*, remote_obj, method):
        return SimpleNamespace(
            remote_obj=remote_obj,
            header=SimpleNamespace(fields={HeaderFields.member: method}),
        )

    jeepney = ModuleType("jeepney")
    jeepney.DBusAddress = DBusAddress
    jeepney.new_method_call = new_method_call
    jeepney_io = ModuleType("jeepney.io")
    jeepney_blocking = ModuleType("jeepney.io.blocking")
    jeepney_blocking.open_dbus_connection = Mock()
    jeepney_low_level = ModuleType("jeepney.low_level")
    jeepney_low_level.HeaderFields = HeaderFields
    jeepney_low_level.MessageType = MessageType
    jeepney.io = jeepney_io
    jeepney_io.blocking = jeepney_blocking
    sys.modules["jeepney"] = jeepney
    sys.modules["jeepney.io"] = jeepney_io
    sys.modules["jeepney.io.blocking"] = jeepney_blocking
    sys.modules["jeepney.low_level"] = jeepney_low_level


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
    def test_first_public_query_refreshes_construction_sample(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(body=[["org.gnome.Mutter.IdleMonitor"]]),
            SimpleNamespace(body=[123]),
            SimpleNamespace(body=[456]),
        ]
        open_connection.return_value = connection

        monitor = DBusIdleMonitor()

        self.assertEqual(monitor.get_dbus_idle(), 456.0)
        self.assertEqual(connection.send_and_get_reply.call_count, 3)
        monitor.close()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_uses_freedesktop_screensaver_for_kde_x11(self, open_connection):
        connection = Mock()
        connection.send_and_get_reply.side_effect = [
            SimpleNamespace(body=[["org.freedesktop.ScreenSaver"]]),
            SimpleNamespace(body=[42]),
            SimpleNamespace(body=[43]),
        ]
        open_connection.return_value = connection
        monitor = DBusIdleMonitor(idle_threshold=60_000)

        self.assertEqual(monitor.idle_threshold, 60_000)
        self.assertEqual(
            monitor.idle_msg.header.fields[HeaderFields.member],
            "GetSessionIdleTime",
        )
        self.assertEqual(monitor.get_dbus_idle(), 43_000.0)
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
            SimpleNamespace(body=[456]),
        ]
        open_connection.return_value = connection
        monitor = DBusIdleMonitor()

        self.assertEqual(
            monitor.idle_msg.header.fields[HeaderFields.member],
            "GetIdletime",
        )
        self.assertEqual(monitor.idle_scale, 1.0)
        self.assertEqual(monitor.get_dbus_idle(), 456.0)
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
