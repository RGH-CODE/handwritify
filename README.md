# Handwritify

Turn book pages, PDFs, PowerPoint slides, or photos into handwritten-style
notes — runs entirely on your own computer, with a simple web page as the
interface. No files leave your machine.

## What it does

1. **Upload** PDF / PPTX / JPG / PNG files, in whatever order you want them
   combined (drag to reorder, or use the ↑/↓ buttons on each file).
2. **Text and pictures are extracted separately.** For photos and scans,
   the page is deskewed and OCR'd, and anything that isn't recognisable
   text — diagrams, photos, tables drawn as art — is automatically
   detected and cropped out as a picture instead of turning into OCR
   garbage in your notes. PDFs and PPTX keep their real text and their
   embedded/vector images the same way.
3. **Choose a look**: handwriting font, paper style and background colour, ink colour, and how
   pictures should be redrawn (pencil sketch, ink line drawing, plain
   black & white, kept as-is, or left out) — plus a full spacing/layout
   panel (line spacing, word/letter spacing, paragraph gaps, indent,
   alignment, margins, page size, heading size, page numbers).
4. **Convert**, then **edit the actual result**: the extracted text opens
   in an editor next to the preview. Fix OCR mistakes, add headings, move
   a picture, insert a page break — then hit Apply and the pages redraw.
   Change any option in step 2 and Apply redraws with the new look too.
5. **Copy** the plain text, **download** a handwritten-look PDF or an
   editable Word (.docx), or **Share** the PDF via your OS's share sheet
   where the browser supports it.

## About the "AI handwriting" engine — please read

There are two ways to generate handwriting digitally:

- **Font + jitter (what this app uses):** a handwriting-style font is drawn
  with randomised per-character rotation, baseline wobble and spacing. Fast,
  works offline, no GPU, looks convincingly organic once you add a real
  handwriting font (see below). Every render uses a random "hand" (seed) —
  hit "New handwriting variation" to reroll it without changing anything else.
- **Neural stroke synthesis:** a trained recurrent network predicts actual
  pen strokes (x, y, pen-up/down), optionally primed on a short sample of
  *your* real handwriting so the output imitates your style. This looks
  more genuinely "AI-generated" and can mimic a specific person's writing,
  but needs PyTorch, pretrained weights, and materially more setup — not
  something to bolt on blind. If you want to go this route later, a good
  starting point is `X-rayLaser/pytorch-handwriting-synthesis-toolkit` on
  GitHub; you'd add it as a second "engine" alongside `handwriting.py` and
  expose it as another option in the style dropdown.

This build ships the first approach so you have something real and working
today.

## How pictures in your photos are handled

When you photograph a book page, Tesseract OCR is only reliable on *text*.
Diagrams, figures, tables drawn as boxes/arrows, and printed photos would
otherwise get "read" as gibberish and dumped into your notes as nonsense
text. To avoid that:

1. Every word Tesseract finds, and where it sits, is recorded.
2. Those word-shaped patches of ink are erased from the page.
3. Whatever ink is left over is grouped into regions; regions big enough
   to plausibly be a picture (not stray specks or paper texture) are
   treated as one, cropped out of the *original* photo (so it keeps full
   detail/colour), and any nearby text that leaked into the crop is
   painted over with the page background.
4. Labels genuinely inside a diagram (e.g. "G1", "S", "G2" in a cell-cycle
   circle) are correctly excluded from the surrounding paragraph text,
   since they sit inside the picture's region.
5. In the final document, each picture becomes a `[[IMG:img_N]]` marker
   at the point it appeared on the page — so it stays in place relative
   to the surrounding text, and you can drag it elsewhere, resize it
   (`[[IMG:img_N|60]]` = 60% width), or delete its line to remove it.
6. You choose how it's redrawn: as a pencil sketch or clean ink line-art
   (so it visually matches hand-drawn notes), a plain black & white photo,
   kept in full colour, or left out entirely.

This is a classic-computer-vision approach (no picture-recognition model
involved), so it works fully offline — but it's a heuristic: very busy or
low-contrast pages may need you to nudge a picture's position in the
editor afterward, which is exactly what the editor is there for.

## 1. Install prerequisites (one-time)

- **Python 3.9+**
- **Tesseract OCR** (needed to read text out of photos/scans):
  - Windows users of the packaged installer do not need to install it separately.
    Building from source or using a portable app build still requires a separate install.
  - Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
  - macOS: `brew install tesseract`
  - Linux: `sudo apt install tesseract-ocr`
- **LibreOffice** (optional — only needed as a fallback for PowerPoint
  slides that have no text at all, e.g. a slide that's just a scanned
  image; not required for PDFs/JPG/PNG or for normal text-based slides):
  - Linux: `sudo apt install libreoffice`
  - macOS/Windows: https://www.libreoffice.org/download/

## 2. Install Python dependencies

```bash
cd handwritify
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Add handwriting fonts

The app looks for font files in the `fonts/` folder. Each `.ttf`/`.otf` you
drop in there becomes a selectable "handwriting format" in the app — so
add a few different ones for real variety (e.g. a neat style, a casual
scribble, a cursive flow). Good free sources:

- Google Fonts handwriting category: https://fonts.google.com/?category=Handwriting
- Look for: "Caveat", "Homemade Apple", "Shadows Into Light", "Patrick Hand",
  "Indie Flower", "Kalam" (any of these work well)

Download the `.ttf` file and put it directly in `handwritify/fonts/`, e.g.:

```
handwritify/fonts/Caveat.ttf
handwritify/fonts/HomemadeApple.ttf
```

Restart the server (or just refresh the page) after adding fonts.

## 4. Run it

Set the login credentials in the terminal before starting the app. Choose
your own values; the project does not include a default password.

PowerShell:

```powershell
$env:HANDWRITIFY_USERNAME = "choose-a-username"
$env:HANDWRITIFY_PASSWORD = "choose-a-strong-password"
```

macOS / Linux:

```bash
export HANDWRITIFY_USERNAME="choose-a-username"
export HANDWRITIFY_PASSWORD="choose-a-strong-password"
```

Then, from the project root, start the server:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

On macOS/Linux, activate the virtual environment with `source venv/bin/activate`
instead of the Windows activation command above.

If PowerShell blocks activation, run this once in the current PowerShell
session:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\venv\Scripts\Activate.ps1
```

Then open **http://localhost:8000** in your browser. Use `python -m uvicorn`
so the command works even when the `uvicorn` executable is not available on
PowerShell's `PATH`. The login credentials only apply to that terminal
session; set them again in a new terminal.

## Project structure

```
handwritify/
  backend/
    main.py          FastAPI server + API routes; serves the frontend too
    schemas.py         Every spacing/format/paper/image option, validated
    ingest.py          Reads PDF/PPTX/JPG/PNG, keeps your chosen order
    ocr.py               Deskew + Tesseract OCR + picture detection for photos/scans
    markup.py           The tiny editable text format (headings, images, page breaks)
    handwriting.py    Renders the document as handwritten-look page images
    export.py            Builds the downloadable PDF (true page size) / editable DOCX
    models.py           Small shared types
  frontend/
    index.html, style.css, app.js   Plain HTML/JS — no build tools needed
  fonts/              Drop handwriting .ttf/.otf files here
  jobs/               Per-conversion working files (auto-created, safe to clear)
```

## Editing the converted output

After converting, the extracted text appears in an editor next to the
page previews. It uses a few plain markers so anyone can learn it in a
minute:

| You want to...              | Do this                              |
|------------------------------|---------------------------------------|
| Start a new paragraph        | Leave a blank line                    |
| Make a heading                | Start the line with `# `             |
| Place a picture                | `[[IMG:img_1]]` on its own line      |
| Resize a picture (% width)    | `[[IMG:img_1|50]]`                   |
| Start a new page               | `[[PAGEBREAK]]` on its own line      |

The **Heading** and **New page** buttons above the editor insert these for
you. Clicking a picture thumbnail inserts its marker at your cursor. Paste
an image from the clipboard into the editor to add it; set its width with
the percentage in its marker. Each uploaded source file can also have its
own paper color and text size using the controls beside its filename.
Press **Apply changes** to redraw the pages with your edits (and with
whatever's currently set in the look/spacing panel — both apply together).
**Download** and **Share** automatically apply any edits you haven't
applied yet, so what you get always matches what's in the editor.

## Notes / known limits

- **Boundless Canvas** is a 420 × 420 mm square for digital-board-style
  notes. It is a large fixed canvas rather than an actually infinite surface;
  content that exceeds it continues onto another canvas page.
- The DOCX export contains the real extracted text and pictures (not a
  flat image) — fully editable, sized to the same page/margins you chose.
  It will only *look* handwritten in Word/LibreOffice if the same font
  is also installed on whatever machine opens it; otherwise the text is
  still there, just in a fallback font.
- `navigator.share` with files (the "Share" button) is only supported in
  some browsers (Chrome/Edge on desktop and mobile, Safari on iOS). Where
  unsupported, the app falls back to copying the text.
- OCR accuracy on photographed pages depends much more on lighting and
  page curvature than on anything in this code — flatten the page and
  shoot it straight-on for best results.
- Picture detection is heuristic (see above) — for very cluttered pages,
  check the editor after converting and nudge/resize/remove pictures as
  needed; that's exactly what it's there for.