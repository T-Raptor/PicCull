# PicCull

A tiny, minimalist photo and video sifter for Windows (Python + Tkinter). Pick a folder, review media, mark files, and apply changes in batch (delete, keep, or copy). Includes persistent sessions, external media player integration (VLC auto-detected), and a fast Gallery view with lazy-loaded thumbnails.

## What it does

- **Two-step workflow**: Mark media during review, then batch apply at the end.
- **Flexible apply options**:
  - Move marked files to `.deleted/`
  - Keep marked files and move all unmarked ones to `.deleted/`
  - Copy marked files to any folder
- **Broad format support**:
  - Images: JPEG, PNG, GIF, BMP, WEBP, TIFF, HEIC / HEIF (iPhone photos)
  - Videos: MP4, MOV, MKV, AVI, WEBM, M4V, WMV, FLV (poster frames via ffmpeg)
- **External media player integration**:
  - Auto-detects VLC at `C:\Program Files\VideoLAN\VLC\vlc.exe`.
  - Configurable via top toolbar **Player** button (persists to `~/.piccull_config.json`).
  - Press <kbd>P</kbd> or double-click canvas to open any video, MOV, or HEIC in VLC.
- **Crash-proof persistence**: Marked state automatically saves to `.piccull_session.json` in the folder. Nothing lost on close.
- **Viewer**: Amber badge indicator for marked files, video/HEIC player badge with quick launch, clickable on-canvas arrows.
- **Gallery**: Scrollable thumbnails with video indicators, right-click to toggle mark in place, double-click to open, adjustable size.

## Install & run

```powershell
python -m venv venv
.\venv\Scripts\Activate
pip install -r requirements.txt
python piccull.py
```

## Use it

1. Click **Open** and choose an image/video folder.
2. Step through media with <kbd>←</kbd>/<kbd>→</kbd> or <kbd>Enter</kbd>.
3. Press <kbd>Del</kbd> or <kbd>Space</kbd> (or click **Mark**) to mark a file and advance.
4. Press <kbd>Ctrl</kbd>+<kbd>Z</kbd> to undo the last mark toggle.
5. In Gallery view, right-click any thumbnail to toggle its mark in place.
6. When viewing media, press <kbd>P</kbd> or double-click the canvas to open it in your media player (VLC). Click **Player** in toolbar to change the executable.
7. Click **Apply (N)** (or press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>) to choose your batch action and apply.

### Keys (quick)

- <kbd>←</kbd> / <kbd>→</kbd> — Navigate previous / next
- <kbd>Del</kbd> / <kbd>Space</kbd> — Toggle mark on current file + advance
- <kbd>Ctrl</kbd>+<kbd>Z</kbd> — Undo last mark toggle and return to file
- <kbd>Enter</kbd> — Next file (Viewer) / Open in Viewer (Gallery)
- <kbd>P</kbd> — Open current media in configured player (VLC)
- <kbd>Ctrl</kbd>+<kbd>Enter</kbd> — Open Apply dialog
- <kbd>Esc</kbd> — Close app

## Notes

- Supported images: JPEG, PNG, GIF, BMP, WEBP, TIFF, HEIC, HEIF
- Supported videos: MP4, MOV, MKV, AVI, WEBM, M4V, WMV, FLV (uses ffmpeg if available)
- Hidden files and folders (`.deleted`, `.piccull_session.json`) are automatically ignored.
- Images scale to fit the window; lightweight (standard library + Pillow + pillow-heif).

## License

MIT
