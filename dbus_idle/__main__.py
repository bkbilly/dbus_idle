from . import IdleMonitor
import argparse


def skim_docstring(im: type[IdleMonitor]) -> str:
    """Return the first line of the given IdleMonitor subclass."""
    doc = im.__doc__
    if doc is None:
        return "No description available."
    doclines = doc.strip().split("\n")
    if len(doclines) == 0:
        return "No description available."
    return doclines[0]


def main():
    parser = argparse.ArgumentParser(
        prog="dbus-idle",
        description="Get idle time in milliseconds from one of several sources.")
    parser.add_argument(
        "-d",
        "--debug",
        action="count",
        help="Show debug messeges (repeat for exception trace)",
        default=0,
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="List available monitors"
    )
    args = parser.parse_args()

    idle_monitor = IdleMonitor(debug=args.debug)
    if args.list:
        print("Available monitors:")
        for monitor_class in IdleMonitor.subclasses:
            print(f" - {monitor_class.__name__}: {skim_docstring(monitor_class)}")
    milliseconds = idle_monitor.get_dbus_idle()
    print(milliseconds)


if __name__ == "__main__":
    main()
