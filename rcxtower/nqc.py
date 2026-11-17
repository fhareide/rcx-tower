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
    name = "nqc.exe" if sys.platform == "win32" else "nqc"
    candidates = [
        os.path.join(getattr(sys, "_MEIPASS", here), name),  # bundled into a packaged app
        os.path.join(here, name),
        shutil.which("nqc") or "",
    ]
    if sys.platform == "win32":
        candidates += [
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "BricxCC", name),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "BricxCC", name),
        ]
    else:
        # a program started from the Finder does not get the shell's PATH
        candidates += ["/opt/homebrew/bin/nqc", "/usr/local/bin/nqc", os.path.expanduser("~/bin/nqc")]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def compile_nqc(source_path, target="RCX2", nqc_path=None, include_dirs=()):
    """Compile an .nqc file; returns the .rcx image bytes. Raises CompileError with NQC's messages."""
    nqc_path = nqc_path or find_nqc()
    if not nqc_path:
        raise CompileError("The NQC compiler was not found. On Windows install BricxCC; elsewhere build NQC "
                           "and put 'nqc' on your PATH. See the Setup tab.")
    fd, out = tempfile.mkstemp(suffix=".rcx")
    os.close(fd)
    try:
        includes = ["-I" + d for d in include_dirs if d]
        r = subprocess.run([nqc_path, "-T" + target, "-O" + out] + includes + [source_path],
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
