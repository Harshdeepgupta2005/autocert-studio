# Packaging AutoCert Studio

How the desktop app is assembled and how to produce the installers
(`.exe` for Windows, `.dmg` for macOS).

---

## How the app is put together

```
┌──────────────────────────── Electron shell (UI + window) ─────────────────┐
│  electron/main.js      spawns the engine, opens the window                │
│  electron/preload.js   exposes native folder-picking to the UI            │
│                                                                       │
│        ┌──────────── Python "engine" (PyInstaller --onedir) ─────────┐  │
│        │  app.py + Flask + Pillow + openpyxl                          │  │
│        │  serves the UI on 127.0.0.1:<free port> and does all work    │  │
│        └────────────────────────────────────────────────────────────── ┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

* The Electron main process starts the engine as a **sidecar**, waits for the
  `ENGINE-READY port=N` line on its stdout, then loads
  `http://127.0.0.1:N` in the app window.
* Everything is **local-only** — the engine binds `127.0.0.1`, nothing is
  exposed to the network.
* User data always goes to the OS data folder (**not** inside the app):
  | OS       | Folder                                                        |
  |----------|---------------------------------------------------------------|
  | macOS    | `~/Library/Application Support/AutoCertStudio`                |
  | Windows  | `%APPDATA%\AutoCertStudio`                                     |
  | Linux    | `~/.config/AutoCertStudio`                                     |

  It contains `uploads/`, `projects/`, `output/`, `demo/` and `fonts/`.
  Users can drop extra `.ttf`/`.otf` files into that `fonts/` folder.
* The app icon sources are regenerated with `venv/bin/python gen_icons.py`.

## Layout of the build system

| Path                         | Purpose                                          |
|------------------------------|--------------------------------------------------|
| `build-engine/dist/engine/`  | PyInstaller output (must be **--onedir**;        |
|                              | `--onefile` hangs silently on some machines)     |
| `electron/engine/`           | staging copy of the engine, bundled via          |
|                              | `extraResources` into `Resources/engine`         |
| `electron/vendor/`           | offline Electron for mac builds that fail the    |
|                              | download (`--config.electronDist=vendor`)        |
| `build_windows.bat`          | one-shot builder for a Windows PC                |
| `build_mac.sh`               | one-shot builder for a Mac (Apple Silicon)       |
| `.github/workflows/build.yml`| cloud builder for both platforms                 |

# ────────────────────────────────────────────────────────────────
# `build_mac.sh` and `build_windows.bat` run all of the steps below  
# on their machine with one double-click / command.
# ────────────────────────────────────────────────────────────────

## Build a macOS `.dmg` (on this Mac)

```bash
./build_mac.sh          # or run the three steps below by hand

# 1. build the frozen engine
cd build-engine
../venv/bin/pyinstaller --onedir --noconfirm --name engine \
  --add-data "../templates:templates" \
  --add-data "../static:static" \
  ../app.py

# 2. stage it next to the Electron code
rm -rf ../electron/engine
cp -R dist/engine ../electron/engine

# 3. package
cd ../electron
npm install --no-fund --no-audit
CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac dmg
# → dist/AutoCertStudio-arm64-1.0.0.dmg
```

If electron-builder cannot download Electron (restricted network), use the
pre-downloaded copy in `electron/vendor/`:

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false \
  npx electron-builder --mac dmg --config.electronDist=vendor
```

For Intel Macs, point `electronDist` at a folder containing the x64
`Electron.app` and pass `--x64`.

## Build the Windows `.exe` (two ways)

### Way 1 — GitHub Actions (recommended, no Windows PC needed)

1. Push this folder to a GitHub repository.
2. Open the **Actions** tab → **build** → *Run workflow*
   (or push a tag such as `v1.0.0`).
3. When the run finishes, download the artifact
   **AutoCertStudio-Windows** → inside is
   `AutoCertStudio-Setup-<version>.exe`.

The macOS job in the same workflow produces both `.dmg` variants.

### Way 2 — any Windows PC

1. Install Python 3.10+ (tick *Add to PATH*) and Node.js 18+.
2. Copy the whole project folder to the PC.
3. Double-click **`build_windows.bat`**.
4. Result: `electron\dist\AutoCertStudio-Setup-1.0.0.exe`.

## Version bumps

Change `"version"` in `electron/package.json`
(and `"version"` in the Python side is carried by `package.json` only).

## Signing & Gatekeeper (what your users will see)

The builds are **unsigned** (no Apple certificate / Windows certificate):

| Platform | What users see                                | What to do |
|----------|-----------------------------------------------|------------|
| macOS    | "unidentified developer" warning              | Right-click the app → **Open** → Open again. Or System Settings → Privacy & Security → *Open Anyway*. |
| Windows  | SmartScreen "More info → Run anyway"          | Click **More info** → **Run anyway**. |

To remove those warnings you would need to sign:
* macOS: Apple Developer account → notarise (`codesign` + `stapler`),
  set `CSC_LINK` in CI.
* Windows: an OV/EV code-signing certificate, set `CSC_LINK`.

## Test checklist after packaging

```bash
# run the packaged engine directly and hit the full API suite
dist/mac-arm64/AutoCert\ Studio.app/Contents/Resources/engine/engine \
  --electron --port 7437 &
../venv/bin/python e2e_test.py        # must print E2E OK

# run the packaged app and capture a screenshot of the window
AUTOCERT_CAPTURE=/tmp/shot.png \
  dist/mac-arm64/AutoCert\ Studio.app/Contents/MacOS/AutoCert\ Studio

# same, but load the built-in demo project first (canvas + preview shot)
AUTOCERT_CAPTURE=/tmp/shot.png AUTOCERT_DEMO=1 \
  dist/mac-arm64/AutoCert\ Studio.app/Contents/MacOS/AutoCert\ Studio
```

Data received/produced during tests lands in the OS data folder listed above.
