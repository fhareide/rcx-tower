# Changelog

Each release's note is its section here. To release: bump `__version__` in
`rcxtower/__init__.py`, add a `## <version>` section below, commit, then push a `v<version>`
tag (see "Releases" in the README).

## Unreleased

- Releases are now published on this repo (github.com/fhareide/rcx-tower), which is open
  source. The old download page, rcx-tower-releases, is archived.

## 0.2.0

- Linux: a download for x86-64 Linux (glibc 2.35 or newer, e.g. Ubuntu 22.04, Debian 12,
  Fedora 36), with NQC and the firmware included. Unpack it and run `./rcx-tower`.
- Linux: the Setup tab's Allow USB access installs a udev rule so the tower can be used
  without root (one password prompt); `sudo rcx-tower install-driver` does the same. The
  window says when the tower is plugged in but not yet allowed.

## 0.1.1

- BricxCC: RCX Tower's TOWERAPI.DLL is now copied into the BricxCC folder once (one Windows
  permission prompt), so BricxCC connects over USB however it is started, also from its own
  shortcut. Before, it only connected when started with the Start BricxCC button.
  A LEGO TOWERAPI.DLL in that folder is kept as a backup.
- Setup tab: new "BricxCC over USB" step showing whether the DLL is in place.
- Bridge tab: Choose... for a BricxCC installed outside Program Files.
- Copy diagnostics now reports where BricxCC is and which TOWERAPI.DLL it will load.

## 0.1.0

The first release.

- Use the LEGO USB IR tower on 64-bit Windows 10/11 through Microsoft's own WinUSB driver.
  The Setup tab installs it in one click, once for each USB port. macOS works too (Apple
  silicon and Intel), with no driver to install.
- NQC editor: syntax colouring, line numbers, example programs, Check / Download / Run / Stop
  (F5 to F8) and compile errors you can click to jump to their line. NQC is included.
- Firmware download, with a fast mode (on by default) that loads LEGO firmware 3.2.8 in
  about 80 seconds instead of four minutes. The firmware is included.
- Brick tools: motors, sounds, sensors, battery, run and stop.
- Bridge, so BricxCC, NQC and other RCX software can use the tower unchanged (USB mode or a
  COM port that imitates the serial tower).
- Tray icon, optional start with Windows, and a log with Copy diagnostics for bug reports.
- Light and dark appearance.
