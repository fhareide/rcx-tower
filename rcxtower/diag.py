"""Log file and the diagnostics report a user can paste into a bug report.

The log is a plain text file in the settings folder. It is kept small: when it
passes MAX_BYTES it is renamed to rcxtower.log.1 (replacing the previous one).
"""
import os
import platform
import subprocess
import sys
import threading
import time
import traceback

from . import __version__
from . import nqc
from . import tower as tw
from .rcx import RCX

MAX_BYTES = 2 * 1024 * 1024
TAIL_LINES = 400

_lock = threading.Lock()
_folder = None


def init(folder):
    """Start logging to `folder`: window messages, all tower traffic, and errors nobody caught."""
    global _folder
    _folder = folder
    write("---- RCX Tower %s started (%s, Python %s, %s, backend %s) ----" % (
        __version__, platform.platform(), platform.python_version(),
        "packaged" if getattr(sys, "frozen", False) else "from source", tw.BACKEND))
    tw.trace = _trace

    def thread_hook(args):
        write("Error in thread %s:\n%s" % (
            args.thread.name if args.thread else "?",
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))))
    threading.excepthook = thread_hook

    def main_hook(kind, value, tb):
        write("Error nobody handled:\n%s" % "".join(traceback.format_exception(kind, value, tb)))
        sys.__excepthook__(kind, value, tb)
    sys.excepthook = main_hook


_last_activity = time.monotonic()


def _trace(text):
    global _last_activity
    _last_activity = time.monotonic()
    write("    " + text)


def quiet_seconds():
    """Seconds since anything last went to or came from the tower."""
    return time.monotonic() - _last_activity


def thread_stacks():
    """Where every thread is right now: shows what a job that never ends is waiting for."""
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        out.append("Thread %s:" % names.get(ident, ident))
        out += [line.rstrip() for line in traceback.format_stack(frame)]
    return "\n".join(out)


def log_path():
    return os.path.join(_folder, "rcxtower.log") if _folder else None


def write(text):
    """Append one entry to the log file. Never raises: logging must not break the program."""
    path = log_path()
    if not path:
        return
    try:
        with _lock:
            os.makedirs(_folder, exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
                os.replace(path, path + ".1")
            now = time.time()
            with open(path, "a", encoding="utf-8") as f:
                f.write("%s.%03d  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                                           int(now * 1000) % 1000, text.rstrip("\n")))
    except OSError:
        pass


def write_exception(label):
    """Call inside an except block: stores the full traceback, which the window does not show."""
    write("%s failed:\n%s" % (label, traceback.format_exc()))


def _private(text):
    """Keep the user's account name out of the report."""
    home = os.path.expanduser("~")
    return text.replace(home, "~") if home and home != "~" else text


SUSPECTS = ("bricxcc.exe", "nqc.exe", "chrome.exe", "msedge.exe", "python.exe", "pythonw.exe")


def _process_names():
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [line.split('","')[0].strip('"').lower() for line in out.splitlines() if line]


def _other_copies(names):
    """How many RCX Tower programs are running besides this one (only one can hold the tower)."""
    mine = os.path.basename(sys.executable).lower()
    count = names.count("rcx tower.exe")
    return max(0, count - (2 if mine == "rcx tower.exe" else 0))  # a packaged copy shows up as two processes


def _tail(path, lines):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return []


def report(bridge=None, live=True, extra=()):
    """Everything worth knowing for a bug report, as text. Runs on the worker thread.

    bridge is a short description when the bridge is running (the tower is then
    in use, so the live test is skipped), else None.
    """
    out = ["RCX Tower diagnostics, %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
           "Version: %s (%s)" % (__version__, "packaged" if getattr(sys, "frozen", False) else "from source"),
           "System: %s" % platform.platform(),
           "Python: %s, %s" % (platform.python_version(), platform.architecture()[0]),
           "USB backend: %s" % tw.BACKEND]
    out += list(extra)
    try:
        state = tw.tower_state()
        paths = tw.find_tower_paths()
        out.append("Tower state: %s; towers usable: %d" % (state, len(paths)))
    except Exception as e:
        state = "error"
        out.append("Tower state: could not look (%s: %s)" % (type(e).__name__, e))
    names = _process_names()
    if names is not None:
        copies = _other_copies(names)
        out.append("Other RCX Tower programs running: %d%s" % (
            copies, "  <-- only one program can use the tower" if copies else ""))
        mine = os.path.basename(sys.executable).lower()
        found = sorted(set(n for n in names if n in SUSPECTS and n != mine))
        out.append("Running programs that can use a tower: %s" % (", ".join(found) or "none"))
    out.append("NQC compiler: %s" % (nqc.find_nqc() or "not found"))
    out.append("Bridge: %s" % (bridge or "off"))

    if bridge:
        out.append("Live test: skipped, the bridge is using the tower")
    elif not live:
        out.append("Live test: skipped, a job is using the tower")
    elif state != "ready":
        out.append("Live test: skipped, no usable tower")
    else:
        out.append("Live test:")
        try:
            with tw.Tower() as t:
                out.append("  open tower: OK")
                for name, step in (
                        ("tower version", lambda: " ".join("%02X" % b for b in t.control(tw.REQ_GET_VERSION))),
                        ("set long range", lambda: (t.set_parm(tw.PARM_RANGE, tw.RANGE_LONG), "OK")[1])):
                    try:
                        out.append("  %s: %s" % (name, step() or "OK"))
                    except Exception as e:
                        out.append("  %s: FAILED (%s: %s)" % (name, type(e).__name__, e))
                rcx = RCX(t)
                for name, step in (("RCX ping", lambda: "OK" if rcx.ping() else None),
                                   ("RCX versions", lambda: str(rcx.versions())),
                                   ("RCX battery", lambda: "%.1f V" % rcx.battery_volts())):
                    try:
                        answer = step()
                    except Exception as e:
                        out.append("  %s: FAILED (%s: %s)" % (name, type(e).__name__, e))
                        break
                    if answer is None:
                        out.append("  %s: no answer (RCX off, out of sight of the tower, or flat batteries)" % name)
                        break
                    out.append("  %s: %s" % (name, answer))
        except Exception as e:
            out.append("  open tower: FAILED (%s: %s)" % (type(e).__name__, e))

    path = log_path()
    out.append("")
    out.append("Last %d lines of %s:" % (TAIL_LINES, path))
    out += ["  " + line for line in _tail(path, TAIL_LINES)] if path else ["  (no log file)"]
    return _private("\n".join(out)) + "\n"
