# PicCull

A tiny, minimalist image sifter for Windows built with Python and Tkinter. Pick a folder, step through images, and press Delete to move unwanted files into a safe `.deleted` folder. Includes a fast Gallery view with lazy-loaded thumbnails.

## Features

- Minimalist, monochrome, monospaced UI (Tkinter)
- Open a folder of images and step through them one by one
- Delete sends files to a sibling `.deleted` folder (no permanent deletion)
- Undo last delete (Ctrl+Z)
- Keyboard navigation: Left/Right arrows, Delete, Enter/Space, Esc
- Clickable on-canvas arrows (no prev on first / no next on last)
- Click the image counter (e.g. `12/240`) to jump to an image number
- Gallery mode:
  - Scrollable grid of thumbnails
  - Double-click a thumbnail to open it in the viewer
  - Selection highlight matches the app’s style
  - Lazy-loading thumbnails in batches of 5 to keep scrolling smooth
  - Near-bottom and mouse-wheel scroll events trigger additional loads automatically

## Requirements

- Python 3.9+
- Pillow (installed via `requirements.txt`)

## Install & run

From the project folder:

```powershell
python -m pip install -r requirements.txt
python piccull.py
```

## Usage

1. Click "Open" and select a folder containing images
2. Use Left/Right to navigate; Delete moves the current image to `.deleted`
3. Click the image counter to jump to a specific index (a minimal modal appears)
4. Toggle Gallery to see a thumbnail grid; scroll to load more thumbnails automatically

Helpful keys:

- Del: move current image to `.deleted`
- Enter/Space: next image
- Ctrl+Z: undo last delete
- Esc: leave Gallery or close dialogs

## Notes

- Supported formats are common raster types (JPEG, PNG, GIF (first frame), BMP, WEBP, TIFF)
- Files are moved (not permanently deleted) into a sibling `.deleted` folder beside the original image with collision-safe renaming
- Window is resizable; images scale to fit while preserving aspect ratio
- Lightweight: standard library + Pillow only

## License

MIT
