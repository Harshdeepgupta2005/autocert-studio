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
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image

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
    return {"fonts": renderer.font_labels()}


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

    excel = cfg.get("excel") or {}
    rows, excel_dir = [], None
    if excel.get("path") and Path(excel["path"]).is_file():
        try:
            _columns, rows = read_table(excel["path"])
            excel_dir = Path(excel["path"]).parent
        except Exception:
            rows = []
    if rows:
        row = max(0, min(row, len(rows) - 1))
        data = rows[row]
    else:
        data = {}

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
    crashes or is force-killed.
    """
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
