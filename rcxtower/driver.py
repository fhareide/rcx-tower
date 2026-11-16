"""Bind Windows' own WinUSB driver to the LEGO USB tower. Replaces the Zadig step.

Windows ships WinUSB (winusb.sys with winusb.inf, signed by Microsoft). It is
only chosen automatically for devices that ask for it, which the 1999 tower does
not. This module does what Device Manager's "Update driver > Let me pick >
Universal Serial Bus devices > WinUsb Device" does: it selects that in-box
driver for the tower and installs it. Nothing is downloaded and no certificate
is added. It needs admin rights (one Windows permission prompt).

WinUSB also needs a "device interface GUID" so programs can find the device;
the in-box INF does not set one for a generic device, so it is written to the
tower's Device Parameters registry key before the driver starts.
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import uuid

HARDWARE_ID = "VID_0694&PID_0001"
INTERFACE_GUID = "{6C1E5B0A-3F2D-4E7B-9A51-52435854574F}"  # RCX Tower's own
USBDEVICE_CLASS = "{88BAE032-5A81-49F0-BC3D-A4FF138216D6}"

DIGCF_PRESENT, DIGCF_ALLCLASSES = 0x2, 0x4
SPDIT_CLASSDRIVER = 1
DI_ENUMSINGLEINF = 0x00010000
DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x00000800
SPDRP_CLASSGUID, SPDRP_SERVICE = 0x08, 0x04
DICS_FLAG_GLOBAL, DIREG_DEV = 1, 1
KEY_SET_VALUE = 0x0002
REG_MULTI_SZ = 7
_INVALID = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        u = uuid.UUID(text)
        g = cls()
        g.a, g.b, g.c = u.fields[0], u.fields[1], u.fields[2]
        g.d[:] = u.bytes[8:]
        return g


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID), ("DevInst", wt.DWORD), ("Reserved", ctypes.c_void_p)]


class SP_DEVINSTALL_PARAMS_W(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("Flags", wt.DWORD), ("FlagsEx", wt.DWORD), ("hwndParent", wt.HWND),
                ("InstallMsgHandler", ctypes.c_void_p), ("InstallMsgHandlerContext", ctypes.c_void_p),
                ("FileQueue", ctypes.c_void_p), ("ClassInstallReserved", ctypes.c_void_p),
                ("Reserved", wt.DWORD), ("DriverPath", wt.WCHAR * 260)]


class SP_DRVINFO_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("DriverType", wt.DWORD), ("Reserved", ctypes.c_void_p),
                ("Description", wt.WCHAR * 256), ("MfgName", wt.WCHAR * 256), ("ProviderName", wt.WCHAR * 256),
                ("DriverDate", wt.FILETIME), ("DriverVersion", ctypes.c_ulonglong)]


_sa = ctypes.WinDLL("setupapi", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_P = ctypes.POINTER
_sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_sa.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
_sa.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wt.DWORD, _P(SP_DEVINFO_DATA)]
_sa.SetupDiGetDeviceInstanceIdW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), ctypes.c_wchar_p, wt.DWORD, _P(wt.DWORD)]
_sa.SetupDiGetDeviceRegistryPropertyW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), wt.DWORD, _P(wt.DWORD),
                                                  ctypes.c_void_p, wt.DWORD, _P(wt.DWORD)]
_sa.SetupDiSetDeviceRegistryPropertyW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), wt.DWORD, ctypes.c_void_p, wt.DWORD]
_sa.SetupDiGetDeviceInstallParamsW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), _P(SP_DEVINSTALL_PARAMS_W)]
_sa.SetupDiSetDeviceInstallParamsW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), _P(SP_DEVINSTALL_PARAMS_W)]
_sa.SetupDiBuildDriverInfoList.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), wt.DWORD]
_sa.SetupDiEnumDriverInfoW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), wt.DWORD, wt.DWORD, _P(SP_DRVINFO_DATA_W)]
_sa.SetupDiSetSelectedDriverW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), _P(SP_DRVINFO_DATA_W)]
_sa.SetupDiDestroyDriverInfoList.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), wt.DWORD]
_sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
_sa.SetupDiCreateDevRegKeyW.restype = ctypes.c_void_p
_sa.SetupDiCreateDevRegKeyW.argtypes = [ctypes.c_void_p, _P(SP_DEVINFO_DATA), wt.DWORD, wt.DWORD, wt.DWORD,
                                        ctypes.c_void_p, wt.LPCWSTR]
_adv.RegSetValueExW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD]
_adv.RegCloseKey.argtypes = [ctypes.c_void_p]


class DriverError(Exception):
    pass


def _err(what):
    return DriverError("%s: %s" % (what, ctypes.WinError(ctypes.get_last_error())))


def _find_tower(devs):
    """SP_DEVINFO_DATA and instance id of the plugged-in tower, or (None, None)."""
    i = 0
    while True:
        dev = SP_DEVINFO_DATA()
        dev.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        if not _sa.SetupDiEnumDeviceInfo(devs, i, ctypes.byref(dev)):
            return None, None
        i += 1
        buf = ctypes.create_unicode_buffer(512)
        if _sa.SetupDiGetDeviceInstanceIdW(devs, ctypes.byref(dev), buf, 512, None):
            inst = buf.value
            if inst.upper().startswith("USB\\" + HARDWARE_ID):
                return dev, inst


def _service(devs, dev):
    buf = ctypes.create_unicode_buffer(256)
    if _sa.SetupDiGetDeviceRegistryPropertyW(devs, ctypes.byref(dev), SPDRP_SERVICE, None, buf, 512, None):
        return buf.value
    return ""


def _winusb_driver(devs, dev):
    """Point the device at winusb.inf and return the generic "WinUsb Device" driver entry."""
    params = SP_DEVINSTALL_PARAMS_W()
    params.cbSize = ctypes.sizeof(SP_DEVINSTALL_PARAMS_W)
    if not _sa.SetupDiGetDeviceInstallParamsW(devs, ctypes.byref(dev), ctypes.byref(params)):
        raise _err("reading the device's install settings")
    params.Flags |= DI_ENUMSINGLEINF
    params.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS
    params.DriverPath = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "inf", "winusb.inf")
    if not os.path.isfile(params.DriverPath):
        raise DriverError("this Windows has no %s" % params.DriverPath)
    if not _sa.SetupDiSetDeviceInstallParamsW(devs, ctypes.byref(dev), ctypes.byref(params)):
        raise _err("selecting winusb.inf")
    if not _sa.SetupDiBuildDriverInfoList(devs, ctypes.byref(dev), SPDIT_CLASSDRIVER):
        raise _err("listing the drivers in winusb.inf")
    found = []
    i = 0
    while True:
        drv = SP_DRVINFO_DATA_W()
        drv.cbSize = ctypes.sizeof(SP_DRVINFO_DATA_W)
        if not _sa.SetupDiEnumDriverInfoW(devs, ctypes.byref(dev), SPDIT_CLASSDRIVER, i, ctypes.byref(drv)):
            break
        i += 1
        found.append(drv)
    names = [d.Description for d in found]
    for drv in found:
        if "winusb" in drv.Description.lower():
            return drv, names
    return None, names


def check():
    """What an install would do, without changing anything. No admin rights needed."""
    devs = _sa.SetupDiGetClassDevsW(None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if devs in (None, _INVALID):
        raise _err("listing devices")
    try:
        dev, inst = _find_tower(devs)
        if dev is None:
            return {"present": False}
        info = {"present": True, "instance": inst, "service": _service(devs, dev),
                "class": "{%s}" % uuid.UUID(bytes_le=bytes(dev.ClassGuid)) if any(bytes(dev.ClassGuid)) else ""}
        try:
            drv, names = _winusb_driver(devs, dev)
            info["drivers_in_inf"] = names
            info["would_install"] = drv.Description if drv else None
        except DriverError as e:
            info["drivers_in_inf"] = []
            info["would_install"] = None
            info["problem"] = str(e)
        return info
    finally:
        _sa.SetupDiDestroyDeviceInfoList(devs)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def install(log=print):
    """Bind WinUSB to the tower. Must run with admin rights. Returns True on success."""
    devs = _sa.SetupDiGetClassDevsW(None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if devs in (None, _INVALID):
        raise _err("listing devices")
    try:
        dev, inst = _find_tower(devs)
        if dev is None:
            raise DriverError("the tower is not plugged in")
        log("Tower found: %s" % inst)

        # the interface GUID has to be in place before WinUSB starts on the device
        key = _sa.SetupDiCreateDevRegKeyW(devs, ctypes.byref(dev), DICS_FLAG_GLOBAL, 0, DIREG_DEV, None, None)
        if key in (None, _INVALID):
            raise _err("opening the tower's registry key")
        value = ctypes.create_unicode_buffer(INTERFACE_GUID + "\0")  # multi-string: name, empty, end
        ok = _adv.RegSetValueExW(key, "DeviceInterfaceGUIDs", 0, REG_MULTI_SZ, value, ctypes.sizeof(value)) == 0
        _adv.RegCloseKey(key)
        if not ok:
            raise DriverError("could not write the device interface GUID")
        log("Device interface GUID written.")

        try:
            drv, names = _winusb_driver(devs, dev)
        except DriverError:
            drv, names = None, []
        if drv is None:
            # a device nobody has claimed has no class yet; give it WinUSB's class and look again
            _sa.SetupDiDestroyDriverInfoList(devs, ctypes.byref(dev), SPDIT_CLASSDRIVER)
            cls = ctypes.create_unicode_buffer(USBDEVICE_CLASS)
            if not _sa.SetupDiSetDeviceRegistryPropertyW(devs, ctypes.byref(dev), SPDRP_CLASSGUID, cls, ctypes.sizeof(cls)):
                raise _err("setting the tower's device class")
            dev.ClassGuid = GUID.parse(USBDEVICE_CLASS)
            drv, names = _winusb_driver(devs, dev)
        if drv is None:
            raise DriverError("winusb.inf has no generic WinUSB driver (it lists: %s)" % (", ".join(names) or "nothing"))
        log("Selected driver: %s (%s)" % (drv.Description, drv.ProviderName))
        if not _sa.SetupDiSetSelectedDriverW(devs, ctypes.byref(dev), ctypes.byref(drv)):
            raise _err("selecting the WinUSB driver")

        newdev = ctypes.WinDLL("newdev", use_last_error=True)
        newdev.DiInstallDevice.argtypes = [wt.HWND, ctypes.c_void_p, _P(SP_DEVINFO_DATA), _P(SP_DRVINFO_DATA_W),
                                           wt.DWORD, _P(wt.BOOL)]
        reboot = wt.BOOL(0)
        if not newdev.DiInstallDevice(None, devs, ctypes.byref(dev), ctypes.byref(drv), 0, ctypes.byref(reboot)):
            raise _err("installing the driver")
        log("Driver installed.%s" % (" Windows wants a restart." if reboot.value else ""))
        return True
    finally:
        _sa.SetupDiDestroyDeviceInfoList(devs)


def result_file():
    return os.path.join(os.environ.get("PROGRAMDATA", os.environ.get("TEMP", ".")), "rcxtower-driver-install.log")


def run_elevated_install():
    """Entry point of the elevated helper: install and leave a log the app can read."""
    lines = []
    try:
        install(lines.append)
        lines.append("RESULT: OK")
    except Exception as e:
        lines.append("RESULT: FAILED: %s" % e)
    try:
        with open(result_file(), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return 0 if lines[-1] == "RESULT: OK" else 1


def start_elevated():
    """Ask Windows for admin rights and run the installer. True if the prompt was started."""
    try:
        os.remove(result_file())
    except OSError:
        pass
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, "install-driver"
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe") if os.path.isfile(
            sys.executable.replace("python.exe", "pythonw.exe")) else sys.executable
        args = '-m rcxtower install-driver'
    cwd = None if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, cwd, 0) > 32


def read_result():
    try:
        with open(result_file(), "r", encoding="utf-8") as f:
            return f.read().strip().split("\n")
    except OSError:
        return None
