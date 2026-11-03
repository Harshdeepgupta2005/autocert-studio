@echo off
REM ============================================================
REM  AutoCert Studio ^- one-shot Windows builder
REM  Produces: electron\dist\AutoCertStudio-Setup-1.0.0.exe
REM
REM  Run this ON A WINDOWS PC. It needs:
REM    - Python 3.10+ (python.org — tick "Add to PATH" on install)
REM    - Node.js 18+  (nodejs.org)
REM    - Internet for the first build (downloads npm + Electron)
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === [1/4] Checking tools ===
where python >nul 2>nul || (echo ERROR: Python not found in PATH. Install from python.org & goto :fail)
where npm   >nul 2>nul || (echo ERROR: npm not found in PATH. Install Node.js from nodejs.org & goto :fail)
python --version
npm --version

echo.
echo === [2/4] Building the Python engine (PyInstaller) ===
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -c "import PyInstaller" 2>nul || python -m pip install --quiet pyinstaller

rmdir /s /q build-engine\dist 2>nul
rmdir /s /q build-engine\build 2>nul
if not exist build-engine mkdir build-engine
cd build-engine
python -m PyInstaller --onedir --name engine --noconfirm ^
  --add-data "..\templates;templates" ^
  --add-data "..\static;static" ^
  ..\app.py
if errorlevel 1 (echo ERROR: engine build failed & cd .. & goto :fail)
cd ..

echo.
echo === [3/4] Staging engine into electron\engine ===
rmdir /s /q electron\engine 2>nul
xcopy /e /i /q /y build-engine\dist\engine electron\engine
if errorlevel 1 (echo ERROR: staging failed & goto :fail)

echo.
echo === [4/4] Building the Windows installer (electron-builder) ===
cd electron
if not exist node_modules call npm install --no-fund --no-audit
if errorlevel 1 (echo ERROR: npm install failed & cd .. & goto :fail)
set CSC_IDENTITY_AUTO_DISCOVERY=false
call npx electron-builder --win
if errorlevel 1 (echo ERROR: electron-builder failed & cd .. & goto :fail)
cd ..

echo.
echo ============================================================
echo  SUCCESS
echo  Installer:  electron\dist\AutoCertStudio-Setup-1.0.0.exe
echo  (version number follows electron\package.json)
echo ============================================================
goto :eof

:fail
echo.
echo BUILD FAILED - see the message above.
pause
exit /b 1
