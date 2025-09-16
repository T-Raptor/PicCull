import os
import sys
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

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

		for w in (self.btn_open, self.btn_prev, self.btn_next, self.btn_delete):
			w.pack(side=tk.LEFT, padx=(8, 0), pady=8)

		# Center canvas for image
		self.canvas = tk.Canvas(
			self,
			bg=self.colors["bg"],
			highlightthickness=0,
		)
		self.canvas.pack(fill=tk.BOTH, expand=True)
		self.canvas.bind("<Configure>", self._on_canvas_resize)

		# Status bar
		bottom = ttk.Frame(self, style="Panel.TFrame")
		bottom.pack(side=tk.BOTTOM, fill=tk.X)
		self.status = ttk.Label(bottom, text="Pick a folder to begin", style="Muted.TLabel")
		self.status.pack(side=tk.LEFT, padx=8, pady=6)

		self._update_controls()

	def _bind_keys(self) -> None:
		self.bind("<Escape>", lambda e: self.destroy())
		self.bind("<Left>", lambda e: self.prev_image())
		self.bind("<Right>", lambda e: self.next_image())
		self.bind("<Delete>", lambda e: self.delete_current())
		self.bind("<Return>", lambda e: self.next_image())
		self.bind("<space>", lambda e: self.next_image())

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
		self.status.configure(text=text)

	def _update_controls(self) -> None:
		has_images = bool(self.images)
		state_normal = tk.NORMAL if has_images else tk.DISABLED
		self.btn_prev.configure(state=state_normal)
		self.btn_next.configure(state=state_normal)
		self.btn_delete.configure(state=state_normal)

	def prev_image(self) -> None:
		if not self.images:
			return
		self.index = (self.index - 1) % len(self.images)
		self._set_status()
		self._show_current()

	def next_image(self) -> None:
		if not self.images:
			return
		self.index = (self.index + 1) % len(self.images)
		self._set_status()
		self._show_current()

	def delete_current(self) -> None:
		if not self.images:
			return
		cur = self.images[self.index]
		try:
			target_dir = ensure_deleted_folder(cur.parent)
			moved_to = safe_move_to_deleted(cur, target_dir)
			# Remove from list and adjust index
			del self.images[self.index]
			if self.images:
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


def main() -> None:
	app = PicCullApp()
	app.mainloop()


if __name__ == "__main__":
	main()

