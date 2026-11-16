"""Entry point for the packaged RCX Tower.exe.

No arguments: open the window. With arguments: the same commands as
`python -m rcxtower` (status, firmware, download, bridge, ...).
"""
import os
import sys

if sys.stdout is None or sys.stderr is None:
    # windowed .exe has no console; send output to a file if asked, else discard it
    target = os.environ.get("RCXTOWER_LOG") or os.devnull
    stream = open(target, "w", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream

from rcxtower.__main__ import main  # noqa: E402
from rcxtower.app import run  # noqa: E402

if __name__ == "__main__":
    if sys.argv[1:] == ["--tray"]:
        sys.exit(run(start_hidden=True))
    sys.exit(main() if len(sys.argv) > 1 else run())
