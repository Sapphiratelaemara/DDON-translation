"""
editor_mixin.py — SharedEditorMixin

Methods shared verbatim (or near-verbatim) between ReviewEditor and
CSVTranslationWindow.  Neither class is a sub-class of the other; the mixin
provides the shared behaviour through multiple inheritance:

    class ReviewEditor(SharedEditorMixin, tk.Toplevel): ...
    class CSVTranslationWindow(SharedEditorMixin, tk.Toplevel): ...

CONTRACT — the following attributes MUST exist on `self` before any mixin
method is called.  They are set by the concrete class's __init__ / _setup_ui:

    Widget references
        self.txt                — main English Text editor
        self.deepl_box          — DeepL suggestion Text widget
        self.chat_history       — AI chat history Text widget
        self.chat_input         — AI chat input Text widget
        self.chat_model_var     — StringVar for selected model
        self.chat_model_combo   — Combobox for model selection
        self.btn_chat_send      — Button (disabled while chatting)
        self.preview_canvas     — Canvas for in-game preview
        self._preview_box_var   — StringVar ("dialogue" | "choice")

    State
        self.cm                 — ConfigManager instance
                                  (ReviewEditor exposes this via a @property)
        self.lore_engine        — LoreEngine instance
        self.anach_ranges       — list[(start, end, word, suggestions)]
        self._box_meta          — dict of box layout metadata
        self._preview_base_images — dict[str, PIL.Image]
        self._preview_font_objs   — dict[str, PIL.ImageFont]
        self._tip_label         — tk.Label tooltip widget
        self._tip_visible       — bool
        self._hovered_range     — current hovered range tuple or None
        self._is_translating    — bool busy-flag
        self._is_chatting       — bool busy-flag
        self._prev_W, _prev_H   — fallback canvas dimensions
        self.colors             — dict of themed colour strings

    Methods provided by the concrete class
        self._update_counters() — refresh line-length counter strip
"""

import re
import threading
import os
import shutil
import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog as tk_simpledialog
from tkinter import ttk

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class SharedEditorMixin:

    # ------------------------------------------------------------------
    # Anachronism tooltip
    # ------------------------------------------------------------------

    def _build_suggestion_text(self, word):
        """Return tooltip text: archaic alternatives + cached definition.
        Checks 'modern→archaic' context override first, then generic."""
        from lore_engine import IN_UNIVERSE_VOCAB
        word_lower = word.lower()
        options = []
        if word_lower in IN_UNIVERSE_VOCAB:
            val = IN_UNIVERSE_VOCAB[word_lower]
            if val:
                options.append(val)
        if not options:
            return f'⚠ "{word}" — no direct replacement (flag only)'
        opts_str = "  /  ".join(options)
        tip = f'⚠ "{word}"  →  {opts_str}   (Tab to insert)'
        for archaic in options:
            override_key = f"{word_lower}→{archaic.lower()}"
            defn = self.lore_engine.get_definition(override_key)
            if not defn:
                defn = self.lore_engine.get_definition(archaic.lower())
            if defn:
                tip += f"\n{defn}"
                break
        return tip

    def _bind_tooltip(self):
        """Bind hover tooltip to self.txt. Safe to call multiple times."""
        if hasattr(self, "_tip_label") and self._tip_label.winfo_exists():
            self._tip_label.destroy()
        self._tip_label = tk.Label(
            self, text="", bg="#ffffe0", fg="black",
            relief="solid", borderwidth=1, font=("Arial", 9),
            wraplength=400, justify="left",
        )
        self._tip_visible = False
        self._hovered_range = None

        def on_motion(event):
            idx = self.txt.index(f"@{event.x},{event.y}")
            for entry in self.anach_ranges:
                start, end, word, _ = entry
                if self.txt.compare(start, "<=", idx) and self.txt.compare(idx, "<", end):
                    self._tip_label.config(text=self._build_suggestion_text(word))
                    self._tip_label.place(
                        x=event.x_root - self.winfo_rootx() + 20,
                        y=event.y_root - self.winfo_rooty() + 10,
                    )
                    self._tip_label.lift()
                    self._tip_visible = True
                    self._hovered_range = entry
                    return
            if self._tip_visible:
                self._tip_label.place_forget()
                self._tip_visible = False
            self._hovered_range = None

        def on_leave(event):
            if self._tip_visible:
                self._tip_label.place_forget()
                self._tip_visible = False
            self._hovered_range = None

        self.txt.bind("<Motion>", on_motion)
        self.txt.bind("<Leave>",  on_leave)

    def _tab_insert_suggestion(self, event):
        """On Tab: replace the hovered or cursor-position word with its
        archaic suggestion. Hover takes priority so mouse workflow is natural."""
        if self._hovered_range:
            start, end, word, suggestions = self._hovered_range
        else:
            idx = self.txt.index(tk.INSERT)
            match = next(
                ((s, e, w, sg) for s, e, w, sg in self.anach_ranges
                 if self.txt.compare(s, "<=", idx) and self.txt.compare(idx, "<=", e)),
                None,
            )
            if not match:
                return None   # not on a highlight — allow normal Tab
            start, end, word, suggestions = match

        if not suggestions:
            return "break"

        replacement      = suggestions[0][0]
        matched          = self.txt.get(start, end)
        first_alpha_orig = next((c for c in matched      if c.isalpha()), None)
        first_alpha_idx  = next((i for i, c in enumerate(replacement) if c.isalpha()), None)
        if first_alpha_orig and first_alpha_orig.isupper() and first_alpha_idx is not None:
            replacement = (
                replacement[:first_alpha_idx]
                + replacement[first_alpha_idx].upper()
                + replacement[first_alpha_idx + 1:]
            )
        self.txt.delete(start, end)
        self.txt.insert(start, replacement)
        self.txt.tag_remove("anachronism", start, f"{start}+{len(replacement)}c")
        if self._tip_visible:
            self._tip_label.place_forget()
            self._tip_visible = False
        self._hovered_range = None
        self._update_counters()
        return "break"

    # ------------------------------------------------------------------
    # In-game preview
    # ------------------------------------------------------------------

    def _update_preview(self, e=None):
        box_key  = self._preview_box_var.get()
        meta     = self._box_meta.get(box_key)
        base_img = self._preview_base_images.get(box_key)
        fnt      = self._preview_font_objs.get(box_key)
        if not fnt or not _PIL_OK or not base_img:
            return

        # 1. Get text and strip tags
        vis_text = re.sub(r"<[^>]+>", "", self.txt.get(1.0, tk.END).strip("\n"))
        
        # 2. To STOP auto-wrapping, we treat the text as a simple list of lines.
        # It will now ONLY wrap if you physically press Enter in the text box.
        wrapped = vis_text.splitlines()

        img_w    = meta.get("img_w", self._prev_W)
        img_h    = meta.get("img_h", self._prev_H)
        self.preview_canvas.config(width=img_w, height=img_h)
        
        render   = base_img.copy()
        draw     = ImageDraw.Draw(render)
        
        pad      = meta["pad"]
        fg       = meta["fg"]
        text_x   = meta.get("text_x") if meta.get("text_x") is not None else pad + 15
        text_y   = meta.get("text_y") if meta.get("text_y") is not None else pad
        
        line_h = meta["line_h"]

        # 3. Draw the lines. 
        # Since we removed the 'for word in line.split()' loop, Python 
        # will no longer calculate widths or force text to the next line.
        for i, line in enumerate(wrapped[:6]):
            draw.text((text_x, text_y + i * line_h), line, font=fnt, fill=fg)

        if len(wrapped) > 6:
            draw.text(
                (text_x, text_y + 6 * line_h - 12),
                f"▼ +{len(wrapped) - 6} lines clipped",
                fill="#ff4444",
            )
            
        self._current_preview_tk = ImageTk.PhotoImage(render)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self._current_preview_tk)

    # --- Box meta initialisation from config ---

    def _init_box_meta(self):
        """Build _box_meta from config, with hardcoded defaults for dialogue/choice."""
        pf = self.cm.config.get("preview_font", {})
        _hardcoded = {
            "dialogue": {
                "crop": (3, 5, 478, 173), "pad": 20, "fg": "#2f2b2b",
                "font_sz": 18, "line_spacing": 1,
            },
            "choice": {
                "crop": (0, 0, 261, 187), "pad": 10, "fg": "#ffffff",
                "font_sz": 12, "line_spacing": 1,
            },
        }
        meta = {}
        all_keys = list(_hardcoded.keys()) + [k for k in pf if k not in _hardcoded]
        for key in all_keys:
            base = dict(_hardcoded.get(key, {
                "crop": (0, 0, 200, 60), "pad": 10,
                "fg": "#000000", "font_sz": 14, "line_spacing": 1,
            }))
            saved = pf.get(key, {})
            if "crop"         in saved: base["crop"]         = tuple(saved["crop"])
            if "font_sz"      in saved: base["font_sz"]      = saved["font_sz"]
            if "line_spacing" in saved: base["line_spacing"]  = saved["line_spacing"]
            if "text_x"       in saved: base["text_x"]       = saved["text_x"]
            if "text_y"       in saved: base["text_y"]       = saved["text_y"]
            if "fg"           in saved: base["fg"]           = saved["fg"]
            meta[key] = base
        return meta

    # --- Build the entire preview section (called from setup_ui) ---

    def _build_preview_controls(self, parent):
        """Build preview header rows + canvas + load box images.
        Must be called after self.cm is available."""
        import os as _os
        self._box_meta = self._init_box_meta()

        # ── Row 1: type selector, font, spacing, calibrate toggle ──
        prev_hdr = tk.Frame(parent, bg=self.colors["bg"])
        prev_hdr.pack(fill="x", pady=(5, 0))

        tk.Label(prev_hdr, text="In-Game Preview:", bg=self.colors["bg"],
                 fg=self.colors["label_fg"]).pack(side="left")

        self._preview_box_var = tk.StringVar(value="dialogue")
        self._preview_type_combo = ttk.Combobox(
            prev_hdr, textvariable=self._preview_box_var,
            values=list(self._box_meta.keys()), state="readonly", width=14)
        self._preview_type_combo.pack(side="left", padx=(4, 2))
        self._preview_type_combo.bind("<<ComboboxSelected>>", self._on_box_type_changed)

        tk.Button(prev_hdr, text="+", command=self._add_preview_box_type,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8, "bold"), relief="flat", padx=4).pack(side="left", padx=(0, 2))
        tk.Button(prev_hdr, text="−", command=self._remove_preview_box_type,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8, "bold"), relief="flat", padx=4).pack(side="left", padx=(0, 8))

        tk.Label(prev_hdr, text="Font:", bg=self.colors["bg"], fg=self.colors["label_fg"],
                 font=("Arial", 9)).pack(side="left")
        self._prev_font_sz_var = tk.StringVar()
        self._prev_font_sz_spin = tk.Spinbox(
            prev_hdr, from_=6, to=48, width=3,
            textvariable=self._prev_font_sz_var,
            command=self._on_preview_font_changed,
            bg=self.colors["text_bg"], fg=self.colors["fg"],
            relief="flat", font=("Arial", 9))
        self._prev_font_sz_spin.pack(side="left", padx=(2, 8))
        self._prev_font_sz_spin.bind("<Return>",   lambda e: self._on_preview_font_changed())
        self._prev_font_sz_spin.bind("<FocusOut>", lambda e: self._on_preview_font_changed())

        tk.Label(prev_hdr, text="Spacing:", bg=self.colors["bg"], fg=self.colors["label_fg"],
                 font=("Arial", 9)).pack(side="left")
        self._prev_spacing_var = tk.StringVar()
        self._prev_spacing_spin = tk.Spinbox(
            prev_hdr, from_=0, to=30, width=3,
            textvariable=self._prev_spacing_var,
            command=self._on_preview_font_changed,
            bg=self.colors["text_bg"], fg=self.colors["fg"],
            relief="flat", font=("Arial", 9))
        self._prev_spacing_spin.pack(side="left", padx=(2, 8))
        self._prev_spacing_spin.bind("<Return>",   lambda e: self._on_preview_font_changed())
        self._prev_spacing_spin.bind("<FocusOut>", lambda e: self._on_preview_font_changed())

        self._calib_btn = tk.Button(
            prev_hdr, text="⚙ Calibrate", command=self._toggle_preview_calib,
            bg=self.colors["btn_bg"], fg=self.colors["fg"],
            font=("Arial", 8), relief="flat", padx=6)
        self._calib_btn.pack(side="left")

        # ── Row 2: calibration controls (hidden by default) ──
        self._calib_frame = tk.Frame(parent, bg=self.colors["bg"])
        # not packed yet — toggle shows/hides it

        def _spin(parent, var, lo, hi, w=5):
            s = tk.Spinbox(parent, from_=lo, to=hi, width=w,
                           textvariable=var,
                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                           relief="flat", font=("Arial", 9))
            return s

        def _lbl(parent, text):
            return tk.Label(parent, text=text, bg=self.colors["bg"],
                            fg=self.colors["label_fg"], font=("Arial", 9))

        cf = self._calib_frame
        _lbl(cf, "Crop:").pack(side="left")
        self._crop_vars = [tk.StringVar() for _ in range(4)]
        for label, var in zip(("x1", "y1", "x2", "y2"), self._crop_vars):
            _lbl(cf, f" {label}").pack(side="left")
            s = _spin(cf, var, 0, 2000, w=4)
            s.pack(side="left", padx=(1, 0))
            s.bind("<Return>",   lambda e: self._on_preview_crop_changed())
            s.bind("<FocusOut>", lambda e: self._on_preview_crop_changed())

        tk.Button(cf, text="Apply", command=self._on_preview_crop_changed,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=5).pack(side="left", padx=(4, 12))

        tk.Frame(cf, bg=self.colors["label_fg"], width=1).pack(side="left", fill="y", pady=2, padx=4)

        _lbl(cf, "Text:").pack(side="left")
        self._text_x_var = tk.StringVar()
        self._text_y_var = tk.StringVar()
        for label, var in (("x", self._text_x_var), ("y", self._text_y_var)):
            _lbl(cf, f" {label}").pack(side="left")
            s = _spin(cf, var, -999, 2000, w=4)
            s.pack(side="left", padx=(1, 0))
            s.bind("<Return>",   lambda e: self._on_preview_text_origin_changed())
            s.bind("<FocusOut>", lambda e: self._on_preview_text_origin_changed())

        tk.Button(cf, text="Apply", command=self._on_preview_text_origin_changed,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=5).pack(side="left", padx=(4, 12))

        tk.Frame(cf, bg=self.colors["label_fg"], width=1).pack(side="left", fill="y", pady=2, padx=4)

        _lbl(cf, " Color:").pack(side="left")
        self._text_fg_var = tk.StringVar()
        fg_entry = tk.Entry(cf, textvariable=self._text_fg_var, width=8,
                            font=("Consolas", 9),
                            bg=self.colors["text_bg"], fg=self.colors["fg"],
                            relief="flat", insertbackground=self.colors["fg"])
        fg_entry.pack(side="left", padx=(2, 4))
        fg_entry.bind("<Return>",   lambda e: self._on_preview_text_origin_changed())
        fg_entry.bind("<FocusOut>", lambda e: self._on_preview_text_origin_changed())

        tk.Button(cf, text="Apply", command=self._on_preview_text_origin_changed,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=5).pack(side="left", padx=(0, 4))

        # Canvas placeholder (sized to dialogue defaults; resized on first _update_preview)
        _DLG_W = 480 - 27
        _DLG_H = 333 - 171
        self._prev_W = _DLG_W
        self._prev_H = _DLG_H
        self.preview_canvas = tk.Canvas(parent, width=_DLG_W, height=_DLG_H,
                                        bg=self.colors["bg"], highlightthickness=0)
        self.preview_canvas.pack(anchor="w", pady=2)

        # Image/font caches
        self._preview_images      = {}
        self._preview_base_images = {}
        self._preview_font_objs   = {}

        # Load all box images and fonts
        for key in list(self._box_meta.keys()):
            self._reload_box_image(key)

        self._sync_preview_font_controls()

    # --- Image loading / reloading ---

    def _reload_box_image(self, box_key):
        """Crop source PNG (or build procedural fallback) for box_key using current meta."""
        import os as _os
        if not _PIL_OK:
            return
        meta = self._box_meta.get(box_key)
        if meta is None:
            return

        # Font
        _asset_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "assets")
        _font_path = next((p for p in [
            _os.path.join(_asset_dir, "DDONfont.otf"),
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "DDONfont.otf"),
        ] if _os.path.exists(p)), None)
        fnt = None
        if _font_path:
            try:
                fnt = ImageFont.truetype(_font_path, meta["font_sz"])
                self._preview_font_objs[box_key] = fnt
            except Exception:
                pass
        if fnt:
            bbox = fnt.getbbox("あ")
            meta["line_h"] = (bbox[3] - bbox[1]) + meta.get("line_spacing", 1)
        else:
            meta["line_h"] = meta["font_sz"] + 3

        # Crop image
        crop = meta["crop"]
        box_w, box_h = crop[2] - crop[0], crop[3] - crop[1]
        if box_w <= 0 or box_h <= 0:
            return

        _box_style = {
            "dialogue": {"bg": (242, 238, 220), "border": (180, 160, 100)},
            "choice":   {"bg": (30, 25, 45),    "border": (120, 100, 200)},
        }
        # Try PNG name derived from key first, then "dialogue_box.png" as fallback
        src_candidates = [
            _os.path.join(_asset_dir, f"{box_key}_box.png"),
            _os.path.join(_asset_dir, "dialogue_box.png"),
        ]
        final_base = None
        for png_path in src_candidates:
            if not _os.path.exists(png_path):
                continue
            try:
                raw = Image.open(png_path).convert("RGBA")
                cropped = raw.crop(meta["crop"])
                rgb_vals = self.winfo_rgb(self.colors["bg"])
                bg_rgb = tuple(c >> 8 for c in rgb_vals) + (255,)
                bg_layer = Image.new("RGBA", cropped.size, bg_rgb)
                bg_layer.paste(cropped, mask=cropped.split()[3])
                final_base = bg_layer.convert("RGB")
                break
            except Exception:
                pass

        if final_base is None:
            style = _box_style.get(box_key, {"bg": (200, 200, 200), "border": (100, 100, 100)})
            final_base = Image.new("RGB", (box_w, box_h), style["bg"])
            d = ImageDraw.Draw(final_base)
            d.rectangle([0, 0, box_w-1, box_h-1], outline=style["border"], width=2)
            d.rectangle([3, 3, box_w-4,  box_h-4], outline=style["border"], width=1)

        self._preview_base_images[box_key] = final_base
        self._preview_images[box_key]      = ImageTk.PhotoImage(final_base)
        meta["img_w"] = final_base.width
        meta["img_h"] = final_base.height

    # --- Font / spacing controls ---

    def _sync_preview_font_controls(self):
        """Sync all calibration spinboxes to the currently selected box."""
        if not hasattr(self, "_prev_font_sz_var"):
            return
        box_key = self._preview_box_var.get()
        meta    = self._box_meta.get(box_key, {})
        self._prev_font_sz_var.set(str(meta.get("font_sz", 12)))
        self._prev_spacing_var.set(str(meta.get("line_spacing", 1)))
        # Calibration spinboxes (may not exist yet during init)
        if hasattr(self, "_crop_vars"):
            crop = meta.get("crop", (0, 0, 100, 50))
            for var, val in zip(self._crop_vars, crop):
                var.set(str(int(val)))
            pad = meta.get("pad", 10)
            self._text_x_var.set(str(meta.get("text_x") if meta.get("text_x") is not None else pad + 15))
            self._text_y_var.set(str(meta.get("text_y") if meta.get("text_y") is not None else pad))
            self._text_fg_var.set(meta.get("fg", "#000000"))

    def _on_preview_font_changed(self, *args):
        """Apply font size and spacing changes for the current box."""
        box_key = self._preview_box_var.get()
        meta    = self._box_meta.get(box_key)
        if meta is None:
            return
        try:
            new_sz = max(6,  min(48, int(self._prev_font_sz_var.get())))
            new_sp = max(0, min(30, int(self._prev_spacing_var.get())))
        except (ValueError, tk.TclError):
            return
        meta["font_sz"]      = new_sz
        meta["line_spacing"] = new_sp
        self._rebuild_preview_font(box_key)
        self._save_preview_config(box_key)
        self._update_preview()

    def _rebuild_preview_font(self, box_key):
        """Recreate PIL font object for box_key and recompute line_h."""
        import os as _os
        if not _PIL_OK:
            return
        meta = self._box_meta.get(box_key)
        if meta is None:
            return
        _asset_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "assets")
        _font_path = next((p for p in [
            _os.path.join(_asset_dir, "DDONfont.otf"),
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "DDONfont.otf"),
        ] if _os.path.exists(p)), None)
        fnt = None
        if _font_path:
            try:
                fnt = ImageFont.truetype(_font_path, meta["font_sz"])
            except Exception:
                pass
        if fnt:
            self._preview_font_objs[box_key] = fnt
            bbox = fnt.getbbox("あ")
            meta["line_h"] = (bbox[3] - bbox[1]) + meta.get("line_spacing", 1)
        else:
            meta["line_h"] = meta["font_sz"] + 3

    # --- Calibration controls ---

    def _toggle_preview_calib(self):
        if self._calib_frame.winfo_ismapped():
            self._calib_frame.pack_forget()
            self._calib_btn.config(text="⚙ Calibrate")
        else:
            # Insert immediately after the canvas's parent frame (prev_hdr)
            self._calib_frame.pack(fill="x", pady=(1, 0),
                                   before=self.preview_canvas)
            self._calib_btn.config(text="⚙ Hide")
            self._sync_preview_font_controls()

    def _on_box_type_changed(self, e=None):
        self._sync_preview_font_controls()
        self._update_preview()

    def _on_preview_crop_changed(self):
        box_key = self._preview_box_var.get()
        meta    = self._box_meta.get(box_key)
        if meta is None:
            return
        try:
            vals = tuple(max(0, int(v.get())) for v in self._crop_vars)
        except (ValueError, tk.TclError):
            return
        if vals[2] <= vals[0] or vals[3] <= vals[1]:
            return   # degenerate crop — ignore
        meta["crop"] = vals
        self._reload_box_image(box_key)
        self._save_preview_config(box_key)
        self._update_preview()

    def _on_preview_text_origin_changed(self):
        box_key = self._preview_box_var.get()
        meta    = self._box_meta.get(box_key)
        if meta is None:
            return
        try:
            meta["text_x"] = int(self._text_x_var.get())
            meta["text_y"] = int(self._text_y_var.get())
        except (ValueError, tk.TclError):
            return
        new_fg = self._text_fg_var.get().strip()
        if new_fg:
            try:
                self.winfo_rgb(new_fg)   # validate colour string
                meta["fg"] = new_fg
            except tk.TclError:
                pass
        self._save_preview_config(box_key)
        self._update_preview()

    def _save_preview_config(self, box_key):
        """Persist current meta values for box_key to config."""
        meta = self._box_meta.get(box_key, {})
        pf   = self.cm.config.setdefault("preview_font", {})
        pf.setdefault(box_key, {}).update({
            "font_sz":      meta.get("font_sz",      12),
            "line_spacing": meta.get("line_spacing",  1),
            "crop":         list(meta.get("crop",     (0, 0, 100, 50))),
            "text_x":       meta.get("text_x"),
            "text_y":       meta.get("text_y"),
            "fg":           meta.get("fg",            "#000000"),
        })
        self.cm.save_all()

    def _add_preview_box_type(self):
        # 1. Ask for the name of the new entry type
        name = tk_simpledialog.askstring("Add Preview Type",
                                         "Enter a name for the new box type\n"
                                         "(e.g. 'notice', 'tooltip'):",
                                         parent=self)
        if not name:
            return
        
        name = name.strip().lower().replace(" ", "_")
        if name in self._box_meta:
            messagebox.showwarning("Duplicate", f"Box type '{name}' already exists.", parent=self)
            return

        # 2. Ask the user to select the source image from their computer
        file_path = filedialog.askopenfilename(
            title=f"Select PNG image for '{name}'",
            filetypes=[("PNG images", "*.png")],
            parent=self
        )
        if not file_path:
            return

        # 3. Define the destination in the project assets folder
        asset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        os.makedirs(asset_dir, exist_ok=True)
        dest_path = os.path.join(asset_dir, f"{name}_box.png")

        try:
            # 4. Copy and rename the file so the editor can find it later
            shutil.copy2(file_path, dest_path)

            # 5. Clone current box settings as a starting point
            current = dict(self._box_meta.get(self._preview_box_var.get(), {
                "crop": (0, 0, 200, 60), "pad": 10, "fg": "#000000", "font_sz": 14, "line_spacing": 1
            }))
            current.pop("img_w", None)
            current.pop("img_h", None)
            current.pop("line_h", None)
            self._box_meta[name] = current
            
            # 6. Refresh UI components
            self._preview_type_combo.config(values=list(self._box_meta.keys()))
            self._preview_box_var.set(name)
            
            # 7. Process the new image immediately
            self._reload_box_image(name)
            self._sync_preview_font_controls()
            self._save_preview_config(name)
            
            messagebox.showinfo("Success", f"Added '{name}' and saved image to assets.", parent=self)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to add new type: {e}", parent=self)

    def _remove_preview_box_type(self):
        box_key = self._preview_box_var.get()
        if box_key in ("dialogue", "choice"):
            messagebox.showwarning("Cannot Remove",
                                   "The built-in 'dialogue' and 'choice' types cannot be removed.",
                                   parent=self)
            return
        if not messagebox.askyesno("Remove", f"Remove box type '{box_key}'?", parent=self):
            return
        self._box_meta.pop(box_key, None)
        self.cm.config.get("preview_font", {}).pop(box_key, None)
        self.cm.save_all()
        remaining = list(self._box_meta.keys())
        self._preview_type_combo.config(values=remaining)
        self._preview_box_var.set(remaining[0] if remaining else "dialogue")
        self._sync_preview_font_controls()
        self._update_preview()

    # ------------------------------------------------------------------
    # DeepL
    # ------------------------------------------------------------------

    def translate_with_deepl(self):
        source_text = self.jp_txt.get(1.0, tk.END).strip()
        if not source_text or self._is_translating:
            return

        cached = self.cm.get_cached("deepl", source_text)
        if cached:
            self.deepl_box.config(state="normal")
            self.deepl_box.delete(1.0, tk.END)
            self.deepl_box.insert(tk.END, cached)
            self.deepl_box.config(state="disabled")
            return

        key = self.cm.get_key("deepl_api_key")
        if not key:
            return   # silently skip — user can set key in Options

        self._is_translating = True
        self.deepl_box.config(state="normal")
        self.deepl_box.delete(1.0, tk.END)
        self.deepl_box.insert(tk.END, "Translating...")
        self.deepl_box.config(state="disabled")

        def worker():
            from api_handler import DeepLClient
            client      = DeepLClient(key)
            target_lang = self.cm.config.get("deepl_target_lang", "EN-US")
            res         = client.translate(source_text, target_lang=target_lang)

            def finalize():
                self.deepl_box.config(state="normal")
                self.deepl_box.delete(1.0, tk.END)
                if "text" in res:
                    self.deepl_box.insert(tk.END, res["text"])
                    self.cm.set_cached("deepl", source_text, res["text"])
                else:
                    self.deepl_box.insert(tk.END, f"ERROR: {res.get('error')}")
                self.deepl_box.config(state="disabled")
                self._is_translating = False

            self.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def click_deepl_suggestion(self, event=None):
        """Paste the DeepL suggestion into the main editor."""
        suggestion = self.deepl_box.get(1.0, tk.END).strip()
        if suggestion and suggestion != "Translating..." and not suggestion.startswith("ERROR"):
            current = self.txt.get(1.0, tk.END).strip()
            if current and not messagebox.askyesno(
                "Overwrite", "Overwrite current English text with DeepL suggestion?", parent=self
            ):
                return
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, suggestion)
            self._update_counters()
            self._update_preview()

    # ------------------------------------------------------------------
    # AI chat
    # ------------------------------------------------------------------

    def _save_selected_model(self, e=None):
        model = self.chat_model_var.get()
        self.cm.config["selected_openrouter_model"] = model
        self.cm.save_all()

    def clear_chat(self):
        self.chat_history.config(state="normal")
        self.chat_history.delete(1.0, tk.END)
        self.chat_history.config(state="disabled")

    def add_chat_context(self):
        jp = self.jp_txt.get(1.0, tk.END).strip()
        en = self.txt.get(1.0, tk.END).strip()
        self.chat_input.insert(tk.END, f"\n[Context]\nJP: {jp}\nEN: {en}\n")
        self.chat_input.see(tk.END)

    def _chat_on_return(self, e):
        if not e.state & 0x1:   # Shift not held
            self.send_ai_chat()
            return "break"

    def refresh_model_list(self):
        """Reload the model list from config (updated in Options)."""
        models  = self.cm.config.get("openrouter_models", ["openrouter/auto"])
        self.chat_model_combo.config(values=models)
        current = self.chat_model_var.get()
        if current not in models:
            self.chat_model_var.set("openrouter/auto")
        messagebox.showinfo("AI Assistant", "Model list reloaded from configuration.")

    def send_ai_chat(self):
        if self._is_chatting:
            return
        key = self.cm.get_key("openrouter_api_key")
        if not key:
            messagebox.showwarning("OpenRouter", "No OpenRouter API key found in Options.")
            return

        user_msg = self.chat_input.get(1.0, tk.END).strip()
        if not user_msg:
            return

        model     = self.chat_model_var.get()
        cache_key = f"{model}::{user_msg}"
        cached    = self.cm.get_cached("openrouter", cache_key)
        if cached:
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
            self.chat_history.tag_config("user", foreground=self.colors["counter_fg"],
                                         font=("Arial", 9, "bold"))
            self.chat_history.insert(tk.END, f"\nAI: {cached}\n", "ai")
            self.chat_history.tag_config("ai", foreground=self.colors["fg"])
            self.chat_history.see(tk.END)
            self.chat_history.config(state="disabled")
            self.chat_input.delete(1.0, tk.END)
            return

        self._is_chatting = True
        self.btn_chat_send.config(state="disabled", text="...")
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
        self.chat_history.tag_config("user", foreground=self.colors["counter_fg"],
                                     font=("Arial", 9, "bold"))
        self.chat_history.insert(tk.END, "\n⏳ Generating…\n", "generating")
        self.chat_history.tag_config("generating", foreground=self.colors["label_fg"],
                                     font=("Arial", 9, "italic"))
        self.chat_history.see(tk.END)
        self.chat_history.config(state="disabled")
        self.chat_input.delete(1.0, tk.END)

        def worker():
            try:
                from api_handler import OpenRouterClient
                client = OpenRouterClient(key)
                
                # 1. Grab the current Japanese source text from the editor
                current_jp = getattr(self, 'jp_source', "")
                
                # 2. Base System Prompt
                sys_prompt = (
                    "You are a DDON localization assistant. Help the user translate or "
                    "refine dialogue while respecting the game's medieval fantasy tone "
                    "and character archetypes."
                )
                
                # 3. Scan the Japanese text using your existing engine and inject terms
                if current_jp and hasattr(self, 'lore_engine'):
                    # scan_text returns a list of tuples: [("剛化", "Harden"), ...]
                    relevant_terms = self.lore_engine.scan_text(current_jp)
                    print(f"DEBUG: Found terms for AI: {relevant_terms}")
                    
                    if relevant_terms:
                        sys_prompt += "\n\nMANDATORY GLOSSARY TERMS FOR THIS LINE:\n"
                        for jp, en in relevant_terms:
                            sys_prompt += f"- {jp} MUST be translated as '{en}'\n"

                messages = [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_msg},
                ]
                
                res = client.chat(messages, model=model)
            except Exception as e:
                print(f"DEBUG THREAD CRASH: {e}")
                
            def finalize():
                self.chat_history.config(state="normal")
                # Remove the ⏳ Generating… placeholder
                ranges = self.chat_history.tag_ranges("generating")
                if ranges:
                    self.chat_history.delete(ranges[0], ranges[-1])
                if "text" in res:
                    self.chat_history.insert(tk.END, f"\nAI: {res['text']}\n", "ai")
                    self.chat_history.tag_config("ai", foreground=self.colors["fg"])
                    self.cm.set_cached("openrouter", cache_key, res["text"])
                else:
                    self.chat_history.insert(tk.END, f"\nERROR: {res.get('error')}\n", "error")
                    self.chat_history.tag_config("error", foreground="#ff4444")
                self.chat_history.see(tk.END)
                self.chat_history.config(state="disabled")
                self._is_chatting = False
                self.btn_chat_send.config(state="normal", text="Send")

            self.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Chat extras: right-click edit/resend + quick prompts
    # ------------------------------------------------------------------

    def _bind_chat_extras(self):
        """Attach a right-click context menu to chat_history.
        Called from setup_ui after chat_history is created."""
        ctx_menu = tk.Menu(self.chat_history, tearoff=0)
        ctx_menu.add_command(label="Copy selection to input",
                             command=self._chat_copy_to_input)
        ctx_menu.add_command(label="Resend last user message",
                             command=self._chat_resend_last)

        def _show_ctx(e):
            try:
                ctx_menu.tk_popup(e.x_root, e.y_root)
            finally:
                ctx_menu.grab_release()

        self.chat_history.bind("<Button-3>", _show_ctx)

    def _quick_prompt(self, template):
        """Fill chat_input with a pre-built prompt substituting {jp} and {en}."""
        jp = self.jp_txt.get(1.0, tk.END).strip()
        en = self.txt.get(1.0, tk.END).strip()
        msg = template.format(jp=jp, en=en)
        self.chat_input.delete(1.0, tk.END)
        self.chat_input.insert(tk.END, msg)
        self.chat_input.focus_set()

    def _chat_copy_to_input(self):
        """Copy the selected chat_history text into chat_input for editing/resending."""
        try:
            sel = self.chat_history.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
            for prefix in ("YOU: ", "AI: "):
                if sel.startswith(prefix):
                    sel = sel[len(prefix):]
                    break
            if sel:
                self.chat_input.delete(1.0, tk.END)
                self.chat_input.insert(tk.END, sel)
                self.chat_input.focus_set()
        except tk.TclError:
            pass  # nothing selected

    def _chat_resend_last(self):
        """Pull the most recent YOU: message back into chat_input for editing/resending."""
        content = self.chat_history.get("1.0", tk.END)
        idx = content.rfind("\nYOU: ")
        if idx == -1:
            return
        msg = content[idx + 6:].strip()
        # Truncate at the next message boundary so we don't grab multiple turns
        for marker in ("\nYOU: ", "\nAI: ", "\n⏳"):
            m = msg.find(marker)
            if m != -1:
                msg = msg[:m].strip()
        if msg:
            self.chat_input.delete(1.0, tk.END)
            self.chat_input.insert(tk.END, msg)
            self.chat_input.focus_set()
