import os
import sys
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
	from PIL import Image, ImageTk, ImageOps
except ImportError:
	# Pillow not installed; provide a helpful message
	raise SystemExit(
		"Pillow is required. Install with: python -m pip install -r requirements.txt"
	)


IMG_EXTS = {".jpg", ".jpeg", ".png"}


def is_image(path: Path) -> bool:
	return path.suffix.lower() in IMG_EXTS


def list_images(folder: Path) -> List[Path]:
	return sorted([p for p in folder.iterdir() if p.is_file() and is_image(p)], key=lambda p: p.name.lower())


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
		}

		# Use a monospaced font available on Windows
		self.font_family = "Consolas" if sys.platform.startswith("win") else "Menlo"
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
		# Undo: (original_parent, moved_to_path, original_index, original_name)
		self._last_deleted: Optional[Tuple[Path, Path, int, str]] = None
		# Canvas arrow items
		self._left_arrow_id: Optional[int] = None
		self._right_arrow_id: Optional[int] = None

		# Modes: 'viewer' or 'gallery'
		self.mode: str = "viewer"
		# Thumbnails
		self.thumb_size: int = 200
		self.thumb_size_var = tk.IntVar(value=self.thumb_size)
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

		self.btn_open = ttk.Button(top, text="Open", command=self.choose_folder)
		self.btn_prev = ttk.Button(top, text="Prev", command=self.prev_image)
		self.btn_next = ttk.Button(top, text="Next", command=self.next_image)
		self.btn_delete = ttk.Button(top, text="Delete", command=self.delete_current)
		self.btn_undo = ttk.Button(top, text="Undo", command=self.undo_last_delete)
		self.btn_mode = ttk.Button(top, text="Gallery", command=self.toggle_gallery)

		for w in (self.btn_open, self.btn_prev, self.btn_next, self.btn_delete, self.btn_undo, self.btn_mode):
			w.pack(side=tk.LEFT, padx=(8, 0), pady=8)

		# Thumbnail size control (adjustable during session)
		sep = ttk.Frame(top, style="Panel.TFrame")
		sep.pack(side=tk.LEFT, padx=8)
		self.thumb_label = ttk.Label(top, text=f"Thumb {self.thumb_size}px", style="Muted.TLabel")
		self.thumb_label.pack(side=tk.LEFT, padx=(8, 4))
		self.thumb_scale = ttk.Scale(
			top,
			from_=96,
			to=384,
			orient=tk.HORIZONTAL,
			value=self.thumb_size,
			length=160,
			command=lambda v: self._on_thumb_size_change(float(v)),
		)
		self.thumb_scale.pack(side=tk.LEFT, padx=(0, 8))

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

		# Gallery container (canvas + scrollbar), initially hidden
		self._build_gallery_ui()

		# Status bar (counter + text)
		bottom = ttk.Frame(self, style="Panel.TFrame")
		bottom.pack(side=tk.BOTTOM, fill=tk.X)
		self.counter_label = ttk.Label(bottom, text="", style="Muted.TLabel")
		self.counter_label.pack(side=tk.LEFT, padx=(8, 0), pady=6)
		self.status_label = ttk.Label(bottom, text="Pick a folder to begin", style="Muted.TLabel")
		self.status_label.pack(side=tk.LEFT, padx=8, pady=6)

		self._update_controls()

		# Ensure we clear ephemeral caches on close
		self.protocol("WM_DELETE_WINDOW", self._on_close)

	def _bind_keys(self) -> None:
		self.bind("<Escape>", lambda e: self.destroy())
		self.bind("<Left>", lambda e: self.prev_image())
		self.bind("<Right>", lambda e: self.next_image())
		self.bind("<Delete>", lambda e: self.delete_current())
		self.bind("<Return>", lambda e: self._on_enter_key())
		self.bind("<space>", lambda e: self._on_enter_key())
		self.bind("<Up>", lambda e: self._move_selection_up())
		self.bind("<Down>", lambda e: self._move_selection_down())
		# Undo: Ctrl+Z
		self.bind("<Control-z>", lambda e: self.undo_last_delete())

	# ----- Image / folder management -----
	def choose_folder(self) -> None:
		path = filedialog.askdirectory(title="Select image folder")
		if not path:
			return
		folder = Path(path)
		imgs = list_images(folder)
		self.folder = folder
		self.images = imgs
		self.index = 0 if imgs else -1
		self._last_deleted = None
		self._set_status()
		self._show_current()
		self._update_controls()
		# Rebuild gallery content if needed
		self._rebuild_gallery()

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
			counter = f"{self.index + 1}/{len(self.images)}"
			info = f" — {im_path.name}"
			if extra:
				info = f"{info}  |  {extra}"
			self.counter_label.configure(text=counter)
			self.status_label.configure(text=info)

	def _update_controls(self) -> None:
		has_images = bool(self.images)
		at_first = has_images and self.index <= 0
		at_last = has_images and self.index >= (len(self.images) - 1)

		# Prev/Next enabled based on edges (no wrap)
		self.btn_prev.configure(state=(tk.NORMAL if (has_images and not at_first) else tk.DISABLED))
		self.btn_next.configure(state=(tk.NORMAL if (has_images and not at_last) else tk.DISABLED))
		self.btn_delete.configure(state=(tk.NORMAL if has_images else tk.DISABLED))
		self.btn_undo.configure(state=(tk.NORMAL if self._last_deleted else tk.DISABLED))

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

	def delete_current(self) -> None:
		if not self.images:
			return
		cur = self.images[self.index]
		try:
			target_dir = ensure_deleted_folder(cur.parent)
			moved_to = safe_move_to_deleted(cur, target_dir)
			# Remove from list and adjust index
			original_index = self.index
			original_parent = cur.parent
			original_name = cur.name
			del self.images[self.index]
			# Purge any thumbnails for this path from cache (all sizes)
			self._purge_thumb_cache_for_path(cur)
			# Prepare undo info
			self._last_deleted = (original_parent, Path(moved_to), original_index, original_name)

			if self.images:
				# Clamp to last element if we deleted last
				self.index = min(self.index, len(self.images) - 1)
			else:
				self.index = -1
			# Build a friendly path string; prefer relative to chosen folder if available
			rel_display = moved_to.name
			if self.folder is not None:
				try:
					rel_display = str(moved_to.relative_to(self.folder))
				except Exception:
					rel_display = moved_to.name
			self._set_status(extra=f"Moved to {rel_display}")
			if self.mode == "viewer":
				self._show_current()
			else:
				# Rebuild gallery grid after delete
				self._rebuild_gallery()
			self._update_controls()
		except Exception as e:
			messagebox.showerror("Error", f"Failed to move file:\n{e}")

	def undo_last_delete(self) -> None:
		if not self._last_deleted:
			return
		original_parent, moved_to, original_index, original_name = self._last_deleted
		try:
			# Compute restore destination with collision-safe naming
			dest = original_parent / original_name
			if dest.exists():
				stem, ext = Path(original_name).stem, Path(original_name).suffix
				i = 1
				while True:
					candidate = original_parent / f"{stem}-restored-{i}{ext}"
					if not candidate.exists():
						dest = candidate
						break
					i += 1
			shutil.move(str(moved_to), str(dest))
			# Insert back into list near original index (clamped)
			insert_at = max(0, min(original_index, len(self.images)))
			self.images.insert(insert_at, dest)
			self.index = insert_at
			self._last_deleted = None
			# Update UI
			rel_display = dest.name
			if self.folder is not None:
				try:
					rel_display = str(dest.relative_to(self.folder))
				except Exception:
					rel_display = dest.name
			self._set_status(extra=f"Restored {rel_display}")
			self._show_current()
			self._update_controls()
		except Exception as e:
			messagebox.showerror("Error", f"Failed to restore file:\n{e}")

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
		try:
			img = Image.open(path)
			# Correct orientation from EXIF if present
			img = ImageOps.exif_transpose(img)
			self.current_image_pil = img
			self._render_to_canvas()
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
		resized = self.current_image_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
		self.current_photo = ImageTk.PhotoImage(resized)

		self.canvas.delete("all")
		self.canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.current_photo, anchor="center")
		self._draw_arrows()

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
		# Mouse wheel scroll (Windows)
		self.gallery_canvas.bind("<MouseWheel>", self._on_mouse_wheel)

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
		self._rebuild_gallery()
		self._set_status()
		self._update_controls()

	def _leave_gallery(self) -> None:
		self.mode = "viewer"
		# Hide gallery
		self._gallery_container.pack_forget()
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
		# Outer frame as border
		outer = tk.Frame(parent, bg=self.colors["border"])
		inner = tk.Frame(outer, bg=self.colors["panel"])  # image background
		inner.pack(padx=1, pady=1)
		thumb = self._get_thumbnail(path)
		lbl = tk.Label(inner, image=thumb, bg=self.colors["panel"]) 
		lbl.pack()
		# Mouse bindings
		def on_click(_e=None, i=index):
			self.index = i
			self._update_selection_highlight()
			self._set_status()
			self._ensure_selected_visible()
		def on_double(_e=None, i=index):
			self.index = i
			self._leave_gallery()
		outer.bind("<Button-1>", on_click)
		inner.bind("<Button-1>", on_click)
		lbl.bind("<Button-1>", on_click)
		outer.bind("<Double-Button-1>", on_double)
		inner.bind("<Double-Button-1>", on_double)
		lbl.bind("<Double-Button-1>", on_double)
		return outer

	def _get_thumbnail(self, path: Path, size: Optional[int] = None) -> ImageTk.PhotoImage:
		s = int(size or self.thumb_size)
		key = (path, s)
		cached = self.thumb_cache.get(key)
		if cached is not None:
			return cached
		try:
			img = Image.open(path)
			img = ImageOps.exif_transpose(img)
			img.thumbnail((s, s), Image.Resampling.LANCZOS)
			photo = ImageTk.PhotoImage(img)
			self.thumb_cache[key] = photo
			return photo
		except Exception:
			# Fallback: empty placeholder
			ph = Image.new("RGB", (s, s), color=(34, 34, 34))
			photo = ImageTk.PhotoImage(ph)
			self.thumb_cache[key] = photo
			return photo

	def _purge_thumb_cache_for_path(self, path: Path) -> None:
		# Remove all sizes for a given path from cache
		to_delete = [k for k in self.thumb_cache.keys() if k[0] == path]
		for k in to_delete:
			self.thumb_cache.pop(k, None)

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

	def _on_mouse_wheel(self, event) -> None:
		if self.mode != "gallery" or not self.gallery_canvas:
			return
		# event.delta is multiples of 120 on Windows; negative means scroll down
		delta_units = int(-event.delta / 120)
		if delta_units:
			self.gallery_canvas.yview_scroll(delta_units, "units")
			self._maybe_trigger_load_more()

	def _ensure_loaded_upto(self, idx: int) -> None:
		# Load more thumbnails up to include the index.
		while idx >= self._gallery_loaded_count and self._gallery_loaded_count < len(self._gallery_tiles):
			self._load_next_batch()

	def _layout_gallery(self) -> None:
		if not self.gallery_canvas or not self.gallery_frame:
			return
		cw = max(1, self.gallery_canvas.winfo_width())
		gap = 16
		tile_w = self.thumb_size + 2 + 2  # inner + border padding
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
		if not self._gallery_tiles:
			return
		for i, tile in enumerate(self._gallery_tiles):
			if tile is None:
				continue
			bg = self.colors["fg"] if i == self.index else self.colors["border"]
			tile.configure(bg=bg)

	def _ensure_selected_visible(self) -> None:
		if not self.gallery_canvas or not self._gallery_tiles or not (0 <= self.index < len(self._gallery_tiles)):
			return
		# Ensure tile exists around selection
		self._ensure_loaded_upto(self.index)
		# Compute target row and approximate y position and scroll to it
		cw = max(1, self.gallery_canvas.winfo_width())
		gap = 16
		tile_w = self.thumb_size + 2 + 2
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
		tile_w = self.thumb_size + 2 + 2
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
	def _on_thumb_size_change(self, value: float) -> None:
		# Snap to nearest 16px to reduce churn
		v = int(round(value / 16.0) * 16)
		v = max(96, min(384, v))
		if v == self.thumb_size:
			# Update label but avoid rebuild
			self.thumb_label.configure(text=f"Thumb {v}px")
			return
		self.thumb_size = v
		self.thumb_size_var.set(v)
		self.thumb_label.configure(text=f"Thumb {v}px")
		# Rebuild gallery lazily at new size; keep cache for other sizes for future reuse
		if self.mode == "gallery":
			self._rebuild_gallery()

	def _on_close(self) -> None:
		# Clear session caches (in-memory only) and exit
		try:
			self.thumb_cache.clear()
		except Exception:
			pass
		self.destroy()

	def _move_selection_up(self) -> None:
		if self.mode != "gallery" or not self.images:
			return
		cw = max(1, self.gallery_canvas.winfo_width()) if self.gallery_canvas else 1
		gap = 16
		tile_w = self.thumb_size + 2 + 2
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
		tile_w = self.thumb_size + 2 + 2
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

