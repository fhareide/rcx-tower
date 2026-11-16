"""User-mode access to the LEGO USB IR Tower (VID 0694, PID 0001) through WinUSB.

Needs the WinUSB driver bound to the tower (done once with Zadig). Uses only
the Python standard library (ctypes against winusb.dll / cfgmgr32.dll).
"""
import ctypes
import ctypes.wintypes as wt
import time
import uuid

VID_PID = "vid_0694&pid_0001"

# Vendor requests understood by the tower firmware
REQ_GET_PARM = 0x01
REQ_SET_PARM = 0x02
REQ_FLUSH = 0x03
REQ_RESET = 0x04
REQ_GET_STAT = 0x05
REQ_GET_POWER = 0x06
REQ_GET_TX_SPEED = 0xEE
REQ_SET_TX_SPEED = 0xEF
REQ_GET_RX_SPEED = 0xF0
REQ_SET_RX_SPEED = 0xF1
REQ_GET_CAPS = 0xFC
REQ_GET_VERSION = 0xFD
REQ_GET_COPYRIGHT = 0xFE

PARM_MODE = 0x01      # 1 = VLL, 2 = IR, 4 = IRC, 8 = radio
PARM_RANGE = 0x02     # 1 = short, 2 = medium, 3 = long
RANGE_SHORT, RANGE_MEDIUM, RANGE_LONG = 1, 2, 3

EP_IN = 0x81
EP_OUT = 0x02

_GENERIC_RW = 0xC0000000
_SHARE_RW = 0x00000003
_OPEN_EXISTING = 3
_FLAG_OVERLAPPED = 0x40000000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_PIPE_TRANSFER_TIMEOUT = 0x03
_ERROR_SEM_TIMEOUT = 121
_CM_PRESENT = 0

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_wusb = ctypes.WinDLL("winusb", use_last_error=True)
_cfg = ctypes.WinDLL("cfgmgr32", use_last_error=True)


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        u = uuid.UUID(text)
        g = cls()
        g.d1, g.d2, g.d3 = u.fields[0], u.fields[1], u.fields[2]
        g.d4[:] = u.bytes[8:]
        return g


class _SETUP(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("RequestType", ctypes.c_ubyte), ("Request", ctypes.c_ubyte),
                ("Value", ctypes.c_ushort), ("Index", ctypes.c_ushort), ("Length", ctypes.c_ushort)]


class _PIPE_INFO(ctypes.Structure):
    _fields_ = [("PipeType", ctypes.c_int), ("PipeId", ctypes.c_ubyte),
                ("MaximumPacketSize", ctypes.c_ushort), ("Interval", ctypes.c_ubyte)]


_k32.CreateFileW.restype = ctypes.c_void_p
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_wusb.WinUsb_Initialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_wusb.WinUsb_Free.argtypes = [ctypes.c_void_p]
_wusb.WinUsb_ControlTransfer.argtypes = [ctypes.c_void_p, _SETUP, ctypes.c_void_p, wt.ULONG,
                                         ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
_wusb.WinUsb_ReadPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, wt.ULONG,
                                  ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
_wusb.WinUsb_WritePipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, wt.ULONG,
                                   ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
_wusb.WinUsb_SetPipePolicy.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, wt.ULONG, wt.ULONG, ctypes.c_void_p]
_wusb.WinUsb_QueryPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.POINTER(_PIPE_INFO)]
_wusb.WinUsb_FlushPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
_wusb.WinUsb_ResetPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
_cfg.CM_Get_Device_Interface_List_SizeW.argtypes = [ctypes.POINTER(wt.ULONG), ctypes.POINTER(_GUID),
                                                    wt.LPCWSTR, wt.ULONG]
_cfg.CM_Get_Device_Interface_ListW.argtypes = [ctypes.POINTER(_GUID), wt.LPCWSTR, ctypes.c_wchar_p,
                                               wt.ULONG, wt.ULONG]


def _interface_guids():
    """Interface GUIDs registered for the tower (Zadig generates one per install)."""
    import winreg
    found = []
    base = r"SYSTEM\CurrentControlSet\Enum\USB\VID_0694&PID_0001"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as dev:
            i = 0
            while True:
                try:
                    inst = winreg.EnumKey(dev, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(dev, inst + r"\Device Parameters") as p:
                        for name in ("DeviceInterfaceGUIDs", "DeviceInterfaceGUID"):
                            try:
                                val, _ = winreg.QueryValueEx(p, name)
                            except OSError:
                                continue
                            for g in ([val] if isinstance(val, str) else val):
                                if g and g not in found:
                                    found.append(g)
                except OSError:
                    pass
    except OSError:
        pass
    return found


def find_tower_paths():
    """Device paths of every connected tower that has WinUSB bound."""
    paths = []
    for text in _interface_guids():
        guid = _GUID.parse(text)
        size = wt.ULONG(0)
        if _cfg.CM_Get_Device_Interface_List_SizeW(ctypes.byref(size), ctypes.byref(guid), None, _CM_PRESENT):
            continue
        if size.value <= 1:
            continue
        buf = ctypes.create_unicode_buffer(size.value)
        if _cfg.CM_Get_Device_Interface_ListW(ctypes.byref(guid), None, buf, size.value, _CM_PRESENT):
            continue
        for p in ctypes.wstring_at(buf, size.value).split("\0"):
            if p and VID_PID in p.lower() and p not in paths:
                paths.append(p)
    return paths


_cfg.CM_Get_Device_ID_List_SizeW.argtypes = [ctypes.POINTER(wt.ULONG), wt.LPCWSTR, wt.ULONG]
_cfg.CM_Get_Device_ID_ListW.argtypes = [wt.LPCWSTR, ctypes.c_wchar_p, wt.ULONG, wt.ULONG]


def tower_state():
    """'ready' (plugged in, WinUSB bound), 'nodriver' (plugged in, no usable driver) or 'absent'."""
    if find_tower_paths():
        return "ready"
    flags = 0x1 | 0x100  # filter by enumerator, present devices only
    size = wt.ULONG(0)
    if _cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "USB", flags) or size.value <= 1:
        return "absent"
    buf = ctypes.create_unicode_buffer(size.value)
    if _cfg.CM_Get_Device_ID_ListW("USB", buf, size.value, flags):
        return "absent"
    ids = ctypes.wstring_at(buf, size.value).lower()
    return "nodriver" if VID_PID in ids else "absent"


class TowerError(OSError):
    pass


class Tower:
    def __init__(self, path=None):
        if path is None:
            paths = find_tower_paths()
            if not paths:
                raise TowerError("No LEGO USB Tower with WinUSB found. Is it plugged in?")
            path = paths[0]
        self.path = path
        self._file = _k32.CreateFileW(path, _GENERIC_RW, _SHARE_RW, None, _OPEN_EXISTING, _FLAG_OVERLAPPED, None)
        if self._file in (None, _INVALID_HANDLE):
            self._file = None
            raise TowerError("Cannot open tower (in use by another program?): %s" % ctypes.WinError(ctypes.get_last_error()))
        self._h = ctypes.c_void_p()
        if not _wusb.WinUsb_Initialize(self._file, ctypes.byref(self._h)):
            err = ctypes.WinError(ctypes.get_last_error())
            _k32.CloseHandle(self._file)
            self._file = None
            raise TowerError("WinUsb_Initialize failed: %s" % err)
        self.packet_size = 8
        for info in self.pipes():
            if info["id"] == EP_IN:
                self.packet_size = info["max_packet"]
        self._read_timeout = None
        self.set_read_timeout(100)

    def close(self):
        if getattr(self, "_h", None):
            _wusb.WinUsb_Free(self._h)
            self._h = None
        if getattr(self, "_file", None):
            _k32.CloseHandle(self._file)
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def pipes(self):
        out = []
        for i in range(8):
            info = _PIPE_INFO()
            if not _wusb.WinUsb_QueryPipe(self._h, 0, i, ctypes.byref(info)):
                break
            out.append({"id": info.PipeId, "type": info.PipeType,
                        "max_packet": info.MaximumPacketSize, "interval": info.Interval})
        return out

    def control(self, request, value=0, index=0, length=8):
        """Vendor IN request to the device; returns the reply bytes."""
        buf = (ctypes.c_ubyte * max(length, 1))()
        got = wt.ULONG(0)
        setup = _SETUP(0xC0, request, value, index, length)
        if not _wusb.WinUsb_ControlTransfer(self._h, setup, buf, length, ctypes.byref(got), None):
            raise TowerError("control request 0x%02X failed: %s" % (request, ctypes.WinError(ctypes.get_last_error())))
        return bytes(buf[:got.value])

    def set_parm(self, parm, value):
        return self.control(REQ_SET_PARM, parm | (value << 8))

    def get_parm(self, parm):
        return self.control(REQ_GET_PARM, parm)

    def reset(self):
        return self.control(REQ_RESET)

    def set_read_timeout(self, ms):
        ms = max(1, int(ms))
        if ms == self._read_timeout:
            return
        val = wt.ULONG(ms)
        _wusb.WinUsb_SetPipePolicy(self._h, EP_IN, _PIPE_TRANSFER_TIMEOUT, ctypes.sizeof(val), ctypes.byref(val))
        self._read_timeout = ms

    def write(self, data):
        data = bytes(data)
        sent = 0
        while sent < len(data):
            chunk = data[sent:sent + 256]
            buf = (ctypes.c_ubyte * len(chunk)).from_buffer_copy(chunk)
            n = wt.ULONG(0)
            if not _wusb.WinUsb_WritePipe(self._h, EP_OUT, buf, len(chunk), ctypes.byref(n), None):
                raise TowerError("write failed: %s" % ctypes.WinError(ctypes.get_last_error()))
            sent += n.value
        return sent

    def read_packet(self, timeout_ms=100):
        """One USB packet from the tower, or b'' if nothing arrived in time."""
        self.set_read_timeout(timeout_ms)
        buf = (ctypes.c_ubyte * self.packet_size)()
        n = wt.ULONG(0)
        if not _wusb.WinUsb_ReadPipe(self._h, EP_IN, buf, self.packet_size, ctypes.byref(n), None):
            err = ctypes.get_last_error()
            if err == _ERROR_SEM_TIMEOUT:
                return bytes(buf[:n.value])
            raise TowerError("read failed: %s" % ctypes.WinError(err))
        return bytes(buf[:n.value])

    def read(self, total_ms=500, quiet_ms=80):
        """Collect bytes until the line has been quiet for quiet_ms or total_ms passed."""
        out = bytearray()
        end = time.monotonic() + total_ms / 1000.0
        while time.monotonic() < end:
            got = self.read_packet(quiet_ms)
            if got:
                out += got
            elif out:
                break
        return bytes(out)

    def drain(self):
        while self.read_packet(20):
            pass


def rcx_frame(payload):
    """Wrap RCX opcode+args in the IR framing: header, byte/complement pairs, checksum."""
    out = bytearray(b"\x55\xff\x00")
    total = 0
    for b in payload:
        out += bytes((b, b ^ 0xFF))
        total += b
    total &= 0xFF
    out += bytes((total, total ^ 0xFF))
    return bytes(out)


def rcx_unframe(raw):
    """Pull the payload out of a framed reply. Returns None if no valid frame is found."""
    for start in range(len(raw)):
        data = []
        i = start
        while i + 1 < len(raw) and raw[i] ^ raw[i + 1] == 0xFF:
            data.append(raw[i])
            i += 2
        # the 55 FF 00 header itself contains one complement pair-free run; skip tiny matches
        if len(data) >= 2 and (sum(data[:-1]) & 0xFF) == data[-1]:
            return bytes(data[:-1])
    return None
