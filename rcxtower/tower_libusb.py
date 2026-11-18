"""LEGO USB tower through libusb (macOS and Linux; also usable on Windows for testing).

Needs the `pyusb` package and a libusb library. `pip install pyusb libusb-package`
provides both; on macOS `brew install libusb` works for the library as well.

macOS needs no driver: no system driver claims the tower, so libusb can open it.
Linux has a kernel driver (legousbtower) that this code detaches while it runs,
and the user needs permission on the device (a udev rule, or root).
"""
import os
import subprocess
import sys

from .towerbase import EP_IN, EP_OUT, PRODUCT_ID, VENDOR_ID, TowerBase, TowerError

LINUX = sys.platform.startswith("linux")
# Lets every user open the tower (by default only root may). One file, read by udev.
UDEV_PATH = "/etc/udev/rules.d/60-lego-usb-tower.rules"
UDEV_RULE = ('# LEGO Mindstorms USB IR tower: usable without root (written by RCX Tower)\n'
             'SUBSYSTEM=="usb", ATTRS{idVendor}=="%04x", ATTRS{idProduct}=="%04x", MODE="0666", TAG+="uaccess"\n'
             % (VENDOR_ID, PRODUCT_ID))

try:
    import usb.core
    import usb.util
    _IMPORT_ERROR = None
except ImportError as e:  # pyusb not installed
    usb = None
    _IMPORT_ERROR = e


def _backend():
    """A libusb backend, preferring the copy shipped by the libusb-package wheel."""
    try:
        import libusb_package
        return libusb_package.get_libusb1_backend()
    except Exception:
        pass
    import usb.backend.libusb1
    return usb.backend.libusb1.get_backend()


def library_problem():
    """None if pyusb and libusb are usable, otherwise a sentence saying what is missing."""
    if usb is None:
        return "the Python package 'pyusb' is not installed"
    try:
        if _backend() is None:
            return "no libusb library was found"
    except Exception as e:
        return "libusb could not be loaded (%s)" % e
    return None


def _devices():
    if library_problem():
        return []
    try:
        return list(usb.core.find(find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID, backend=_backend()))
    except usb.core.USBError:
        return []


def _name(dev):
    return "usb:%s:%s" % (dev.bus, dev.address)


def find_tower_paths():
    """Names of the plugged-in towers, e.g. 'usb:1:5'."""
    return [_name(d) for d in _devices()]


def _node(dev):
    return "/dev/bus/usb/%03d/%03d" % (dev.bus, dev.address)


def _allowed(dev):
    """Linux: may this user open the tower? (Checked on the device file, without opening it.)"""
    if not LINUX:
        return True
    node = _node(dev)
    return not os.path.exists(node) or os.access(node, os.R_OK | os.W_OK)


def tower_state():
    """'ready' (plugged in and reachable), 'nolib' (pyusb/libusb missing), 'noperm' (Linux:
    plugged in, but this user may not open it; see install_udev_rule) or 'absent'."""
    if library_problem():
        return "nolib"
    devices = _devices()
    if not devices:
        return "absent"
    return "ready" if any(_allowed(d) for d in devices) else "noperm"


def udev_rule_installed():
    try:
        with open(UDEV_PATH) as f:
            return f.read() == UDEV_RULE
    except OSError:
        return False


def udev_commands():
    """Shell commands (run as root) that install the rule and apply it to a tower plugged in now."""
    return ["printf '%%s' '%s' > %s" % (UDEV_RULE.replace("'", "'\\''"), UDEV_PATH),
            "udevadm control --reload-rules",
            "udevadm trigger --subsystem-match=usb --attr-match=idVendor=%04x" % VENDOR_ID]


def install_udev_rule():
    """Install the udev rule: directly as root, else through pkexec (the desktop's password
    prompt). Returns None when done, else a sentence saying what went wrong."""
    script = " && ".join(udev_commands())
    cmd = ["sh", "-c", script] if os.geteuid() == 0 else ["pkexec", "sh", "-c", script]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return "pkexec is not available. In a terminal run:  sudo %s install-driver" % (
            sys.argv[0] if getattr(sys, "frozen", False) else "python3 -m rcxtower")
    except subprocess.TimeoutExpired:
        return "no answer from the password prompt"
    if r.returncode != 0:
        return "the password prompt was cancelled or failed (%s)" % ((r.stderr or "").strip() or r.returncode)
    return None


def _is_timeout(err):
    if type(err).__name__ == "USBTimeoutError":
        return True
    return getattr(err, "errno", None) in (60, 110, 10060) or "timed out" in str(err).lower() \
        or "timeout" in str(err).lower()


class Tower(TowerBase):
    def __init__(self, path=None):
        problem = library_problem()
        if problem:
            raise TowerError("Cannot use the USB tower: %s. Run: pip install pyusb libusb-package" % problem)
        devices = _devices()
        if path is not None:
            devices = [d for d in devices if _name(d) == path]
        if not devices:
            raise TowerError("No LEGO USB Tower found. Is it plugged in?")
        self._dev = dev = devices[0]
        self.path = _name(dev)
        self._claimed = False
        try:
            try:
                if dev.is_kernel_driver_active(0):   # Linux: the legousbtower module
                    dev.detach_kernel_driver(0)
            except (NotImplementedError, usb.core.USBError):
                pass                                 # not supported or not needed on this system
            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass                                 # already configured by the system
            usb.util.claim_interface(dev, 0)
            self._claimed = True
        except usb.core.USBError as e:
            self.close()
            if LINUX and getattr(e, "errno", None) == 13:
                raise TowerError("No permission to use the tower. Click Allow USB access on the Setup tab, "
                                 "or run: sudo rcx-tower install-driver")
            raise TowerError("Cannot open tower (in use by another program, or no permission?): %s" % e)

    def close(self):
        dev = getattr(self, "_dev", None)
        if dev is None:
            return
        try:
            if self._claimed:
                usb.util.release_interface(dev, 0)
            usb.util.dispose_resources(dev)
        except usb.core.USBError:
            pass
        self._claimed = False
        self._dev = None

    def control(self, request, value=0, index=0, length=8):
        """Vendor IN request to the device; returns the reply bytes."""
        try:
            return bytes(self._dev.ctrl_transfer(0xC0, request, value, index, length, timeout=1000))
        except usb.core.USBError as e:
            raise TowerError("control request 0x%02X failed: %s" % (request, e))

    def write(self, data):
        data = bytes(data)
        try:
            # generous timeout: the tower accepts bytes only as fast as it can send them by IR
            return self._dev.write(EP_OUT, data, timeout=2000 + len(data) * 20)
        except usb.core.USBError as e:
            raise TowerError("write failed: %s" % e)

    def read_packet(self, timeout_ms=100):
        """One USB packet from the tower, or b'' if nothing arrived in time."""
        try:
            return bytes(self._dev.read(EP_IN, self.packet_size, timeout=max(1, int(timeout_ms))))
        except usb.core.USBError as e:
            if _is_timeout(e):
                return b""
            raise TowerError("read failed: %s" % e)
