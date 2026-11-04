#!/bin/bash
# ============================================================
#  AutoCert Studio — one-shot macOS builder (Apple Silicon)
#  Produces: electron/dist/AutoCertStudio-arm64-<version>.dmg
#
#  Needs: Python 3.10+ and Node.js 18+ on PATH.
#  Equivalent of build_windows.bat for the Mac.
# ============================================================
set -e
cd "$(dirname "$0")"

echo
echo "=== [1/4] Checking tools ==="
command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 1; }
command -v npm     >/dev/null || { echo "ERROR: npm not found — install Node.js"; exit 1; }
python3 --version
npm --version

echo
echo "=== [2/4] Building the Python engine (PyInstaller) ==="
if [ ! -x venv/bin/python ]; then
  echo "Creating private venv…"
  python3 -m venv venv
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install --quiet -r requirements.txt pyinstaller
fi
./venv/bin/pip install --quiet -r requirements.txt pyinstaller

rm -rf build-engine/build build-engine/dist
mkdir -p build-engine
cd build-engine
../venv/bin/pyinstaller --onedir --noconfirm --name engine \
  --add-data "../templates:templates" \
  --add-data "../static:static" \
  ../app.py
cd ..

echo
echo "=== [3/4] Staging engine into electron/engine ==="
rm -rf electron/engine
cp -R build-engine/dist/engine electron/engine

echo
echo "=== [4/4] Building the macOS .dmg (arm64) ==="
cd electron
[ -d node_modules ] || npm install --no-fund --no-audit
CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac dmg --arm64
cd ..

echo
echo "============================================================"
echo " SUCCESS"
echo " Installer:  electron/dist/AutoCertStudio-arm64-<version>.dmg"
echo " App bundle: electron/dist/mac-arm64/AutoCert Studio.app"
echo "============================================================"
