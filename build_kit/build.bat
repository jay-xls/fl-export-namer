@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Builds the shareable app:
rem   dist\FL Export Namer\              the app folder (PyInstaller one-folder build)
rem   dist\FL Export Namer Setup X.exe   installer, if Inno Setup 6 is installed
rem   dist\FL Export Namer X.zip         zip of the app folder (always)
rem Every path is quoted, so folders with & ( ) or spaces in their names are fine.

cd /d "%~dp0.."
if errorlevel 1 (echo Couldn't open the project folder. & pause & exit /b 1)

where py >nul 2>nul
if errorlevel 1 (echo Python launcher "py" not found - install Python 3.11+ from python.org first. & pause & exit /b 1)

set "VER="
for /f "tokens=2 delims==" %%v in ('findstr /b "__version__" "namer_core.py"') do set "VER=%%~v"
if defined VER set "VER=%VER: =%"
if defined VER set "VER=%VER:"=%"
if not defined VER set "VER=dev"

echo.
echo  == Building FL Export Namer v%VER% ==
echo.

rem Clean virtual environment = only the libraries the app needs end up in the build.
set "PY=.venv-build\Scripts\python.exe"
if not exist "%PY%" (
  echo  Creating build environment...
  py -3 -m venv ".venv-build"
)
if not exist "%PY%" (echo Couldn't create the build environment - see above. & pause & exit /b 1)

echo  Installing build dependencies...
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -r "requirements-dev.txt"
if errorlevel 1 (echo pip failed - see above. & pause & exit /b 1)

echo  Running PyInstaller - takes a minute or two...
if exist "build\pyi" rmdir /s /q "build\pyi"
if exist "dist\FL Export Namer" rmdir /s /q "dist\FL Export Namer"
"%PY%" -m PyInstaller --noconfirm --clean --workpath "build\pyi" --distpath "dist" "build_kit\FLExportNamer.spec"
if errorlevel 1 (echo PyInstaller failed - see above. & pause & exit /b 1)

echo  Smoke test: frozen app imports + detection libraries...
"dist\FL Export Namer\FL Export Namer.exe" --selftest
set "RC=%ERRORLEVEL%"
if exist "%APPDATA%\FL Export Namer\selftest.txt" type "%APPDATA%\FL Export Namer\selftest.txt"
if not "%RC%"=="0" (echo  SELFTEST FAILED - details above / in the log. & pause & exit /b 1)

echo  Zipping...
if exist "dist\FL Export Namer %VER%.zip" del "dist\FL Export Namer %VER%.zip"
rem Python's zip writer uses standard "/" paths (PowerShell's Compress-Archive writes "\" which
rem breaks on Mac, phones and some unzip tools).
"%PY%" -m zipfile -c "dist\FL Export Namer %VER%.zip" "dist\FL Export Namer"

set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC goto :noinno
echo  Building installer...
"%ISCC%" /Q "/DAppVersion=%VER%" "build_kit\installer.iss"
if errorlevel 1 (echo Inno Setup failed - see above. & pause & exit /b 1)
goto :done

:noinno
echo  Inno Setup 6 not found - skipped Setup.exe. Install it with:
echo     winget install JRSoftware.InnoSetup
echo  then run build.bat again. The zip works without it.

:done
echo.
echo  Done. Output is in the "dist" folder.
start "" explorer "dist"
pause
endlocal
