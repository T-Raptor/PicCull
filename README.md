# PicCull

A tiny, minimalist, monochrome, monospaced Python GUI to quickly sift through images and mark deletes.

- Folder picker to choose a directory with images (jpg, jpeg, png)
- Navigate one image at a time with keyboard or buttons
- Press Delete (Del) or click Delete to move the image into a `.deleted` folder

## Run

1. Optionally create/activate a virtual env.
2. Install dependencies and start.

```powershell
python -m pip install -r requirements.txt
python piccull.py
```

## Keys

- Left/Right arrows: previous/next image
- Del: move current image to `.deleted` (created next to the image file)
- Enter/Space: next image
- Esc: close app

## Notes

- Files are moved (not permanently deleted) into a sibling `.deleted` folder beside the original image.
- Window is resizable; image scales to fit while preserving aspect ratio.
- Lightweight: standard library + Pillow only.

## License

MIT
