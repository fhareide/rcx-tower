"""The RCX Tower window: status, firmware, programs, remote control, bridge, setup."""
import json
import os
import queue
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk

import sys

from . import __version__
from . import diag
from . import editor as ed
from . import firmware as fw
from . import nqc
from . import tower as tw
from .rcx import RCX

# RCXTOWER_PORTABLE_UI=1 shows the window as it looks on macOS/Linux, for testing on Windows
WINDOWS = sys.platform == "win32" and not os.environ.get("RCXTOWER_PORTABLE_UI")
MAC = sys.platform == "darwin"
if WINDOWS:
    # the bridge, the driver installer, the BricxCC helper and the tray icon are Windows-only
    import winreg
    from . import bridge as br
    from . import driver as drv
    from . import towerapi as ta
    from . import tray as tr

UI_FONT = "Segoe UI" if WINDOWS else ("Helvetica Neue" if MAC else "DejaVu Sans")
MONO_FONT = "Consolas" if WINDOWS else ("Menlo" if MAC else "DejaVu Sans Mono")

USB_MODE = "USB (nothing to install)"
SENSOR_CHOICES = ["as the program set it", "touch", "light", "temperature", "rotation", "raw"]
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rcxtower.ico")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "RCX Tower"
FROZEN = bool(getattr(sys, "frozen", False))


def autostart_enabled():
    if not WINDOWS:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    """Start the packaged app hidden in the tray when the user logs in."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, '"%s" --tray' % sys.executable)
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass

ZADIG_URL = "https://zadig.akeo.ie"
COM0COM_URL = "https://sourceforge.net/projects/com0com/"
BRICXCC_URL = "https://sourceforge.net/projects/bricxcc/"
PYUSB_URL = "https://github.com/pyusb/pyusb#installing"
NQC_URL = "https://bricxcc.sourceforge.net/nqc/"


def _settings_dir():
    home = os.path.expanduser("~")
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA", home), "rcxtower")
    if MAC:
        return os.path.join(home, "Library", "Application Support", "rcxtower")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config")), "rcxtower")


SETTINGS = os.path.join(_settings_dir(), "settings.json")


def load_settings():
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


class App:
    def __init__(self, root, start_hidden=False):
        self.root = root
        self.tray = None
        self._told_about_tray = False
        self.settings = load_settings()
        diag.init(os.path.dirname(SETTINGS))
        self.jobs = queue.Queue()
        self.events = queue.Queue()
        self.bridge = None
        self.bridge_tower = None
        self.busy = False
        self._job = None
        self._job_warned = False
        root.report_callback_exception = self._tk_error
        self._last_counts = (0, 0)

        root.title("RCX Tower %s" % __version__)
        root.minsize(720, 640)
        root.geometry("860x760")
        self.mono_font = MONO_FONT
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if os.path.isfile(ICON):
            try:
                root.iconbitmap(ICON)
            except tk.TclError:
                pass
        self._build()
        if WINDOWS:
            self.tray = tr.Tray(ICON if os.path.isfile(ICON) else None, "RCX Tower", self._tray_menu,
                                lambda action: self.events.put(("tray", action)))
            if not self.tray.start():
                self.tray = None
        if start_hidden and self.tray:
            root.withdraw()
        threading.Thread(target=self._worker, name="rcx-worker", daemon=True).start()
        self.root.after(100, self._pump)
        self.root.after(200, self._tick)
        if WINDOWS and self.settings.get("bridge_autostart"):
            self.root.after(600, self.start_bridge)
        else:
            self.root.after(600, self.refresh)

    # ---- layout ----------------------------------------------------------
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        self.tower_var = tk.StringVar(value="Tower: checking...")
        self.rcx_var = tk.StringVar(value="RCX: not checked yet")
        ttk.Label(top, textvariable=self.tower_var, font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.rcx_var, font=(UI_FONT, 10, "bold")).grid(row=1, column=0, sticky="w")
        self.refresh_btn = ttk.Button(top, text="Check RCX", command=self.refresh)
        self.refresh_btn.grid(row=0, column=1, rowspan=2, sticky="e")
        top.columnconfigure(0, weight=1)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, **pad)
        self.nb = nb
        brick = self._tab_brick(nb)          # creates the slot setting the editor shares
        self.editor = ed.Editor(nb, self)
        nb.add(self.editor, text="  Editor  ")
        nb.add(brick, text="  Brick  ")
        nb.add(self._tab_remote(nb), text="  Remote  ")
        if WINDOWS:
            nb.add(self._tab_bridge(nb), text="  Bridge (BricxCC / NQC)  ")
        nb.add(self._tab_setup(nb), text="  Setup  ")

        self.progress = ttk.Progressbar(self.root, maximum=100)
        self.progress.pack(fill="x", **pad)
        self.busy_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.busy_var).pack(anchor="w", padx=8)

        logf = ttk.Frame(self.root)
        logf.pack(fill="x", **pad)
        self.log_box = tk.Text(logf, height=5, state="disabled", wrap="word", font=(MONO_FONT, 9))
        sb = ttk.Scrollbar(logf, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

    def _tab_brick(self, parent):
        f = ttk.Frame(parent, padding=10)
        fwf = ttk.LabelFrame(f, text="Firmware", padding=8)
        fwf.pack(fill="x")
        self.fw_path = tk.StringVar(value=self.settings.get("firmware_path", ""))
        ttk.Entry(fwf, textvariable=self.fw_path).grid(row=0, column=0, sticky="ew")
        ttk.Button(fwf, text="Browse...", command=lambda: self._browse(
            self.fw_path, [("RCX firmware", "*.lgo *.srec"), ("All files", "*.*")])).grid(row=0, column=1, padx=4)
        ttk.Button(fwf, text="Download firmware", command=self.do_firmware).grid(row=0, column=2)
        self.fw_fast = tk.BooleanVar(value=bool(self.settings.get("firmware_fast", True)))
        ttk.Checkbutton(fwf, text="Fast", variable=self.fw_fast).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(fwf, text=("Leave the box empty to use the built-in LEGO firmware 3.2.8. " if fw.bundled_path() else "")
                  + "Needed once after the batteries have been out. Takes about a minute and a half with Fast ticked, "
                    "about four minutes without; keep the RCX close to the tower.", wraplength=540, foreground="#555").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        fwf.columnconfigure(0, weight=1)

        pf = ttk.LabelFrame(f, text="Program", padding=8)
        pf.pack(fill="x", pady=(10, 0))
        self.prog_path = tk.StringVar(value=self.settings.get("program_path", ""))
        ttk.Entry(pf, textvariable=self.prog_path).grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Button(pf, text="Browse...", command=lambda: self._browse(
            self.prog_path, [("NQC source or image", "*.nqc *.rcx"), ("All files", "*.*")])).grid(row=0, column=4, padx=4)
        ttk.Label(pf, text="Slot").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.slot = tk.IntVar(value=self.settings.get("slot", 1))
        ttk.Spinbox(pf, from_=1, to=5, width=3, textvariable=self.slot).grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.run_after = tk.BooleanVar(value=self.settings.get("run_after", False))
        ttk.Checkbutton(pf, text="Run after download", variable=self.run_after).grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Button(pf, text="Compile and download", command=self.do_program).grid(row=1, column=4, pady=(6, 0))
        pf.columnconfigure(3, weight=1)

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(10, 0))
        ttk.Button(bf, text="Run", command=lambda: self.simple("Starting program", lambda r: r.start_task(0))).pack(side="left")
        ttk.Button(bf, text="Stop", command=lambda: self.simple("Stopping", lambda r: r.stop_all())).pack(side="left", padx=4)
        ttk.Button(bf, text="Beep", command=lambda: self.simple("Beep", lambda r: r.play_sound(1))).pack(side="left")
        ttk.Button(bf, text="Switch RCX off", command=lambda: self.simple("Switching off", lambda r: r.power_off())).pack(side="right")
        return f

    def _tab_remote(self, parent):
        f = ttk.Frame(parent, padding=10)
        mf = ttk.LabelFrame(f, text="Motors", padding=8)
        mf.pack(fill="x")
        self.power = tk.IntVar(value=7)
        for row, (name, mask) in enumerate((("A", 1), ("B", 2), ("C", 4))):
            ttk.Label(mf, text="Motor " + name, width=9).grid(row=row, column=0, pady=2)
            ttk.Button(mf, text="<< Reverse", command=lambda m=mask: self.motor(m, False)).grid(row=row, column=1, padx=2)
            ttk.Button(mf, text="Stop", command=lambda m=mask: self.simple("Motor stop", lambda r: r.motors(m, "off"))).grid(row=row, column=2, padx=2)
            ttk.Button(mf, text="Forward >>", command=lambda m=mask: self.motor(m, True)).grid(row=row, column=3, padx=2)
        ttk.Label(mf, text="Power").grid(row=0, column=4, padx=(16, 4))
        ttk.Spinbox(mf, from_=0, to=7, width=3, textvariable=self.power).grid(row=0, column=5)
        ttk.Button(mf, text="Stop all motors", command=lambda: self.simple("Motors off", lambda r: r.motors(7, "off"))).grid(
            row=2, column=4, columnspan=2, padx=(16, 0))

        sf = ttk.LabelFrame(f, text="Sounds", padding=8)
        sf.pack(fill="x", pady=(10, 0))
        for i, name in enumerate(("Click", "Beep beep", "Down", "Up", "Low buzz", "Fast up")):
            ttk.Button(sf, text=name, command=lambda n=i: self.simple("Sound", lambda r: r.play_sound(n))).pack(side="left", padx=2)

        vf = ttk.LabelFrame(f, text="Sensors", padding=8)
        vf.pack(fill="x", pady=(10, 0))
        self.sensor_kinds = []
        self.sensor_vals = []
        self._sensor_applied = {}
        saved = self.settings.get("sensors", [])
        for i in range(3):
            ttk.Label(vf, text="Input %d" % (i + 1)).grid(row=i, column=0, sticky="w", pady=1)
            kind = tk.StringVar(value=saved[i] if i < len(saved) and saved[i] in SENSOR_CHOICES else SENSOR_CHOICES[0])
            ttk.Combobox(vf, textvariable=kind, values=SENSOR_CHOICES, state="readonly", width=20).grid(
                row=i, column=1, padx=6, pady=1)
            val = tk.StringVar(value="-")
            ttk.Label(vf, textvariable=val, font=(MONO_FONT, 10), width=16).grid(row=i, column=2, sticky="w")
            self.sensor_kinds.append(kind)
            self.sensor_vals.append(val)
        ttk.Button(vf, text="Read sensors", command=self.read_sensors).grid(row=0, column=3, padx=(10, 0))
        self.sensor_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(vf, text="Keep reading", variable=self.sensor_auto,
                        command=self.read_sensors).grid(row=1, column=3, padx=(10, 0), sticky="w")
        ttk.Label(f, text="Motor, sound and sensor control need firmware on the RCX.", foreground="#555").pack(anchor="w", pady=(8, 0))
        return f

    def _tab_bridge(self, parent):
        f = ttk.Frame(parent, padding=10)
        ttk.Label(f, wraplength=560, text=(
            "The bridge lets BricxCC, NQC and other RCX software use the tower unchanged. "
            "USB mode needs nothing installed: the software is told the tower is on port 'usb'. "
            "COM port mode imitates the old serial tower and needs com0com; use it only for "
            "software that cannot talk to a USB tower.")).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Mode").pack(side="left")
        self.pair_var = tk.StringVar()
        self.pair_box = ttk.Combobox(row, textvariable=self.pair_var, state="readonly", width=30)
        self.pair_box.pack(side="left", padx=6)
        self.bridge_btn = ttk.Button(row, text="Start bridge", command=self.toggle_bridge)
        self.bridge_btn.pack(side="left")
        self.autostart = tk.BooleanVar(value=self.settings.get("bridge_autostart", False))
        ttk.Checkbutton(row, text="Start with the app", variable=self.autostart, command=self._save).pack(side="left", padx=10)
        self.bridge_var = tk.StringVar(value="Bridge is off.")
        ttk.Label(f, textvariable=self.bridge_var, font=(UI_FONT, 10, "bold"), wraplength=560).pack(anchor="w", pady=(10, 0))
        self.bridge_hint = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.bridge_hint, wraplength=560, foreground="#555").pack(anchor="w", pady=(4, 0))

        bx = ttk.LabelFrame(f, text="BricxCC", padding=8)
        bx.pack(fill="x", pady=(12, 0))
        self.bricx_btn = ttk.Button(bx, text="Start BricxCC", command=self.start_bricxcc)
        self.bricx_btn.pack(side="left")
        self.bricx_var = tk.StringVar(value="")
        ttk.Label(bx, textvariable=self.bricx_var, wraplength=430, foreground="#444").pack(side="left", padx=10)

        opts = ttk.LabelFrame(f, text="Running in the background", padding=8)
        opts.pack(fill="x", pady=(12, 0))
        self.keep_in_tray = tk.BooleanVar(value=self.settings.get("keep_in_tray", True))
        ttk.Checkbutton(opts, text="Keep running in the tray when the window is closed",
                        variable=self.keep_in_tray, command=self._save).pack(anchor="w")
        self.with_windows = tk.BooleanVar(value=autostart_enabled())
        cb = ttk.Checkbutton(opts, text="Start with Windows, hidden in the tray",
                             variable=self.with_windows, command=self._toggle_autostart)
        cb.pack(anchor="w")
        if not FROZEN:
            cb.configure(state="disabled", text="Start with Windows, hidden in the tray (only in RCX Tower.exe)")
        return f

    def start_bricxcc(self):
        """Start BricxCC so it can use the USB bridge: give it our TOWERAPI.DLL and run the bridge."""
        exe = ta.find_bricxcc()
        if not exe:
            self.log("BricxCC is not installed in Program Files. See the Setup tab.")
            return
        state = ta.bricxcc_state(exe)

        def job():
            if state == "blocked":
                self.log("Another TOWERAPI.DLL on this PC would be used instead of RCX Tower's. Copying ours into "
                         "the BricxCC folder; Windows will ask for permission.")
                if not ta.copy_into_bricxcc(exe):
                    self.log("The copy was cancelled, so BricxCC cannot use the USB bridge yet.")
                    return
                for _ in range(60):
                    time.sleep(0.5)
                    if ta.bricxcc_state(exe) == "ready":
                        break
                else:
                    self.log("The file did not arrive in the BricxCC folder. Was the permission prompt refused?")
                    return
            if not isinstance(self.bridge, br.UsbBridge):
                self._bridge_off()
                self._bridge_on(br.USB_PORT)
            ta.start_bricxcc(exe)
            self.log("BricxCC started. In its Find Brick box choose port 'usb' and brick type RCX2. "
                     "If BricxCC was already open, close that one and use the new window.")
        self.submit("Starting BricxCC", job, raw=True)

    def _toggle_autostart(self):
        try:
            set_autostart(bool(self.with_windows.get()))
            self.log("Start with Windows is now %s." % ("on" if self.with_windows.get() else "off"))
        except OSError as e:
            self.log("Could not change the Windows startup setting: %s" % e)
            self.with_windows.set(autostart_enabled())

    # ---- tray ------------------------------------------------------------
    def _tray_menu(self):
        return [("open", "Open RCX Tower"),
                ("bridge", "Stop bridge" if self.bridge else "Start bridge"),
                (None, None),
                ("exit", "Exit")]

    def _tray_action(self, action):
        if action == "open":
            self.show()
        elif action == "bridge":
            self.toggle_bridge()
        elif action == "exit":
            self.quit()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self):
        if self.tray and self.keep_in_tray.get():
            self._save()
            self.root.withdraw()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.tray.notify("RCX Tower is still running",
                                 "Find it in the tray next to the clock. Right-click the icon to exit.")
        else:
            self.quit()

    def _tab_setup(self, parent):
        f = ttk.Frame(parent, padding=10)
        self.setup_rows = {}
        self.setup_buttons = {}
        if WINDOWS:
            items = (
                ("tower", "1. USB tower driver (WinUSB)", "Install tower driver", self.install_driver),
                ("nqc", "2. NQC compiler (to download .nqc programs)", "Get BricxCC", BRICXCC_URL),
                ("com0com", "Optional: virtual COM port (only for COM port mode)", "Get com0com", COM0COM_URL),
            )
        else:
            items = (
                ("tower", "1. USB access (pyusb and libusb)", "How to install", PYUSB_URL),
                ("nqc", "2. NQC compiler (to download .nqc programs)", "Get NQC", NQC_URL),
            )
        for key, title, btn, url in items:
            box = ttk.Frame(f)
            box.pack(fill="x", pady=4)
            mark = tk.StringVar(value="...")
            detail = tk.StringVar(value="")
            ttk.Label(box, textvariable=mark, width=10, font=(UI_FONT, 9, "bold")).grid(row=0, column=0, sticky="nw")
            ttk.Label(box, text=title, font=(UI_FONT, 10, "bold")).grid(row=0, column=1, sticky="w")
            action = url if callable(url) else (lambda u=url: webbrowser.open(u))
            button = ttk.Button(box, text=btn, command=action)
            button.grid(row=0, column=2, sticky="e")
            ttk.Label(box, textvariable=detail, wraplength=440, foreground="#444").grid(row=1, column=1, sticky="w")
            box.columnconfigure(1, weight=1)
            self.setup_rows[key] = (mark, detail)
            self.setup_buttons[key] = button
        ttk.Separator(f).pack(fill="x", pady=(12, 8))
        box = ttk.Frame(f)
        box.pack(fill="x")
        ttk.Label(box, text="Something not working?", font=(UI_FONT, 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(box, wraplength=440, foreground="#444",
                  text="Copy diagnostics tests the tower and the RCX and copies the result, with the recent log, "
                       "so you can paste it into a message.").grid(row=1, column=0, sticky="w")
        ttk.Button(box, text="Copy diagnostics", command=self.copy_diagnostics).grid(row=0, column=1, sticky="e")
        ttk.Button(box, text="Open log folder", command=self.open_log_folder).grid(row=1, column=1, sticky="ne")
        box.columnconfigure(0, weight=1)
        return f

    def install_driver(self):
        """Bind Windows' built-in WinUSB driver to the tower (one admin prompt)."""
        def job():
            if tw.tower_state() == "absent":
                self.log("Plug the tower in first.")
                return
            self.log("Installing the tower driver. Windows will ask for permission.")
            if not drv.start_elevated():
                self.log("The permission prompt was cancelled; nothing was changed.")
                return
            lines = None
            for _ in range(120):
                time.sleep(0.5)
                lines = drv.read_result()
                if lines:
                    break
            for line in lines or ["No answer from the installer (was the permission prompt refused?)."]:
                self.log("  " + line)
            for _ in range(20):  # the device takes a moment to come back
                if tw.tower_state() == "ready":
                    self.log("The tower driver is installed and working.")
                    return
                time.sleep(0.5)
            self.log("The tower is still not usable. Unplug it and plug it back in; if that does not help, "
                     "bind WinUSB with Zadig instead (%s)." % ZADIG_URL)
        self.submit("Installing the tower driver", job, raw=True)

    # ---- helpers ---------------------------------------------------------
    def _browse(self, var, types):
        start = os.path.dirname(var.get()) if var.get() else None
        path = filedialog.askopenfilename(filetypes=types, initialdir=start)
        if path:
            var.set(path)
            self._save()

    def _save(self):
        try:
            slot = int(self.slot.get())
        except (tk.TclError, ValueError):
            slot = 1
        self.settings.update(firmware_fast=bool(self.fw_fast.get()))
        self.settings.update(firmware_path=self.fw_path.get(), program_path=self.prog_path.get(), slot=slot,
                             run_after=bool(self.run_after.get()))
        if WINDOWS:
            self.settings.update(bridge_autostart=bool(self.autostart.get()),
                                 keep_in_tray=bool(self.keep_in_tray.get()), pair=self.pair_var.get())
        save_settings(self.settings)

    def _tk_error(self, kind, value, tb):
        import traceback
        diag.write("Error in the window:\n%s" % "".join(traceback.format_exception(kind, value, tb)))
        self._append_log("Something went wrong in the window: %s (details are in the log file)" % value)

    def log(self, text):
        diag.write(text)
        self.events.put(("log", text))

    def copy_diagnostics(self):
        """Put a report for a bug report on the clipboard (and in diagnostics.txt next to the log)."""
        bridge = None
        if self.bridge is not None:
            bridge = "running, %s" % type(self.bridge).__name__
        extra = ["Status shown: %s | %s" % (self.tower_var.get(), self.rcx_var.get())]

        running = self._job
        if running:
            # The worker is busy, perhaps for ever: report from here, without touching the tower.
            extra.append("A job is running: '%s' for %d s; no tower activity for %d s" % (
                running[0], time.monotonic() - running[1], diag.quiet_seconds()))
            extra.append("Where each thread is:")
            extra += ["  " + line for line in diag.thread_stacks().splitlines()]

        def job():
            text = diag.report(bridge=bridge, extra=extra, live=not running)
            diag.write("Diagnostics report made.")
            try:
                with open(os.path.join(os.path.dirname(SETTINGS), "diagnostics.txt"), "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
            self.events.put(("clipboard", text))
        if running:
            threading.Thread(target=job, name="diagnostics", daemon=True).start()
        else:
            self.submit("Collecting diagnostics", job, raw=True)

    def open_log_folder(self):
        folder = os.path.dirname(SETTINGS)
        os.makedirs(folder, exist_ok=True)
        if WINDOWS:
            os.startfile(folder)
        else:
            webbrowser.open("file://" + folder)

    def _append_log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("%H:%M:%S  ") + text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---- worker thread: everything that touches the tower ----------------
    def submit(self, label, fn, raw=False):
        """fn(rcx) runs on the worker with the tower open; raw jobs get no tower."""
        self.jobs.put((label, fn, raw))

    def _worker(self):
        while True:
            label, fn, raw = self.jobs.get()
            self.events.put(("busy", label))
            resume = False
            began = time.monotonic()
            self._job = (label, began)
            self._job_warned = False
            diag.write("Job started: %s" % label)
            try:
                if raw:
                    fn()
                else:
                    resume = self._bridge_off()
                    with tw.Tower() as t:
                        t.set_parm(tw.PARM_RANGE, tw.RANGE_LONG)
                        fn(RCX(t))
            except Exception as e:
                diag.write_exception(label)
                self.log("%s failed: %s" % (label, e))
            finally:
                if resume:
                    try:
                        self._bridge_on(self._bridge_port)
                    except Exception as e:
                        diag.write_exception("Restarting the bridge")
                        self.log("Could not restart the bridge: %s" % e)
                diag.write("Job ended: %s (%.1f s)" % (label, time.monotonic() - began))
                self._job = None
                self.events.put(("idle", None))

    def _bridge_on(self, port):
        self.bridge_tower = tw.Tower()
        try:
            self.bridge_tower.set_parm(tw.PARM_RANGE, tw.RANGE_LONG)
            self.bridge_tower.set_speed(tw.SPEED_2400)  # a cut-short fast download leaves it at 4800
            if port == br.USB_PORT:
                self.bridge = br.UsbBridge(self.bridge_tower, on_bytes=self._bridge_event)
            else:
                self.bridge = br.Bridge(self.bridge_tower, port)
            self.bridge.start()
        except Exception:
            self.bridge_tower.close()
            self.bridge_tower = None
            self.bridge = None
            raise
        self._bridge_port = port

    @staticmethod
    def _bridge_event(kind, data):
        """Runs on the bridge thread. The bytes themselves are already in the log as tower traffic."""
        if kind in ("open", "close", "timeout"):
            diag.write("    bridge: %s" % {"open": "a program connected", "close": "the program disconnected",
                                           "timeout": "told the program that the RCX did not answer"}[kind])

    def _bridge_off(self):
        """Stop the bridge if it runs. Returns True if it was running."""
        was = self.bridge is not None
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        if self.bridge_tower:
            self.bridge_tower.close()
            self.bridge_tower = None
        return was

    # ---- actions ---------------------------------------------------------
    def refresh(self):
        def job(rcx):
            if not rcx.ping(retries=3):
                self.events.put(("rcx", "RCX: no answer. Switch it on and point it at the tower."))
                return
            v = rcx.versions()
            if v["has_firmware"]:
                text = "RCX: firmware %s, battery %.1f V" % (v["firmware"], rcx.battery_volts())
            else:
                text = "RCX: answering, but no firmware loaded (ROM %s)" % v["rom"]
            self.events.put(("rcx", text))
        self.submit("Checking the RCX", job)

    def simple(self, label, fn):
        self.submit(label, fn)

    def motor(self, mask, forward):
        try:
            level = max(0, min(7, int(self.power.get())))
        except (tk.TclError, ValueError):
            level = 7

        def job(rcx):
            rcx.motor_power(mask, level)
            rcx.motor_direction(mask, forward)
            rcx.motors(mask, "on")
        self.submit("Motor on", job)

    def read_sensors(self):
        kinds = [k.get() for k in self.sensor_kinds]
        self.settings["sensors"] = kinds
        save_settings(self.settings)

        def job(rcx):
            out = []
            for port, kind in enumerate(kinds, 1):
                if kind != SENSOR_CHOICES[0] and self._sensor_applied.get(port) != kind:
                    rcx.set_sensor(port, kind)
                    self._sensor_applied[port] = kind
                    time.sleep(0.15)  # let the reading settle after a type change
                v = rcx.sensor(port)
                if kind == "light":
                    out.append("%d %%" % v)
                elif kind == "touch":
                    out.append("pressed" if v else "released")
                elif kind == "temperature":
                    out.append("%.1f C" % (v / 10.0))
                elif kind == "rotation":
                    out.append("%d steps" % v)
                else:
                    out.append(str(v))
            self.events.put(("sensors", out))
        self.submit("Reading sensors", job)

    def do_firmware(self):
        path = self.fw_path.get().strip() or (fw.bundled_path() or "")
        if not os.path.isfile(path):
            self.log("Choose a firmware file first (for example firm0328.lgo).")
            return
        self.log("Using firmware file %s" % os.path.basename(path))
        self._save()
        fast = bool(self.fw_fast.get())

        def job(rcx):
            image = fw.load_srec(path)
            self.log("Firmware image is %d bytes. Sending%s..." % (len(image), " (fast)" if fast else ""))
            if not fast and not rcx.ping(retries=3):
                raise RuntimeError("the RCX does not answer")
            start = time.monotonic()
            v = rcx.download_firmware(image, lambda d, t: self.events.put(("progress", 100.0 * d / t)),
                                      fast=fast, note=self.log)
            self.log("Firmware %s installed in %d seconds." % (v["firmware"], time.monotonic() - start))
            self.events.put(("rcx", "RCX: firmware %s" % v["firmware"]))
        self.submit("Downloading firmware", job)

    def do_program(self):
        path = self.prog_path.get().strip()
        if not os.path.isfile(path):
            self.log("Choose an .nqc or .rcx file first.")
            return
        self._save()
        slot = self.settings.get("slot", 1)
        run = self.settings.get("run_after", False)

        def job(rcx):
            if path.lower().endswith(".rcx"):
                with open(path, "rb") as f:
                    image = f.read()
            else:
                image, messages = nqc.compile_nqc(path)
                if messages:
                    self.log(messages)
            n = rcx.download_program(image, slot, lambda d, t: self.events.put(("progress", 100.0 * d / max(t, 1))))
            self.log("Downloaded %s to slot %d (%d task/sub)." % (os.path.basename(path), slot, n))
            if run:
                rcx.start_task(0)
        self.submit("Downloading program", job)

    def toggle_bridge(self):
        if self.bridge:
            self.submit("Stopping bridge", self._bridge_off, raw=True)
        else:
            self.start_bridge()

    def start_bridge(self):
        pair = self.pair_var.get()
        port = pair.split("<->")[1].strip() if "<->" in pair else br.USB_PORT
        self._save()
        self.submit("Starting bridge", lambda: self._bridge_on(port), raw=True)

    # ---- periodic UI work ------------------------------------------------
    def _pump(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._append_log(data)
                elif kind == "busy":
                    self.busy = True
                    self.busy_var.set(data + "...")
                    self.progress["value"] = 0
                elif kind == "idle":
                    self.busy = self.jobs.qsize() > 0
                    if not self.busy:
                        self.busy_var.set("Ready")
                        self.progress["value"] = 0
                elif kind == "rcx":
                    self.rcx_var.set(data)
                    self._append_log(data)
                elif kind == "sensors":
                    for var, text in zip(self.sensor_vals, data):
                        var.set(text)
                    if self.sensor_auto.get() and self.root.state() == "normal" and not self.jobs.qsize():
                        self.root.after(400, lambda: self.sensor_auto.get() and self.read_sensors())
                elif kind == "progress":
                    self.progress["value"] = data
                elif kind == "clipboard":
                    self.root.clipboard_clear()
                    self.root.clipboard_append(data)
                    self.root.update()
                    self._append_log("Diagnostics copied (%d lines). Paste them into your message. "
                                     "They are also saved as diagnostics.txt in the log folder." % len(data.splitlines()))
                elif kind == "editor":
                    self.editor.show_messages(*data)
                elif kind == "tray":
                    self._tray_action(data)
                    if data == "exit":
                        return
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    STUCK_SECONDS = 20

    def _watch_job(self):
        """A job that has done nothing with the tower for a while: say so, and record where it waits."""
        job = self._job
        if not job or self._job_warned:
            return
        label, began = job
        if time.monotonic() - began > self.STUCK_SECONDS and diag.quiet_seconds() > self.STUCK_SECONDS:
            self._job_warned = True
            diag.write("STUCK: '%s' has been running for %d s with no tower activity for %d s.\n%s" % (
                label, time.monotonic() - began, diag.quiet_seconds(), diag.thread_stacks()))
            self._append_log("%s is taking unusually long. Unplug the tower and plug it back in. If it happens "
                             "again, use Copy diagnostics on the Setup tab and send the result." % label)

    def _tick(self):
        self._watch_job()
        try:
            state = "ready" if self.bridge else tw.tower_state()
        except Exception as e:
            if not getattr(self, "_tick_failed", False):
                self._tick_failed = True
                diag.write_exception("Looking for the tower")
                self.log("Looking for the tower failed: %s" % e)
            state = "absent"
        if state != getattr(self, "_last_state", None):
            diag.write("Tower state: %s -> %s" % (getattr(self, "_last_state", None), state))
            self._last_state = state
        self.tower_var.set({"ready": "Tower: connected", "nodriver": "Tower: plugged in, but the driver is missing for this USB port (see Setup)",
                            "nolib": "Tower: the USB library is missing (see Setup)",
                            "absent": "Tower: not plugged in"}[state])
        mark, detail = self.setup_rows["tower"]
        mark.set({"ready": "OK", "nodriver": "TO DO", "nolib": "TO DO", "absent": "?"}[state])
        if WINDOWS:
            detail.set({
                "ready": "WinUSB is bound to the tower.",
                "nodriver": "Click Install tower driver. It uses the WinUSB driver that is already part of Windows; "
                            "nothing is downloaded. Windows asks for permission once per USB port: after moving "
                            "the tower to another port, install again.",
                "nolib": "The libusb backend was chosen but pyusb or libusb is missing.",
                "absent": "Plug the tower in to check its driver."}[state])
            self.setup_buttons["tower"].state(["!disabled"] if state == "nodriver" else ["disabled"])
        else:
            detail.set({
                "ready": "The tower is reachable. No driver is needed on this system.",
                "nolib": "In a terminal run:  pip3 install pyusb libusb-package",
                "absent": "The USB library is installed. Plug the tower in."}.get(state, ""))

        path = nqc.find_nqc()
        mark, detail = self.setup_rows["nqc"]
        mark.set("OK" if path else "TO DO")
        if WINDOWS:
            detail.set("Found: %s" % path if path else
                       "Install BricxCC (it includes nqc.exe), or put nqc.exe next to this program.")
        else:
            detail.set("Found: %s" % path if path else
                       "Build NQC from its source and put the 'nqc' program on your PATH or next to this app. "
                       "Ready-made .rcx files can be downloaded without it.")
        if WINDOWS:
            self._tick_windows()
        self.root.after(1500, self._tick)

    def _tick_windows(self):
        """Keep the bridge, BricxCC and tray parts of the window up to date."""
        pairs = br.com0com_pairs()
        pair_names = ["COM port: %s <-> %s" % p for p in pairs]
        names = [USB_MODE] + pair_names
        if list(self.pair_box["values"]) != names:
            self.pair_box["values"] = names
            want = self.settings.get("pair", "")
            self.pair_var.set(want if want in names else USB_MODE)
        mark, detail = self.setup_rows["com0com"]
        mark.set("OK" if pairs else "not used")
        detail.set("Found: %s." % ", ".join("%s <-> %s" % p for p in pairs) if pairs else
                   "Not needed for USB mode. For COM port mode install the signed com0com build, make one "
                   "pair in its Setup tool and name one end e.g. COM2 (tick 'use Ports class').")

        if self.bridge:
            if self.bridge.error or not self.bridge.running:
                self.log("Bridge stopped: %s" % (self.bridge.error or "unknown reason"))
                self.submit("Stopping bridge", self._bridge_off, raw=True)
            else:
                app_port = self._app_port()
                if app_port == br.USB_PORT:
                    self.bridge_var.set("Bridge is running. In BricxCC choose port 'usb'; for NQC add -Susb.")
                    state = "A program is connected. " if self.bridge.client_connected else "No program connected yet. "
                else:
                    self.bridge_var.set("Bridge is running. In BricxCC or NQC choose port %s (serial tower)." % app_port)
                    state = ""
                self.bridge_hint.set("%sBrick type RCX2. Sent %d bytes, received %d bytes." % (
                    state, self.bridge.tx_count, self.bridge.rx_count))
                self.bridge_btn.configure(text="Stop bridge")
        else:
            self.bridge_var.set("Bridge is off.")
            self.bridge_hint.set("")
            self.bridge_btn.configure(text="Start bridge")
        exe = ta.find_bricxcc()
        if not exe:
            self.bricx_var.set("BricxCC is not installed.")
            self.bricx_btn.state(["disabled"])
        else:
            self.bricx_btn.state(["!disabled"])
            self.bricx_var.set({
                "ready": "Ready. Starts BricxCC and the USB bridge; choose port 'usb' in BricxCC.",
                "portable": "Starts BricxCC and the USB bridge; choose port 'usb' in BricxCC.",
                "blocked": "First use needs one admin prompt: LEGO's own TOWERAPI.DLL is on this PC and must be "
                           "overridden inside the BricxCC folder.",
            }[ta.bricxcc_state(exe)])
        if self.tray:
            if self.bridge:
                self.tray.set_tooltip("RCX Tower - bridge on %s" % self._app_port())
            else:
                self.tray.set_tooltip("RCX Tower - bridge off")

    def _app_port(self):
        """The port name the user gives to BricxCC / NQC for the running bridge."""
        if isinstance(self.bridge, br.UsbBridge):
            return br.USB_PORT
        pair = self.pair_var.get()
        return pair.split(":", 1)[-1].split("<->")[0].strip() if "<->" in pair else br.USB_PORT

    def quit(self, ask=True):
        if ask and not self.editor.confirm_close():
            self.show() if self.root.state() != "normal" else None
            return
        self._save()
        try:
            self._bridge_off()
            if self.tray:
                self.tray.stop()
                self.tray = None
        finally:
            self.root.destroy()


class SingleInstance:
    """Only one RCX Tower window per user: only one program can use the tower, so a second
    copy could do nothing but fail. Starting it again brings the first window to the front."""

    NAME = "Local\\RCXTower-running"
    SHOW = "Local\\RCXTower-show"

    def __init__(self):
        self.first = True
        self._event = None
        if not WINDOWS:
            return
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateEventW.restype = ctypes.c_void_p
        k32.SetEvent.argtypes = [ctypes.c_void_p]
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._k32 = k32
        self._mutex = k32.CreateMutexW(None, False, self.NAME)   # kept until the program ends
        self.first = ctypes.get_last_error() != 183              # ERROR_ALREADY_EXISTS
        self._event = k32.CreateEventW(None, False, False, self.SHOW)  # auto-reset

    def ask_first_to_show(self):
        if self._event:
            self._k32.SetEvent(self._event)

    def asked_to_show(self):
        """True once each time another copy was started."""
        return bool(self._event) and self._k32.WaitForSingleObject(self._event, 0) == 0


def run(selftest=False, start_hidden=False):
    single = SingleInstance()
    if not single.first and not selftest:
        single.ask_first_to_show()
        return 0
    root = tk.Tk()
    if WINDOWS:
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
    app = App(root, start_hidden=start_hidden)

    def watch_for_second_copy():
        if single.asked_to_show():
            diag.write("RCX Tower was started again; showing this window instead.")
            app.show()
        root.after(400, watch_for_second_copy)
    if single.first:
        watch_for_second_copy()
    if selftest:
        def editor_checks():
            e = app.editor
            e.new("task main()\n{\n    SetSensor(SENSOR_1, SENSOR_TOUCH);\n    Oops(;\n    int x = 3\n}\n")
            e.check()

            def after_bad():
                print("editor bad program:", list(e.msg_box.get(0, "end")))
                print("editor error lines marked:", [str(r) for r in e.text.tag_ranges("errline")][:4],
                      "| cursor at", e.text.index("insert"))
                e.text.edit_modified(False)
                e.new(ed.TEMPLATES[1][1])
                tags = {t: len(e.text.tag_ranges(t)) // 2 for t in ed.COLOURS}
                print("editor colouring (ranges per kind):", tags)
                e.check()
                root.after(1500, lambda: (print("editor good program:", list(e.msg_box.get(0, "end"))),
                                          e.text.edit_modified(False)))
            root.after(1500, after_bad)
        root.after(300, editor_checks)

        app.sensor_kinds[0].set("touch")
        app.sensor_kinds[2].set("light")
        root.after(1500, app.read_sensors)

        def tray_checks():
            # drive the tray the way clicks would: hide, reopen, toggle the bridge twice
            print("tray icon added:", bool(app.tray and app.tray.ok))
            print("tray menu:", [label for _a, label in app._tray_menu() if label])
            app.on_close()
            root.update()
            print("after closing the window: state =", root.state(), "(withdrawn = hidden in tray)")
            app.events.put(("tray", "open"))
            root.after(400, lambda: print("after tray 'open': state =", root.state()))
            root.after(500, lambda: app.events.put(("tray", "bridge")))
            root.after(2600, lambda: print("after tray 'start bridge':", app.bridge_var.get(),
                                           "| tooltip:", app.tray.tooltip if app.tray else None))
            root.after(2700, lambda: app.events.put(("tray", "bridge")))
            root.after(4800, lambda: print("after tray 'stop bridge':", app.bridge_var.get()))
            root.after(5000, report)

        def report():
            if app.busy or app.jobs.qsize():
                root.after(300, report)
                return
            print(app.tower_var.get())
            print(app.rcx_var.get())
            for key, (mark, detail) in app.setup_rows.items():
                print("setup %-8s %-6s %s" % (key, mark.get(), detail.get()))
            print("tabs:", [app.nb.tab(t, "text").strip() for t in app.nb.tabs()])
            if WINDOWS:
                print("pairs:", list(app.pair_box["values"]), "| selected:", app.pair_var.get())
                print("bridge:", app.bridge_var.get())
                print("bricxcc:", app.bricx_var.get())
            print("sensors:", [(k.get(), v.get()) for k, v in zip(app.sensor_kinds, app.sensor_vals)])
            print("log:", app.log_box.get("1.0", "end").strip().replace("\n", " | "))
            app.quit(ask=False)
        root.after(3000, tray_checks if WINDOWS else report)
    root.mainloop()
    return 0
