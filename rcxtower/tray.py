"""System tray icon through the Win32 API (ctypes only).

Runs its own hidden window and message loop on a background thread. Menu
choices and clicks are reported through the `on_action` callback, which is
called on that thread: the receiver must hand the work to its own thread.
"""
import ctypes
import ctypes.wintypes as wt
import threading

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_TRAY = 0x8000 + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
MF_STRING, MF_SEPARATOR, MF_DEFAULT = 0x0, 0x800, 0x1000
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40


class _GUID(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", _GUID), ("hBalloonIcon", wt.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


_user32.DefWindowProcW.restype = LRESULT
_user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_user32.CreateWindowExW.restype = wt.HWND
_user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
_user32.DestroyWindow.argtypes = [wt.HWND]
_user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.LoadImageW.restype = wt.HANDLE
_user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
_user32.LoadIconW.restype = wt.HICON
_user32.LoadIconW.argtypes = [wt.HINSTANCE, wt.LPCWSTR]
_user32.CreatePopupMenu.restype = wt.HMENU
_user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
_user32.SetMenuDefaultItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
_user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
_user32.DestroyMenu.argtypes = [wt.HMENU]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
_user32.SetForegroundWindow.argtypes = [wt.HWND]
_shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
_kernel32.GetModuleHandleW.restype = wt.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]


class Tray:
    """menu: callable returning a list of (action, label) pairs; (None, None) is a separator.
    The first entry is the default (double-click / left-click) action."""

    def __init__(self, icon_path, tooltip, menu, on_action):
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.menu = menu
        self.on_action = on_action
        self.ok = False
        self.hwnd = None
        self._nid = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # keep a reference or it gets collected
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(3)
        return self.ok

    def _run(self):
        hinst = _kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW()
        cls.lpfnWndProc = self._proc
        cls.hInstance = hinst
        cls.lpszClassName = "RCXTowerTray%d" % threading.get_ident()
        if not _user32.RegisterClassW(ctypes.byref(cls)):
            self._ready.set()
            return
        self.hwnd = _user32.CreateWindowExW(0, cls.lpszClassName, "RCX Tower", 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            self._ready.set()
            return
        icon = None
        if self.icon_path:
            icon = _user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not icon:
            icon = _user32.LoadIconW(None, ctypes.cast(32512, wt.LPCWSTR))  # stock application icon
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = icon
        nid.szTip = self.tooltip[:127]
        self._nid = nid
        self.ok = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        self._ready.set()
        msg = wt.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        if self.ok:
            _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self.ok = False

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                items = self.menu()
                if items:
                    self.on_action(items[0][0])
            elif event == WM_RBUTTONUP:
                self._popup()
            return 0
        if msg == WM_CLOSE:
            _user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup(self):
        items = self.menu()
        menu = _user32.CreatePopupMenu()
        actions = {}
        for i, (action, label) in enumerate(items, 1):
            if action is None:
                _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                _user32.AppendMenuW(menu, MF_STRING, i, label)
                actions[i] = action
        _user32.SetMenuDefaultItem(menu, 1, 0)
        pt = wt.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(self.hwnd)  # so the menu closes when clicking elsewhere
        chosen = _user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
        _user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        _user32.DestroyMenu(menu)
        if chosen in actions:
            self.on_action(actions[chosen])

    def set_tooltip(self, text):
        if not self.ok or text == self.tooltip:
            return
        self.tooltip = text
        self._nid.uFlags = NIF_TIP
        self._nid.szTip = text[:127]
        _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def notify(self, title, text):
        """Show a notification bubble from the tray icon."""
        if not self.ok:
            return
        self._nid.uFlags = NIF_INFO
        self._nid.szInfoTitle = title[:63]
        self._nid.szInfo = text[:255]
        self._nid.dwInfoFlags = 1  # information icon
        _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))

    def stop(self):
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(2)
