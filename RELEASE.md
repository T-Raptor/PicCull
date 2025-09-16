# Releasing PicCull (Windows .exe)

This project ships Windows builds via GitHub Releases. A workflow builds a portable `.exe` whenever you push a tag like `v1.0.0`.

## One-time setup

1. Ensure the repo is on GitHub with the default branch (e.g., `main`).
2. Optional: Add `fonts/JetBrainsMono-Regular.ttf` to bundle the monospaced font at runtime.

## Local build (optional)

If you want to test locally before tagging:

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
# Include fonts if present so the app uses JetBrains Mono
pyinstaller --onefile --noconsole --name PicCull --add-data "fonts;fonts" piccull.py
# Output: dist/PicCull.exe
```

Notes:

- If `fonts/` doesn’t exist, you can omit `--add-data`; the app will fall back to system fonts.
- The app’s font loader is PyInstaller-aware and works with `--onefile` and `--onedir`.

## CI release (recommended)

Pushing a tag that starts with `v` triggers the workflow at `.github/workflows/release.yml`:

- Builds `PicCull.exe` with PyInstaller
- Renames it to `PicCull-<tag>-win64.exe`
- Creates a GitHub Release and uploads the exe

Create and push a tag:

```powershell
# Replace v1.0.0 with your version
git tag v1.0.0
git push origin v1.0.0
```

Or from the GitHub UI, create a new release with tag `v1.0.0` and publish—Actions will run automatically.

## Font bundling

- To ship JetBrains Mono, place `JetBrainsMono-Regular.ttf` under `fonts/` in the repo.
- The workflow will pick it up automatically and include it: `--add-data "fonts;fonts"`.
- At runtime, the app registers the font (tkextrafont first, then Windows private font fallback).

## Troubleshooting

- If the font doesn’t appear, confirm `fonts/JetBrainsMono-Regular.ttf` exists in the repo/tag and that the Release assets include only one `.exe` named `PicCull-<tag>-win64.exe`.
- If PyInstaller fails, check for syntax errors: `python -m py_compile piccull.py`.
- For verbose PyInstaller logs, add `--log-level=DEBUG`.
