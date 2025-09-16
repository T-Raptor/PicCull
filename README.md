# PicCull

A tiny, minimalist image sifter for Windows (Python + Tkinter). Pick a folder, step through images, and press Delete to move files into a safe `.deleted` folder. Includes a fast Gallery view with lazy-loaded thumbnails.

## What it does

- Open a folder of images and review them quickly
- Delete moves files to a sibling `.deleted` folder (non-destructive); undo with <kbd>Ctrl</kbd>+<kbd>Z</kbd>
- Viewer: <kbd>←</kbd>/<kbd>→</kbd> to navigate, <kbd>Enter</kbd>/<kbd>Space</kbd> for next, clickable on-canvas arrows
- Gallery: scrollable thumbnails, double-click to open, lazy-loaded, adjustable size

## Install & run

```powershell
python -m venv venv
.\venv\Scripts\Activate
pip install -r requirements.txt
python piccull.py
```

## Use it

1. Click "Open" and choose a folder with images
2. Left/Right to move; Delete sends the current image to `.deleted`
3. Click the counter (e.g., `12/240`) to jump to an image
4. Toggle Gallery to browse thumbnails; scroll to load more

Keys (quick):

- <kbd>←</kbd>/<kbd>→</kbd> - Navigate
- <kbd>Enter</kbd>/<kbd>Space</kbd> - Next
- <kbd>Del</kbd> - Move to `.deleted`
- <kbd>Ctrl</kbd>+<kbd>Z</kbd> - Undo
- <kbd>Esc</kbd> - Leave Gallery/Close dialogs

## Notes

- Common formats: JPEG, PNG, GIF (first frame), BMP, WEBP, TIFF
- Images scale to fit the window; lightweight (stdlib + Pillow)

## License

MIT
