import ctypes
import unittest
from unittest.mock import Mock, patch

from dbus_idle import X11IdleMonitor


def x11_libraries(*, query_status=1, info=None):
    lib_x11 = Mock()
    lib_x11.XOpenDisplay.return_value = 1
    lib_x11.XDefaultRootWindow.return_value = 2

    lib_xss = Mock()
    lib_xss.XScreenSaverAllocInfo.return_value = info
    lib_xss.XScreenSaverQueryInfo.return_value = query_status
    return lib_x11, lib_xss


class X11IdleMonitorTests(unittest.TestCase):
    @patch.object(X11IdleMonitor, "_load_lib")
    def test_frees_info_when_initial_query_fails(self, load_lib):
        info = object()
        lib_x11, lib_xss = x11_libraries(query_status=0, info=info)
        load_lib.side_effect = [lib_x11, lib_xss]

        with self.assertRaises(RuntimeError):
            X11IdleMonitor()

        lib_x11.XFree.assert_called_once_with(info)
        lib_x11.XCloseDisplay.assert_called_once_with(1)

    @patch.object(X11IdleMonitor, "_load_lib")
    def test_frees_info_and_display_once_when_destroyed(self, load_lib):
        info = object()
        lib_x11, lib_xss = x11_libraries(info=info)
        load_lib.side_effect = [lib_x11, lib_xss]
        monitor = X11IdleMonitor()

        monitor.close()
        monitor.close()

        lib_x11.XFree.assert_called_once_with(info)
        lib_x11.XCloseDisplay.assert_called_once_with(1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            monitor.get_dbus_idle()

    @patch.object(X11IdleMonitor, "_load_lib")
    def test_closes_resources_when_later_query_fails(self, load_lib):
        info = object()
        lib_x11, lib_xss = x11_libraries(info=info)
        load_lib.side_effect = [lib_x11, lib_xss]
        monitor = X11IdleMonitor()
        lib_xss.XScreenSaverQueryInfo.return_value = 0

        with self.assertRaises(RuntimeError):
            monitor.get_dbus_idle()

        lib_x11.XFree.assert_called_once_with(info)
        lib_x11.XCloseDisplay.assert_called_once_with(1)

    @patch.object(X11IdleMonitor, "_load_lib")
    def test_closes_resources_when_later_query_raises(self, load_lib):
        info = object()
        lib_x11, lib_xss = x11_libraries(info=info)
        load_lib.side_effect = [lib_x11, lib_xss]
        monitor = X11IdleMonitor()
        lib_xss.XScreenSaverQueryInfo.side_effect = RuntimeError("query crashed")

        with self.assertRaisesRegex(RuntimeError, "query crashed"):
            monitor.get_dbus_idle()

        lib_x11.XFree.assert_called_once_with(info)
        lib_x11.XCloseDisplay.assert_called_once_with(1)

    @patch.object(X11IdleMonitor, "_load_lib")
    def test_uses_xlib_ulong_for_window_and_drawable(self, load_lib):
        info = object()
        lib_x11, lib_xss = x11_libraries(info=info)
        load_lib.side_effect = [lib_x11, lib_xss]
        monitor = X11IdleMonitor()

        self.assertIs(lib_x11.XDefaultRootWindow.restype, ctypes.c_ulong)
        self.assertIs(lib_xss.XScreenSaverQueryInfo.argtypes[1], ctypes.c_ulong)
        self.assertEqual(lib_xss.XScreenSaverAllocInfo.argtypes, [])
        monitor.close()

    @patch.object(X11IdleMonitor, "_load_lib")
    def test_rejects_failed_info_allocation_before_query(self, load_lib):
        lib_x11, lib_xss = x11_libraries(info=None)
        load_lib.side_effect = [lib_x11, lib_xss]

        with self.assertRaises(MemoryError):
            X11IdleMonitor()

        lib_xss.XScreenSaverQueryInfo.assert_not_called()
        lib_x11.XFree.assert_not_called()
        lib_x11.XCloseDisplay.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
