"""Rendering engine for AutoCert Studio.

Draws text / photo fields (defined in a project config) onto a template image,
once per Excel row. Also assembles the combined PDF.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from collections import deque
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app_config import FONTS_DIR

FONT_EXTS = {".ttf", ".otf", ".ttc"}

_FONT_DIRS = [
    FONTS_DIR,                                          # user-droppable fonts
    Path.home() / "Library" / "Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
]
if sys.platform == "win32":
    _FONT_DIRS.append(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
if sys.platform.startswith("linux"):
    for extra in ("/usr/share/fonts", "/usr/local/share/fonts"):
        _FONT_DIRS.append(Path(extra))

_FALLBACKS = ["Arial", "Helvetica Neue", "Verdana", "Georgia", "Times New Roman"]


# ---------------------------------------------------------------- fonts ----

@lru_cache(maxsize=1)
def _font_index() -> dict[str, Path]:
    """casefolded font name -> file path (first match wins)."""
    index: dict[str, Path] = {}
    for d in _FONT_DIRS:
        if not d.is_dir():
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.suffix.lower() not in FONT_EXTS or p.name.startswith("."):
                continue
            key = p.stem.replace("_", " ").strip().casefold()
            if key and key not in index:
                index[key] = p
    return index


@lru_cache(maxsize=1)
def font_list() -> list[tuple[str, str]]:
    """Sorted (display_label, path) for the font picker."""
    pairs = [
        (p.stem.replace("_", " ").strip(), str(p))
        for p in _font_index().values()
    ]
    pairs = [(l, p) for (l, p) in pairs if l]
    pairs.sort(key=lambda t: (t[0].casefold(), len(t[0])))
    # dedupe case-insensitively (first occurrence kept)
    seen: set[str] = set()
    out = []
    for label, path in pairs:
        k = label.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append((label, path))
    return out


def font_labels() -> list[str]:
    return [label for label, _path in font_list()]


def refresh_fonts() -> None:
    """Re-scan every font folder (call after fonts are imported or removed)."""
    _font_index.cache_clear()
    font_list.cache_clear()
    get_font.cache_clear()


def _match_font(label: str) -> Path | None:
    if not label:
        return None
    idx = _font_index()
    want = str(label).strip().casefold()
    if not want:
        return None
    if want in idx:                                  # exact
        return idx[want]
    for k, v in idx.items():                         # prefix
        if k.startswith(want):
            return v
    for k, v in idx.items():                         # contains word
        if want in k:
            return v
    return None


@lru_cache(maxsize=None)
def get_font(label: str, size: int):
    size = max(6, int(size))
    candidates = [label, *_FALLBACKS]
    for name in candidates:
        p = _match_font(name)
        if p:
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default(size)


def font_path(label: str) -> str | None:
    """Resolve a font display label to its file path (None if unknown)."""
    p = _match_font(label)
    return str(p) if p else None


# ----------------------------------------------------------------- data ----

_STRPTIME_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%Y/%m/%d",
]


def format_value(value, datefmt: str = "") -> str:
    if value is None:
        return ""
    # datetime is a subclass of date -> check datetime first
    if isinstance(value, _dt.datetime):
        return value.strftime(datefmt or "%d/%m/%Y")
    if isinstance(value, _dt.date):
        return value.strftime(datefmt or "%d/%m/%Y")
    if isinstance(value, str):
        s = value.strip()
        if datefmt and s:
            for f in _STRPTIME_FORMATS:
                try:
                    return _dt.datetime.strptime(s, f).strftime(datefmt)
                except ValueError:
                    pass
        return s
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _column_name(col) -> str:
    if isinstance(col, dict):
        return str(col.get("name", "")).strip()
    return str(col or "").strip()


def compose_text(field: dict, row: dict) -> str:
    name = _column_name(field.get("column"))
    value = row.get(name, "")
    mid = format_value(value, field.get("datefmt") or "")
    txt = (field.get("prefix") or "") + mid + (field.get("suffix") or "")
    txt = txt.strip()
    if field.get("uppercase"):
        txt = txt.upper()
    return txt


def _wrap_lines(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    if not max_width or max_width <= 0:
        return [" ".join(words)]
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if not cur or draw.textlength(cand, font=font) <= max_width:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def layout_text(text: str, field: dict) -> dict:
    """Measure how a text block will be drawn, without painting it.

    Returns {lines, width, height, line_h} with exactly the geometry
    _draw_text uses, so the UI can place a true bounding box around text.
    """
    font = get_font(field.get("font") or "", int(field.get("size") or 40))
    wrap = int(field.get("wrap_width") or 0)
    dummy = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines = _wrap_lines(dummy, text, font, wrap)
    if not lines:
        return {"lines": [], "width": 0, "height": 0, "line_h": 0}

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    n = len(lines)
    if n > 1 and not wrap:
        line_gap = int(field.get("line_spacing") or 8)
    else:
        line_gap = int(field.get("line_spacing") or max(4, round(0.15 * line_h)))
    width = max(round(dummy.textlength(ln, font=font)) for ln in lines)
    height = n * line_h + line_gap * (n - 1)
    return {"lines": lines, "width": width, "height": height, "line_h": line_h}


# ----------------------------------------------------------------- draw ----

def _draw_text(base, draw, field: dict, row: dict) -> None:
    txt = compose_text(field, row)
    if not txt:
        return
    metrics = layout_text(txt, field)
    lines = metrics["lines"]
    font = get_font(field.get("font") or "", int(field.get("size") or 40))

    align = field.get("align") or "center"
    valign = field.get("valign") or ("top" if int(field.get("wrap_width") or 0) else "center")
    x, y = float(field.get("x", 0)), float(field.get("y", 0))
    color = field.get("color") or "#111111"

    line_h = metrics["line_h"]
    total_h = metrics["height"]
    n = len(lines)
    line_gap = max(0, (total_h - n * line_h) // (n - 1)) if n > 1 else 0

    if valign == "top":
        y0 = y
    elif valign == "bottom":
        y0 = y - total_h
    else:
        y0 = y - total_h / 2

    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        if align == "left":
            lx = x
        elif align == "right":
            lx = x - lw
        else:
            lx = x - lw / 2
        ly = y0 + i * (line_h + line_gap)
        draw.text((lx, ly), line, font=font, fill=color)


def resolve_photo(value, config: dict, excel_dir=None) -> Path | None:
    if value is None:
        return None
    v = str(value).strip().strip('"').strip()
    if not v or v.lower() in {"n/a", "na", "none"}:
        return None
    if excel_dir is not None and not isinstance(excel_dir, Path):
        excel_dir = Path(excel_dir)
    candidates: list[Path] = [Path(v)]
    if excel_dir is not None:
        candidates.append(excel_dir / v)
        candidates.append(excel_dir / Path(v).name)
    pf = config.get("photos_folder")
    if pf:
        candidates.append(Path(pf) / v)
        candidates.append(Path(pf) / Path(v).name)
        pfn = Path(pf).expanduser()
        if not pfn.is_absolute():
            pfn = (Path.cwd() / pfn).resolve()
        candidates.append(pfn / v)
        candidates.append(pfn / Path(v).name)
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


# --------------------------------------------------- photo shaping ----

# background-removal results are cached per file+tolerance so a batch
# re-uses the same photo across many rows without re-computing.
_BG_CACHE: dict = {}
_BG_CACHE_MAX = 48
_MAX_BG_WORK = 640           # flood-fill at most this many px on the long side
_TOL_MAX = 140


def _remove_background(ph: Image.Image, tol: int, cache_key=None) -> Image.Image:
    """Make the background of a photo transparent.

    Flood-fills from the border pixels with a tolerance, so only background
    *connected to the border* is removed — same-coloured parts inside the
    subject survive. Returns an RGBA image with a soft-edged alpha.
    """
    tol = max(2, min(_TOL_MAX, int(tol or 30)))
    work = ph.convert("RGB")
    if max(work.size) > _MAX_BG_WORK:
        scale = _MAX_BG_WORK / max(work.size)
        work = work.resize(
            (max(1, round(work.width * scale)), max(1, round(work.height * scale))),
            Image.Resampling.BILINEAR,
        )

    mask = None
    if cache_key is not None:
        cached = _BG_CACHE.get(cache_key)
        if cached and cached[0] == tol:
            mask = cached[1]
    if mask is None:
        mask = Image.new("L", work.size, 255)   # 255 = keep, 0 = background
        mpx = mask.load()
        wpx = work.load()
        W, H = work.size
        seeds = [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1),
                 (0, H // 2), (W // 2, 0), (W - 1, H // 2), (W // 2, H - 1)]
        visited = bytearray(W * H)
        q: deque = deque()
        for sx, sy in seeds:
            idx = sy * W + sx
            if not visited[idx]:
                visited[idx] = 1
                q.append((sx, sy, wpx[sx, sy][:3]))
        t2 = tol * tol * 3
        while q:
            px, py, seed = q.popleft()
            mpx[px, py] = 0
            for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                if 0 <= nx < W and 0 <= ny < H:
                    idx = ny * W + nx
                    if not visited[idx]:
                        nr, ng, nb = wpx[nx, ny][:3]
                        if ((seed[0] - nr) ** 2 + (seed[1] - ng) ** 2
                                + (seed[2] - nb) ** 2) <= t2:
                            visited[idx] = 1
                            q.append((nx, ny, seed))
        if cache_key is not None:
            if len(_BG_CACHE) >= _BG_CACHE_MAX:
                _BG_CACHE.pop(next(iter(_BG_CACHE)))
            _BG_CACHE[cache_key] = (tol, mask)

    # upscale the working mask and keep a soft anti-aliased edge
    alpha = mask.resize(ph.size, Image.Resampling.LANCZOS)
    alpha = alpha.point(lambda v: 0 if v < 40 else (255 if v > 215 else v))
    out = ph.convert("RGBA")
    out.putalpha(alpha)
    return out


def _box_mask(w: int, h: int, shape: str, radius: int) -> Image.Image:
    """Alpha mask for the photo box: rectangle / rounded / circle."""
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    if shape == "circle":
        d.ellipse([0, 0, w - 1, h - 1], fill=255)
    elif shape == "round":
        r = max(0, min(int(radius or 0), min(w, h) // 2))
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    else:
        d.rectangle([0, 0, w - 1, h - 1], fill=255)
    return mask


def _draw_photo(base, draw, field: dict, row: dict, config: dict,
                excel_dir: Path | None, warnings: list | None) -> None:
    x = int(field.get("x", 0))
    y = int(field.get("y", 0))
    w = max(4, int(field.get("width", 300)))
    h = max(4, int(field.get("height", 400)))
    shape = field.get("shape") or "rect"
    radius = int(field.get("radius") or 0)
    bg_remove = bool(field.get("bg_remove"))
    bg_tol = field.get("bg_tol", 30)

    name = _column_name(field.get("column"))
    path = resolve_photo(row.get(name, ""), config, excel_dir)

    if not path:
        draw.rectangle([x, y, x + w, y + h], fill=(235, 235, 240),
                       outline=(200, 70, 70), width=3)
        try:
            draw.text((x + 10, y + h // 2 - 10), "MISSING PHOTO",
                      font=get_font("Arial", 20), fill=(150, 40, 40))
        except Exception:
            pass
        if warnings is not None:
            warnings.append("photo not found in Excel column")
        return

    try:
        ph = Image.open(path)
    except Exception:
        if warnings is not None:
            warnings.append(f"could not open photo: {path.name}")
        draw.rectangle([x, y, x + w, y + h], fill=(235, 235, 240),
                       outline=(200, 70, 70), width=3)
        return

    if bg_remove:
        try:
            mtime = 0
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                pass
            ph = _remove_background(ph, bg_tol, cache_key=(str(path), mtime))
        except Exception:
            if warnings is not None:
                warnings.append(f"background removal failed for: {path.name}")
            ph = ph.convert("RGB")
    else:
        ph = ph.convert("RGB")

    fit = field.get("fit") or "fill"
    if fit == "fill":
        scale = max(w / ph.width, h / ph.height)
        nw, nh = max(w, round(ph.width * scale)), max(h, round(ph.height * scale))
        ph = ph.resize((nw, nh), Image.Resampling.LANCZOS)
        left, top = (nw - w) // 2, (nh - h) // 2
        ph = ph.crop((left, top, left + w, top + h))
        px, py = x, y
    else:  # contain
        scale = min(w / ph.width, h / ph.height)
        nw, nh = max(1, round(ph.width * scale)), max(1, round(ph.height * scale))
        ph = ph.resize((nw, nh), Image.Resampling.LANCZOS)
        px, py = x + (w - nw) // 2, y + (h - nh) // 2

    if shape != "rect" or bg_remove:
        if shape == "rect":
            alpha = ph.getchannel("A")
        elif bg_remove:
            alpha = ImageChops.darker(_box_mask(ph.width, ph.height, shape, radius),
                                      ph.getchannel("A"))
        else:
            alpha = _box_mask(ph.width, ph.height, shape, radius)
        base.paste(ph, (px, py), alpha)
    else:
        base.paste(ph, (px, py))

    bw = int(field.get("border") or 0)
    if bw > 0:
        color = field.get("border_color") or "#20306E"
        r = max(0, min(radius, min(w, h) // 2))
        if shape == "circle":
            draw.ellipse([x + bw // 2, y + bw // 2, x + w - bw // 2, y + h - bw // 2],
                         outline=color, width=bw)
        elif shape == "round" and r > 0:
            draw.rounded_rectangle(
                [x + bw // 2, y + bw // 2, x + w - bw // 2, y + h - bw // 2],
                radius=r, outline=color, width=bw,
            )
        else:
            draw.rectangle(
                [x + bw // 2, y + bw // 2, x + w - bw // 2, y + h - bw // 2],
                outline=color, width=bw,
            )


# -------------------------------------------------------------- render -----

def render_card(template_path, config: dict, row: dict,
                photos_folder: str = "", excel_dir=None,
                collect_warnings: list | None = None) -> Image.Image:
    """Render one card/certificate for `row` and return an RGB image."""
    if photos_folder:
        config = dict(config)
        config["photos_folder"] = photos_folder

    with Image.open(template_path) as tpl:
        if tpl.mode in ("RGBA", "LA", "P"):
            tpl_rgba = tpl.convert("RGBA")
            base = Image.new("RGB", tpl_rgba.size, (255, 255, 255))
            base.paste(tpl_rgba, mask=tpl_rgba.split()[-1])
        else:
            base = tpl.convert("RGB")

    draw = ImageDraw.Draw(base)
    for field in config.get("fields", []):
        if field.get("type") == "photo":
            _draw_photo(base, draw, field, row, config, excel_dir, collect_warnings)
        else:
            _draw_text(base, draw, field, row)
    return base


# ----------------------------------------------------------------- pdf -----

def build_pdf(png_paths: list[str], out_path: str, mode: str = "fit") -> None:
    """Combine rendered PNGs into one PDF.

    mode 'fit'  -> each page is exactly the design size at 300 dpi
    mode 'a4l' / 'a4p' -> design scaled to fit an A4 page (300 dpi), centered
    """
    if not png_paths:
        raise ValueError("no images to combine")

    if mode in ("a4l", "a4p"):
        page_w, page_h = (3508, 2480) if mode == "a4l" else (2480, 3508)

        def _pages():
            for pth in png_paths:
                im = Image.open(pth).convert("RGB")
                scale = min(page_w / im.width, page_h / im.height)
                im = im.resize(
                    (max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                    Image.Resampling.LANCZOS,
                )
                page = Image.new("RGB", (page_w, page_h), "white")
                page.paste(im, ((page_w - im.width) // 2, (page_h - im.height) // 2))
                yield page

        pages = _pages()
    else:
        def _pages():
            for pth in png_paths:
                yield Image.open(pth).convert("RGB")

        pages = _pages()

    first = next(pages)
    first.save(out_path, "PDF", save_all=True, append_images=pages,
               resolution=300, quality=92)
