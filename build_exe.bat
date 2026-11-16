@echo off
rem Build dist\RCX Tower.exe (single file, no console). Needs: pip install pyinstaller
rem Bundles the LEGO firmware and, if found, nqc.exe from BricxCC.
cd /d "%~dp0"
set NQC=%ProgramFiles(x86)%\BricxCC\nqc.exe
set EXTRA=
if exist "%NQC%" set EXTRA=--add-binary "%NQC%;."
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "RCX Tower" ^
  --icon "rcxtower\data\rcxtower.ico" ^
  --add-data "rcxtower\data\firm0328.lgo;rcxtower\data" ^
  --add-data "rcxtower\data\rcxtower.ico;rcxtower\data" %EXTRA% rcxtower_app.py
