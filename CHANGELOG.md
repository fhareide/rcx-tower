# Changelog

Each release's note is its section here. To release: bump `__version__` in
`rcxtower/__init__.py`, add a `## <version>` section below, and push to main.

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
