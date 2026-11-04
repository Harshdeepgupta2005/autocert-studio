"""AutoCert Studio — batch generator for certificates & ID cards.

Run:  python3 app.py   (a browser window opens automatically)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image, ImageDraw

import renderer
from app_config import RES_DIR, UPLOADS, PROJECTS, OUTPUT, DATA_DIR, FONTS_DIR
from data_utils import read_table
from demo_builder import demo_config

app = Flask(
    __name__,
    template_folder=str(RES_DIR / "templates"),
    static_folder=str(RES_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        return JOBS.get(job_id, {})


# ----------------------------------------------------------------- pages ---

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


# ----------------------------------------------------------------- fonts ---

@app.get("/api/fonts")
def fonts():
    return {"fonts": renderer.font_labels(), "dir": str(FONTS_DIR)}


# --------------------------------------------------------------- uploads ---

TEMPLATE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}
TABLE_EXTS = {"xlsx", "xlsm", "csv"}


class _BadUpload(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _save_upload(allowed_exts: set[str]) -> Path:
    """Store the posted file under uploads/ and return its path.

    Raises _BadUpload with a user-facing message when the file is missing
    or has the wrong extension.
    """
    f = request.files.get("file")
    if not f or not f.filename:
        raise _BadUpload("No file received")
    name = Path(f.filename).name
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in allowed_exts:
        raise _BadUpload("Please use the right file type for this step")
    p = UPLOADS / f"{uuid.uuid4().hex}.{ext if ext != 'jpeg' else 'jpg'}"
    f.save(p)
    return p


@app.post("/api/upload-template")
def upload_template():
    try:
        p = _save_upload(TEMPLATE_EXTS)
    except _BadUpload:
        return jsonify(error="Please use a PNG or JPG image for the design."), 400
    try:
        with Image.open(p) as im:
            w, h = im.size
    except Exception:
        p.unlink(missing_ok=True)
        return jsonify(error="That file could not be opened as an image."), 400
    return {"path": str(p), "name": p.name, "width": w, "height": h}


@app.post("/api/upload-excel")
def upload_excel():
    try:
        p = _save_upload(TABLE_EXTS)
    except _BadUpload:
        return jsonify(error="Please use an .xlsx or .csv file."), 400
    try:
        columns, rows = read_table(p)
    except Exception as e:
        p.unlink(missing_ok=True)
        return jsonify(error=f"Could not read that file: {e}"), 400
    if not columns:
        return jsonify(error="The file has no header row."), 400
    if not rows:
        return jsonify(error="The file has no data rows under the header."), 400
    return {"path": str(p), "name": p.name, "columns": columns, "row_count": len(rows)}


# --------------------------------------------------------------- preview ---

@app.post("/api/preview")
def preview():
    cfg = request.get_json(force=True, silent=True)
    if not cfg or not cfg.get("template"):
        return jsonify(error="No template loaded"), 400
    row = 0
    try:
        row = int(request.args.get("row", 0))
    except ValueError:
        pass

    data, excel_dir = _excel_row(cfg, row)

    warnings: list[str] = []
    try:
        img = renderer.render_card(cfg["template"]["path"], cfg, data,
                                   photos_folder=cfg.get("photos_folder") or "",
                                   excel_dir=excel_dir,
                                   collect_warnings=warnings)
    except FileNotFoundError:
        return jsonify(error="Design file is missing — please re-upload it."), 404
    except Exception as e:
        return jsonify(error=f"Render failed: {e}"), 500

    buf = io.BytesIO()
    img.save(buf, "PNG")
    resp = Response(buf.getvalue(), mimetype="image/png")
    if warnings:
        resp.headers["X-Generation-Warnings"] = " | ".join(warnings)
    return resp


def _excel_row(cfg: dict, row_index: int):
    """Return (row_data, excel_dir) for preview/metrics."""
    excel = cfg.get("excel") or {}
    if excel.get("path") and Path(excel["path"]).is_file():
        try:
            _columns, rows = read_table(excel["path"])
            excel_dir = Path(excel["path"]).parent
            if rows:
                row_index = max(0, min(row_index, len(rows) - 1))
                return rows[row_index], excel_dir
            return {}, excel_dir
        except Exception:
            pass
    return {}, None


# ------------------------------------------------------------ text metrics---

@app.post("/api/text-metrics")
def text_metrics():
    """Exact rendered size of one text field (for on-canvas bounding boxes).

    Body: the project config (same shape /api/preview takes).
    Query: ?row=N to pick which Excel row provides the sample value.
    """
    cfg = request.get_json(force=True, silent=True)
    field = (cfg or {}).get("field") or {}
    row = 0
    try:
        row = int(request.args.get("row", 0))
    except ValueError:
        pass
    data, _excel_dir = _excel_row(cfg or {}, row)
    txt = renderer.compose_text(field, data)
    if not txt:
        return {"width": 0, "height": 0, "text": ""}
    m = renderer.layout_text(txt, field)
    return {"width": m["width"], "height": m["height"], "text": txt}


# ----------------------------------------------------------------- fonts ---

@app.get("/api/font-preview")
def font_preview():
    """Render sample text in the requested font as a small PNG strip.

    The default sample avoids symbols (@, ·, …) that many display fonts
    lack; the UI itself now shows real text previews via /api/font-file.
    """
    label = request.args.get("label", "")
    text = (request.args.get("text") or "Abc 123")[:28]
    path = renderer.font_path(label)
    if not path:
        return jsonify(error="unknown font"), 404
    try:
        font = renderer.get_font(label, 24)
        tmp = Image.new("RGB", (4, 4))
        d = ImageDraw.Draw(tmp)
        w = max(2, int(d.textlength(text, font=font)) + 8)
        ascent, descent = font.getmetrics()
        h = ascent + descent + 6
        img = Image.new("RGB", (w, h), (255, 255, 255))
        ImageDraw.Draw(img).text((4, 2), text, font=font, fill=(20, 24, 44))
    except Exception:
        return jsonify(error="font could not be rendered"), 500
    buf = io.BytesIO()
    img.save(buf, "PNG")
    resp = Response(buf.getvalue(), mimetype="image/png")
    resp.headers["Cache-Control"] = "max-age=86400"
    return resp


@app.post("/api/import-fonts")
def import_fonts():
    """Save uploaded .ttf/.otf/.ttc files into the user fonts folder."""
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="No font files received"), 400
    added: list[str] = []
    for f in files:
        if not f or not f.filename:
            continue
        name = Path(f.filename).name
        if Path(name).suffix.lower() not in renderer.FONT_EXTS:
            continue
        dest = FONTS_DIR / name
        try:
            f.save(dest)
            added.append(dest.stem.replace("_", " ").strip())
        except OSError:
            continue
    if not added:
        return jsonify(error="No .ttf, .otf or .ttc files in the upload"), 400
    renderer.refresh_fonts()
    return {"added": added, "fonts": renderer.font_labels()}


@app.post("/api/fonts/refresh")
def fonts_refresh():
    """Re-scan font folders (also after removing files manually)."""
    renderer.refresh_fonts()
    return {"fonts": renderer.font_labels()}


@app.get("/api/font-file")
def font_file():
    """Serve a font file so the UI can show real text previews (@font-face)."""
    label = request.args.get("label", "")
    path = renderer.font_path(label)
    if not path:
        return jsonify(error="unknown font"), 404
    p = Path(path)
    mime = {".ttf": "font/ttf", ".otf": "font/otf", ".ttc": "font/collection"} \
        .get(p.suffix.lower(), "font/ttf")
    resp = send_file(p, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


# --------------------------------------------- import fonts from a link ---

_GOOGLE_HOSTS = ("fonts.google.com", "fonts.googleapis.com", "fonts.gstatic.com")
_GOOGLE_UA = "Mozilla/4.0 (compatible; AutoCertStudio)"   # legacy css API → TTF urls
_FONT_URL_TIMEOUT = 30
_MAX_LINK_FONTS = 12                                      # safety cap per import


def _ssl_context():
    """TLS context with a CA bundle that exists on every machine.

    Some Python installs (notably python.org builds on macOS) ship without
    system-CA wiring; certifi travels with the app, so HTTPS font imports
    just work.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL_CTX = _ssl_context()


def _url_fetch(url: str):
    req = urllib.request.Request(
        url, headers={"User-Agent": _GOOGLE_UA,
                      "Accept": "*/*", "Connection": "close"})
    with urllib.request.urlopen(req, timeout=_FONT_URL_TIMEOUT, context=_SSL_CTX) as r:
        return r.read()


def _font_ext_for(data: bytes, name: str) -> str:
    """Extension by magic bytes, falling back to the URL/file name."""
    if data[:4] == b"OTTO":
        return ".otf"
    if data[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
        return ".ttf"
    return Path(urllib.parse.urlparse(name).path).suffix.lower()


def _google_family_and_styles(url: str):
    """Extract a family name from a Google Fonts link/served css URL."""
    parts = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(parts.query)
    if "family" in q:                                   # css / css2 with ?family=
        fam = q["family"][0]
        fam = fam.split(":")[0].strip("+ ").replace("+", " ")
        return fam or None, []
    if parts.hostname and parts.hostname.endswith("fonts.google.com"):
        seg = [s for s in parts.path.split("/") if s]     # /specimen/Poppins
        if seg:
            fam = urllib.parse.unquote(seg[-1]).replace("+", " ").strip()
            if fam:
                return fam, []
    return None, []


def _css_ttf_urls(css: bytes):
    """(url, weight, italic) for every truetype src in a Google css response."""
    out = []
    try:
        text = css.decode("utf-8", "replace")
    except Exception:
        return out
    for block in text.split("@font-face")[1:]:
        m = re.search(r"url\((https://[^)\s]+)\)", block)
        if not m:
            continue
        w = re.search(r"font-weight:\s*([\w ]+);", block)
        style_italic = bool(re.search(r"font-style:\s*italic", block))
        try:
            weight = int((w.group(1) if w else "400").strip() or 400)
        except ValueError:
            weight = 400
        out.append((m.group(1), weight, style_italic))
    return out


def _style_suffix(weight: int, italic: bool) -> str:
    if italic and weight in (400, 500):
        return " Italic"
    if italic:
        return f" {weight} Italic"
    return "" if weight == 400 else f" {weight}"


def _save_font_bytes(data: bytes, base_name: str, ext: str, added: list) -> None:
    ext = ext if ext in renderer.FONT_EXTS else ".ttf"
    safe = re.sub(r"[^\w\-. ()]+", "_", base_name).strip(" _") or "ImportedFont"
    dest = FONTS_DIR / (safe + ext)
    ix = 2
    while dest.exists() and dest.stat().st_size != len(data):
        dest = FONTS_DIR / f"{safe} ({ix}){ext}"
        ix += 1
    dest.write_bytes(data)
    added.append({"file": dest.name, "label": dest.stem.replace("_", " ").strip()})


def _import_font_from_url(url: str):
    """Download font(s) from a Google Fonts page/link or any direct font URL.

    Returns (added_files, warning). Raises urlopen errors to the caller.
    """
    added: list[dict] = []
    host = urllib.parse.urlparse(url).hostname or ""
    path = urllib.parse.urlparse(url).path or ""

    # 1) direct .ttf/.otf/.ttc link (any server)
    if not host.endswith(_GOOGLE_HOSTS[0]) and \
            Path(path).suffix.lower() in renderer.FONT_EXTS:
        data = _url_fetch(url)
        name = urllib.parse.unquote(Path(path).name) or "Font.ttf"
        _save_font_bytes(data, Path(name).stem, Path(name).suffix.lower(), added)
        return added, ""

    # 2) Google Fonts: derive the family, fetch the legacy css API (always TTF)
    fam, _guessed = _google_family_and_styles(url)
    if not fam:
        return [], "That does not look like a Google Fonts link or a .ttf/.otf file. " \
                   "Try https://fonts.google.com/specimen/Poppins"
    seen_urls: set[str] = set()
    for variant in ("", ":700", ":i", ":700i"):        # regular · bold · italic · bold-italic
        try:
            css_url = ("https://fonts.googleapis.com/css?family="
                       + urllib.parse.quote_plus(fam) + variant)
            for u, weight, italic in _css_ttf_urls(_url_fetch(css_url)):
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                if len(added) >= _MAX_LINK_FONTS:
                    break
                data = _url_fetch(u)
                ext = _font_ext_for(data, u)
                _save_font_bytes(data, fam + _style_suffix(weight, italic), ext, added)
            if added:
                pass                       # keep trying richer variants below too
        except Exception:
            continue                       # a missing style simply contributes nothing
    return added, "" if added else \
        f"Google reported no downloadable files for “{fam}”."


@app.post("/api/import-font-url")
def import_font_url():
    """Import fonts from a Google Fonts link or any direct .ttf/.otf URL."""
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify(error="Paste a font link first."), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    try:
        added, warning = _import_font_from_url(url)
    except Exception as e:
        return jsonify(error=f"Could not download the font: {e}"), 400
    if not added:
        return jsonify(error=warning or "No font files found at that link."), 400
    renderer.refresh_fonts()
    return {"added": [a["label"] for a in added],
            "files": [a["file"] for a in added],
            "fonts": renderer.font_labels()}


# -------------------------------------------------------------- generate ---

def _sanitize(v: str) -> str:
    v = re.sub(r"[^\w\-. ()\[\]]", "", str(v)).strip(" .")
    v = re.sub(r"\s+", " ", v)
    return v


def _run_job(job_id: str, cfg: dict):
    job = JOBS[job_id]
    try:
        excel_path = cfg["excel"]["path"]
        if not Path(excel_path).is_file():
            raise FileNotFoundError("Excel file is missing — re-upload it.")
        template_path = cfg["template"]["path"]
        if not Path(template_path).is_file():
            raise FileNotFoundError("Design file is missing — re-upload it.")

        _cols, rows = read_table(excel_path)
        if not rows:
            raise ValueError("No data rows found in the Excel file.")
        excel_dir = Path(excel_path).parent
        job.update(total=len(rows), status="running")

        outdir = OUTPUT / f"{time.strftime('%Y%m%d-%H%M%S')}_{job_id}"
        outdir.mkdir(parents=True, exist_ok=True)

        prefix = cfg.get("file_prefix") or ""
        fn_col = (cfg.get("filename_column") or "").strip()
        photos_folder = cfg.get("photos_folder") or ""

        used: set[str] = set()
        png_paths: list[str] = []
        for i, row in enumerate(rows):
            warnings: list[str] = []
            try:
                img = renderer.render_card(template_path, cfg, row,
                                           photos_folder=photos_folder,
                                           excel_dir=excel_dir,
                                           collect_warnings=warnings)
            except Exception as e:  # keep the batch alive
                img = None
                warnings.append(f"render failed: {e}")
            if warnings:
                job["errors"].append({"row": i + 1, "message": "; ".join(warnings)})

            if img is not None:
                base = _sanitize(prefix)
                if fn_col:
                    base = _sanitize(prefix + row.get(fn_col, ""))
                if not base:
                    base = f"row_{i + 1:04d}"
                stem, n = base, 1
                while stem in used:
                    n += 1
                    stem = f"{base} ({n})"
                used.add(stem)
                p = outdir / f"{stem}.png"
                img.save(p, "PNG")
                png_paths.append(str(p))

            job["done"] = i + 1
            job["current"] = row.get(fn_col) or f"row {i + 1}"

        pdf_path = None
        if png_paths:
            pdf_path = outdir / "combined.pdf"
            renderer.build_pdf(png_paths, str(pdf_path), cfg.get("pdf_mode") or "fit")

        zip_path = OUTPUT / f"{outdir.name}.zip"
        shutil.make_archive(str(OUTPUT / outdir.name), "zip", root_dir=outdir)

        job.update(status="done", output=str(outdir),
                   pdf=str(pdf_path) if pdf_path else "", zip=str(zip_path))
        try:  # pop the results folder open in Explorer / Finder / Files
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(outdir)])
            elif os.name == "nt":
                os.startfile(str(outdir))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(outdir)])
        except Exception:
            pass
    except Exception as e:
        job.update(status="error", error=str(e))


@app.post("/api/generate")
def generate():
    cfg = request.get_json(force=True, silent=True)
    if not cfg or "template" not in cfg or "excel" not in cfg:
        return jsonify(error="Upload a design and an Excel file first."), 400
    # keep the jobs table bounded (browser sessions accumulate old jobs)
    with JOBS_LOCK:
        while len(JOBS) >= 50:
            JOBS.pop(next(iter(JOBS)))
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"id": job_id, "status": "running", "total": 0, "done": 0,
                        "current": "", "errors": [], "output": "", "zip": "",
                        "error": ""}
    threading.Thread(target=_run_job, args=(job_id, cfg), daemon=True).start()
    return {"job": job_id}


@app.get("/api/status/<job_id>")
def status(job_id: str):
    return _get_job(job_id)


@app.get("/api/download/<job_id>")
def download(job_id: str):
    job = _get_job(job_id)
    zp = job.get("zip")
    if not zp or not Path(zp).is_file():
        return jsonify(error="ZIP not ready"), 404
    return send_file(zp, as_attachment=True)


# -------------------------------------------------------------- projects ---

_PROJ_SAFE = re.compile(r"[^A-Za-z0-9 _()\[\]-]")


def _proj_path(name: str) -> Path:
    safe = _PROJ_SAFE.sub("", name).strip()[:80]
    if not safe:
        raise ValueError("Project name is empty")
    return PROJECTS / f"{safe}.json"


@app.get("/api/projects")
def list_projects():
    items = []
    for p in sorted(PROJECTS.glob("*.json")):
        try:
            cfg = p.read_text()
            items.append({"name": p.stem, "size": len(cfg)})
        except OSError:
            pass
    return {"projects": items}


@app.post("/api/projects/save")
def save_project():
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name") or "").strip()
    cfg = body.get("config") or {}
    if not name:
        return jsonify(error="Enter a project name"), 400
    try:
        _proj_path(name).write_text(json.dumps(cfg))
    except Exception as e:
        return jsonify(error=str(e)), 400
    return {"ok": True, "name": name}


@app.get("/api/projects/load")
def load_project():
    name = request.args.get("name", "")
    try:
        p = _proj_path(name)
    except ValueError:
        return jsonify(error="Bad project name"), 400
    if not p.is_file():
        return jsonify(error="Project not found"), 404
    return send_file(p, as_attachment=False)


@app.post("/api/projects/delete")
def delete_project():
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name") or "")
    try:
        _proj_path(name).unlink(missing_ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 400
    return {"ok": True}


# ----------------------------------------------------------------- image ---

_ALLOWED_ROOTS = [
    UPLOADS.resolve(),
    (DATA_DIR / "demo").resolve(),
    PROJECTS.resolve(),
    FONTS_DIR.resolve(),
]


@app.get("/api/template-image")
def template_image():
    raw = request.args.get("path", "")
    try:
        p = Path(raw).expanduser().resolve()
    except Exception:
        return jsonify(error="bad path"), 400
    if not any(p.is_relative_to(root) for root in _ALLOWED_ROOTS):
        return jsonify(error="forbidden"), 403
    if not p.is_file():
        return jsonify(error="design file not found"), 404
    return send_file(p)


# ------------------------------------------------------------ sample/demo ---

@app.get("/api/sample-excel")
def sample_excel():
    from demo_builder import make_sample_workbook
    return send_file(io.BytesIO(make_sample_workbook()), as_attachment=True,
                     download_name="sample_list.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/demo")
def demo_project():
    return demo_config()


# ------------------------------------------------------------------ main ---

def _pick_port(start: int = 7437) -> int:
    import socket
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def _watch_stdin() -> None:
    """Sidecar mode: exit as soon as the parent (Electron) closes our stdin.

    Guarantees the engine never outlives the app window, even if Electron
    crashes or is force-killed. Only breaks the process when stdin is a
    pipe / file (a parent that can actually be "closed"): when stdin is a
    terminal or /dev/null there is no watchable parent — keep serving.
    """
    import stat
    try:
        md = os.fstat(0).st_mode
        watchable = stat.S_ISFIFO(md) or stat.S_ISREG(md)
    except OSError:
        watchable = False
    if not watchable:
        return
    try:
        while sys.stdin.buffer.read(64 * 1024):
            pass
    except Exception:
        pass
    os._exit(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--electron", action="store_true",
                        help="run as Electron sidecar: no browser, print READY line")
    args = parser.parse_args()

    port = args.port if args.port else _pick_port()
    url = f"http://localhost:{port}"

    if args.electron:
        os.environ["AUTOCERT_ELECTRON"] = "1"
        threading.Thread(target=_watch_stdin, daemon=True).start()
        print(f"ENGINE-READY port={port}", flush=True)
        app.run(host="127.0.0.1", port=port, threaded=True)
        return

    print()
    print("  ============================================================")
    print("   AutoCert Studio")
    print("   Your browser should open automatically at:")
    print(f"   {url}")
    print("   (Keep this window open while you work. Close it to quit.)")
    print("  ============================================================")
    print()
    import webbrowser
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    main()
