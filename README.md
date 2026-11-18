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

## macOS and Linux

Less tested than Windows: the RCX protocol code is the same, but the USB layer for these systems
(`rcxtower/tower_libusb.py`) has had far less use. Reports are welcome.

What is different from Windows:

- **No driver.** macOS lets a program open the tower directly through libusb. Linux has its own
  tower driver (`legousbtower`), which RCX Tower detaches while it runs. Linux lets only root
  use a new USB device, so it needs a udev rule once: **Allow USB access** on the Setup tab
  (asks for your password through pkexec) or `sudo rcx-tower install-driver` writes
  `/etc/udev/rules.d/60-lego-usb-tower.rules` for USB ID `0694:0001`.
- **No bridge, no BricxCC, no tray icon.** Those exist for Windows software. The window has the
  Editor, Brick, Remote and Setup tabs.
- **NQC is included in the packaged apps.** Running from source, build NQC and put `nqc` on
  your `PATH` (or in `/opt/homebrew/bin`, `/usr/local/bin` or `~/bin`). Without it you can still
  download firmware and ready-made `.rcx` files, and use the Remote tab.

From source:

    pip3 install pyusb libusb-package     (libusb-package brings the libusb library itself)
    python3 -m rcxtower status
    python3 -m rcxtower gui

On macOS, `brew install libusb` works in place of `libusb-package`. The Python from python.org
includes tkinter; Homebrew's needs `brew install python-tk`. On Debian/Ubuntu install
`python3-tk`.

### Building the Mac and Linux apps

The release workflow (see Releases below) builds both on GitHub. To build one yourself:

- **Mac:** `./build_mac.sh` makes `dist/RCX-Tower-<version>-mac-<processor>.dmg`. It needs
  Python 3.9+ with tkinter and the Xcode command line tools.
- **Linux:** `./build_linux.sh` makes `dist/RCX-Tower-<version>-linux-<processor>.tar.gz`: one
  `rcx-tower` program, the udev rule and a short README. It needs Python 3.9+ with tkinter, and
  make, g++, flex and bison for NQC. The program runs on the glibc it was built with or newer,
  so build on the oldest distribution you want to support (the releases use Ubuntu 22.04).

Both scripts build the NQC compiler from https://github.com/BrickBot/nqc and put it inside the
app. If that build fails the app is still made, without the ability to compile programs
(`build/nqc-build.log` says why).

The Mac app is not signed with an Apple developer certificate. The first time, macOS refuses to
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
52 functions that do nothing). The first click on **Start BricxCC**, or **Set up BricxCC** on the
Setup tab, copies it into the BricxCC folder, which takes one admin prompt. After that BricxCC can
use the USB bridge however it is started, also from its own shortcut. A LEGO `TOWERAPI.DLL`
already in that folder is kept as `TOWERAPI.DLL.lego-backup`; one in the Windows folder (from the
LEGO SDK or RIS software) is left alone, since the copy in BricxCC's folder is found first. If
BricxCC is not in Program Files, click **Choose...** on the Bridge tab. NQC needs none of this.

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

Downloads are published at <https://github.com/fhareide/rcx-tower-releases>, whose workflow
builds the Windows exe, both Mac dmgs and the Linux tar.gz from this repo. To make a release:

1. Once per clone, install the hook: `cp tools/hooks/pre-push .git/hooks/pre-push` (needs `gh`
   logged in).
2. Bump `__version__` in `rcxtower/__init__.py` and add its section to [CHANGELOG.md](CHANGELOG.md)
   (the section becomes the release note). Commit and push.
3. Tag and push the tag: `git tag v0.1.1 && git push origin v0.1.1`. The hook tags the releases
   repo too, which starts the build there.

LEGO and Mindstorms are trademarks of the LEGO Group, which does not sponsor or endorse this
project.
