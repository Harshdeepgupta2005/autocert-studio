"""Builds the built-in demo assets (sample ID-card template, photos, Excel).

Used by the app's "Load demo" button and by selftest.py.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

from PIL import Image, ImageDraw
from openpyxl import Workbook

import renderer
from app_config import DEMO_DIR

# canvas size for the demo ID card
TEMPLATE_SIZE = (1200, 750)
W, H = TEMPLATE_SIZE

FRAME = "#20306E"   # deep blue
GOLD = "#E8B23A"
INK = "#16233F"

DEMO_COLUMNS = ["Full Name", "ID Number", "Course", "Issue Date", "Photo"]
DEMO_ROWS = [
    ["Aarav Sharma", "ACM-2026-001", "B.Tech CSE", datetime.date(2026, 1, 15), "1_Aarav.jpg"],
    ["Ishita Verma", "ACM-2026-002", "B.Tech ECE", "15/03/2026", "2_Ishita.jpg"],
    ["Rohan Mehta", "ACM-2026-003", "MBA Finance", "2026-05-02", "3_Rohan.jpg"],
    ["Meera Iyer", "ACM-2026-004", "M.Sc Physics", "12/07/2026", "4_Meera.jpg"],
    ["Karan Singh", "ACM-2026-005", "BBA", "2026-08-19", "5_Karan.jpg"],
]

def build_template(path: Path) -> None:
    img = Image.new("RGB", TEMPLATE_SIZE, (255, 255, 255))
    d = ImageDraw.Draw(img)

    # outer frame
    d.rectangle([10, 10, W - 11, H - 11], outline=FRAME, width=6)
    # header band
    d.rectangle([14, 14, W - 15, 140], fill=FRAME)
    d.text((W / 2, 62), "STUDENT IDENTITY CARD",
           font=renderer.get_font("Arial Bold", 50), fill="white", anchor="mm")
    d.text((W / 2, 108), "ACME INSTITUTE OF TECHNOLOGY",
           font=renderer.get_font("Arial", 24), fill=GOLD, anchor="mm")
    # gold strip under header
    d.rectangle([14, 146, W - 15, 158], fill=GOLD)

    # photo frame
    d.rectangle([70, 215, 300, 505], outline=FRAME, width=3)
    d.text((185, 360), "PHOTO", font=renderer.get_font("Arial Bold", 24),
           fill="#9AA3B2", anchor="mm")

    # static labels for the info column
    label_font = renderer.get_font("Arial Bold", 22)
    d.text((370, 232), "FULL NAME", font=label_font, fill="#5A6270")
    d.text((370, 372), "ID NUMBER", font=label_font, fill="#5A6270")
    d.text((370, 492), "PROGRAM", font=label_font, fill="#5A6270")
    d.text((370, 612), "ISSUED ON", font=label_font, fill="#5A6270")

    # accent dashes next to values
    for y in (258, 398, 518, 638):
        d.rectangle([370, y + 62, 420, y + 66], fill=GOLD)

    # signature line
    d.line([880, 690, 1140, 690], fill="#555E6D", width=2)
    d.text((1010, 664), "Registrar Signature", font=renderer.get_font("Arial", 18),
           fill="#555E6D", anchor="mm")
    # footer note
    d.text((60, 706), "This card is the property of ACME Institute of Technology. "
           "If found, please return.", font=renderer.get_font("Arial", 15),
           fill="#8A93A3")

    img.save(path)


def build_photo(path: Path, initial: str, bg: str) -> None:
    img = Image.new("RGB", (400, 500), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 399, 499], outline=(255, 255, 255))
    d.ellipse([130, 120, 270, 260], fill="#FFFFFF")
    d.text((200, 188), initial, font=renderer.get_font("Arial Bold", 90),
           fill=bg, anchor="mm")
    d.rectangle([0, 300, 400, 500], fill=(255, 255, 255))
    d.text((200, 340), "SAMPLE", font=renderer.get_font("Arial Bold", 40),
           fill="#7A8194", anchor="mm")
    d.text((200, 392), "PHOTO", font=renderer.get_font("Arial Bold", 40),
           fill="#B6BCC9", anchor="mm")
    img.save(path, quality=88)


def make_sample_workbook() -> bytes:
    """Sample Excel as bytes so the user can download a template."""
    wb = Workbook()
    ws = wb.active
    ws.title = "List"
    ws.append(DEMO_COLUMNS)
    for r in DEMO_ROWS:
        ws.append(list(r))
    widths = [22, 16, 18, 14, 16]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_demo_assets() -> dict:
    """Create demo folder contents once; return paths."""
    DEMO_DIR.mkdir(exist_ok=True)
    photos_dir = DEMO_DIR / "photos"
    photos_dir.mkdir(exist_ok=True)

    template = DEMO_DIR / "template_id_card.png"
    if not template.exists():
        build_template(template)

    colors = ["#4F46E5", "#0E9F6E", "#D97706", "#DC2626", "#0284C7"]
    initials = ["A", "I", "R", "M", "K"]
    for i, (row, col) in enumerate(zip(DEMO_ROWS, colors)):
        p = photos_dir / row[4]
        if not p.exists():
            build_photo(p, initials[i], col)

    excel = DEMO_DIR / "sample_list.xlsx"
    if not excel.exists():
        excel.write_bytes(make_sample_workbook())

    excel_dir = excel.parent
    return {
        "template": str(template),
        "excel": str(excel),
        "photos_dir": str(photos_dir),
        "excel_dir": str(excel_dir),
        "columns": DEMO_COLUMNS,
    }


def demo_config() -> dict:
    assets = build_demo_assets()
    dims = Image.open(assets["template"]).size

    def text_field(idn, column, x, y, size, extra=None):
        f = {
            "id": idn, "type": "text", "column": column, "x": x, "y": y,
            "font": "Arial", "size": size, "color": INK,
            "align": "left", "valign": "center", "wrap_width": 0,
            "uppercase": False, "datefmt": "", "prefix": "", "suffix": "",
        }
        if extra:
            f.update(extra)
        return f

    fields = [
        text_field("n", "Full Name", 370, 288, 42),
        text_field("i", "ID Number", 370, 426, 36),
        text_field("c", "Course", 370, 546, 36),
        text_field("d", "Issue Date", 370, 664, 32,
                   {"datefmt": "%d %b %Y"}),
        {
            "id": "p", "type": "photo", "column": "Photo",
            "x": 91, "y": 236, "width": 188, "height": 248,
            "fit": "fill", "border": 0, "border_color": FRAME,
        },
    ]
    return {
        "name": "Demo ID Card",
        "photos_folder": assets["photos_dir"],
        "filename_column": "ID Number",
        "file_prefix": "",
        "pdf_mode": "fit",
        "template": {"path": assets["template"], "name": "template_id_card.png",
                     "width": dims[0], "height": dims[1]},
        "excel": {"path": assets["excel"], "name": "sample_list.xlsx",
                  "columns": DEMO_COLUMNS, "row_count": len(DEMO_ROWS)},
        "fields": fields,
    }
