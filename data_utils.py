"""Excel / CSV reading helpers for AutoCert Studio."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from openpyxl import load_workbook


def read_table(path: str):
    """Return (columns, rows). columns = [header strings], rows = [dicts].

    First row is treated as the header. Fully empty rows are dropped.
    """
    p = Path(path)
    if p.suffix.lower() == ".csv":
        headers, data = _read_csv(p)
    else:
        headers, data = _read_xlsx(p)

    columns: list[str] = []
    for h in headers:
        name = str(h if h is not None else "").strip()
        if not name:
            name = "Column"
        base, n = name, 1
        while name in columns:
            n += 1
            name = f"{base} ({n})"
        columns.append(name)

    def norm(raw: list) -> dict:
        d = {}
        for i, name in enumerate(columns):
            v = raw[i] if i < len(raw) else ""
            if v is None:
                v = ""
            if hasattr(v, "strip"):
                v = str(v)  # keep leading/trailing spaces in values as typed
            d[name] = v
        return d

    rows = [norm(r) for r in data]
    rows = [r for r in rows if any(str(v).strip() for v in r.values())]
    return columns, rows


def _read_csv(p: Path):
    all_rows: list[list[str]] = []
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(p, newline="", encoding=enc) as fh:
                all_rows = list(csv.reader(fh))
            break
        except UnicodeDecodeError:
            continue
    if not all_rows:
        return [], []
    if len(all_rows) == 1 and all_rows[0] and "\t" in all_rows[0][0]:
        # tab separated data saved as .csv
        text = "\n".join(",".join(r) for r in all_rows)
        all_rows = list(csv.reader(io.StringIO(text.replace("\t", ","))))
    return all_rows[0], all_rows[1:]


def _read_xlsx(p: Path):
    wb = load_workbook(p, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    tables = list(ws.iter_rows(values_only=True))
    wb.close()
    if not tables:
        return [], []
    headers = list(tables[0])
    data = [list(r) for r in tables[1:]]
    return headers, data
