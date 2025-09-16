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

		for w in (self.btn_open, self.btn_prev, self.btn_next, self.btn_delete, self.btn_undo):
			w.pack(side=tk.LEFT, padx=(8, 0), pady=8)

		# Center canvas for image
		self.canvas = tk.Canvas(
			self,
			bg=self.colors["bg"],
			highlightthickness=0,
		)
		self.canvas.pack(fill=tk.BOTH, expand=True)
		self.canvas.bind("<Configure>", self._on_canvas_resize)

		# Status bar (counter + text)
		bottom = ttk.Frame(self, style="Panel.TFrame")
		bottom.pack(side=tk.BOTTOM, fill=tk.X)
		self.counter_label = ttk.Label(bottom, text="", style="Muted.TLabel")
		self.counter_label.pack(side=tk.LEFT, padx=(8, 0), pady=6)
		self.status_label = ttk.Label(bottom, text="Pick a folder to begin", style="Muted.TLabel")
		self.status_label.pack(side=tk.LEFT, padx=8, pady=6)

		self._update_controls()

	def _bind_keys(self) -> None:
		self.bind("<Escape>", lambda e: self.destroy())
		self.bind("<Left>", lambda e: self.prev_image())
		self.bind("<Right>", lambda e: self.next_image())
		self.bind("<Delete>", lambda e: self.delete_current())
		self.bind("<Return>", lambda e: self.next_image())
		self.bind("<space>", lambda e: self.next_image())
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
		self._show_current()
		self._update_controls()

	def next_image(self) -> None:
		if not self.images or self.index >= (len(self.images) - 1):
			return
		self.index += 1
		self._set_status()
		self._show_current()
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
			self._show_current()
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
		if not self.current_image_pil:
			return
		# Debounce rapid resize events
		if self._resize_after_id:
			try:
				self.after_cancel(self._resize_after_id)
			except Exception:
				pass
		self._resize_after_id = self.after(80, self._render_to_canvas)

	def _render_to_canvas(self) -> None:
		if not self.current_image_pil:
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


def main() -> None:
	app = PicCullApp()
	app.mainloop()


if __name__ == "__main__":
	main()

