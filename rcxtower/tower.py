"""The LEGO USB IR tower (VID 0694, PID 0001).

Picks the backend for this system: WinUSB on Windows, libusb everywhere else.
Set the environment variable RCXTOWER_BACKEND=libusb to force libusb on Windows.

    from rcxtower import tower
    with tower.Tower() as t:
        t.set_parm(tower.PARM_RANGE, tower.RANGE_LONG)
        t.write(tower.rcx_frame([0x10]))
        print(t.read())
"""
import os
import sys

from .towerbase import *  # noqa: F401,F403  (constants, TowerError, TowerBase, rcx_frame)
from .towerbase import TowerBase, TowerError, rcx_frame  # noqa: F401

BACKEND = os.environ.get("RCXTOWER_BACKEND", "").lower() or ("winusb" if sys.platform == "win32" else "libusb")

if BACKEND == "winusb":
    from .tower_winusb import Tower as _Backend, find_tower_paths, tower_state  # noqa: F401
else:
    from .tower_libusb import Tower as _Backend, find_tower_paths, tower_state  # noqa: F401

# Set to a function taking one line of text to see everything that goes to and from the tower
# (rcxtower.diag does, for the log file). None = no tracing.
trace = None


def _hex(data):
    return " ".join("%02X" % b for b in data)


class Tower(_Backend):
    """The backend for this system, with every call reported to `trace`."""

    def __init__(self, *args, **kw):
        try:
            super().__init__(*args, **kw)
        except Exception as e:
            if trace:
                trace("tower open FAILED: %s" % e)
            raise
        if trace:
            trace("tower open (%s, packet size %s)" % (BACKEND, getattr(self, "packet_size", "?")))

    def close(self):
        if trace:
            trace("tower close")
        super().close()

    def control(self, request, value=0, index=0, length=8):
        try:
            reply = super().control(request, value, index, length)
        except Exception as e:
            if trace:
                trace("ctl %02X value %04X FAILED: %s" % (request, value, e))
            raise
        if trace:
            trace("ctl %02X value %04X -> %s" % (request, value, _hex(reply)))
        return reply

    def write(self, data):
        if trace:
            trace("tx %d: %s" % (len(data), _hex(data)))
        try:
            return super().write(data)
        except Exception as e:
            if trace:
                trace("tx FAILED: %s" % e)
            raise

    def read_packet(self, timeout_ms=100):
        try:
            got = super().read_packet(timeout_ms)
        except Exception as e:
            if trace:
                trace("rx FAILED: %s" % e)
            raise
        if got and trace:
            trace("rx %d: %s" % (len(got), _hex(got)))
        return got
