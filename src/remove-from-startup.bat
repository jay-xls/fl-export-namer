@echo off
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DAW Export Fixer.lnk" 2>nul
del "%USERPROFILE%\Desktop\Beat Sorter.lnk" 2>nul
if defined OneDrive del "%OneDrive%\Desktop\Beat Sorter.lnk" 2>nul
echo Removed from startup. Quit the running copy from its tray icon (right-click ^> Quit).
echo Your settings and history are in %APPDATA%\DAW Export Fixer - delete that folder to wipe them.
pause
