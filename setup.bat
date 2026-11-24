@echo off
setlocal
cd /d "%~dp0"
echo.
echo  == DAW Export Fixer setup ==
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo  Python isn't installed ^(or the "py" launcher is missing^).
  echo  Install Python 3.11+ from https://www.python.org/downloads/ - use the python.org installer,
  echo  not the Microsoft Store one - then run this again.
  echo.
  pause
  exit /b 1
)

echo  Installing the few libraries it needs...
py -3 -m pip install --user --quiet -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo  pip install failed - see the message above.
  pause
  exit /b 1
)

echo  Adding it to Windows startup...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\DAW Export Fixer.lnk');" ^
  "$s.TargetPath=(Get-Command pyw).Source;" ^
  "$s.Arguments=[char]34+'%~dp0daw_export_fixer.pyw'+[char]34;" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.Save()"

echo  Adding a "Beat Sorter" shortcut to your desktop (drop old exports onto it)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Beat Sorter.lnk');" ^
  "$s.TargetPath=(Get-Command pyw).Source;" ^
  "$s.Arguments=[char]34+'%~dp0beat_sorter.pyw'+[char]34;" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.Description='Drop old beats here - estimates BPM and key, renames and files them';" ^
  "$s.Save()"

echo  Starting it now - a setup window will pop up the first time.
start "" pyw "%~dp0daw_export_fixer.pyw"
echo.
echo  Done. It lives in the system tray (the red bars icon - check the ^^ overflow menu).
echo.
pause
