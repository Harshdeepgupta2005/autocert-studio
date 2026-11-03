"""Headless pipeline test: builds demo assets, renders all rows, saves PNG+PDF.

Run:  ./venv/bin/python selftest.py
"""
from pathlib import Path

import renderer
from data_utils import read_table
from demo_builder import build_demo_assets, demo_config

OUT = Path(__file__).resolve().parent / "selftest_output"


def main() -> int:
    assets = build_demo_assets()
    cfg = demo_config()
    cols, rows = read_table(assets["excel"])
    print(f"cols={cols!r} rows={len(rows)}")

    OUT.mkdir(exist_ok=True)
    pngs = []
    for i, row in enumerate(rows):
        warnings = []
        img = renderer.render_card(assets["template"], cfg, row,
                                   photos_folder=assets["photos_dir"],
                                   excel_dir=assets["excel_dir"],
                                   collect_warnings=warnings)
        p = OUT / f"test_{row['ID Number']}.png"
        img.save(p, "PNG")
        pngs.append(str(p))
        print(f"  row {i+1}: {row['Full Name']:<14} -> {p.name}"
              + (f"  WARNINGS: {warnings}" if warnings else ""))

    pdf = OUT / "test_combined.pdf"
    renderer.build_pdf(pngs, str(pdf), "fit")
    print(f"PDF: {pdf} ({pdf.stat().st_size//1024} KB)")

    # also an A4 landscape variant for good measure
    pdf2 = OUT / "test_combined_a4.pdf"
    renderer.build_pdf(pngs[:2], str(pdf2), "a4l")
    print(f"PDF (A4L): {pdf2} ({pdf2.stat().st_size//1024} KB)")

    print("SELFTEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
