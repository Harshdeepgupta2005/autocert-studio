"""Shared runtime paths for AutoCert Studio.

Works in three modes:
  * plain "python app.py"            -> files live next to the script
  * PyInstaller frozen (engine)      -> resources inside the bundle, data in
                                        the user's application-support folder
  * Electron sidecar                 -> same as frozen + AUTOCERT_ELECTRON=1
"""
import os
import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, "_MEIPASS", None))
IS_ELECTRON = bool(os.environ.get("AUTOCERT_ELECTRON"))


def _default_data_dir() -> Path:
    if IS_FROZEN or IS_ELECTRON:
        home = Path.home()
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "AutoCertStudio"
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "AutoCertStudio"
        return home / ".config" / "AutoCertStudio"
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    if IS_FROZEN:
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


DATA_DIR = _default_data_dir()
RES_DIR = _resource_dir()

UPLOADS = DATA_DIR / "uploads"
PROJECTS = DATA_DIR / "projects"
OUTPUT = DATA_DIR / "output"
DEMO_DIR = DATA_DIR / "demo"
FONTS_DIR = DATA_DIR / "fonts"

for _d in (UPLOADS, PROJECTS, OUTPUT, DEMO_DIR, FONTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
