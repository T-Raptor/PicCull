# PicCull

A tiny, minimalist image sifter for Windows (Python + Tkinter). Pick a folder, review images, mark files, and apply changes in batch (delete, keep, or copy). Includes persistent sessions and a fast Gallery view with lazy-loaded thumbnails.

## What it does

- **Two-step workflow**: Mark images during review, then batch apply at the end.
- **Flexible apply options**:
  - Move marked images to `.deleted/`
  - Keep marked images and move all unmarked ones to `.deleted/`
  - Copy marked images to any folder
- **Crash-proof persistence**: Marked state automatically saves to `.piccull_session.json` in the folder. Nothing lost on close.
- **Viewer**: Amber badge indicator for marked files, keyboard navigation, clickable on-canvas arrows.
- **Gallery**: Scrollable thumbnails, right-click to toggle mark in place, double-click to open, adjustable size.

## Install & run

```powershell
python -m venv venv
.\venv\Scripts\Activate
pip install -r requirements.txt
python piccull.py
```

## Use it

1. Click **Open** and choose an image folder.
2. Step through images with <kbd>←</kbd>/<kbd>→</kbd> or <kbd>Enter</kbd>.
3. Press <kbd>Del</kbd> or <kbd>Space</kbd> (or click **Mark**) to mark an image and advance.
4. Press <kbd>Ctrl</kbd>+<kbd>Z</kbd> to undo the last mark toggle.
5. In Gallery view, right-click any thumbnail to toggle its mark in place.
6. Click **Apply (N)** (or press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>) to choose your batch action and apply.

### Keys (quick)

- <kbd>←</kbd> / <kbd>→</kbd> — Navigate previous / next
- <kbd>Del</kbd> / <kbd>Space</kbd> — Toggle mark on current image + advance
- <kbd>Ctrl</kbd>+<kbd>Z</kbd> — Undo last mark toggle and return to image
- <kbd>Enter</kbd> — Next image (Viewer) / Open in Viewer (Gallery)
- <kbd>Ctrl</kbd>+<kbd>Enter</kbd> — Open Apply dialog
- <kbd>Esc</kbd> — Close app

## Notes

- Supported formats: JPEG, PNG, GIF, BMP, WEBP, TIFF
- Hidden files and folders (`.deleted`, `.piccull_session.json`) are automatically ignored.
- Images scale to fit the window; lightweight (standard library + Pillow).

## License

MIT
