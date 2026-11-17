@echo off
rem Build dist\RCX Tower.exe (single file, no console). Needs: pip install pyinstaller
rem Bundles the LEGO firmware and nqc.exe: vendor\windows\nqc.exe (from BricxCC 3.3,
rem NQC 3.1 r6), or BricxCC's own copy if that one is missing.
cd /d "%~dp0"
set NQC=%~dp0vendor\windows\nqc.exe
if not exist "%NQC%" set NQC=%ProgramFiles(x86)%\BricxCC\nqc.exe
set EXTRA=
if exist "%NQC%" set EXTRA=--add-binary "%NQC%;."
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "RCX Tower" ^
  --icon "rcxtower\data\rcxtower.ico" ^
  --add-data "rcxtower\data\firm0328.lgo;rcxtower\data" ^
  --add-data "rcxtower\data\rcxtower.ico;rcxtower\data" %EXTRA% rcxtower_app.py
