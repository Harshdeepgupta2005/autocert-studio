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
- **Circular & rounded photos**: every photo box has a *shape* —
  rectangle, rounded (with an adjustable corner **radius**) or full
  **circle** (great for ID-card portraits).
- **Background remover (✂)**: tick *Remove photo background* on a photo box
  and solid/plain backdrops are cut out automatically (the subject stays).
  The *removal strength* slider decides how aggressive it is. Works together
  with any shape — e.g. a circular cut-out with a transparent background.
- **Certificates**: use "Wrap width" to flow sentences, and the
  *Text before / after* boxes for lines like
  `This is to certify that <Full Name> …`
- Font size, colour, alignment and date formats are per-field.
- **Projects** (💾) save the whole layout to reuse next time.
- **PDF page size**: *Fit to design* keeps full-bleed; A4 modes letterbox the
  design on a 300 dpi A4 page.

## Placing things exactly

- **Drag & snap** — when you drag a field near another field's centre/edges
  or the canvas edges/centre, purple **snap guides** appear and it glides
  into perfect alignment (other fields' edges and centres are targets too).
- **X / Y inputs** — type exact pixel coordinates in the field properties.
- **Align buttons** — `⇤ ⇔ ⇥` pin the field to the design's left/centre/right
  edge and `⇒/⤒ ⥮ ⤓` to the top/centre/bottom. Text fields align by their
  *true rendered bounding box* (the dashed outline you see on the canvas is
  exactly the block that will be printed).
- **Nudge** — arrow keys move by 1 px, Shift+arrows by 10 px.

## Fonts

- The font picker shows a **live preview** of every font in its own
  handwriting (searchable list, ~370 fonts on a typical Mac).
- **⤓ Import** installs your own `.ttf` / `.otf` / `.ttc` files: pick them and
  they are copied into your fonts folder and appear in the list instantly
  (also readable by the app next launch — same folder as below).

## Tips

- Design at final print quality: A4 certificate → 3508×2480 px (300 dpi);
  standard ID card → 1050×675 px (300 dpi).
- Keep the text sizes generous — they stay pixel-perfect for everyone.
- Extra fonts: the app reads system fonts, plus any `.ttf`/`.otf` you drop in
  your personal **fonts** folder — or just use the **⤓ Import** button on the
  font picker. In the desktop app that folder is inside
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
build_mac.sh                     # full macOS .dmg build in one command
uploads/  projects/  output/     # data folders (project folder in browser mode)
PACKAGING.md                     # how to build the .exe / .dmg installers
```

Regression suites: `selftest.py` (rendering) and `e2e_test.py` (full API round
trip — needs a running server on `127.0.0.1:7437`, works against dev *
and* packaged engines).

Debug capture hooks (simulate user actions in the Electron shell and quit):

```
AUTOCERT_CAPTURE=/tmp/shot.png   # screenshot the window then exit
AUTOCERT_DEMO=1                  # load the built-in demo first
AUTOCERT_SELECT=1                # select the first text field (shows properties)
AUTOCERT_PROPS=1                 # scroll the property panel into view
AUTOCERT_ERR=1                   # open the generation-warnings dialog
```
