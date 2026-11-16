"""Command line for the LEGO USB tower.

    python -m rcxtower status
    python -m rcxtower firmware firm0328.lgo
    python -m rcxtower download program.nqc --slot 1 --run
    python -m rcxtower bridge            (serial-tower emulation for BricxCC / NQC)
"""
import argparse
import sys
import time

from . import bridge as br
from . import firmware as fw
from . import nqc
from . import tower as tw
from .rcx import RCX, RCXError


def _bar(done, total):
    width = 30
    filled = int(width * done / max(total, 1))
    sys.stdout.write("\r  [%s%s] %3d%%" % ("#" * filled, "." * (width - filled), 100 * done // max(total, 1)))
    sys.stdout.flush()
    if done >= total:
        sys.stdout.write("\n")


def cmd_status(a):
    paths = tw.find_tower_paths()
    if not paths:
        print("Tower: not found (not plugged in, or WinUSB driver not bound)")
        return 2
    with tw.Tower(paths[0]) as t:
        v = t.control(tw.REQ_GET_VERSION)
        print("Tower: connected, firmware %d.%d build %d" % (v[4], v[5], v[6] | v[7] << 8) if len(v) >= 8
              else "Tower: connected")
        t.set_parm(tw.PARM_RANGE, tw.RANGE_LONG)
        rcx = RCX(t)
        if not rcx.ping(retries=3):
            print("RCX:   no answer (switched on and facing the tower?)")
            return 1
        ver = rcx.versions()
        print("RCX:   ROM %s, firmware %s" % (ver["rom"], ver["firmware"] if ver["has_firmware"] else "none loaded"))
        if ver["has_firmware"]:
            print("       battery %.2f V" % rcx.battery_volts())
    pairs = br.com0com_pairs()
    print("Virtual COM pairs: %s" % (", ".join("%s<->%s" % p for p in pairs) or "none (com0com not installed)"))
    return 0


def cmd_driver_check(a):
    from . import driver
    info = driver.check()
    if not info["present"]:
        print("Tower: not plugged in")
        return 2
    print("Tower:           %s" % info["instance"])
    print("Current driver:  %s" % (info["service"] or "none"))
    print("Device class:    %s" % (info["class"] or "none"))
    print("In winusb.inf:   %s" % (", ".join(info["drivers_in_inf"]) or "nothing listed"))
    print("Would install:   %s" % (info["would_install"] or "NOTHING FOUND"))
    if info.get("problem"):
        print("Problem:         %s" % info["problem"])
    return 0


def cmd_install_driver(a):
    from . import driver
    if not driver.is_admin():
        print("This needs admin rights. Use the Install tower driver button in the app.")
        return 1
    return driver.run_elevated_install()


def cmd_firmware(a):
    path = a.file or fw.bundled_path()
    if not path:
        print("No firmware file given and none is bundled.")
        return 2
    image = fw.load_srec(path)
    print("Firmware %s: %d bytes" % (path, len(image)))
    with tw.Tower() as t:
        t.set_parm(tw.PARM_RANGE, tw.RANGE_LONG)
        rcx = RCX(t)
        if not rcx.ping(retries=3):
            print("RCX does not answer.")
            return 1
        start = time.monotonic()
        ver = rcx.download_firmware(image, _bar)
        print("Done in %d s. RCX firmware is now %s" % (time.monotonic() - start, ver["firmware"]))
    return 0


def cmd_download(a):
    if a.file.lower().endswith(".rcx"):
        with open(a.file, "rb") as f:
            image = f.read()
    else:
        image, messages = nqc.compile_nqc(a.file, a.target)
        if messages:
            print(messages)
    with tw.Tower() as t:
        t.set_parm(tw.PARM_RANGE, tw.RANGE_LONG)
        rcx = RCX(t)
        if not rcx.ping(retries=3):
            print("RCX does not answer.")
            return 1
        n = rcx.download_program(image, a.slot, _bar)
        print("Downloaded %d task/sub chunk(s)%s" % (n, " to slot %d" % a.slot if a.slot else ""))
        if a.run:
            rcx.start_task(0)
    return 0


def cmd_bridge(a):
    port = a.port or br.USB_PORT

    def log(direction, data):
        label = {"tx": "PC->RCX", "rx": "RCX->PC", "open": "program opened the tower",
                 "close": "program closed the tower", "timeout": "read timed out (no IR)"}[direction]
        print("%s %s" % (label, " ".join("%02X" % b for b in data)), flush=True)

    with tw.Tower() as t:
        t.set_parm(tw.PARM_RANGE, {"short": 1, "medium": 2, "long": 3}[a.range])
        if port.lower() == br.USB_PORT:
            b = br.UsbBridge(t, on_bytes=log if a.verbose else None)
            print("Bridge running. In BricxCC choose port 'usb'; for NQC use -Susb. Ctrl+C to stop.", flush=True)
        else:
            b = br.Bridge(t, port, echo=not a.no_echo, on_bytes=log if a.verbose else None)
            print("Bridge running: USB tower <-> %s (serial tower emulation). Ctrl+C to stop." % port, flush=True)
        try:
            b.run_forever()
        except KeyboardInterrupt:
            print("stopped")
        if b.error:
            print("Bridge stopped: %s" % b.error)
            return 1
    return 0


def cmd_simple(a):
    with tw.Tower() as t:
        t.set_parm(tw.PARM_RANGE, tw.RANGE_LONG)
        rcx = RCX(t)
        if a.cmd == "beep":
            rcx.play_sound(a.sound)
        elif a.cmd == "run":
            if a.slot:
                rcx.select_program(a.slot)
            rcx.start_task(0)
        elif a.cmd == "stop":
            rcx.stop_all()
        elif a.cmd == "off":
            rcx.power_off()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rcxtower", description="LEGO USB IR tower tools for 64-bit Windows")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("gui", help="open the RCX Tower window")
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(fn=lambda a: __import__("rcxtower.app", fromlist=["run"]).run(a.selftest))
    sub.add_parser("status", help="check tower, RCX and virtual ports").set_defaults(fn=cmd_status)
    sub.add_parser("driver-check", help="show what installing the tower driver would do (changes nothing)"
                   ).set_defaults(fn=cmd_driver_check)
    sub.add_parser("install-driver", help="bind Windows' WinUSB driver to the tower (needs admin rights)"
                   ).set_defaults(fn=cmd_install_driver)
    p = sub.add_parser("firmware", help="download firmware (.lgo) to the RCX")
    p.add_argument("file", nargs="?", help="default: the bundled LEGO firmware 3.2.8")
    p.set_defaults(fn=cmd_firmware)
    p = sub.add_parser("download", help="download an .nqc or .rcx program")
    p.add_argument("file")
    p.add_argument("--slot", type=int, choices=range(1, 6))
    p.add_argument("--target", default="RCX2")
    p.add_argument("--run", action="store_true", help="start the program afterwards")
    p.set_defaults(fn=cmd_download)
    p = sub.add_parser("bridge", help="let BricxCC / NQC use the tower (port 'usb', nothing to install)")
    p.add_argument("port", nargs="?", help="'usb' (default), or the bridge end of a com0com pair such as CNCB0")
    p.add_argument("--range", choices=("short", "medium", "long"), default="long")
    p.add_argument("--no-echo", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_bridge)
    p = sub.add_parser("beep", help="play a system sound 0-5")
    p.add_argument("sound", nargs="?", type=int, default=1)
    p.set_defaults(fn=cmd_simple)
    p = sub.add_parser("run", help="start the program")
    p.add_argument("--slot", type=int, choices=range(1, 6))
    p.set_defaults(fn=cmd_simple)
    sub.add_parser("stop", help="stop all tasks").set_defaults(fn=cmd_simple)
    sub.add_parser("off", help="switch the RCX off").set_defaults(fn=cmd_simple)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    try:
        return a.fn(a)
    except (tw.TowerError, RCXError, fw.FirmwareError, nqc.CompileError, OSError) as e:
        print("Error: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
