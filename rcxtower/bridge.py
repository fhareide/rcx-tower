"""Present the USB tower as a serial tower on a virtual COM port (com0com pair).

NQC, BricxCC and other old software open the other end of the pair and treat
it as the original serial IR tower.
"""
import ctypes
import ctypes.wintypes as wt
import threading

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = ctypes.c_void_p
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
_k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_INVALID = ctypes.c_void_p(-1).value
_MAXDWORD = 0xFFFFFFFF


class _COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [("ReadIntervalTimeout", wt.DWORD), ("ReadTotalTimeoutMultiplier", wt.DWORD),
                ("ReadTotalTimeoutConstant", wt.DWORD), ("WriteTotalTimeoutMultiplier", wt.DWORD),
                ("WriteTotalTimeoutConstant", wt.DWORD)]


class _DCB(ctypes.Structure):
    _fields_ = [("DCBlength", wt.DWORD), ("BaudRate", wt.DWORD), ("flags", wt.DWORD),
                ("wReserved", wt.WORD), ("XonLim", wt.WORD), ("XoffLim", wt.WORD),
                ("ByteSize", ctypes.c_ubyte), ("Parity", ctypes.c_ubyte), ("StopBits", ctypes.c_ubyte),
                ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char), ("ErrorChar", ctypes.c_char),
                ("EofChar", ctypes.c_char), ("EvtChar", ctypes.c_char), ("wReserved1", wt.WORD)]


_k32.SetCommTimeouts.argtypes = [ctypes.c_void_p, ctypes.POINTER(_COMMTIMEOUTS)]
_k32.GetCommState.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DCB)]
_k32.SetCommState.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DCB)]


class ComPort:
    def __init__(self, name, wait_ms=4):
        self.name = name
        self.h = _k32.CreateFileW("\\\\.\\" + name, 0xC0000000, 0, None, 3, 0, None)
        if self.h in (None, _INVALID):
            self.h = None
            raise OSError("cannot open %s: %s" % (name, ctypes.WinError(ctypes.get_last_error())))
        # 8 data bits, no flow control: the port default is 7 bits, which strips the top bit
        dcb = _DCB()
        dcb.DCBlength = ctypes.sizeof(_DCB)
        _k32.GetCommState(self.h, ctypes.byref(dcb))
        dcb.BaudRate = 2400
        dcb.flags = 0x1011  # binary, DTR on, RTS on, nothing else
        dcb.ByteSize, dcb.Parity, dcb.StopBits = 8, 0, 0
        if not _k32.SetCommState(self.h, ctypes.byref(dcb)):
            err = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise OSError("cannot configure %s: %s" % (name, err))
        # return as soon as any byte is there, or after wait_ms with nothing
        to = _COMMTIMEOUTS(_MAXDWORD, _MAXDWORD, wait_ms, 0, 500)
        _k32.SetCommTimeouts(self.h, ctypes.byref(to))
        self._buf = (ctypes.c_ubyte * 4096)()

    def read(self):
        n = wt.DWORD(0)
        if not _k32.ReadFile(self.h, self._buf, len(self._buf), ctypes.byref(n), None):
            raise OSError("COM read failed: %s" % ctypes.WinError(ctypes.get_last_error()))
        return bytes(self._buf[:n.value])

    def write(self, data):
        if not data:
            return
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        n = wt.DWORD(0)
        _k32.WriteFile(self.h, buf, len(data), ctypes.byref(n), None)

    def close(self):
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None


def com0com_pairs():
    """Virtual pairs found on this machine as (app_port, bridge_port), e.g. ('COM2', 'CNCB0')."""
    import winreg
    names = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
            i = 0
            while True:
                try:
                    dev, port, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                names[dev.lower()] = port
    except OSError:
        return []
    pairs = []
    for dev, port in sorted(names.items()):
        # com0com names its devices \Device\com0com1N (side A) and \Device\com0com2N (side B)
        base = "\\device\\com0com1"
        if dev.startswith(base):
            other = names.get("\\device\\com0com2" + dev[len(base):])
            if other:
                pairs.append((port, other))
    return pairs


_k32.CreateNamedPipeW.restype = ctypes.c_void_p
_k32.CreateNamedPipeW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p]
_k32.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_k32.DisconnectNamedPipe.argtypes = [ctypes.c_void_p]
_k32.PeekNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                               ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.SetNamedPipeHandleState.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD), ctypes.c_void_p, ctypes.c_void_p]
_k32.DefineDosDeviceW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR]

USB_PORT = "usb"  # what the user selects in BricxCC / passes to nqc as -Susb

_ntdll = ctypes.WinDLL("ntdll")


class _IOSB(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_void_p)]


_ntdll.NtQueryInformationFile.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IOSB), ctypes.c_void_p, wt.ULONG, ctypes.c_int]
_ntdll.NtQueryInformationFile.restype = ctypes.c_long


def _client_is_reading(pipe):
    """True if the program at the other end of the pipe is blocked in a read.

    Windows charges a waiting reader's buffer against the writer's quota, so a
    write quota below the full outbound quota with nothing queued means a read
    is pending. Returns None if the query fails.
    """
    info = (wt.ULONG * 10)()  # FILE_PIPE_LOCAL_INFORMATION
    iosb = _IOSB()
    if _ntdll.NtQueryInformationFile(pipe, ctypes.byref(iosb), info, ctypes.sizeof(info), 24) != 0:
        return None
    return info[7] < info[6]  # WriteQuotaAvailable < OutboundQuota


class UsbBridge:
    """Makes \\\\.\\LEGOTOWER1 exist without any driver.

    That is the device name LEGO's old 32-bit driver created, and the name NQC
    and BricxCC open when told the tower is on "usb". Here it is a DOS device
    name pointing at a named pipe owned by this program; bytes are pumped
    between the pipe and the real tower. Nothing is installed and no admin
    rights are needed. The name exists only in this user's logon session and
    only while the bridge runs.

    A real driver lets a read time out when the RCX stays silent. A pipe cannot,
    so when the program is waiting in a read and the IR link has been quiet for
    a while, a zero-length message is written, which ends that read with
    0 bytes: the same thing a timeout looks like.
    """

    FIRST_BYTE_MS = 300   # quiet time before a waiting read gives up, nothing received yet
    NEXT_BYTE_MS = 70     # ... once part of a reply has arrived

    DEVICE = "LEGOTOWER1"
    TARGET = "\\Device\\NamedPipe\\rcxtower_usb"
    PIPE = "\\\\.\\pipe\\rcxtower_usb"

    def __init__(self, tower, on_bytes=None):
        self.tower = tower
        self.port_name = USB_PORT
        self.on_bytes = on_bytes
        self.tx_count = 0
        self.rx_count = 0
        self.error = None
        self.client_connected = False
        self.connections = 0
        self.timeouts = 0
        self._stop = threading.Event()
        self._thread = None
        self._pipes = []
        self._named = False

    INSTANCES = 4  # spare connections, so a program can close the tower and reopen it at once

    def _open(self):
        # duplex; message-type (needed for the zero-length "timeout" write); non-blocking server end
        for i in range(self.INSTANCES):
            first = 0x00080000 if i == 0 else 0  # fail if another program already owns the name
            pipe = _k32.CreateNamedPipeW(self.PIPE, 3 | first, 4 | 1, self.INSTANCES, 8192, 8192, 0, None)
            if pipe in (None, _INVALID):
                err = ctypes.WinError(ctypes.get_last_error())
                self._close()
                raise OSError("cannot create the USB tower emulation (is RCX Tower already running?): %s" % err)
            self._pipes.append(pipe)
        if not _k32.DefineDosDeviceW(1, self.DEVICE, self.TARGET):
            err = ctypes.WinError(ctypes.get_last_error())
            self._close()
            raise OSError("cannot create the device name %s: %s" % (self.DEVICE, err))
        self._named = True
        self._stop.clear()

    def _close(self):
        if self._named:
            _k32.DefineDosDeviceW(1 | 2 | 4, self.DEVICE, self.TARGET)
            self._named = False
        for pipe in self._pipes:
            _k32.DisconnectNamedPipe(pipe)
            _k32.CloseHandle(pipe)
        self._pipes = []

    def start(self):
        self._open()
        self._thread = threading.Thread(target=self._run, name="tower-usb-bridge", daemon=True)
        self._thread.start()

    def run_forever(self):
        self._open()
        self._run()

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
            self._thread = None

    def _drop(self, pipe):
        """The program on this connection is gone: make the connection available again."""
        _k32.DisconnectNamedPipe(pipe)
        self.client_connected = False
        if self.on_bytes:
            self.on_bytes("close", b"")

    def _run(self):
        import time
        tower = self.tower
        buf = (ctypes.c_ubyte * 8192)()
        n = wt.DWORD(0)
        active = None
        quiet_since = time.monotonic()  # last moment the IR link was busy
        limit = self.FIRST_BYTE_MS
        unanswered = False              # fallback rule if the read state cannot be queried
        try:
            while not self._stop.is_set():
                # see whether a program has opened the device on one of the idle connections
                for pipe in self._pipes:
                    if pipe == active:
                        continue
                    if _k32.ConnectNamedPipe(pipe, None):
                        continue
                    err = ctypes.get_last_error()
                    if err == 232:      # opened and already closed again
                        _k32.DisconnectNamedPipe(pipe)
                    elif err == 535:    # a program is connected
                        if active is not None:
                            self._drop(active)  # the newest program gets the tower
                        active = pipe
                        self.client_connected = True
                        self.connections += 1
                        if self.on_bytes:
                            self.on_bytes("open", b"")
                        tower.drain()
                        quiet_since = time.monotonic()
                        limit = self.FIRST_BYTE_MS
                        unanswered = False
                if active is None:
                    time.sleep(0.005)
                    continue
                avail = wt.DWORD(0)
                if not _k32.PeekNamedPipe(active, None, 0, None, ctypes.byref(avail), None):
                    self._drop(active)  # the program closed the device
                    active = None
                    continue
                if avail.value:
                    _k32.ReadFile(active, buf, min(avail.value, len(buf)), ctypes.byref(n), None)
                    out = bytes(buf[:n.value])
                    if out:
                        tower.write(out)
                        self.tx_count += len(out)
                        if self.on_bytes:
                            self.on_bytes("tx", out)
                        quiet_since = time.monotonic() + len(out) * 0.005  # still on the air
                        limit = self.FIRST_BYTE_MS
                        unanswered = True
                back = tower.read_packet(4)
                while back:
                    data = (ctypes.c_ubyte * len(back)).from_buffer_copy(back)
                    _k32.WriteFile(active, data, len(back), ctypes.byref(n), None)
                    self.rx_count += len(back)
                    if self.on_bytes:
                        self.on_bytes("rx", back)
                    quiet_since = time.monotonic()
                    limit = self.NEXT_BYTE_MS
                    unanswered = False
                    back = tower.read_packet(4)
                if (time.monotonic() - quiet_since) * 1000.0 > limit:
                    reading = _client_is_reading(active)
                    if reading or (reading is None and unanswered):
                        _k32.WriteFile(active, buf, 0, ctypes.byref(n), None)  # "read timed out"
                        self.timeouts += 1
                        if self.on_bytes:
                            self.on_bytes("timeout", b"")
                        quiet_since = time.monotonic()
                        limit = self.FIRST_BYTE_MS
                        unanswered = False
        except Exception as e:  # tower unplugged
            self.error = e
        finally:
            self.client_connected = False
            self._close()


class Bridge:
    """Pumps bytes between a tower.Tower and one end of a virtual COM pair."""

    def __init__(self, tower, port, echo=True, on_bytes=None):
        self.tower = tower
        self.port_name = port
        self.echo = echo
        self.on_bytes = on_bytes  # callback(direction, data): direction "tx" (PC->RCX) or "rx"
        self.tx_count = 0
        self.rx_count = 0
        self.error = None
        self._stop = threading.Event()
        self._thread = None
        self._com = None

    def start(self):
        self._com = ComPort(self.port_name)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tower-bridge", daemon=True)
        self._thread.start()

    def run_forever(self):
        self._com = ComPort(self.port_name)
        self._stop.clear()
        self._run()

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
            self._thread = None

    def _run(self):
        com, tower = self._com, self.tower
        try:
            tower.drain()
            while not self._stop.is_set():
                out = com.read()
                if out:
                    tower.write(out)
                    if self.echo:
                        com.write(out)  # the serial tower hears its own IR, software expects that
                    self.tx_count += len(out)
                    if self.on_bytes:
                        self.on_bytes("tx", out)
                back = tower.read_packet(4)
                while back:
                    com.write(back)
                    self.rx_count += len(back)
                    if self.on_bytes:
                        self.on_bytes("rx", back)
                    back = tower.read_packet(4)
        except Exception as e:  # tower unplugged, port vanished
            self.error = e
        finally:
            com.close()
            self._com = None
