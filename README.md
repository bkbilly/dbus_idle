# dbus-idle

[![pypi](https://img.shields.io/pypi/v/dbus-idle.svg)](https://pypi.python.org/pypi/dbus-idle)
![python version](https://img.shields.io/pypi/pyversions/dbus-idle.svg)
![license](https://img.shields.io/pypi/l/dbus-idle.svg)

Python library to detect user idle time in milliseconds (and from that, inactivity) on Linux, Windows, and macOS.


## Requirements

* Python 3.7 or later
* One of the following:
  * D-Bus with `org.freedesktop.DBus` interface
  * `xprintidle` command
  * libX11 with `XScreenSaverInfo`
  * `swayidle` command
  * Windows
  * macOS


## Installation

Install using:
```
sudo apt install meson libdbus-glib-1-dev patchelf
pip install dbus-idle
```

On non-Linux systems,
```
pip install dbus-idle
```

## Usage

You can use this module from the command line
```bash
dbus-idle
```
or access the current idle time from within your python program
```python
from dbus_idle import IdleMonitor

milliseconds = IdleMonitor().get_dbus_idle()
```

`IdleMonitor.is_idle()` uses a 120-second threshold by default. Both
`idle_threshold` and `get_dbus_idle()` use milliseconds:

```python
monitor = IdleMonitor(idle_threshold=120_000)
```

## Contribution
This is based on the work by [Alexander Frenzel](https://github.com/escaped/idle_time)
