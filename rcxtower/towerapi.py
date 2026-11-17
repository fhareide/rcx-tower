"""Builds a stand-in for LEGO's TOWERAPI.DLL (32-bit).

BricxCC only uses a USB tower through TOWERAPI.DLL: it calls
LEGOTowerSetIRSpeed, LEGOTowerSetLinkMode, LEGOTowerSetTimeouts and
LEGOTowerFlush on the handle it opened, and refuses to connect if the DLL is
missing. LEGO's DLL talks to LEGO's 32-bit driver, which does not exist on
64-bit Windows. With RCX Tower's USB bridge the tower is already configured
and timeouts are handled by the bridge, so every function here does nothing:
the "set" calls report success, the "get" and "find" calls report failure.

The DLL is written byte by byte (no compiler needed). All exports are
stdcall, as in LEGO's header; each is `mov eax, result / ret <arg bytes>`.
"""
import os
import struct

# name: (number of 32-bit stack arguments, return value)
EXPORTS = {
    "LEGOTowerSetRange": (2, 1), "LEGOTowerGetRange": (2, 0),
    "LEGOTowerSetLinkMode": (2, 1), "LEGOTowerGetLinkMode": (2, 0),
    "LEGOTowerSetEndianness": (2, 1), "LEGOTowerGetEndianness": (2, 0),
    "LEGOTowerFlush": (2, 1), "LEGOTowerReset": (1, 1),
    "LEGOTowerSetTimeouts": (4, 1), "LEGOTowerGetTimeouts": (4, 0),
    "LEGOTowerGetCaps": (3, 0), "LEGOTowerGetVersion": (2, 0),
    "LEGOTowerGetCopyright": (3, 0), "LEGOTowerGetCredits": (3, 0),
    "LEGOTowerGetLedMode": (2, 0), "LEGOTowerSetLedMode": (2, 1),
    "LEGOTowerGetLedState": (3, 0), "LEGOTowerSetLedState": (3, 1),
    "LEGOTowerGetIRSpeed": (3, 0), "LEGOTowerSetIRSpeed": (3, 1),
    "LEGOTowerResetCommStats": (1, 1), "LEGOTowerGetCommStats": (2, 0),
    "LEGOTowerSetDefaultConfig": (1, 1), "LEGOTowerGetDefaultConfig": (1, 0),
    "LEGOTowerGetFactoryConfig": (1, 0), "LEGOTowerGetErrorState": (2, 0),
    "LEGOTowerGetState": (2, 0), "LEGOTowerGetWin32Error": (1, 0),
    "LEGOTowerSetCarrierFrequency": (2, 1), "LEGOTowerGetCarrierFrequency": (2, 0),
    "LEGOTowerSetCarrierDutyCycle": (3, 1), "LEGOTowerGetCarrierDutyCycle": (3, 0),
    "LEGOTowerSetIRCParm": (4, 1), "LEGOTowerGetIRCParm": (3, 0),
    "LEGOTowerSetIRCTimeFrame": (2, 1), "LEGOTowerGetIRCTimeFrame": (2, 0),
    "LEGOTowerSetIRCPacketSize": (2, 1), "LEGOTowerGetIRCPacketSize": (2, 0),
    "LEGOTowerRestart": (1, 1), "LEGOTowerRestartAll": (0, 1),
    "LEGOTowerReenumerateAll": (0, 1), "LEGOTowerIsUSBEnabled": (0, 1),
    "LEGOTowerFindFirst": (1, 0), "LEGOTowerFindNext": (1, 0),
    "LEGOTowerFindPrev": (1, 0), "LEGOTowerFindStop": (1, 1),
    "LEGOTowerGetDeviceInfo": (2, 0), "LEGOTowerGetPathName": (1, 0),
    "LEGOTowerGetPathNameCopy": (3, 0), "LEGOTowerGetProblemDesc": (3, 0),
    "LEGOTowerGetDeviceInfoByNumber": (3, 0), "LEGOTowerGetHostControllerInfo": (2, 0),
}

DLL_NAME = "TOWERAPI.DLL"
_SECTION, _FILE = 0x1000, 0x200
_TEXT_RVA = 0x1000


def _align(n, a):
    return (n + a - 1) // a * a


def build():
    """Return the bytes of the DLL."""
    names = sorted(EXPORTS)  # the loader does a binary search, so byte order matters
    code = bytearray()
    offsets = {}
    for name in names:
        nargs, result = EXPORTS[name]
        offsets[name] = len(code)
        code += b"\xB8" + struct.pack("<I", result)                      # mov eax, result
        code += (b"\xC2" + struct.pack("<H", nargs * 4)) if nargs else b"\xC3"  # ret n
    code += b"\xCC" * (-len(code) % 16)

    # export data sits after the code in the same section
    base = _TEXT_RVA + len(code)
    n = len(names)
    dir_size = 40
    funcs_rva = base + dir_size
    names_rva = funcs_rva + 4 * n
    ords_rva = names_rva + 4 * n
    strings_rva = ords_rva + 2 * n
    strings = bytearray(DLL_NAME.encode() + b"\0")
    name_rvas = []
    for name in names:
        name_rvas.append(strings_rva + len(strings))
        strings += name.encode() + b"\0"
    export = struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, strings_rva, 1, n, n, funcs_rva, names_rva, ords_rva)
    export += b"".join(struct.pack("<I", _TEXT_RVA + offsets[name]) for name in names)
    export += b"".join(struct.pack("<I", r) for r in name_rvas)
    export += b"".join(struct.pack("<H", i) for i in range(n))
    export += bytes(strings)

    text = bytes(code) + export
    text_raw = _align(len(text), _FILE)
    reloc_rva = _TEXT_RVA + _align(len(text), _SECTION)
    reloc = struct.pack("<IIHH", _TEXT_RVA, 12, 0, 0)  # one block with two no-op entries
    reloc_raw = _align(len(reloc), _FILE)
    size_of_image = reloc_rva + _align(len(reloc), _SECTION)

    dos = bytearray(64)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    coff = struct.pack("<HHIIIHH", 0x014C, 2, 0, 0, 0, 224, 0x2102)  # i386, executable | 32-bit | DLL
    opt = struct.pack("<HBBIIIIII", 0x10B, 1, 0, text_raw, reloc_raw, 0, 0, _TEXT_RVA, reloc_rva)
    opt += struct.pack("<IIIHHHHHHIIIIHHIIIIII",
                       0x10000000, _SECTION, _FILE, 4, 0, 0, 0, 4, 0, 0,
                       size_of_image, _FILE, 0, 2, 0x0140,  # GUI subsystem; ASLR + NX compatible
                       0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    dirs = [(0, 0)] * 16
    dirs[0] = (base, len(export))
    dirs[5] = (reloc_rva, len(reloc))
    opt += b"".join(struct.pack("<II", *d) for d in dirs)
    assert len(opt) == 224
    sections = struct.pack("<8sIIIIIIHHI", b".text", len(text), _TEXT_RVA, text_raw, _FILE, 0, 0, 0, 0, 0x60000020)
    sections += struct.pack("<8sIIIIIIHHI", b".reloc", len(reloc), reloc_rva, reloc_raw, _FILE + text_raw,
                            0, 0, 0, 0, 0x42000040)
    headers = bytes(dos) + b"PE\0\0" + coff + opt + sections
    assert len(headers) <= _FILE
    return (headers.ljust(_FILE, b"\0") + text.ljust(text_raw, b"\0") + reloc.ljust(reloc_raw, b"\0"))


def install(folder):
    """Write the DLL into `folder` (created if needed) and return its path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, DLL_NAME)
    data = build()
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return path
    except OSError:
        pass
    with open(path, "wb") as f:  # fails if a running BricxCC has an older copy loaded
        f.write(data)
    return path


def default_folder():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "rcxtower", "towerapi")


BACKUP_NAME = "TOWERAPI.DLL.lego-backup"  # LEGO's own DLL, kept when ours replaces it


def find_bricxcc(chosen=None):
    """BricxCC.exe: the one the user chose (if it still exists), else the one in Program Files."""
    if chosen and os.path.isfile(chosen):
        return chosen
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            exe = os.path.join(base, "BricxCC", "BricxCC.exe")
            if os.path.isfile(exe):
                return exe
    return None


def is_standin(data):
    """True for any version of the DLL `build` makes (LEGO's own is far larger, with a DOS stub)."""
    return (len(data) <= 4096 and data[:2] == b"MZ" and data[0x3C:0x40] == struct.pack("<I", 64)
            and b"LEGOTowerSetIRSpeed" in data)


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def bricxcc_state(exe):
    """Which TOWERAPI.DLL is in BricxCC's own folder, where Windows looks first.

    'ready'    our current stand-in: BricxCC can use the USB bridge however it is started
    'outdated' an older version of our stand-in
    'lego'     another TOWERAPI.DLL (LEGO's own, from the SDK or the RIS software); it needs
               LEGO's 32-bit driver, which 64-bit Windows does not have
    'missing'  none: BricxCC refuses to use a USB tower unless started by RCX Tower
    """
    data = _read(os.path.join(os.path.dirname(exe), DLL_NAME))
    if data is None:
        return "missing"
    if data == build():
        return "ready"
    return "outdated" if is_standin(data) else "lego"


def system_copy():
    """A TOWERAPI.DLL in a Windows folder that a 32-bit BricxCC searches, or None."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for sub in ("SysWOW64", "System32", "System", ""):
        path = os.path.join(windir, sub, DLL_NAME)
        if os.path.isfile(path):
            if sub == "System32" and os.path.isdir(os.path.join(windir, "SysWOW64")):
                continue  # 64-bit system folder: a 32-bit BricxCC never sees it
            return path
    return None


def install_commands(exe):
    """The copy commands that put the stand-in into BricxCC's folder, keeping LEGO's DLL."""
    src = install(default_folder())
    folder = os.path.dirname(exe)
    dst = os.path.join(folder, DLL_NAME)
    backup = os.path.join(folder, BACKUP_NAME)
    commands = []
    if bricxcc_state(exe) == "lego" and not os.path.exists(backup):
        commands.append('copy /y "%s" "%s"' % (dst, backup))
    commands.append('copy /y "%s" "%s"' % (src, dst))
    return commands


def copy_into_bricxcc(exe):
    """Put the stand-in into BricxCC's folder; LEGO's own DLL there is kept as BACKUP_NAME.

    Returns 'done' when the folder is writable (BricxCC outside Program Files), 'prompt' when
    Windows was asked for permission (the copy then happens in another process, so poll
    bricxcc_state), or 'cancelled'.
    """
    folder = os.path.dirname(exe)
    try:
        if bricxcc_state(exe) == "lego" and not os.path.exists(os.path.join(folder, BACKUP_NAME)):
            os.replace(os.path.join(folder, DLL_NAME), os.path.join(folder, BACKUP_NAME))
        install(folder)
        return "done"
    except OSError:
        pass  # Program Files: needs admin rights
    import ctypes
    args = "/c " + " && ".join(install_commands(exe))
    started = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", args, None, 0) > 32
    return "prompt" if started else "cancelled"


def describe(exe):
    """Lines for the diagnostics report."""
    if not exe:
        return ["BricxCC: not found"]
    lines = ["BricxCC: %s" % exe,
             "TOWERAPI.DLL in the BricxCC folder: %s" % {
                 "ready": "RCX Tower's (current)", "outdated": "RCX Tower's (older version)",
                 "lego": "another one, probably LEGO's  <-- BricxCC cannot use the USB bridge",
                 "missing": "none  <-- BricxCC works over USB only when started from RCX Tower",
             }[bricxcc_state(exe)]]
    if os.path.exists(os.path.join(os.path.dirname(exe), BACKUP_NAME)):
        lines.append("LEGO's TOWERAPI.DLL kept as: %s" % BACKUP_NAME)
    copy = system_copy()
    if copy:
        lines.append("TOWERAPI.DLL in a Windows folder: %s" % copy)
    return lines


def start_bricxcc(exe):
    """Start BricxCC so that it finds the stand-in when no copy is in its own folder."""
    import subprocess
    folder = os.path.dirname(install(default_folder()))
    subprocess.Popen([exe], cwd=folder, close_fds=True)
