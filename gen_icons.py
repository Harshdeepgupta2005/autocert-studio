"""Generates the AutoCert Studio app icons (macOS .icns + Windows .ico).

Draws a premium gradient app icon: indigo squircle with a certificate sheet,
gold seal and an "Aa" mark.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import renderer

OUT = Path(__file__).resolve().parent / "electron" / "build"
OUT.mkdir(parents=True, exist_ok=True)
S = 1024


def grad_image(size, c1, c2):
    """Vertical-diagonal gradient."""
    w, h = size
    small = Image.new("RGB", (w // 8 or 1, h // 8 or 1))
    px = small.load()
    for y in range(small.height):
        for x in range(small.width):
            t = (x / small.width + y / small.height) / 2
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return small.resize(size, Image.Resampling.BILINEAR)


def rounded_mask(size, radius_ratio=0.225):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    r = int(size[0] * radius_ratio)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=r, fill=255)
    return m


def draw_icon(size):
    scale = size / S
    img = grad_image((size, size), (72, 58, 205), (146, 86, 246))

    d = ImageDraw.Draw(img)

    # subtle inner highlight ring
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(S * 0.225 * scale), outline=(255, 255, 255, 40), width=max(1, int(3 * scale)))

    # certificate sheet
    sw, sh = int(430 * scale), int(520 * scale)
    sx, sy = (size - sw) // 2, int((size - sh) // 2 + 10 * scale)
    d.rounded_rectangle([sx, sy, sx + sw, sy + sh], radius=int(34 * scale), fill="#FFFFFF")
    d.rounded_rectangle([sx, sy, sx + sw, sy + sh], radius=int(34 * scale),
                        outline=(230, 232, 244), width=max(2, int(4 * scale)))

    # header band on the sheet
    d.rounded_rectangle([sx + int(34 * scale), sy + int(34 * scale),
                         sx + sw - int(34 * scale), sy + int(110 * scale)],
                        radius=int(18 * scale), fill="#20306E")
    d.text((sx + sw // 2, sy + int(72 * scale)), "CERTIFICATE",
           font=renderer.get_font("Arial Bold", max(8, int(44 * scale))),
           fill="#FFFFFF", anchor="mm")

    # gray text lines
    for i, lw in enumerate((0.72, 0.58, 0.65)):
        y = sy + int((150 + 66 * i) * scale)
        d.rounded_rectangle([sx + int(48 * scale), y,
                             sx + int(48 * scale) + int((sw - 96) * lw), y + int(26 * scale)],
                            radius=int(13 * scale), fill="#E4E7F2")

    # big name placeholder line (darker) + gold underline
    d.rounded_rectangle([sx + int(48 * scale), sy + int(370 * scale),
                         sx + sw - int(48 * scale), sy + int(412 * scale)],
                        radius=int(20 * scale), fill="#C9CEDE")
    d.rounded_rectangle([sx + int(48 * scale), sy + int(430 * scale),
                         sx + int(48 * scale) + int(120 * scale), sy + int(444 * scale)],
                        radius=int(7 * scale), fill="#E8B23A")

    # gold seal bottom right
    cx, cy, r = sx + sw - int(70 * scale), sy + sh - int(70 * scale), int(64 * scale)
    # ribbon tails
    d.polygon([(cx - int(28 * scale), cy + int(40 * scale)),
               (cx - int(58 * scale), cy + int(120 * scale)),
               (cx - int(6 * scale), cy + int(96 * scale))], fill="#E8B23A")
    d.polygon([(cx + int(24 * scale), cy + int(36 * scale)),
               (cx + int(52 * scale), cy + int(118 * scale)),
               (cx + int(2 * scale), cy + int(96 * scale))], fill="#D99A26")
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#F2C14E",
              outline="#D99A26", width=max(2, int(5 * scale)))
    d.ellipse([cx - int(r * 0.62), cy - int(r * 0.62), cx + int(r * 0.62), cy + int(r * 0.62)],
              outline="#B9861F", width=max(1, int(4 * scale)))
    lw = max(3, int(9 * scale))
    d.line([(cx - int(26 * scale), cy + int(2 * scale)), (cx - int(4 * scale), cy + int(26 * scale))],
           fill="#7A5A11", width=lw, joint="curve")
    d.line([(cx - int(4 * scale), cy + int(26 * scale)), (cx + int(28 * scale), cy - int(24 * scale))],
           fill="#7A5A11", width=lw, joint="curve")

    return img


def main():
    icon = draw_icon(S)
    png = OUT / "icon.png"
    icon.save(png)

    # macOS iconset -> icns
    iconset = OUT / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for sz in (16, 32, 64, 128, 256, 512, 1024):
        img = icon.resize((sz, sz), Image.Resampling.LANCZOS)
        img.save(iconset / f"icon_{sz}x{sz}.png")
        if sz >= 32:
            img.resize((sz // 2, sz // 2), Image.Resampling.LANCZOS).save(
                iconset / f"icon_{sz // 2}x{sz // 2}@2x.png")

    # Windows .ico (multiple resolutions in one file)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                 (64, 64), (128, 128), (256, 256)])
    print("icons written to", OUT)
    print(png)


if __name__ == "__main__":
    main()
