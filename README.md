# AutoCert Studio 🎓

Batch generator for **certificates** and **ID cards** from one design + one
Excel list. Everything runs locally — no internet needed, no data leaves
the computer.

**Two ways to run it**

| | Desktop app (for everyone) | Browser mode (for building/testing) |
|---|---|---|
| macOS | open **AutoCert Studio.app** (from the `.dmg`) | double-click **`start.command`** |
| Windows | run the `AutoCertStudio-Setup.exe` installer | install Python & run `venv\Scripts\python app.py` |

Installers are built per `PACKAGING.md` (including an automatic
GitHub Actions pipeline that produces the `.exe` on a cloud Windows machine).

## Quick start (desktop)

1. Mount the `.dmg`, drag **AutoCert Studio** to Applications, open it
   (first time: right-click → **Open** to pass the unsigned-app warning).
2. The welcome guide explains the 4 steps. Use **? Guide** to reopen it.

## Quick start (browser mode, macOS)

Double-click **`start.command`** (first run installs its own private Python
environment). Your browser opens at `http://localhost:7437`.

## How to use

1. **Design** — export your certificate/ID design as **PNG** or **JPG**
   (from Canva / Photoshop / Illustrator / Figma). Bake all *static* parts
   (logo, borders, titles) into the image.
2. **Excel list** — first row must be the column names, e.g.
   `Full Name | ID Number | Course | Issue Date | Photo`
   (use `⬇ Get a sample Excel` in the app to see the format).
3. **Fields** — click **Text field**) or **Photo box**, then click on
   the design where it belongs. Assign the Excel column, font, size, colour,
   alignment. Drag to fine-tune (arrow keys nudge by 1px, Shift+arrows by 10).
4. **Live preview** — pick any row number to see exactly how it will come out.
5. **⚡ Generate all** — creates a results folder with **one PNG per person**
   (named from the column you choose) plus **combined.pdf**, and opens the
   folder automatically. A **ZIP** download copies everything too.

## Extras

- **Photos on ID cards**: keep a folder of photos, paste its path in
  *Photos folder*. In the Excel "Photo" column put the file name
  (`a1_aarav.jpg`). Full paths also work. If a photo is missing the card is
  still generated with a red "MISSING PHOTO" box, and it is reported at the end.
- **Certificates**: use "Wrap width" to flow sentences, and the
  *Text before / after* boxes for lines like
  `This is to certify that <Full Name> …`
- Font size, colour, alignment and date formats are per-field.
- **Projects** (💾) save the whole layout to reuse next time.
- **PDF page size**: *Fit to design* keeps full-bleed; A4 modes letterbox the
  design on a 300 dpi A4 page.

## Tips

- Design at final print quality: A4 certificate → 3508×2480 px (300 dpi);
  standard ID card → 1050×675 px (300 dpi).
- Keep the text sizes generous — they stay pixel-perfect for everyone.
- Extra fonts: the app reads system fonts, plus any `.ttf`/`.otf` you drop in
  your personal **fonts** folder. Click the fonts line in the app to find it —
  in the desktop app it is inside
  `~/Library/Application Support/AutoCertStudio/fonts`
  (or `%APPDATA%\AutoCertStudio\fonts` on Windows).

## Notes

- The app is local-only (`127.0.0.1`); nobody else can reach it.
- Old `.xls` files are not supported — re-save as `.xlsx` or export to CSV.
- If generation is wrong, check the **Live preview** first — it is pixel
  identical to the final output.
- Desktop-app data (uploads, saved projects, outputs, fonts) lives in your
  OS data folder: `~/Library/Application Support/AutoCertStudio`
  (`%APPDATA%\AutoCertStudio` on Windows). The app menu has
  *Open My Files Folder* to jump there.

## For developers

```
venv/bin/python selftest.py      # headless render test → selftest_output/
start.command                    # runs app.py (Flask, port 7437+, auto-browser)
npm start                        # in electron/ → run Electron in dev mode
uploads/  projects/  output/     # data folders (project folder in browser mode)
PACKAGING.md                     # how to build the .exe / .dmg installers
```

Regression suites: `selftest.py` (rendering) and `e2e_test.py` (full API round
trip — needs a running server on `127.0.0.1:7437`, works against dev *
and* packaged engines).
