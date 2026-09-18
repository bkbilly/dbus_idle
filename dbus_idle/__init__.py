import time
import ctypes
import ctypes.util
import logging
from typing import Any, List, Optional, Type
import subprocess
import os
import shlex
import tempfile


logger = logging.getLogger("dbus_idle")

class IdleMonitor:
    subclasses: List[Type["IdleMonitor"]] = []

    def __init__(self, *, idle_threshold: int = 120_000, debug: bool=False) -> None:
        self.idle_threshold = idle_threshold
        self.class_used = None
        if debug:
            logger.setLevel(logging.DEBUG)

    def __init_subclass__(self) -> None:
        super().__init_subclass__()
        self.subclasses.append(self)

    @classmethod
    def get_monitor(self, **kwargs) -> "IdleMonitor":
        """
        Return the first available idle monitor.
        """
        for monitor_class in self.subclasses:
            try:
                return monitor_class(**kwargs)
            except Exception:
                logger.warning("Could not load %s", monitor_class, exc_info=True)
        raise RuntimeError("Could not find a working monitor.")

    def get_dbus_idle(self) -> Optional[float]:
        """
        Return idle time in milliseconds.
        """
        if self.class_used is None:
            for monitor_class in self.subclasses:
                try:
                    self.class_used = monitor_class()
                    logger.debug("Using: %s", monitor_class.__name__)
                    return self.class_used.get_dbus_idle()
                except Exception:
                    logger.info("Could not load %s", monitor_class.__name__, exc_info=False)
                    self.class_used = None
            logger.warning("Could not find any working monitor to get idle time.")
            return None
        else:
            try:
                return self.class_used.get_dbus_idle()
            except Exception:
                logger.warning("Can't run the working monitor anymore.", exc_info=False)
                self.class_used = None
                return None

    def is_idle(self) -> bool:
        """
        Return whether the user is idling.
        """
        idle_time = self.get_dbus_idle()
        if idle_time is None:
            return False
        return idle_time > self.idle_threshold


class DBusIdleMonitor(IdleMonitor):
    """
    Idle monitor for GNOME and KDE X11 sessions running on DBus.

    Based on
      * https://unix.stackexchange.com/a/492328
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        from jeepney.low_level import MessageType

        self.message_error_type = MessageType.error
        self.connection = open_dbus_connection(bus="SESSION")
        try:
            dbus_addr = DBusAddress(
                object_path="/org/freedesktop/DBus",
                bus_name="org.freedesktop.DBus",
                interface="org.freedesktop.DBus",
            )

            msg = new_method_call(remote_obj=dbus_addr, method="ListNames")
            reply = self.connection.send_and_get_reply(msg)
            self.idle_msg = None
            self.idle_scale = 1.0
            services = set(reply.body[0])
            gnome_service = "org.gnome.Mutter.IdleMonitor"
            kde_service = "org.freedesktop.ScreenSaver"
            if gnome_service in services:
                idle_addr = DBusAddress(
                    "/org/gnome/Mutter/IdleMonitor/Core",
                    bus_name=gnome_service,
                    interface=gnome_service,
                )
                self.idle_msg = new_method_call(
                    remote_obj=idle_addr,
                    method="GetIdletime",
                )
            elif kde_service in services:
                idle_addr = DBusAddress(
                    "/ScreenSaver",
                    bus_name=kde_service,
                    interface=kde_service,
                )
                self.idle_msg = new_method_call(
                    remote_obj=idle_addr,
                    method="GetSessionIdleTime",
                )
                self.idle_scale = 1000.0
            if self.idle_msg is None:
                raise AttributeError()
            self._read_idle()
        except Exception:
            self.close()
            raise

    def _read_idle(self) -> float:
        if self.connection is None:
            raise RuntimeError("DBus idle monitor is closed")
        idle_reply = self.connection.send_and_get_reply(self.idle_msg)
        message_type = getattr(getattr(idle_reply, "header", None), "message_type", None)
        if message_type == self.message_error_type:
            detail = idle_reply.body[0] if idle_reply.body else "DBus idle query failed"
            raise RuntimeError(detail)
        return float(idle_reply.body[0]) * self.idle_scale

    def get_dbus_idle(self) -> float:
        try:
            return self._read_idle()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        connection = getattr(self, "connection", None)
        if connection is None:
            return
        self.connection = None
        try:
            connection.close()
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()


class XprintidleIdleMonitor(IdleMonitor):
    """Idle monitor using xprintidle command."""

    def __init__(self, **kwargs) -> None:
        from shutil import which

        super().__init__(**kwargs)
        self.executable = which("xprintidle")
        if self.executable is None:
            raise AttributeError()

    def get_dbus_idle(self) -> float:
        res = subprocess.run(
            [self.executable],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        if res.returncode != 0:
            raise RuntimeError("xprintidle failed")
        stdout = res.stdout.decode("UTF-8").strip()
        if not stdout or not stdout.isdigit():
            raise RuntimeError("xprintidle output invalid")

        idle_sec = int(stdout)
        return float(idle_sec)


class X11IdleMonitor(IdleMonitor):
    """
    Idle monitor for systems running X11.

    Based on
      * http://tperl.blogspot.com/2007/09/x11-idle-time-and-focused-window-in.html
      * https://stackoverflow.com/a/55966565/7774036
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        class XScreenSaverInfo(ctypes.Structure):
            _fields_ = [
                ("window", ctypes.c_ulong),  # screen saver window
                ("state", ctypes.c_int),  # off, on, disabled
                ("kind", ctypes.c_int),  # blanked, internal, external
                ("since", ctypes.c_ulong),  # milliseconds
                ("idle", ctypes.c_ulong),  # milliseconds
                ("event_mask", ctypes.c_ulong),
            ]  # events

        self.lib_x11 = self._load_lib("X11")
        # specify required types
        self.lib_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.lib_x11.XOpenDisplay.restype = ctypes.c_void_p
        self.lib_x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.lib_x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.lib_x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.lib_x11.XCloseDisplay.restype = ctypes.c_int
        self.lib_x11.XFree.argtypes = [ctypes.c_void_p]
        self.lib_x11.XFree.restype = ctypes.c_int

        self.xss_info = None
        self.display = self.lib_x11.XOpenDisplay(None)
        if self.display is None:
            raise AttributeError()

        try:
            self.root_window = self.lib_x11.XDefaultRootWindow(self.display)

            self.lib_xss = self._load_lib("Xss")
            # specify required types
            self.lib_xss.XScreenSaverQueryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(XScreenSaverInfo),
            ]
            self.lib_xss.XScreenSaverQueryInfo.restype = ctypes.c_int
            self.lib_xss.XScreenSaverAllocInfo.argtypes = []
            self.lib_xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
            # allocate memory for idle information
            self.xss_info = self.lib_xss.XScreenSaverAllocInfo()
            if not self.xss_info:
                raise MemoryError("Could not allocate XScreenSaverInfo")

            status = self.lib_xss.XScreenSaverQueryInfo(self.display, self.root_window, self.xss_info)
            if status == 0:
                raise RuntimeError("Not Supported...")
        except Exception:
            self.close()
            raise

    def get_dbus_idle(self) -> float:
        try:
            if self.display is None or self.xss_info is None:
                raise RuntimeError("X11 idle monitor is closed")
            status = self.lib_xss.XScreenSaverQueryInfo(
                self.display,
                self.root_window,
                self.xss_info,
            )
            if status == 0:
                raise RuntimeError("XScreenSaverQueryInfo failed")
            return float(self.xss_info.contents.idle)
        except Exception:
            self.close()
            raise

    def _load_lib(self, name: str) -> Any:
        path = ctypes.util.find_library(name)
        if path is None:
            raise OSError(f"Could not find library `{name}`")
        return ctypes.cdll.LoadLibrary(path)

    def close(self) -> None:
        if getattr(self, "xss_info", None) and getattr(self, "lib_x11", None):
            try:
                self.lib_x11.XFree(self.xss_info)
            except Exception:
                pass
            finally:
                self.xss_info = None
        if getattr(self, "display", None) and getattr(self, "lib_x11", None):
            try:
                self.lib_x11.XCloseDisplay(self.display)
            except Exception:
                pass
            finally:
                self.display = None

    def __del__(self) -> None:
        self.close()


class SwayIdleMonitor(IdleMonitor):
    """Idle monitor using swayidle command for Wayland environments."""

    def __init__(self, **kwargs) -> None:
        from shutil import which

        super().__init__(**kwargs)
        self.idleproc = None
        self.state_dir = None
        self.output_file = None
        self.staging_file = None

        swayidle = which("swayidle")
        date = which("date")
        move = which("mv")
        if swayidle is None or date is None or move is None:
            raise AttributeError()

        try:
            self.state_dir = tempfile.mkdtemp(prefix="dbus-idle-")
            self.output_file = os.path.join(self.state_dir, "idle.state")
            self.staging_file = os.path.join(self.state_dir, "idle.state.next")
            with open(self.output_file, "w") as state_file:
                state_file.write("0")
        except Exception:
            self.close()
            raise

        try:
            date_format = "+%s.%N"
            command = subprocess.run(
                [date, date_format],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                if command.returncode != 0:
                    raise ValueError
                float(command.stdout.strip())
            except (AttributeError, ValueError):
                date_format = "+%s"

            output_file = shlex.quote(self.output_file)
            staging_file = shlex.quote(self.staging_file)
            date_command = f"{shlex.quote(date)} {date_format}"
            move_command = shlex.quote(move)
            timeout_command = (
                f"umask 077; {date_command} > {staging_file} && "
                f"{move_command} {staging_file} {output_file}"
            )
            resume_command = (
                f"umask 077; printf 0 > {staging_file} && "
                f"{move_command} {staging_file} {output_file}"
            )

            self.idleproc = subprocess.Popen(
                [
                    swayidle,
                    "-w",
                    "timeout",
                    "1",
                    timeout_command,
                    "resume",
                    resume_command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self.close()
            raise

    def get_dbus_idle(self) -> float:
        try:
            if self.idleproc is None:
                raise RuntimeError("swayidle monitor is closed")

            returncode = self.idleproc.poll()
            if returncode is not None:
                raise RuntimeError(f"swayidle exited with status {returncode}")

            with open(self.output_file, "r") as file:
                idle_time = float(file.read())
            if idle_time != 0:
                # swayidle records the timestamp after the one-second timeout.
                idle_time = max(0.0, time.time() - idle_time + 1)

            return idle_time * 1000
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        idleproc = getattr(self, "idleproc", None)
        self.idleproc = None
        if idleproc is not None:
            try:
                if idleproc.poll() is None:
                    idleproc.terminate()
                    try:
                        idleproc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        idleproc.kill()
                        idleproc.wait()
            except Exception:
                pass

        for path in (getattr(self, "staging_file", None), getattr(self, "output_file", None)):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        state_dir = getattr(self, "state_dir", None)
        if state_dir is not None:
            try:
                os.rmdir(state_dir)
            except FileNotFoundError:
                self.state_dir = None
            except OSError:
                pass
            else:
                self.state_dir = None

    def __del__(self) -> None:
        self.close()

class WindowsIdleMonitor(IdleMonitor):
    """
    Idle monitor for Windows.

    Based on
      * https://stackoverflow.com/q/911856
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        import win32api
        self.win32api = win32api

    def get_dbus_idle(self) -> float:
        current_tick = self.win32api.GetTickCount()
        last_tick = self.win32api.GetLastInputInfo()
        return float(current_tick - last_tick)
