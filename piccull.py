import concurrent.futures
import io
import json
import os
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import tkinter.font as tkfont

try:
	from PIL import Image, ImageTk, ImageOps, ImageDraw
except ImportError:
	# Pillow not installed; provide a helpful message
	raise SystemExit(
		"Pillow is required. Install with: python -m pip install -r requirements.txt"
	)

# Register HEIC/HEIF opener if pillow-heif installed
try:
	import pillow_heif
	pillow_heif.register_heif_opener()
except ImportError:
	pass


IMG_EXTS = {
	".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
	".heic", ".heif", ".hif",
}
VID_EXTS = {
	".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".flv",
}
MEDIA_EXTS = IMG_EXTS | VID_EXTS
SESSION_FILENAME = ".piccull_session.json"


def load_app_config() -> dict:
	cfg_path = Path.home() / ".piccull_config.json"
	if cfg_path.exists():
		try:
			return json.loads(cfg_path.read_text(encoding="utf-8"))
		except Exception:
			pass
	return {}


def save_app_config(cfg: dict) -> None:
	cfg_path = Path.home() / ".piccull_config.json"
	try:
		cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
	except Exception:
		pass


def find_default_media_player() -> Optional[str]:
	candidates = [
		r"C:\Program Files\VideoLAN\VLC\vlc.exe",
		r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
	]
	for c in candidates:
		if Path(c).is_file():
			return c
	return shutil.which("vlc") or shutil.which("mpv")


def is_video(path: Path) -> bool:
	return path.suffix.lower() in VID_EXTS


def is_image(path: Path) -> bool:
	return path.suffix.lower() in MEDIA_EXTS and not path.name.startswith(".")


def list_images(folder: Path) -> List[Path]:
	return sorted(
		[p for p in folder.iterdir() if p.is_file() and is_image(p)],
		key=lambda p: p.name.lower(),
	)


def extract_video_frame(path: Path) -> Image.Image:
	"""Extract video poster frame via ffmpeg or generate fallback placeholder."""
	creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
	# Use fast input seeking and mjpeg pipe (3-5x faster than png encoding)
	cmd = ["ffmpeg", "-ss", "0.1", "-i", str(path), "-vframes", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "-"]
	try:
		proc = subprocess.run(
			cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			creationflags=creationflags,
			timeout=3,
		)
		if proc.stdout:
			img = Image.open(io.BytesIO(proc.stdout))
			return ImageOps.exif_transpose(img)
	except Exception:
		pass

	# Fallback placeholder when ffmpeg cannot extract
	ph = Image.new("RGB", (640, 360), color=(26, 26, 26))
	draw = ImageDraw.Draw(ph)
	draw.polygon([(300, 155), (300, 205), (345, 180)], fill=(200, 200, 200))
	return ph


def load_media_image(path: Path, max_size: Optional[Tuple[int, int]] = None) -> Image.Image:
	"""Load image or extract video/HEIC poster frame with fast draft downsampling."""
	if is_video(path):
		return extract_video_frame(path)
	try:
		with Image.open(path) as img:
			# Fast draft mode for JPEG to decode directly at lower resolution in libjpeg
			if max_size and path.suffix.lower() in {".jpg", ".jpeg"}:
				try:
					img.draft("RGB", (max_size[0] * 2, max_size[1] * 2))
				except Exception:
					pass
			transposed = ImageOps.exif_transpose(img)
			transposed.load()
			return transposed
	except Exception:
		# Fall back to ffmpeg if Pillow cannot decode (e.g. HEIC without pillow-heif)
		if path.suffix.lower() in {".heic", ".heif", ".hif"}:
			img = extract_video_frame(path)
			if img:
				return img
		raise


def ensure_deleted_folder(base: Path) -> Path:
	dest = base / ".deleted"
	dest.mkdir(exist_ok=True)
	return dest


def safe_move_to_deleted(src: Path, deleted_dir: Path) -> Path:
	"""Move src to deleted_dir, avoiding collisions by adding suffixes."""
	target = deleted_dir / src.name
	if not target.exists():
		shutil.move(str(src), str(target))
		return target
	stem, ext = src.stem, src.suffix
	i = 1
	while True:
		candidate = deleted_dir / f"{stem}-{i}{ext}"
		if not candidate.exists():
			shutil.move(str(src), str(candidate))
			return candidate
		i += 1


class PicCullApp(tk.Tk):
	def __init__(self) -> None:
		super().__init__()
		self.title("PicCull")
		self.geometry("1000x700")
		self.minsize(640, 420)

		# Minimalist, monochrome palette
		self.colors = {
			"bg": "#111111",
			"fg": "#EAEAEA",
			"muted": "#888888",
			"panel": "#1A1A1A",
			"border": "#2A2A2A",
			"marked": "#C8A400",   # amber — marked tile border / badge
		}

		# Track any Windows private fonts we load to remove on exit
		self._win_private_fonts: list[Path] = []
		# Fonts: prefer JetBrains Mono (bundled or system), then fallbacks
		self.font_family = self._pick_font_family()
		self.base_font = (self.font_family, 11)
		self.small_font = (self.font_family, 10)

		self.configure(bg=self.colors["bg"])
		self._setup_style()

		# State
		self.folder: Optional[Path] = None
		self.images: List[Path] = []
		self.index: int = -1
		self.current_image_pil: Optional[Image.Image] = None
		self.current_photo: Optional[ImageTk.PhotoImage] = None
		self._resize_after_id: Optional[str] = None
		# Canvas arrow items
		self._left_arrow_id: Optional[int] = None
		self._right_arrow_id: Optional[int] = None

		# Background prefetching and viewer image cache
		self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
		self._viewer_pil_cache: dict[tuple[Path, int, int], Image.Image] = {}

		# Marking state
		self.marked: set[str] = set()          # filenames (not paths) currently marked
		self._session_file: Optional[Path] = None
		self._last_mark_action: Optional[Tuple[str, str, int]] = None  # (name, action, index) for Ctrl+Z undo

		# External media player (user-specified or auto-detected VLC)
		self.config = load_app_config()
		self.media_player: Optional[str] = self.config.get("media_player") or find_default_media_player()

		# Modes: 'viewer' or 'gallery'
		self.mode: str = "viewer"
		# Thumbnails
		self.thumb_size: int = 200
		self.thumb_size_var = tk.IntVar(value=self.thumb_size)
		self.thumb_step: int = 48  # large increments to avoid frequent rebuilds
		# Cache thumbnails for the session keyed by (path, size)
		self.thumb_cache: dict[tuple[Path, int], ImageTk.PhotoImage] = {}
		self._gallery_tiles: list[tk.Frame] = []
		self._gallery_loaded_count: int = 0
		self._gallery_loading: bool = False
		self._gallery_load_after: Optional[str] = None
		self._gallery_container: ttk.Frame  # initialized in _build_gallery_ui
		self.gallery_canvas: tk.Canvas     # initialized in _build_gallery_ui
		self.gallery_vscroll: ttk.Scrollbar
		self.gallery_frame: ttk.Frame
		self._gallery_window_id: Optional[int] = None

		# UI
		self._build_ui()
		self._bind_keys()

	def _setup_style(self) -> None:
		style = ttk.Style(self)
		# Use default theme, but override colors to be monochrome
		try:
			style.theme_use("clam")
		except tk.TclError:
			pass
		style.configure(
			"TFrame",
			background=self.colors["bg"],
		)
		style.configure(
			"Panel.TFrame",
			background=self.colors["panel"],
			bordercolor=self.colors["border"],
			relief="flat",
		)
		style.configure(
			"TLabel",
			background=self.colors["bg"],
			foreground=self.colors["fg"],
			font=self.base_font,
		)
		style.configure(
			"Muted.TLabel",
			background=self.colors["bg"],
			foreground=self.colors["muted"],
			font=self.small_font,
		)
		style.configure(
			"TButton",
			background=self.colors["panel"],
			foreground=self.colors["fg"],
			bordercolor=self.colors["border"],
			relief="flat",
			font=self.base_font,
			padding=(10, 6),
		)
		style.map(
			"TButton",
			background=[("active", self.colors["border"])],
			foreground=[("disabled", self.colors["muted"])],
		)

	def _build_ui(self) -> None:
		# Top toolbar
		top = ttk.Frame(self, style="Panel.TFrame")
		top.pack(side=tk.TOP, fill=tk.X)

		self.btn_open = ttk.Button(top, text="Open", command=self.choose_folder, takefocus=False)
		self.btn_prev = ttk.Button(top, text="Prev", command=self.prev_image, takefocus=False)
		self.btn_next = ttk.Button(top, text="Next", command=self.next_image, takefocus=False)
		self.btn_mark = ttk.Button(top, text="Mark", command=self.toggle_mark, takefocus=False)
		self.btn_unmark_all = ttk.Button(top, text="Unmark All", command=self.unmark_all, takefocus=False)
		self.btn_apply = ttk.Button(top, text="Apply (0)", command=self.apply_marks, takefocus=False)
		self.btn_mode = ttk.Button(top, text="Gallery", command=self.toggle_gallery, takefocus=False)
		self.btn_player = ttk.Button(top, text="Player", command=self.configure_player, takefocus=False)

		for w in (self.btn_open, self.btn_prev, self.btn_next, self.btn_mark,
				  self.btn_unmark_all, self.btn_apply, self.btn_mode, self.btn_player):
			w.pack(side=tk.LEFT, padx=(8, 0), pady=8)

		# Thumbnail size control (Gallery-only panel)
		self.thumb_panel = ttk.Frame(top, style="Panel.TFrame")
		self.thumb_label = ttk.Label(self.thumb_panel, text=f"Thumb {self.thumb_size}px", style="Muted.TLabel")
		self.thumb_label.pack(side=tk.LEFT, padx=(8, 6), pady=8)
		self.thumb_scale = ttk.Scale(
			self.thumb_panel,
			from_=96,
			to=384,
			orient=tk.HORIZONTAL,
			value=self.thumb_size,
			length=160,
			command=lambda v: self._on_thumb_scale_move(float(v)),
			takefocus=False,
		)
		self.thumb_scale.pack(side=tk.LEFT, padx=(0, 8), pady=8)
		# Apply on mouse/key release only
		self.thumb_scale.bind("<ButtonRelease-1>", self._apply_thumb_size_from_scale)
		self.thumb_scale.bind("<KeyRelease>", self._apply_thumb_size_from_scale)

		# Center view container
		self.view_area = ttk.Frame(self, style="TFrame")
		self.view_area.pack(fill=tk.BOTH, expand=True)

		# Viewer canvas
		self.canvas = tk.Canvas(
			self.view_area,
			bg=self.colors["bg"],
			highlightthickness=0,
		)
		self.canvas.pack(fill=tk.BOTH, expand=True)
		self.canvas.bind("<Configure>", self._on_canvas_resize)
		self.canvas.bind("<Double-Button-1>", lambda e: self.play_current_video())

		# Gallery container (canvas + scrollbar), initially hidden
		self._build_gallery_ui()

		# Status bar (counter + text)
		bottom = ttk.Frame(self, style="Panel.TFrame")
		bottom.pack(side=tk.BOTTOM, fill=tk.X)
		self.counter_label = ttk.Label(bottom, text="", style="Muted.TLabel")
		self.counter_label.pack(side=tk.LEFT, padx=(8, 0), pady=6)
		self.status_label = ttk.Label(bottom, text="Pick a folder to begin", style="Muted.TLabel")
		self.status_label.pack(side=tk.LEFT, padx=8, pady=6)
		# Marked count shown right-aligned in status bar
		self.marked_label = ttk.Label(bottom, text="", style="Muted.TLabel")
		self.marked_label.pack(side=tk.RIGHT, padx=(0, 8), pady=6)

		self._update_controls()

		# Ensure we clear ephemeral caches on close
		self.protocol("WM_DELETE_WINDOW", self._on_close)

	def _resource_path(self, *parts: str) -> Path:
		"""Return absolute path to a bundled resource (PyInstaller/_MEIPASS aware)."""
		base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))  # type: ignore[attr-defined]
		return base.joinpath(*parts)

	def _pick_font_family(self) -> str:
		"""Choose monospaced font, optionally loading a bundled TTF.
		Order:
		1) Try to load fonts/JetBrainsMono-Regular.ttf via tkextrafont (cross-platform C-extension).
		2) Use system-installed "JetBrains Mono" if present.
		3) On Windows, fall back to AddFontResourceEx (private, process-only) if tkextrafont not available.
		4) Fallback: Consolas (Windows) / Menlo (macOS) / Courier New / TkFixedFont.
		"""
		preferred = "JetBrains Mono"
		# Attempt to load bundled TTF if available and extension installed
		try:
			fonts_dir = self._resource_path("fonts")
			bundle = fonts_dir / "JetBrainsMono-Regular.ttf"
			if bundle.exists():
				try:
					from tkextrafont import Font as ExtraFont  # type: ignore
					ExtraFont(file=str(bundle), family=preferred)
				except Exception:
					# As a Windows-specific fallback, try adding a private font resource
					if sys.platform.startswith("win"):
						try:
							import ctypes
							FR_PRIVATE = 0x10
							res = ctypes.windll.gdi32.AddFontResourceExW(str(bundle), FR_PRIVATE, 0)
							if res > 0:
								self._win_private_fonts.append(bundle)
						except Exception:
							pass
		except Exception:
			pass
		# Inspect available families after optional load
		try:
			families = set(tkfont.families(self))
		except Exception:
			families = set()
		if preferred in families:
			return preferred
		# Fallbacks by platform
		if sys.platform.startswith("win"):
			if "Consolas" in families:
				return "Consolas"
		else:
			if "Menlo" in families:
				return "Menlo"
		# Cross-platform fallbacks
		if "Courier New" in families:
			return "Courier New"
		return "TkFixedFont"

	def _bind_keys(self) -> None:
		# Prevent focused buttons from consuming space
		try:
			self.unbind_class("TButton", "<Key-space>")
		except Exception:
			pass

		self.bind("<Escape>", lambda e: self.destroy())
		self.bind("<Left>", lambda e: self.prev_image())
		self.bind("<Right>", lambda e: self.next_image())
		self.bind("<Delete>", lambda e: self.toggle_mark())
		self.bind("<space>", lambda e: (self.toggle_mark(), "break")[1])
		self.bind("<Return>", lambda e: self._on_enter_key())
		self.bind("<Up>", lambda e: self._move_selection_up())
		self.bind("<Down>", lambda e: self._move_selection_down())
		# Ctrl+Z: undo last mark toggle
		self.bind("<Control-z>", lambda e: self._undo_last_mark())
		# Ctrl+Return: open apply dialog
		self.bind("<Control-Return>", lambda e: self.apply_marks())
		# P: play current video
		self.bind("<p>", lambda e: self.play_current_video())
		self.bind("<P>", lambda e: self.play_current_video())
		# Global mouse wheel: scroll gallery anywhere; in viewer, wheel navigates
		self.bind_all("<MouseWheel>", self._on_global_mouse_wheel, add=True)

	# ----- Session persistence -----

	def _load_session(self) -> None:
		"""Load marked set from .piccull_session.json if it exists for the current folder."""
		if self.folder is None:
			return
		self._session_file = self.folder / SESSION_FILENAME
		if self._session_file.exists():
			try:
				data = json.loads(self._session_file.read_text(encoding="utf-8"))
				raw_marked = set(data.get("marked", []))
				# Prune filenames that no longer exist on disk
				existing = {p.name for p in self.images}
				self.marked = raw_marked & existing
			except Exception:
				self.marked = set()
		else:
			self.marked = set()
		self._last_mark_action = None

	def _save_session(self) -> None:
		"""Write current mark state to disk immediately."""
		if self._session_file is None or self.folder is None:
			return
		data = {
			"version": 1,
			"folder": str(self.folder),
			"marked": sorted(self.marked),
		}
		try:
			self._session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
		except Exception:
			pass

	def _delete_session_file(self) -> None:
		"""Remove the session file after a successful apply."""
		if self._session_file and self._session_file.exists():
			try:
				self._session_file.unlink()
			except Exception:
				pass
		self._session_file = None

	# ----- Image / folder management -----

	def choose_folder(self) -> None:
		path = filedialog.askdirectory(title="Select image folder")
		self.focus_set()
		if not path:
			return
		folder = Path(path)
		imgs = list_images(folder)
		self.folder = folder
		self.images = imgs
		self.index = 0 if imgs else -1
		self._load_session()
		self._set_status()
		self._show_current()
		self._update_controls()
		# Rebuild gallery content if needed
		self._rebuild_gallery()

	def _refresh_image_list(self) -> None:
		"""Re-scan the folder, update image list, clamp index, refresh UI."""
		if self.folder is None:
			return
		self.images = list_images(self.folder)
		if self.images:
			self.index = max(0, min(self.index, len(self.images) - 1))
		else:
			self.index = -1
		self._set_status()
		if self.mode == "viewer":
			self._show_current()
		else:
			self._rebuild_gallery()
		self._update_controls()

	def _set_status(self, extra: str = "") -> None:
		if self.index == -1 or not self.images:
			text = "No images found" if self.folder else "Pick a folder to begin"
		else:
			im_path = self.images[self.index]
			text = f"{self.index + 1}/{len(self.images)} — {im_path.name}"
		if extra:
			text = f"{text}  |  {extra}"
		# Update counter and status parts
		if self.index == -1 or not self.images:
			self.counter_label.configure(text="")
			self.status_label.configure(text=text)
		else:
			im_path = self.images[self.index]
			is_marked = im_path.name in self.marked
			is_vid = is_video(im_path)
			vid_tag = "[VIDEO] " if is_vid else ""
			counter = f"{self.index + 1}/{len(self.images)}"
			info = f" — {vid_tag}{im_path.name}"
			if is_marked:
				info = f"{info}  ●"
			if extra:
				info = f"{info}  |  {extra}"
			self.counter_label.configure(text=counter)
			self.status_label.configure(text=info)
		# Marked count in right side of status bar
		n = len(self.marked)
		self.marked_label.configure(text=(f"{n} marked" if n > 0 else ""))

	def _update_controls(self) -> None:
		has_images = bool(self.images)
		at_first = has_images and self.index <= 0
		at_last = has_images and self.index >= (len(self.images) - 1)

		# Prev/Next enabled based on edges (no wrap)
		self.btn_prev.configure(state=(tk.NORMAL if (has_images and not at_first) else tk.DISABLED))
		self.btn_next.configure(state=(tk.NORMAL if (has_images and not at_last) else tk.DISABLED))
		self.btn_mark.configure(state=(tk.NORMAL if has_images else tk.DISABLED))
		self.btn_unmark_all.configure(state=(tk.NORMAL if self.marked else tk.DISABLED))
		self.btn_apply.configure(
			state=(tk.NORMAL if self.marked else tk.DISABLED),
			text=f"Apply ({len(self.marked)})",
		)

		# Update Mark button label to reflect current image state
		if has_images and self.images and 0 <= self.index < len(self.images):
			cur_name = self.images[self.index].name
			self.btn_mark.configure(text=("Unmark" if cur_name in self.marked else "Mark"))
		else:
			self.btn_mark.configure(text="Mark")

		# Bind/unbind counter click for jump
		try:
			self.counter_label.unbind("<Button-1>")
			self.counter_label.unbind("<Enter>")
			self.counter_label.unbind("<Leave>")
		except Exception:
			pass
		if has_images:
			self.counter_label.configure(cursor="hand2")
			self.counter_label.bind("<Button-1>", lambda e: self._on_counter_click())
			self.counter_label.bind("<Enter>", lambda e: self.counter_label.configure(cursor="hand2"))
			self.counter_label.bind("<Leave>", lambda e: self.counter_label.configure(cursor=""))
		else:
			self.counter_label.configure(cursor="")

		# Update canvas arrows
		self._draw_arrows()
		# Update mode button label
		self.btn_mode.configure(text=("Viewer" if self.mode == "gallery" else "Gallery"))

	def _on_enter_key(self) -> None:
		if self.mode == "gallery":
			# Open selected image in viewer
			if self.images and 0 <= self.index < len(self.images):
				self._leave_gallery()
			else:
				return
		else:
			self.next_image()

	def _on_counter_click(self) -> None:
		if not self.images:
			return
		n = len(self.images)
		current = self.index + 1 if self.index >= 0 else 1
		val = self._ask_image_number(n, current)
		if val is None:
			return
		target = int(val) - 1
		if 0 <= target < n and target != self.index:
			self.index = target
			self._set_status()
			self._show_current()
			self._update_controls()
			if self.mode == "gallery":
				self._update_selection_highlight()
				self._ensure_selected_visible()

	def _ask_image_number(self, total: int, current: int) -> Optional[int]:
		"""Open a minimalist modal to ask for an image number (1..total)."""
		top = tk.Toplevel(self)
		top.title("Go to image")
		top.configure(bg=self.colors["panel"])  # background to match app
		top.transient(self)
		top.resizable(False, False)
		top.grab_set()

		frm = ttk.Frame(top, style="Panel.TFrame", padding=12)
		frm.pack(fill=tk.BOTH, expand=True)

		lbl = ttk.Label(frm, text=f"Enter image number (1-{total}):", style="TLabel")
		lbl.pack(anchor="w", pady=(0, 6))

		var = tk.StringVar(value=str(current))
		entry = ttk.Entry(frm, font=self.base_font, textvariable=var)
		entry.pack(fill=tk.X)
		entry.select_range(0, tk.END)
		entry.focus_set()

		btns = ttk.Frame(frm, style="Panel.TFrame")
		btns.pack(fill=tk.X, pady=(10, 0))
		cancel_btn = ttk.Button(btns, text="Cancel", command=top.destroy)
		ok_btn = ttk.Button(btns, text="OK")
		cancel_btn.pack(side=tk.RIGHT)
		ok_btn.pack(side=tk.RIGHT, padx=(0, 8))

		result: dict[str, Optional[int]] = {"value": None}

		def on_ok(_e=None) -> None:
			s = var.get().strip()
			if not s.isdigit():
				entry.bell()
				return
			v = int(s)
			if v < 1 or v > total:
				entry.bell()
				return
			result["value"] = v
			top.destroy()

		ok_btn.configure(command=on_ok)
		top.bind("<Return>", on_ok)
		top.bind("<Escape>", lambda e: top.destroy())

		# Center the dialog over the app window
		top.update_idletasks()
		x = self.winfo_rootx() + (self.winfo_width() // 2 - top.winfo_width() // 2)
		y = self.winfo_rooty() + (self.winfo_height() // 2 - top.winfo_height() // 2)
		top.geometry(f"+{max(0, x)}+{max(0, y)}")

		top.wait_window()
		return result["value"]

	def prev_image(self) -> None:
		if not self.images or self.index <= 0:
			return
		self.index -= 1
		self._set_status()
		if self.mode == "viewer":
			self._show_current()
		else:
			self._update_selection_highlight()
			self._ensure_selected_visible()
		self._update_controls()

	def next_image(self) -> None:
		if not self.images or self.index >= (len(self.images) - 1):
			return
		self.index += 1
		self._set_status()
		if self.mode == "viewer":
			self._show_current()
		else:
			self._update_selection_highlight()
			self._ensure_selected_visible()
		self._update_controls()

	# ----- Marking -----

	def toggle_mark(self) -> None:
		"""Toggle mark on the current image and advance to next."""
		if not self.images or self.index < 0:
			return
		cur_idx = self.index
		name = self.images[cur_idx].name
		if name in self.marked:
			self.marked.discard(name)
			self._last_mark_action = (name, "unmarked", cur_idx)
		else:
			self.marked.add(name)
			self._last_mark_action = (name, "marked", cur_idx)
		self._save_session()
		self._set_status()
		self._update_controls()
		if self.mode == "gallery":
			self._update_selection_highlight()
		elif self.mode == "viewer":
			self._draw_mark_badge()
		# Auto-advance after marking (preserves the rapid-fire culling rhythm)
		self.next_image()

	def _undo_last_mark(self) -> None:
		"""Undo the last mark/unmark toggle and return to that image."""
		if not self._last_mark_action:
			return
		name, action, prev_idx = self._last_mark_action
		self._last_mark_action = None
		if action == "marked":
			self.marked.discard(name)
		else:
			self.marked.add(name)
		self._save_session()
		if 0 <= prev_idx < len(self.images) and self.images[prev_idx].name == name:
			self.index = prev_idx
		self._set_status()
		self._update_controls()
		if self.mode == "gallery":
			self._update_selection_highlight()
			self._ensure_selected_visible()
		elif self.mode == "viewer":
			self._show_current()

	def unmark_all(self) -> None:
		"""Clear all marks, with confirmation if count > 0."""
		if not self.marked:
			return
		n = len(self.marked)
		if not messagebox.askyesno(
			"Unmark All",
			f"Clear all {n} marked image{'s' if n != 1 else ''}?",
			default="no",
		):
			return
		self.marked.clear()
		self._last_mark_action = None
		self._save_session()
		self._set_status()
		self._update_controls()
		if self.mode == "gallery":
			self._update_selection_highlight()
		elif self.mode == "viewer":
			self._draw_mark_badge()

	# ----- Apply -----

	def apply_marks(self) -> None:
		"""Open apply dialog and execute the chosen batch operation."""
		if not self.marked or self.folder is None:
			return

		n_marked = len(self.marked)
		n_total = len(self.images)
		n_unmarked = n_total - n_marked

		choice = self._ask_apply_action(n_marked, n_unmarked)
		if choice is None:
			return

		errors: List[str] = []

		try:
			if choice == "delete_marked":
				dest = ensure_deleted_folder(self.folder)
				moved_names = set()
				for name in list(self.marked):
					src = self.folder / name
					if src.exists():
						try:
							safe_move_to_deleted(src, dest)
							moved_names.add(name)
						except Exception as e:
							errors.append(f"{name}: {e}")
					else:
						moved_names.add(name)
				self._purge_thumb_cache_for_names(moved_names)
				self.marked -= moved_names

			elif choice == "keep_marked":
				dest = ensure_deleted_folder(self.folder)
				unmarked = {p.name for p in self.images} - self.marked
				moved_names = set()
				for name in unmarked:
					src = self.folder / name
					if src.exists():
						try:
							safe_move_to_deleted(src, dest)
							moved_names.add(name)
						except Exception as e:
							errors.append(f"{name}: {e}")
					else:
						moved_names.add(name)
				self._purge_thumb_cache_for_names(moved_names)
				self.marked.clear()

			elif choice == "copy_marked":
				target = filedialog.askdirectory(title="Copy marked images to…")
				if not target:
					return
				target_dir = Path(target)
				copied_names = set()
				for name in list(self.marked):
					src = self.folder / name
					if src.exists():
						try:
							shutil.copy2(str(src), str(target_dir / name))
							copied_names.add(name)
						except Exception as e:
							errors.append(f"{name}: {e}")
				self.marked -= copied_names

		except Exception as e:
			messagebox.showerror("Apply failed", str(e))
			return

		self._last_mark_action = None
		if not self.marked:
			self._delete_session_file()
		else:
			self._save_session()
		self._refresh_image_list()

		if errors:
			messagebox.showwarning(
				"Apply completed with errors",
				f"{len(errors)} file(s) failed:\n" + "\n".join(errors[:10]),
			)

	def _ask_apply_action(self, n_marked: int, n_unmarked: int) -> Optional[str]:
		"""Minimalist modal to choose how to apply marks. Returns action key or None."""
		top = tk.Toplevel(self)
		top.title("Apply marks")
		top.configure(bg=self.colors["panel"])
		top.transient(self)
		top.resizable(False, False)
		top.grab_set()

		frm = ttk.Frame(top, style="Panel.TFrame", padding=16)
		frm.pack(fill=tk.BOTH, expand=True)

		ttk.Label(frm, text=f"What to do with {n_marked} marked image{'s' if n_marked != 1 else ''}?",
				  style="TLabel").pack(anchor="w", pady=(0, 12))

		result: dict[str, Optional[str]] = {"value": None}

		def pick(val: str) -> None:
			result["value"] = val
			top.destroy()

		btn_del = ttk.Button(
			frm,
			text=f"Move {n_marked} marked  →  .deleted/",
			command=lambda: pick("delete_marked"),
		)
		btn_del.pack(fill=tk.X, pady=(0, 6))

		def _confirm_keep_fn() -> None:
			if messagebox.askyesno(
				"Confirm keep",
				f"This will move {n_unmarked} unmarked image{'s' if n_unmarked != 1 else ''} to .deleted/.\nContinue?",
				default="no",
				parent=top,
			):
				pick("keep_marked")

		# "Keep only marked" deletes many files — show the count clearly
		btn_keep = ttk.Button(
			frm,
			text=f"Keep {n_marked} marked, move {n_unmarked} others  →  .deleted/",
			command=_confirm_keep_fn,
		)
		btn_keep.pack(fill=tk.X, pady=(0, 6))

		btn_copy = ttk.Button(
			frm,
			text=f"Copy {n_marked} marked  →  choose folder…",
			command=lambda: pick("copy_marked"),
		)
		btn_copy.pack(fill=tk.X, pady=(0, 12))

		ttk.Button(frm, text="Cancel", command=top.destroy).pack(anchor="e")

		# Center over app
		top.update_idletasks()
		x = self.winfo_rootx() + (self.winfo_width() // 2 - top.winfo_width() // 2)
		y = self.winfo_rooty() + (self.winfo_height() // 2 - top.winfo_height() // 2)
		top.geometry(f"+{max(0, x)}+{max(0, y)}")
		top.bind("<Escape>", lambda e: top.destroy())

		top.wait_window()
		return result["value"]

	# ----- Rendering -----

	def _show_current(self) -> None:
		self.canvas.delete("all")
		self.current_image_pil = None
		self.current_photo = None

		if self.index == -1 or not self.images:
			# Draw a soft hint text
			w = self.canvas.winfo_width() or 800
			h = self.canvas.winfo_height() or 600
			self.canvas.create_text(
				w // 2,
				h // 2,
				text="No image",
				fill=self.colors["muted"],
				font=self.base_font,
			)
			# No image; also clear arrows
			self._draw_arrows()
			return

		path = self.images[self.index]
		cw = max(1, self.canvas.winfo_width())
		ch = max(1, self.canvas.winfo_height())
		cache_key = (path, cw, ch)

		cached_pil = self._viewer_pil_cache.get(cache_key)
		if cached_pil is not None:
			self.current_image_pil = cached_pil
			self._render_precomputed_to_canvas(cached_pil)
		else:
			try:
				img = load_media_image(path, max_size=(cw, ch))
				self.current_image_pil = img
				img_w, img_h = img.size
				scale = min(cw / img_w, ch / img_h)
				new_w = max(1, int(img_w * scale))
				new_h = max(1, int(img_h * scale))
				resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
				self._cache_viewer_pil(cache_key, resized)
				self._render_precomputed_to_canvas(resized)
			except Exception as e:
				self.canvas.create_text(
					20,
					20,
					text=f"Error loading {path.name}: {e}",
					fill="#FF5555",
					anchor="nw",
					font=self.small_font,
				)
				self._draw_arrows()

		# Prefetch neighboring images in background thread
		self._trigger_prefetch()

	def _trigger_prefetch(self) -> None:
		"""Prefetch neighboring images in a background thread for instant browsing."""
		if not self.images or self.mode != "viewer":
			return
		cw = max(1, self.canvas.winfo_width())
		ch = max(1, self.canvas.winfo_height())
		for idx in (self.index + 1, self.index + 2, self.index - 1):
			if 0 <= idx < len(self.images):
				p = self.images[idx]
				key = (p, cw, ch)
				if key not in self._viewer_pil_cache:
					self._executor.submit(self._bg_load_and_cache, p, cw, ch)

	def _bg_load_and_cache(self, path: Path, cw: int, ch: int) -> None:
		try:
			key = (path, cw, ch)
			if key in self._viewer_pil_cache:
				return
			img = load_media_image(path, max_size=(cw, ch))
			img_w, img_h = img.size
			scale = min(cw / img_w, ch / img_h)
			new_w = max(1, int(img_w * scale))
			new_h = max(1, int(img_h * scale))
			resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
			self._cache_viewer_pil(key, resized)
		except Exception:
			pass

	def _cache_viewer_pil(self, key: Tuple[Path, int, int], img: Image.Image) -> None:
		if len(self._viewer_pil_cache) > 12:
			oldest = next(iter(self._viewer_pil_cache))
			self._viewer_pil_cache.pop(oldest, None)
		self._viewer_pil_cache[key] = img

	def _render_precomputed_to_canvas(self, resized: Image.Image) -> None:
		canvas_w = max(1, self.canvas.winfo_width())
		canvas_h = max(1, self.canvas.winfo_height())
		self.current_photo = ImageTk.PhotoImage(resized)
		self.canvas.delete("all")
		self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.current_photo, anchor="center")
		self._draw_arrows()
		self._draw_mark_badge()
		self._draw_video_badge()

	def _on_canvas_resize(self, _event) -> None:
		if self.mode != "viewer" or not self.current_image_pil:
			return
		# Debounce rapid resize events
		if self._resize_after_id:
			try:
				self.after_cancel(self._resize_after_id)
			except Exception:
				pass
		self._resize_after_id = self.after(80, self._render_to_canvas)

	def _render_to_canvas(self) -> None:
		if self.mode != "viewer" or not self.current_image_pil:
			return
		canvas_w = max(1, self.canvas.winfo_width())
		canvas_h = max(1, self.canvas.winfo_height())
		img_w, img_h = self.current_image_pil.size

		scale = min(canvas_w / img_w, canvas_h / img_h)
		new_w = max(1, int(img_w * scale))
		new_h = max(1, int(img_h * scale))
		resized = self.current_image_pil.resize((new_w, new_h), Image.Resampling.BILINEAR)
		self._render_precomputed_to_canvas(resized)

	def _draw_mark_badge(self) -> None:
		"""Draw a small amber dot in the top-right corner when current image is marked."""
		# Remove any existing badge
		self.canvas.delete("mark_badge")
		if not self.images or self.index < 0:
			return
		if self.images[self.index].name not in self.marked:
			return
		cw = self.canvas.winfo_width() or 800
		r = 10
		pad = 14
		x, y = cw - pad, pad
		self.canvas.create_oval(
			x - r, y - r, x + r, y + r,
			fill=self.colors["marked"],
			outline="",
			tags="mark_badge",
		)

	def _draw_video_badge(self) -> None:
		"""Draw media player indicator in viewer canvas if current media is video or HEIC."""
		self.canvas.delete("video_badge")
		if not self.images or self.index < 0:
			return
		cur = self.images[self.index]
		is_vid = is_video(cur)
		is_heic = cur.suffix.lower() in {".heic", ".heif", ".hif"}
		if not is_vid and not is_heic:
			return
		ch = self.canvas.winfo_height() or 600
		p_name = Path(self.media_player).stem.upper() if self.media_player else "PLAYER"
		label_type = "VIDEO" if is_vid else cur.suffix.upper()[1:]
		self.canvas.create_text(
			20,
			ch - 24,
			text=f"▶ {label_type}  (Double-click or press P to open in {p_name})",
			fill=self.colors["fg"],
			font=self.small_font,
			anchor="w",
			tags="video_badge",
		)

	def configure_player(self) -> None:
		"""Open dialog to configure user-specified media player executable."""
		initial_dir = r"C:\Program Files\VideoLAN\VLC" if sys.platform.startswith("win") else None
		chosen = filedialog.askopenfilename(
			title="Select Media Player (e.g. VLC)",
			initialdir=initial_dir if initial_dir and Path(initial_dir).exists() else None,
			filetypes=[("Executables", "*.exe"), ("All Files", "*.*")] if sys.platform.startswith("win") else [("All Files", "*.*")],
		)
		self.focus_set()
		if chosen:
			self.media_player = chosen
			self.config["media_player"] = chosen
			save_app_config(self.config)
			name = Path(chosen).name
			self._set_status(extra=f"Player set to {name}")
			if self.mode == "viewer":
				self._draw_video_badge()

	def open_in_player(self) -> None:
		"""Open current media file in user-specified media player or system default."""
		if not self.images or self.index < 0:
			return
		cur = self.images[self.index]
		if not cur.exists():
			return
		player = self.media_player
		if player and Path(player).is_file():
			try:
				subprocess.Popen([player, str(cur)])
				return
			except Exception as e:
				messagebox.showerror("Error launching player", f"Failed to open with {player}:\n{e}")
		# Fallback to system default association
		try:
			if sys.platform.startswith("win"):
				os.startfile(str(cur))
			elif sys.platform == "darwin":
				subprocess.Popen(["open", str(cur)])
			else:
				subprocess.Popen(["xdg-open", str(cur)])
		except Exception as e:
			messagebox.showerror("Error opening file", str(e))

	play_current_video = open_in_player

	def _clear_arrow_items(self) -> None:
		if self._left_arrow_id is not None:
			try:
				self.canvas.delete(self._left_arrow_id)
			except Exception:
				pass
			self._left_arrow_id = None
		if self._right_arrow_id is not None:
			try:
				self.canvas.delete(self._right_arrow_id)
			except Exception:
				pass
			self._right_arrow_id = None

	def _draw_arrows(self) -> None:
		# Remove existing arrows
		self._clear_arrow_items()
		if self.mode != "viewer":
			return
		has_images = bool(self.images)
		if not has_images or self.index < 0:
			return
		at_first = self.index <= 0
		at_last = self.index >= (len(self.images) - 1)

		cw = self.canvas.winfo_width() or 800
		ch = self.canvas.winfo_height() or 600
		y = ch // 2
		# Responsive arrow size
		size = max(18, min(72, int(ch * 0.08)))
		arrow_font = (self.font_family, size)
		padding = max(16, int(cw * 0.02))
		x_left = padding
		x_right = cw - padding

		# Left arrow (hidden on first)
		if not at_first:
			self._left_arrow_id = self.canvas.create_text(
				x_left, y, text="‹", fill=self.colors["fg"], font=arrow_font, anchor="w"
			)
			self.canvas.tag_bind(self._left_arrow_id, "<Button-1>", lambda e: self.prev_image())
			self.canvas.tag_bind(self._left_arrow_id, "<Enter>", lambda e: self.canvas.config(cursor="hand2"))
			self.canvas.tag_bind(self._left_arrow_id, "<Leave>", lambda e: self.canvas.config(cursor=""))

		# Right arrow (hidden on last)
		if not at_last:
			self._right_arrow_id = self.canvas.create_text(
				x_right, y, text="›", fill=self.colors["fg"], font=arrow_font, anchor="e"
			)
			self.canvas.tag_bind(self._right_arrow_id, "<Button-1>", lambda e: self.next_image())
			self.canvas.tag_bind(self._right_arrow_id, "<Enter>", lambda e: self.canvas.config(cursor="hand2"))
			self.canvas.tag_bind(self._right_arrow_id, "<Leave>", lambda e: self.canvas.config(cursor=""))

	# ---------- Gallery UI ----------

	def _build_gallery_ui(self) -> None:
		self._gallery_container = ttk.Frame(self.view_area, style="TFrame")
		# Canvas and vertical scrollbar
		self.gallery_canvas = tk.Canvas(
			self._gallery_container,
			bg=self.colors["bg"],
			highlightthickness=0,
		)
		self.gallery_vscroll = ttk.Scrollbar(
			self._gallery_container, orient="vertical", command=self.gallery_canvas.yview
		)
		self.gallery_canvas.configure(yscrollcommand=self.gallery_vscroll.set)
		self.gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		self.gallery_vscroll.pack(side=tk.RIGHT, fill=tk.Y)

		self.gallery_frame = ttk.Frame(self.gallery_canvas, style="TFrame")
		self._gallery_window_id = self.gallery_canvas.create_window(
			(0, 0), window=self.gallery_frame, anchor="nw"
		)
		self.gallery_frame.bind("<Configure>", self._on_gallery_frame_configure)
		self.gallery_canvas.bind("<Configure>", self._on_gallery_canvas_configure)
		# Note: mouse wheel is handled globally in _on_global_mouse_wheel

		# Initially hidden
		self._gallery_container.pack_forget()

	def toggle_gallery(self) -> None:
		if self.mode == "viewer":
			self._enter_gallery()
		else:
			self._leave_gallery()

	def _enter_gallery(self) -> None:
		self.mode = "gallery"
		# Hide viewer canvas
		self.canvas.pack_forget()
		# Show gallery container
		self._gallery_container.pack(fill=tk.BOTH, expand=True)
		# Show the gallery-only thumbnail size panel
		self.thumb_panel.pack(side=tk.LEFT)
		self._rebuild_gallery()
		self._set_status()
		self._update_controls()

	def _leave_gallery(self) -> None:
		self.mode = "viewer"
		# Hide gallery
		self._gallery_container.pack_forget()
		# Hide the gallery-only thumbnail size panel
		self.thumb_panel.pack_forget()
		# Show viewer canvas
		self.canvas.pack(fill=tk.BOTH, expand=True)
		self._show_current()
		self._set_status()
		self._update_controls()

	def _rebuild_gallery(self) -> None:
		if not self.gallery_frame:
			return
		# Clear existing tiles
		for child in list(self.gallery_frame.winfo_children()):
			child.destroy()
		self._gallery_tiles.clear()
		# Build tiles
		# Create placeholders list matching images; actual tiles will be created lazily
		self._gallery_tiles = [None] * len(self.images)  # type: ignore[list-item]
		self._gallery_loaded_count = 0
		self._layout_gallery()
		self._load_next_batch()
		self._update_selection_highlight()
		self._ensure_selected_visible()

	def _create_tile(self, parent: tk.Misc, index: int, path: Path) -> tk.Frame:
		is_marked = path.name in self.marked
		border_color = self.colors["marked"] if is_marked else self.colors["border"]
		# Outer frame as border
		outer = tk.Frame(parent, bg=border_color)
		inner = tk.Frame(outer, bg=self.colors["panel"])  # image background
		inner.pack(padx=2, pady=2)
		thumb = self._get_thumbnail(path)
		lbl = tk.Label(inner, image=thumb, bg=self.colors["panel"])
		lbl.pack()
		# Mouse bindings
		def on_click(_e=None, i=index):
			self.index = i
			self._update_selection_highlight()
			self._set_status()
			self._ensure_selected_visible()
			self._update_controls()
		def on_double(_e=None, i=index):
			self.index = i
			self._leave_gallery()
		def on_right_click(_e=None, i=index):
			self.index = i
			name = self.images[i].name
			if name in self.marked:
				self.marked.discard(name)
				self._last_mark_action = (name, "unmarked", i)
			else:
				self.marked.add(name)
				self._last_mark_action = (name, "marked", i)
			self._save_session()
			self._set_status()
			self._update_controls()
			self._update_selection_highlight()
		outer.bind("<Button-1>", on_click)
		inner.bind("<Button-1>", on_click)
		lbl.bind("<Button-1>", on_click)
		outer.bind("<Double-Button-1>", on_double)
		inner.bind("<Double-Button-1>", on_double)
		lbl.bind("<Double-Button-1>", on_double)
		outer.bind("<Button-3>", on_right_click)
		inner.bind("<Button-3>", on_right_click)
		lbl.bind("<Button-3>", on_right_click)
		return outer

	def _get_thumbnail(self, path: Path, size: Optional[int] = None) -> ImageTk.PhotoImage:
		s = int(size or self.thumb_size)
		key = (path, s)
		cached = self.thumb_cache.get(key)
		if cached is not None:
			return cached
		try:
			img = load_media_image(path, max_size=(s, s))
			img.thumbnail((s, s), Image.Resampling.BILINEAR)
			if is_video(path):
				# Overlay small play indicator badge on video thumbnail
				draw = ImageDraw.Draw(img)
				tw, th = img.size
				bw, bh = 22, 16
				bx, by = max(0, tw - bw - 4), max(0, th - bh - 4)
				draw.rectangle([bx, by, bx + bw, by + bh], fill=(0, 0, 0))
				draw.polygon([(bx + 7, by + 4), (bx + 7, by + 12), (bx + 16, by + 8)], fill=(255, 255, 255))
			photo = ImageTk.PhotoImage(img)
			self.thumb_cache[key] = photo
			return photo
		except Exception:
			# Fallback: empty placeholder
			ph = Image.new("RGB", (s, s), color=(34, 34, 34))
			if is_video(path):
				draw = ImageDraw.Draw(ph)
				draw.polygon([(s // 2 - 6, s // 2 - 10), (s // 2 - 6, s // 2 + 10), (s // 2 + 10, s // 2)], fill=(160, 160, 160))
			photo = ImageTk.PhotoImage(ph)
			self.thumb_cache[key] = photo
			return photo

	def _purge_thumb_cache_for_path(self, path: Path) -> None:
		# Remove all sizes for a given path from cache
		to_delete = [k for k in self.thumb_cache.keys() if k[0] == path]
		for k in to_delete:
			self.thumb_cache.pop(k, None)
		v_delete = [k for k in self._viewer_pil_cache.keys() if k[0] == path]
		for k in v_delete:
			self._viewer_pil_cache.pop(k, None)

	def _purge_thumb_cache_for_names(self, names: set[str]) -> None:
		"""Remove all cached thumbnails whose filename is in names."""
		to_delete = [k for k in self.thumb_cache.keys() if k[0].name in names]
		for k in to_delete:
			self.thumb_cache.pop(k, None)
		v_delete = [k for k in self._viewer_pil_cache.keys() if k[0].name in names]
		for k in v_delete:
			self._viewer_pil_cache.pop(k, None)

	def _on_gallery_frame_configure(self, _event=None) -> None:
		if not self.gallery_canvas or not self.gallery_frame:
			return
		self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all"))
		self._maybe_trigger_load_more()

	def _on_gallery_canvas_configure(self, _event=None) -> None:
		# Ensure the inner frame matches canvas width and reflow layout
		if not self.gallery_canvas or self._gallery_window_id is None:
			return
		cw = self.gallery_canvas.winfo_width()
		self.gallery_canvas.itemconfigure(self._gallery_window_id, width=cw)
		self._layout_gallery()
		self._maybe_trigger_load_more()

	def _on_global_mouse_wheel(self, event) -> Optional[str]:
		"""Global wheel handler.
		- In Gallery: scroll the gallery canvas regardless of focus if pointer is within it.
		- In Viewer: wheel navigates prev/next when pointer is over the viewer canvas.
		Return "break" when handled to prevent duplicate scrolling; otherwise None.
		"""
		try:
			w = event.widget
		except Exception:
			w = None
		# Helper to check containment
		def within(child: tk.Misc | None, parent: tk.Misc | None) -> bool:
			while child is not None:
				if child is parent:
					return True
				child = getattr(child, "master", None)
			return False

		# Ignore wheel when over scrollbars or sliders
		wclass = getattr(w, "winfo_class", lambda: "")()
		if wclass in ("TScrollbar", "Scrollbar", "TScale"):
			return None

		# Gallery scroll when pointer is over gallery canvas or its inner frame/children
		if self.mode == "gallery" and self.gallery_canvas:
			if within(w, self.gallery_canvas) or within(w, self.gallery_frame):
				units = int(-event.delta / 120) or (1 if event.delta < 0 else -1)
				self.gallery_canvas.yview_scroll(units, "units")
				self._maybe_trigger_load_more()
				return "break"

		# Viewer: navigate prev/next when pointer is over viewer canvas
		if self.mode == "viewer" and self.canvas:
			if within(w, self.canvas):
				if event.delta < 0:
					self.next_image()
				else:
					self.prev_image()
				return "break"

		return None

	def _ensure_loaded_upto(self, idx: int) -> None:
		# Load more thumbnails up to include the index.
		while idx >= self._gallery_loaded_count and self._gallery_loaded_count < len(self._gallery_tiles):
			self._load_next_batch()

	def _layout_gallery(self) -> None:
		if not self.gallery_canvas or not self.gallery_frame:
			return
		cw = max(1, self.gallery_canvas.winfo_width())
		gap = 16
		tile_w = self.thumb_size + 4 + 4  # inner + border padding (2px each side)
		cols = max(1, (cw - gap) // (tile_w + gap))
		# Place any already-created tiles; placeholders will be skipped
		for i, tile in enumerate(self._gallery_tiles):
			if tile is None:
				continue
			row = i // cols
			col = i % cols
			tile.grid(row=row, column=col, padx=gap, pady=gap, sticky="n")
		# Make columns expand equally
		for c in range(cols):
			self.gallery_frame.grid_columnconfigure(c, weight=1)

	def _update_selection_highlight(self) -> None:
		"""Update gallery tile borders: marked=amber, selected=white, both=amber+thick, neither=dark."""
		if not self._gallery_tiles:
			return
		for i, tile in enumerate(self._gallery_tiles):
			if tile is None:
				continue
			is_selected = (i == self.index)
			is_marked = (
				i < len(self.images) and self.images[i].name in self.marked
			)
			if is_marked and is_selected:
				tile.configure(bg=self.colors["marked"])
				# Thicker border signals both marked and selected
				for child in tile.winfo_children():
					child.pack_configure(padx=4, pady=4)
			elif is_marked:
				tile.configure(bg=self.colors["marked"])
				for child in tile.winfo_children():
					child.pack_configure(padx=2, pady=2)
			elif is_selected:
				tile.configure(bg=self.colors["fg"])
				for child in tile.winfo_children():
					child.pack_configure(padx=2, pady=2)
			else:
				tile.configure(bg=self.colors["border"])
				for child in tile.winfo_children():
					child.pack_configure(padx=2, pady=2)

	def _ensure_selected_visible(self) -> None:
		if not self.gallery_canvas or not self._gallery_tiles or not (0 <= self.index < len(self._gallery_tiles)):
			return
		# Ensure tile exists around selection
		self._ensure_loaded_upto(self.index)
		# Compute target row and approximate y position and scroll to it
		cw = max(1, self.gallery_canvas.winfo_width())
		gap = 16
		tile_w = self.thumb_size + 4 + 4
		cols = max(1, (cw - gap) // (tile_w + gap))
		row = self.index // cols
		row_height = self.thumb_size + gap + 4
		y = row * row_height
		bbox = self.gallery_canvas.bbox("all")
		if bbox:
			max_y = max(1, bbox[3])
			self.gallery_canvas.yview_moveto(max(0.0, min(1.0, y / max_y)))

		# Trigger more loading if near bottom
		self._maybe_trigger_load_more()

	def _maybe_trigger_load_more(self) -> None:
		if not self.gallery_canvas or not self._gallery_tiles:
			return
		bbox = self.gallery_canvas.bbox("all")
		if not bbox:
			return
		_, y0, _, y1 = bbox
		view_y0 = self.gallery_canvas.canvasy(0)
		view_y1 = view_y0 + self.gallery_canvas.winfo_height()
		# If within 1.5 screens of bottom, load more
		if view_y1 + (self.gallery_canvas.winfo_height() * 0.5) >= y1:
			self._load_next_batch()

	def _load_next_batch(self) -> None:
		if self._gallery_loading:
			return
		if self._gallery_loaded_count >= len(self._gallery_tiles):
			return
		self._gallery_loading = True
		batch_size = 5
		start = self._gallery_loaded_count
		end = min(len(self._gallery_tiles), start + batch_size)
		for i in range(start, end):
			path = self.images[i]
			tile = self._create_tile(self.gallery_frame, i, path)
			self._gallery_tiles[i] = tile
		self._gallery_loaded_count = end
		self._layout_gallery()
		self._update_selection_highlight()
		self._gallery_loading = False
		# If still near bottom, schedule another batch with slight delay to stay responsive
		if self._gallery_load_after:
			try:
				self.after_cancel(self._gallery_load_after)
			except Exception:
				pass
		self._gallery_load_after = self.after(50, self._maybe_trigger_load_more)
		# Compute target row and approximate y position
		cw = max(1, self.gallery_canvas.winfo_width())
		gap = 16
		tile_w = self.thumb_size + 4 + 4
		cols = max(1, (cw - gap) // (tile_w + gap))
		row = self.index // cols
		row_height = self.thumb_size + gap + 4
		y = row * row_height
		bbox = self.gallery_canvas.bbox("all")
		if bbox is None:
			return
		max_y = max(1, bbox[3])
		self.gallery_canvas.yview_moveto(max(0.0, min(1.0, y / max_y)))

	# ----- Thumbnail size handling -----

	def _snap_thumb(self, v: int) -> int:
		# Snap around 96..384 using large steps
		lo, hi, step = 96, 384, self.thumb_step
		offset = max(0, v - lo)
		snapped = lo + int(round(offset / step)) * step
		return max(lo, min(hi, snapped))

	def _on_thumb_scale_move(self, value: float) -> None:
		# During drag, update label only (snapped), avoid rebuild
		v = self._snap_thumb(int(value))
		self.thumb_label.configure(text=f"Thumb {v}px")

	def _apply_thumb_size_from_scale(self, _e=None) -> None:
		v = self._snap_thumb(int(self.thumb_scale.get()))
		# Snap the slider thumb to the discrete value
		try:
			self.thumb_scale.set(v)
		except Exception:
			pass
		if v == self.thumb_size:
			# Nothing changed
			self.thumb_label.configure(text=f"Thumb {v}px")
			return
		self.thumb_size = v
		self.thumb_size_var.set(v)
		self.thumb_label.configure(text=f"Thumb {v}px")
		# Rebuild gallery lazily at new size; keep cache for other sizes for future reuse
		if self.mode == "gallery":
			self._rebuild_gallery()

	def _on_close(self) -> None:
		# Save session before exit so marks are never lost
		self._save_session()
		# Clear session caches (in-memory only) and exit
		try:
			self.thumb_cache.clear()
			self._viewer_pil_cache.clear()
			self._executor.shutdown(wait=False, cancel_futures=True)
		except Exception:
			pass
		# Remove any private fonts we added on Windows
		if sys.platform.startswith("win") and self._win_private_fonts:
			try:
				import ctypes
				for p in self._win_private_fonts:
					try:
						ctypes.windll.gdi32.RemoveFontResourceExW(str(p), 0x10, 0)
					except Exception:
						pass
			except Exception:
				pass
		self.destroy()

	def _move_selection_up(self) -> None:
		if self.mode != "gallery" or not self.images:
			return
		cw = max(1, self.gallery_canvas.winfo_width()) if self.gallery_canvas else 1
		gap = 16
		tile_w = self.thumb_size + 4 + 4
		cols = max(1, (cw - gap) // (tile_w + gap))
		self.index = max(0, self.index - cols)
		self._set_status()
		self._update_selection_highlight()
		self._ensure_selected_visible()
		self._update_controls()

	def _move_selection_down(self) -> None:
		if self.mode != "gallery" or not self.images:
			return
		cw = max(1, self.gallery_canvas.winfo_width()) if self.gallery_canvas else 1
		gap = 16
		tile_w = self.thumb_size + 4 + 4
		cols = max(1, (cw - gap) // (tile_w + gap))
		self.index = min(len(self.images) - 1, self.index + cols)
		self._set_status()
		self._update_selection_highlight()
		self._ensure_selected_visible()
		self._update_controls()


def main() -> None:
	app = PicCullApp()
	app.mainloop()


if __name__ == "__main__":
	main()
