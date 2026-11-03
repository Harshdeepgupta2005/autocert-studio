"""End-to-end HTTP test against a running AutoCert Studio server (stdlib only)."""
import http.client
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 7437
ROOT = f"http://{HOST}:{PORT}"


def get_json(path):
    with urllib.request.urlopen(ROOT + path, timeout=30) as r:
        return json.loads(r.read())


def multipart(path, fpath, field="file"):
    boundary = "----e2eboundary8291"
    fp = Path(fpath)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{fp.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + fp.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    conn = http.client.HTTPConnection(HOST, PORT, timeout=60)
    conn.request("POST", path, body=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, json.loads(data)


def post_json(path, payload):
    req = urllib.request.Request(ROOT + path, method="POST",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main() -> int:
    ok = get_json("/api/health")
    assert ok["ok"]

    fonts = get_json("/api/fonts")
    names = fonts["fonts"]
    assert any("Arial" in n for n in names), names[:5]
    print(f"/api/fonts → {len(names)} fonts, sample: {names[:3]}")

    st, upl = multipart("/api/upload-template", BASE / "demo" / "template_id_card.png")
    assert st == 200 and upl["width"] == 1200, upl
    print("/api/upload-template →", upl["name"], upl["width"], "×", upl["height"])

    st, exl = multipart("/api/upload-excel", BASE / "demo" / "sample_list.xlsx")
    assert st == 200 and exl["row_count"] == 5, exl
    print("/api/upload-excel →", exl["columns"])

    cfg = {
        "template": upl, "excel": exl,
        "photos_folder": str((BASE / "demo" / "photos").resolve()),
        "filename_column": "ID Number", "file_prefix": "Card_",
        "pdf_mode": "fit",
        "fields": [
            {"id": "n1", "type": "text", "column": "Full Name", "x": 370, "y": 288,
             "font": "Arial", "size": 42, "color": "#16233F",
             "align": "left", "valign": "center", "wrap_width": 0,
             "uppercase": False, "datefmt": "", "prefix": "", "suffix": ""},
            {"id": "p1", "type": "photo", "column": "Photo", "x": 91, "y": 236,
             "width": 188, "height": 248, "fit": "fill", "border": 0,
             "border_color": "#20306E"},
        ],
    }

    # preview row 2
    req = urllib.request.Request(ROOT + "/api/preview?row=1", method="POST",
                                 data=json.dumps(cfg).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        png = r.read()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 30000
    print(f"/api/preview → {len(png)//1024} KB PNG ok")

    # missing-photo warning path: column named wrongly
    bad = json.loads(json.dumps(cfg))
    bad["fields"][1] = dict(bad["fields"][1], column="Photo")
    bad["photos_folder"] = "/definitely/not/a/folder"
    req = urllib.request.Request(ROOT + "/api/preview?row=0", method="POST",
                                 data=json.dumps(bad).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
        assert r.headers.get("x-generation-warnings")
    print("/api/preview (missing photo) → warning header present")

    # generate + poll
    job = post_json("/api/generate", cfg)["job"]
    while True:
        stt = get_json("/api/status/" + job)
        if stt.get("status") != "running":
            break
        time.sleep(0.4)
    assert stt["status"] == "done", stt
    assert stt["done"] == 5 and stt["total"] == 5, stt
    print("/api/generate → done:", stt["output"])
    assert Path(stt["output"], "combined.pdf").is_file()
    npng = len(list(Path(stt["output"]).glob("Card_*.png")))
    assert npng == 5, npng
    print("   output ok: 5 PNGs (Card_) + combined.pdf")

    # zip download
    with urllib.request.urlopen(ROOT + "/api/download/" + job, timeout=60) as r:
        data = r.read()
    assert len(data) > 10000
    print(f"/api/download → {len(data)//1024} KB zip ok")

    # projects save/load
    post_json("/api/projects/save", {"name": "e2e-test", "config": cfg})
    plist = get_json("/api/projects")["projects"]
    assert any(p["name"] == "e2e-test" for p in plist), plist
    got = get_json("/api/projects/load?name=e2e-test")
    assert got["template"]["path"] == cfg["template"]["path"]
    post_json("/api/projects/delete", {"name": "e2e-test"})
    plist = get_json("/api/projects")["projects"]
    assert not any(p["name"] == "e2e-test" for p in plist)
    print("/api/projects → save/list/load/delete ok")

    # sample excel + demo config
    with urllib.request.urlopen(ROOT + "/api/sample-excel", timeout=30) as r:
        assert len(r.read()) > 4000
    demo = get_json("/api/demo")
    assert demo["fields"] and demo["template"]["width"] == 1200
    print("/api/sample-excel, /api/demo → ok")

    print("E2E OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
