# RCX Tower

Use the LEGO Mindstorms **USB IR tower** (RCX 1.0 / 2.0, part 9713 tower) on 64-bit Windows 10 and 11.

LEGO's own tower driver is 32-bit only. RCX Tower replaces it with Microsoft's built-in WinUSB
driver plus a small program that speaks the tower's protocol.

## What it does

- **Editor** for NQC programs: syntax colouring, line numbers, ready-made example programs,
  Check (F5), Download (F6), Run (F7) and Stop (F8). Compile errors are listed under the text;
  click one to jump to its line. No other program is needed to write and run RCX programs.
- **Brick tools**, talking to the tower directly: firmware download, compile and download NQC
  programs, run/stop, motors, sounds, sensors.
- **Bridge**: lets NQC, BricxCC and other RCX software use the tower unchanged. In USB mode
  (the default, nothing to install) the software is told the tower is on port `usb`. A COM port
  mode that imitates the old *serial* tower is there for software that needs it.
- **Setup checklist** that shows which of the one-time steps below are done.
- **Tray icon**: closing the window keeps the bridge running; right-click the icon to open the
  window, start or stop the bridge, or exit. Optional start with Windows (`RCX Tower.exe --tray`).

## Status

| Feature | State |
|---|---|
| Tower over WinUSB, ping, version query | Tested on Windows 11 |
| Bridge, USB mode: NQC download, run, raw commands, no-reply handling | Tested |
| Bridge, USB mode with BricxCC (via the Start BricxCC button) | Connects; downloads from BricxCC not yet tested |
| Bridge, COM port mode with BricxCC connecting | Tested |
| NQC compile, .rcx image parsing | Tested |
| Editor: colouring, Check with error list, templates | Tested |
| Editor: Download and Run buttons | Same code path as the Brick tab's download; not yet clicked with an RCX switched on |
| Firmware download without Fast (LEGO 3.2.8, about four minutes) | Tested |
| Fast firmware download (the **Fast** box, on by default, or `firmware --fast`) | Tested: LEGO 3.2.8 in 83 seconds |
| Program download with tasks and subs, run, variable read-back | Tested |
| Battery, sensor read, sound and motor commands | Accepted by the RCX; motors and sound not checked by eye or ear |
| Firmware download through the bridge from BricxCC | Not yet tested |

## One-time setup

1. **Tower driver.** Plug the tower in, open the Setup tab and click **Install tower driver**.
   It binds the WinUSB driver that is already part of Windows (the same thing as Device Manager's
   *Update driver > Let me pick > Universal Serial Bus devices > WinUsb Device*), so nothing is
   downloaded and no certificate is added. Windows asks for permission once.

   **The driver is set per USB port.** The tower has no serial number, so Windows treats it as
   a new device in every port it has not seen it in. If you plug the tower into another port
   (or a second tower into a new one), RCX Tower shows "the driver is missing for this USB
   port": click **Install tower driver** again. Each port only needs it once.

   *Status: the selection logic is tested; a full install on a PC without a tower driver is not
   yet tested.* Fallback: run [Zadig](https://zadig.akeo.ie), choose *Options > List All
   Devices*, pick **LEGO USB Tower** (USB ID `0694 0001`), set the driver to **WinUSB** and click
   *Install Driver*.
That is the only required step when using `RCX Tower.exe`, which includes NQC and the firmware.

Optional:

- **NQC**, when running from source: install
  [BricxCC](https://sourceforge.net/projects/bricxcc/), which includes `nqc.exe`, or put
  `nqc.exe` next to this program.
- **Virtual COM port**, only for the bridge's COM port mode: install the signed
  [com0com](https://sourceforge.net/projects/com0com/) build, create one pair in its Setup tool
  and name one end e.g. `COM2` (tick *use Ports class*).

The RCX also needs firmware after its batteries have been out. LEGO firmware 3.2.8
(`firm0328.lgo`, from the LEGO Mindstorms SDK 2.5, copyright The LEGO Group) is included in
`rcxtower/data` and is used when no other file is chosen.

## Fast firmware download

**Fast** next to the Download firmware button is ticked by default (on the command line use `python -m rcxtower firmware --fast`).
RCX Tower first sends an 88-byte helper program at normal speed, which makes the RCX talk at
4800 baud without the complement byte after every byte, then sends the firmware that way. It
takes a bit over a minute instead of about four.

If a fast download is cut short, the RCX stays in fast mode until it is switched off and on
(or its batteries are taken out when it has no firmware). Retrying with **Fast** ticked picks up
from there. The tower keeps its speed for as long as it is plugged in, so RCX Tower sets it
back to normal every time it opens the tower.

The helper is `fastdl.srec` from firmdl3 by Kekoa Proudfoot, under the Mozilla Public License 1.0
(`rcxtower/fastdl.py`).

## One window at a time

Only one program can use the tower, so RCX Tower runs once per user. Starting it again (also
when it is hidden in the tray) brings the running window to the front instead of opening a
second one.

## When something does not work

Open the **Setup** tab and click **Copy diagnostics**. RCX Tower tests the tower and the RCX step
by step (open the tower, read its version, ping the RCX, read its versions and battery) and copies
the result to the clipboard together with the last 400 lines of its log, ready to paste into a
bug report. The report also says whether another copy of RCX Tower is running and which running
programs could be holding the tower (BricxCC, NQC, Chrome, Edge, Python): only one program can use
the tower at a time. Your account name is replaced by `~` in file paths.

Everything shown in the window's log box is also written to `rcxtower.log`, together with
what the window leaves out: every byte sent to and received from the tower with millisecond
times, every tower setting that is changed, each command and retry, when each job starts and
ends, bridge connections, and full error details. If a job does nothing with the tower for 20
seconds, the window says so and the log records where the program is waiting; Copy diagnostics
still works then. **Open log folder** shows where it is: `%APPDATA%\rcxtower` on
Windows, `~/Library/Application Support/rcxtower` on macOS, `~/.config/rcxtower` on Linux. The
file is kept under about two megabytes; the previous one is kept as `rcxtower.log.1`.

## macOS and Linux (experimental)

**Status: written but never run on a Mac or on Linux.** The RCX protocol code is the same as on
Windows, where it is tested; the USB layer for these systems (`rcxtower/tower_libusb.py`) is new
and unverified. Reports are welcome.

What is different from Windows:

- **No driver step.** macOS lets a program open the tower directly through libusb. Linux has its
  own tower driver (`legousbtower`), which RCX Tower detaches while it runs; you also need
  permission on the device (a udev rule for USB ID `0694:0001`, or run as root).
- **No bridge, no BricxCC, no tray icon.** Those exist for Windows software. The window has the
  Editor, Brick, Remote and Setup tabs.
- **NQC has to be built from source** and the `nqc` program put on your `PATH` (or in
  `/opt/homebrew/bin`, `/usr/local/bin` or `~/bin`). Without it you can still download firmware
  and ready-made `.rcx` files, and use the Remote tab.

Setup:

    pip3 install pyusb libusb-package     (libusb-package brings the libusb library itself)
    python3 -m rcxtower status
    python3 -m rcxtower gui

On macOS, `brew install libusb` works in place of `libusb-package`. The Python from python.org
includes tkinter; Homebrew's needs `brew install python-tk`.

### A Mac app and .dmg

**Status: the build script and workflow are written but have never been run.**

A Mac app cannot be built on Windows, so there are two ways to get the `.dmg`:

- **On GitHub:** open the repository's *Actions* tab, choose **Mac dmg** and click *Run workflow*
  (pushing a tag such as `v0.1.0` starts it too). When it finishes, the run's page has two
  downloads under *Artifacts*: one for Apple silicon Macs and one for Intel Macs. On a private
  repository this uses the account's Actions minutes, and Mac minutes count ten times.
- **On a Mac:** run `./build_mac.sh`. It needs Python 3.9+ with tkinter and the Xcode command
  line tools, and leaves `dist/RCX-Tower-<version>-mac-<processor>.dmg`.

The script also builds the NQC compiler from https://github.com/BrickBot/nqc and puts it inside
the app. If that build fails the app is still made, without the ability to compile programs
(`build/nqc-build.log` says why).

The app is not signed with an Apple developer certificate. The first time, macOS refuses to
open it: right-click the app, choose *Open*, then *Open* again (on recent macOS versions:
*System Settings > Privacy & Security > Open Anyway*).

The libusb backend can also be tried on Windows, on a tower that already has WinUSB bound:
set the environment variable `RCXTOWER_BACKEND=libusb`.

## Running

Requires Python 3.9+ on Windows. No extra packages.

    python -m rcxtower gui        the window (or double-click "RCX Tower.pyw")
    python -m rcxtower status
    python -m rcxtower firmware firm0328.lgo
    python -m rcxtower download program.nqc --slot 1 --run
    python -m rcxtower bridge     serial-tower emulation only

With the bridge running in USB mode, choose port **usb** and brick type **RCX2** in BricxCC, or
pass `-Susb` to NQC. In COM port mode use the COM port shown (e.g. `COM2`) as a serial tower.
Leave "fast" firmware mode off in either case.

### BricxCC and TOWERAPI.DLL

BricxCC only uses a USB tower through LEGO's `TOWERAPI.DLL` and refuses to connect without it.
LEGO's DLL needs LEGO's 32-bit driver, so RCX Tower generates a stand-in (`rcxtower/towerapi.py`,
52 functions that do nothing) and the **Start BricxCC** button makes BricxCC load it. If LEGO's
own DLL is already on the PC (installed by the LEGO SDK or RIS software into the Windows folder),
the stand-in has to be copied into the BricxCC folder, which takes one admin prompt. NQC needs
none of this.

### How USB mode works without a driver

LEGO's old driver exposed the tower as the device `\\.\LEGOTOWER1`, and that is the name NQC and
BricxCC open. RCX Tower creates that name itself with `DefineDosDevice`, pointing it at a named
pipe it owns, and pumps bytes between the pipe and the tower. No admin rights are needed. The
name exists only in the current user's logon session and only while the bridge runs, so software
started "as administrator" will not see it. When the RCX does not answer, the bridge writes a
zero-length message to the pipe so the waiting program sees a read timeout instead of hanging.

## How it works

The tower has one interrupt IN and one interrupt OUT endpoint that carry the raw IR byte stream,
plus vendor control requests for range and speed. `rcxtower/tower.py` picks a backend for
those: `tower_winusb.py` (Windows, `winusb.dll` through ctypes) or `tower_libusb.py` (macOS and
Linux, pyusb). `rcxtower/rcx.py` implements the RCX packet framing and opcodes.
`rcxtower/bridge.py` pumps bytes between the tower and one end of a com0com pair, echoing sent
bytes the way the serial tower does.

## Licence

RCX Tower's own code is released under the [MIT licence](LICENSE).

Two things in this project are not covered by it:

- `rcxtower/data/firm0328.lgo` is the LEGO RCX firmware 3.2.8, copyright The LEGO Group. It comes
  from the LEGO Mindstorms SDK 2.5 and is included for convenience only.
- `vendor/windows/nqc.exe` (from BricxCC 3.3), which `RCX Tower.exe` builds include, and the
  NQC the Mac build compiles from <https://github.com/BrickBot/nqc>. NQC (Not Quite C, by Dave
  Baum and John Hansen) is under the Mozilla Public License 1.0; its source is at
  <https://bricxcc.sourceforge.net/nqc/>.

## Releases

Downloads are published at <https://github.com/fhareide/rcx-tower-releases>. To make one, bump
`__version__` in `rcxtower/__init__.py`, add its section to [CHANGELOG.md](CHANGELOG.md) and push
to main; `.github/workflows/build.yml` builds the Windows exe and both Mac dmgs and publishes them.

LEGO and Mindstorms are trademarks of the LEGO Group, which does not sponsor or endorse this
project.
