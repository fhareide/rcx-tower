"""The Editor tab: write NQC, check it, download it, jump to errors."""
import os
import re
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import nqc

MAC = sys.platform == "darwin"
MOD = "Command" if MAC else "Control"

KEYWORDS = """task sub void inline int const if else while do for repeat until switch case default
break continue return start stop asm acquire monitor catch true false abs sign""".split()

API = """SetSensor SetSensorType SetSensorMode ClearSensor SensorValue SensorType SensorMode SensorValueRaw
SensorValueBool SetOutput SetDirection SetPower On Off Float Fwd Rev Toggle OnFwd OnRev OnFor
SetGlobalOutput SetGlobalDirection SetMaxPower PlaySound PlayTone MuteSound UnmuteSound ClearSound
SelectDisplay SetUserDisplay SendMessage ClearMessage Message SetTxPower Wait StopAllTasks Random
SetRandomSeed SetSleepTime SleepNow ClearTimer Timer SetTimer FastTimer ClearCounter IncCounter DecCounter
Counter SetEvent ClearEvent ClearAllEvents EventState CalibrateEvent SetUpperLimit UpperLimit SetLowerLimit
LowerLimit SetHysteresis Hysteresis SetClickTime ClickTime SetClickCounter ClickCounter ActiveEvents Event
CreateDatalog AddToDatalog UploadDatalog SetWatch Watch Program SelectProgram BatteryLevel FirmwareVersion
SetSerialComm SetSerialPacket SetSerialData SerialData SendSerial SetPriority""".split()

CONSTANT = r"(?:SENSOR|OUT|SOUND|TX_POWER|DISPLAY|ACQUIRE|EVENT|SERIAL|STYPE|SMODE|EST|EVENT_TYPE)_[A-Z0-9_]+"

HIGHLIGHT = re.compile("|".join([
    r"(?P<com>//[^\n]*|/\*.*?\*/|/\*.*\Z)",
    r'(?P<str>"(?:[^"\\\n]|\\.)*"?)',
    r"(?P<pre>^[ \t]*#[^\n]*)",
    r"(?P<num>\b(?:0[xX][0-9a-fA-F]+|\d+)\b)",
    r"(?P<kw>\b(?:%s)\b)" % "|".join(KEYWORDS),
    r"(?P<api>\b(?:%s)\b(?=\s*\())" % "|".join(API),
    r"(?P<const>\b%s\b)" % CONSTANT,
]), re.S | re.M)

COLOURS = {"com": "#2e7d32", "str": "#a31515", "pre": "#7b3fa0", "num": "#b5651d",
           "kw": "#0033b3", "api": "#00627a", "const": "#8a5a00"}
# the same kinds on a dark background
COLOURS_DARK = {"com": "#7fbf7f", "str": "#e39a8a", "pre": "#c99be0", "num": "#e0b070",
                "kw": "#7aa8ff", "api": "#5cc8d8", "const": "#e0c070"}
# everything else that has a fixed colour: (light, dark)
SHADES = {"gutter": ("#f0f0f0", "#2a2a2a"), "number": ("#888888", "#8a8a8a"),
          "errline": ("#ffd6d6", "#5a2626"), "warnline": ("#fff3bf", "#4e4520"),
          "ok": ("#1b6e1b", "#7fd67f"), "bad": ("#b00020", "#ff8a8a")}

TEMPLATES = [
    ("Empty program", "task main()\n{\n    \n}\n"),
    ("Motor A while touch sensor 1 is pressed", """task main()
{
    SetSensor(SENSOR_1, SENSOR_TOUCH);
    SetPower(OUT_A, 7);
    SetDirection(OUT_A, OUT_FWD);

    while (true)
    {
        if (SENSOR_1 == 1)
            On(OUT_A);
        else
            Off(OUT_A);
    }
}
"""),
    ("Motor A by light sensor 3", """#define THRESHOLD 45        // percent

task main()
{
    SetSensor(SENSOR_3, SENSOR_LIGHT);
    SetPower(OUT_A, 7);
    SetDirection(OUT_A, OUT_FWD);

    while (true)
    {
        if (SENSOR_3 < THRESHOLD)
            On(OUT_A);
        else
            Off(OUT_A);
    }
}
"""),
    ("Drive forward, turn on bump", """// Motors on A and C, touch sensor on input 1.

task main()
{
    SetSensor(SENSOR_1, SENSOR_TOUCH);

    while (true)
    {
        OnFwd(OUT_A + OUT_C);
        until (SENSOR_1 == 1);      // wait for a bump

        OnRev(OUT_A + OUT_C);       // back off
        Wait(50);                   // 0.5 s
        OnFwd(OUT_A);               // spin
        Wait(40);
    }
}
"""),
]

SNIPPETS = [
    ("if / else", "if (condition)\n{\n    \n}\nelse\n{\n    \n}\n"),
    ("while loop", "while (condition)\n{\n    \n}\n"),
    ("repeat N times", "repeat (4)\n{\n    \n}\n"),
    ("wait until", "until (SENSOR_1 == 1);\n"),
    ("new task", "task name()\n{\n    \n}\n"),
    ("subroutine", "sub name()\n{\n    \n}\n"),
    ("touch sensor on input 1", "SetSensor(SENSOR_1, SENSOR_TOUCH);\n"),
    ("light sensor on input 3", "SetSensor(SENSOR_3, SENSOR_LIGHT);\n"),
    ("rotation sensor on input 2", "SetSensor(SENSOR_2, SENSOR_ROTATION);\n"),
    ("play a sound", "PlaySound(SOUND_UP);\n"),
    ("play a tone", "PlayTone(440, 50);   // 440 Hz for 0.5 s\n"),
]

ERROR_LINE = re.compile(r"^#\s*(Error|Warning):\s*(.*)$")
FILE_LINE = re.compile(r'^File\s+"([^"]*)"\s*;\s*line\s+(\d+)')


def parse_messages(text):
    """NQC's output as a list of (kind, message, file, line). line is None when NQC gave none."""
    found = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = ERROR_LINE.match(line.strip())
        if not m:
            continue
        fname, lineno = "", None
        if i + 1 < len(lines):
            f = FILE_LINE.match(lines[i + 1].strip())
            if f:
                fname, lineno = f.group(1), int(f.group(2))
        found.append((m.group(1), m.group(2), fname, lineno))
    return found


class Editor(ttk.Frame):
    """app must offer: submit(label, fn, raw), events (queue), log(text), slot (IntVar), settings, mono_font."""

    _transferred = None   # (text, slot) of the last successful download from this editor

    def __init__(self, parent, app):
        super().__init__(parent, padding=(6, 6, 6, 4))
        self.app = app
        self.path = None
        self._highlight_job = None
        self._messages = []
        self._build()
        last = app.settings.get("editor_file", "")
        if last and os.path.isfile(last):
            self._load(last)
        else:
            self._set_text(TEMPLATES[0][1])
            self.text.mark_set("insert", "3.4")
        self.text.edit_modified(False)
        self._update_title()

    # ---- layout ----------------------------------------------------------
    def _shade(self, name):
        return SHADES[name][1 if self._dark else 0]

    def _build(self):
        self._dark = bool(getattr(self.app, "dark", False))
        muted = getattr(self.app, "muted", "#555555")
        native = sys.platform == "win32" and not os.environ.get("RCXTOWER_PORTABLE_UI")   # elsewhere buttons are wider: use two rows and natural widths
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        for label, cmd in (("New", self.new), ("Open...", self.open), ("Save", self.save), ("Save as...", self.save_as)):
            button = ttk.Button(bar, text=label, command=cmd)
            if native:
                button.configure(width=len(label) + 1)
            button.pack(side="left", padx=(0, 3))

        insert = ttk.Menubutton(bar, text="Insert")
        menu = tk.Menu(insert, tearoff=False)
        for label, code in SNIPPETS:
            menu.add_command(label=label, command=lambda c=code: self.insert_snippet(c))
        menu.add_separator()
        examples = tk.Menu(menu, tearoff=False)
        for label, code in TEMPLATES:
            examples.add_command(label=label, command=lambda c=code: self.new(c))
        menu.add_cascade(label="New from example", menu=examples)
        insert["menu"] = menu
        insert.pack(side="left", padx=(6, 0))

        if not native:
            bar = ttk.Frame(self)
            bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="Stop (F8)", command=self.stop_program).pack(side="right")
        ttk.Button(bar, text="Run (F7)", command=self.run_program).pack(side="right", padx=3)
        ttk.Button(bar, text="Download (F6)", command=self.download).pack(side="right")
        ttk.Button(bar, text="Check (F5)", command=self.check).pack(side="right", padx=3)
        ttk.Spinbox(bar, from_=1, to=5, width=2, textvariable=self.app.slot).pack(side="right")
        ttk.Label(bar, text="Slot").pack(side="right", padx=(0, 3))

        self.title_var = tk.StringVar()
        ttk.Label(self, textvariable=self.title_var, foreground=muted).pack(anchor="w", pady=(4, 2))

        # messages go in first (at the bottom) so the editor gets the space that is left
        self.msg_box = tk.Listbox(self, height=4, activestyle="none", font=(self.app.mono_font, 9))
        self.msg_box.pack(side="bottom", fill="x", pady=(4, 0))
        self.msg_box.bind("<<ListboxSelect>>", self._goto_message)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        font = (self.app.mono_font, 11)
        self.gutter = tk.Canvas(body, width=38, highlightthickness=0, background=self._shade("gutter"))
        self.gutter.pack(side="left", fill="y")
        scroll = ttk.Scrollbar(body, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.text = tk.Text(body, wrap="none", undo=True, maxundo=-1, autoseparators=True, font=font,
                            height=12, tabs=("4c",), insertwidth=2, padx=4, pady=2,
                            yscrollcommand=lambda a, b: (scroll.set(a, b), self._draw_gutter()))
        self.text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.text.yview)
        self._font = font

        for tag, colour in (COLOURS_DARK if self._dark else COLOURS).items():
            self.text.tag_configure(tag, foreground=colour)
        self.text.tag_configure("com", font=(font[0], font[1], "italic"))
        self.text.tag_configure("errline", background=self._shade("errline"))
        self.text.tag_configure("warnline", background=self._shade("warnline"))
        self.text.tag_raise("sel")

        t = self.text
        t.bind("<<Modified>>", self._on_modified)
        t.bind("<KeyRelease>", lambda e: self._schedule_highlight())
        t.bind("<Configure>", lambda e: self._draw_gutter())
        t.bind("<Return>", self._newline)
        t.bind("<Tab>", self._tab)
        t.bind("<KeyPress-braceright>", self._close_brace)
        for seq, cmd in (("<%s-s>" % MOD, self.save), ("<%s-o>" % MOD, self.open), ("<%s-n>" % MOD, self.new),
                         ("<F5>", self.check), ("<F6>", self.download), ("<F7>", self.run_program),
                         ("<F8>", self.stop_program)):
            t.bind(seq, lambda e, c=cmd: (c(), "break")[1])

    # ---- text helpers ----------------------------------------------------
    def get_text(self):
        return self.text.get("1.0", "end-1c")

    def _set_text(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.edit_reset()
        self.clear_messages()
        self.highlight()

    def _newline(self, event):
        line = self.text.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        if line.rstrip().endswith("{"):
            indent += "    "
        self.text.insert("insert", "\n" + indent)
        self.text.see("insert")
        return "break"

    def _tab(self, event):
        self.text.insert("insert", "    ")
        return "break"

    def _close_brace(self, event):
        # typing } on an otherwise empty line moves it one level back
        before = self.text.get("insert linestart", "insert")
        if before and not before.strip() and len(before) >= 4:
            self.text.delete("insert-4c", "insert")
        return None

    def insert_snippet(self, code):
        line = self.text.get("insert linestart", "insert")
        indent = line if not line.strip() else ""
        body = code.replace("\n", "\n" + indent).rstrip(" ")
        self.text.insert("insert", body)
        self.text.focus_set()
        self._schedule_highlight(1)

    def _on_modified(self, event=None):
        self._update_title()
        self._draw_gutter()

    def _update_title(self):
        name = self.path or "untitled.nqc (not saved yet)"
        self.title_var.set(("* " if self.text.edit_modified() else "") + name)

    def _draw_gutter(self):
        g = self.gutter
        g.delete("all")
        index = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            number = index.split(".")[0]
            g.create_text(34, info[1] + 2, anchor="ne", text=number, fill=self._shade("number"), font=(self._font[0], 9))
            index = self.text.index("%s+1line" % index)
            if index.split(".")[0] == number:
                break

    def _schedule_highlight(self, delay=150):
        if self._highlight_job:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(delay, self.highlight)

    def highlight(self):
        self._highlight_job = None
        content = self.get_text()
        for tag in COLOURS:
            self.text.tag_remove(tag, "1.0", "end")
        for m in HIGHLIGHT.finditer(content):
            tag = m.lastgroup
            self.text.tag_add(tag, "1.0+%dc" % m.start(), "1.0+%dc" % m.end())
        self._draw_gutter()

    # ---- files -----------------------------------------------------------
    def _may_discard(self):
        if not self.text.edit_modified():
            return True
        answer = messagebox.askyesnocancel("RCX Tower", "Save the changes to %s?" % (
            os.path.basename(self.path) if self.path else "this program"))
        if answer is None:
            return False
        return self.save() if answer else True

    def new(self, content=None):
        if not self._may_discard():
            return
        self.path = None
        self._set_text(content if content is not None else TEMPLATES[0][1])
        self.text.edit_modified(False)
        self._update_title()
        self.text.focus_set()

    def _load(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            self.app.log("Cannot open %s: %s" % (path, e))
            return False
        self.path = path
        self._set_text(content)
        self.text.edit_modified(False)
        self._remember()
        self._update_title()
        return True

    def open(self):
        if not self._may_discard():
            return
        start = os.path.dirname(self.path) if self.path else None
        path = filedialog.askopenfilename(filetypes=[("NQC programs", "*.nqc *.nqh"), ("All files", "*.*")],
                                          initialdir=start)
        if path:
            self._load(path)

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            with open(self.path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.get_text())
        except OSError as e:
            self.app.log("Cannot save %s: %s" % (self.path, e))
            return False
        self.text.edit_modified(False)
        self._remember()
        self._update_title()
        return True

    def save_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".nqc", filetypes=[("NQC programs", "*.nqc")],
                                            initialfile=os.path.basename(self.path) if self.path else "program.nqc")
        if not path:
            return False
        self.path = path
        return self.save()

    def _remember(self):
        self.app.settings["editor_file"] = self.path or ""

    def confirm_close(self):
        """Called when the app is about to exit. False cancels the exit."""
        return self._may_discard()

    # ---- compile and download --------------------------------------------
    def clear_messages(self):
        self._messages = []
        self.msg_box.delete(0, "end")
        self.text.tag_remove("errline", "1.0", "end")
        self.text.tag_remove("warnline", "1.0", "end")

    def show_messages(self, output, ok, summary):
        """Runs on the window's thread. output is NQC's text; summary is the headline."""
        self.clear_messages()
        self.msg_box.insert("end", summary)
        self.msg_box.itemconfigure(0, foreground=self._shade("ok" if ok else "bad"))
        self._messages = [None]
        mine = os.path.basename(self._compile_name)
        for kind, message, fname, lineno in parse_messages(output):
            other = fname and os.path.basename(fname) != mine
            where = "line %d" % lineno if lineno else ""
            if other:
                where = "%s %s" % (os.path.basename(fname), where)
            self.msg_box.insert("end", "  %s%s%s" % (kind + ": " + message, "   " if where else "", "(%s)" % where if where else ""))
            self._messages.append(None if other else lineno)
            if lineno and not other:
                tag = "errline" if kind == "Error" else "warnline"
                self.text.tag_add(tag, "%d.0" % lineno, "%d.0 lineend+1c" % lineno)
        first = next((n for n in self._messages if n), None)
        if first and not ok:
            self._goto_line(first)

    def _goto_message(self, event=None):
        sel = self.msg_box.curselection()
        if sel and sel[0] < len(self._messages) and self._messages[sel[0]]:
            self._goto_line(self._messages[sel[0]])

    def _goto_line(self, lineno):
        self.text.mark_set("insert", "%d.0" % lineno)
        self.text.see("%d.0" % lineno)
        self.text.focus_set()

    _compile_name = "untitled.nqc"

    def _compile(self):
        """Compile the current text. Returns (image or None, output). Runs on the worker thread."""
        source, path = self._snapshot
        folder = tempfile.mkdtemp(prefix="rcxtower-")
        name = os.path.basename(path) if path else "untitled.nqc"
        temp = os.path.join(folder, name)
        self._compile_name = name
        try:
            with open(temp, "w", encoding="utf-8", newline="\n") as f:
                f.write(source)
            include = [os.path.dirname(path)] if path else []
            try:
                image, output = nqc.compile_nqc(temp, include_dirs=include)
                return image, output
            except nqc.CompileError as e:
                return None, str(e)
        finally:
            for leftover in (temp,):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
            try:
                os.rmdir(folder)
            except OSError:
                pass

    def _post(self, output, ok, summary):
        self.app.events.put(("editor", (output, ok, summary)))

    def check(self):
        self._snapshot = (self.get_text(), self.path)

        def job():
            image, output = self._compile()
            if image is None:
                count = len([m for m in parse_messages(output) if m[0] == "Error"])
                self._post(output, False, "Not OK: %d error%s. Click a line below to go there." % (
                    count, "" if count == 1 else "s") if count else "Not OK: " + output.strip().splitlines()[-1])
            else:
                self._post(output, True, "OK: compiles to %d bytes." % len(image))
        self.app.submit("Checking the program", job, raw=True)

    def download(self, run=False):
        self._snapshot = (self.get_text(), self.path)
        try:
            slot = max(1, min(5, int(self.app.slot.get())))
        except (tk.TclError, ValueError):
            slot = 1

        def job(rcx):
            image, output = self._compile()
            if image is None:
                count = len([m for m in parse_messages(output) if m[0] == "Error"])
                self._post(output, False, "Not downloaded: %d error%s." % (count, "" if count == 1 else "s"))
                return
            self._post(output, True, "Compiled (%d bytes). Downloading to slot %d..." % (len(image), slot))
            n = rcx.download_program(image, slot, lambda d, t: self.app.events.put(("progress", 100.0 * d / max(t, 1))))
            if run:
                rcx.start_task(0)
            self._transferred = (self._snapshot[0], slot)
            self._post(output, True, "Downloaded to slot %d (%d task/sub)%s." % (slot, n, " and started" if run else ""))
        self.app.submit("Downloading the program", job)

    def _slot(self):
        try:
            return max(1, min(5, int(self.app.slot.get())))
        except (tk.TclError, ValueError):
            return 1

    def needs_transfer(self):
        # True when the text on screen is not what this editor last sent to the chosen slot.
        return self._transferred != (self.get_text(), self._slot())

    def run_program(self):
        if self.needs_transfer():
            changed = self._transferred is not None and self._transferred[1] == self._slot()
            answer = messagebox.askyesnocancel("RCX Tower", "%s\n\nTransfer it now and then run it?\n\n"
                                               "No runs whatever is already in slot %d." % (
                "The program has changed since it was last transferred." if changed else
                "This program has not been transferred to slot %d yet." % self._slot(), self._slot()))
            if answer is None:
                return
            if answer:
                self.download(run=True)
                return
        self.app.submit("Starting the program", lambda rcx: rcx.start_task(0))

    def stop_program(self):
        self.app.submit("Stopping the program", lambda rcx: rcx.stop_all())
