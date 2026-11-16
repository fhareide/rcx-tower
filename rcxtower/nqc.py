"""Find and run the NQC compiler to turn .nqc source into an .rcx image."""
import os
import shutil
import subprocess
import sys
import tempfile


class CompileError(Exception):
    pass


def find_nqc():
    here = os.path.dirname(os.path.abspath(sys.argv[0] or "."))
    candidates = [
        os.path.join(getattr(sys, "_MEIPASS", here), "nqc.exe"),
        os.path.join(here, "nqc.exe"),
        shutil.which("nqc") or "",
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "BricxCC", "nqc.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "BricxCC", "nqc.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def compile_nqc(source_path, target="RCX2", nqc_path=None):
    """Compile an .nqc file; returns the .rcx image bytes. Raises CompileError with NQC's messages."""
    nqc_path = nqc_path or find_nqc()
    if not nqc_path:
        raise CompileError("nqc.exe not found. Install BricxCC or put nqc.exe next to this program.")
    fd, out = tempfile.mkstemp(suffix=".rcx")
    os.close(fd)
    try:
        r = subprocess.run([nqc_path, "-T" + target, "-O" + out, source_path],
                           capture_output=True, text=True, errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        messages = (r.stdout + r.stderr).strip()
        if r.returncode != 0 or not os.path.getsize(out):
            raise CompileError(messages or "nqc failed with exit code %d" % r.returncode)
        with open(out, "rb") as f:
            return f.read(), messages
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
