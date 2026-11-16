# RCX Tower

Use the LEGO Mindstorms **USB IR tower** (RCX 1.0 / 2.0, part 9713 tower) on 64-bit Windows 10 and 11.

LEGO's own tower driver is 32-bit only. RCX Tower replaces it with Microsoft's built-in WinUSB
driver plus a small program that speaks the tower's protocol.

## What it does

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
| Firmware download (LEGO 3.2.8, about four minutes) | Tested |
| Program download with tasks and subs, run, variable read-back | Tested |
| Battery, sensor read, sound and motor commands | Accepted by the RCX; motors and sound not checked by eye or ear |
| Firmware download through the bridge from BricxCC | Not yet tested |

## One-time setup

1. **Tower driver.** Plug the tower in, open the Setup tab and click **Install tower driver**.
   It binds the WinUSB driver that is already part of Windows (the same thing as Device Manager's
   *Update driver > Let me pick > Universal Serial Bus devices > WinUsb Device*), so nothing is
   downloaded and no certificate is added. Windows asks for permission once.
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
plus vendor control requests for range and speed. `rcxtower/tower.py` drives those through
`winusb.dll` with ctypes. `rcxtower/rcx.py` implements the RCX packet framing and opcodes.
`rcxtower/bridge.py` pumps bytes between the tower and one end of a com0com pair, echoing sent
bytes the way the serial tower does.

## Licence

RCX Tower's own code is released under the [MIT licence](LICENSE).

Two things in this project are not covered by it:

- `rcxtower/data/firm0328.lgo` is the LEGO RCX firmware 3.2.8, copyright The LEGO Group. It comes
  from the LEGO Mindstorms SDK 2.5 and is included for convenience only.
- `RCX Tower.exe` builds include `nqc.exe` when BricxCC is installed on the build machine. NQC
  (Not Quite C, by Dave Baum and John Hansen) is under the Mozilla Public License 1.0; its source
  is at <https://bricxcc.sourceforge.net/nqc/>.

LEGO and Mindstorms are trademarks of the LEGO Group, which does not sponsor or endorse this
project.
