@echo off
rem Start the LEGO USB tower bridge. Leave this window open while using NQC / BricxCC.
cd /d "%~dp0"
python -u -m rcxtower bridge %*
pause
