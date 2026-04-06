import sys
sys.dont_write_bytecode = True

import csv
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from translator_engine import TranslationEngine
from lore_engine import LoreEngine
from file_utils import _read_csv
from editor_mixin import SharedEditorMixin


class CSVTranslationWindow(SharedEditorMixin, tk.Toplevel):
    """Open a single CSV and step through its rows for translation."""

    def __init__(self, parent_app):
        path = filedialog.askopenfilename(
            title="Open CSV for Translation",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        super().__init__(parent_app.root)
        self.parent_app = parent_app
        self.cm = parent_app.cm
        self.csv_path = path
        self.title(f"Translate — {os.path.basename(path)}")
        self.geometry("1200x820")

        self.dark_mode = self.cm.config.get("dark_mode", False)
        self._apply_colors()

        self.engine = TranslationEngine(self.cm.config.get("tag_map", {}))
        self.lore_engine = LoreEngine(self.cm.config.get("archetypes"))
        self.lore_engine.load_data(
            self.cm.config.get("bible_path", ""),
            self.cm.config.get("glossary_path", ""))

        self.raw, self.dialect, self.all_rows = _read_csv(path)
        # data_rows: (original_index, row) skipping header (row 0) and rows without JP
        self.data_rows = [(i, r) for i, r in enumerate(self.all_rows)
                          if i > 0 and len(r) > 2 and r[2].strip()]

        self.show_translated_var = tk.BooleanVar(value=False)
        self.current_list_idx = 0
        self._current_row_idx = -1

        self.jp_source = ""
        self.speaker_name = ""
        self.entry_type = ""
        self.entry_type_var = tk.StringVar()

        presets = self.cm.config.get("presets", {"Standard": 50})
        self.limit = list(presets.values())[0]
        wall_presets = self.cm.config.get("wall_presets", {"Standard": 7})
        self.wall_limit = list(wall_presets.values())[0]
        self.effective_limit = self.limit

        self._tip_label = tk.Label(self)
        self._tip_visible = False
        self._hovered_range = None
        self.anach_ranges = []
        self.in_universe_var = tk.BooleanVar(value=self.cm.config.get("in_universe", False))

        # Busy flags for API
        self._is_translating = False
        self._is_chatting = False

        self._setup_ui()
        self._populate_list()
        self._load_by_list_idx(0)
        self._bind_tooltip()
        self.txt.bind("<Tab>",          self._tab_insert_suggestion)
        self.bind("<Control-Return>",   lambda e: self._save_item())
        self.bind("<Control-Right>",    lambda e: self._next_item())
        self.bind("<Control-r>",        lambda e: self._rewrap())
        self.bind("<Control-d>",        lambda e: self._replace_dashes("—"))
        self.bind("<Control-D>",        lambda e: self._replace_dashes("..."))

    # ── colours ──────────────────────────────────────────────────────────
    def _apply_colors(self):
        if self.dark_mode:
            self.colors = {
                "bg": "#1a1a2e", "fg": "#e0e0e0", "text_bg": "#16213e",
                "jp_bg": "#0f1923", "sidebar_bg": "#1e1e35", "btn_bg": "#0f3460",
                "label_fg": "#8888aa", "counter_fg": "#4ec9b0",
                "insert_color": "#ffffff", "accent": "#e94560", "apply_bg": "#03dac6",
                "translated_bg": "#0d1f0d", "translated_fg": "#558855",
                "untranslated_bg": "#16213e", "untranslated_fg": "#e0e0e0",
                "active_bg": "#e94560", "active_fg": "#ffffff",
            }
        else:
            self.colors = {
                "bg": "#f5f6fa", "fg": "#2c2c3e", "text_bg": "#ffffff",
                "jp_bg": "#f0f4f8", "sidebar_bg": "#eef0f7", "btn_bg": "#dfe4ea",
                "label_fg": "#7f8c8d", "counter_fg": "#2980b9",
                "insert_color": "#000000", "accent": "#3867d6", "apply_bg": "#20bf6b",
                "translated_bg": "#f0fff0", "translated_fg": "#2d7a2d",
                "untranslated_bg": "#ffffff", "untranslated_fg": "#2c2c3e",
                "active_bg": "#3867d6", "active_fg": "#ffffff",
            }

    # ── helpers ───────────────────────────────────────────────────────────
    def _is_translated(self, row):
        en = row[3].strip() if len(row) > 3 else ""
        jp = row[2].strip() if len(row) > 2 else ""
        return bool(en) and en != jp

    def _visible_rows(self):
        if self.show_translated_var.get():
            return self.data_rows
        return [(i, r) for i, r in self.data_rows if not self._is_translated(r)]

    # ── UI build ──────────────────────────────────────────────────────────
    def _setup_ui(self):
        self.configure(bg=self.colors["bg"])

        # Title bar
        title_bar = tk.Frame(self, bg=self.colors["accent"], pady=6)
        title_bar.pack(fill="x")
        tk.Label(title_bar, text=f"Translating: {os.path.basename(self.csv_path)}",
                 bg=self.colors["accent"], fg="white",
                 font=("Arial", 11, "bold")).pack(side="left", padx=12)
        self.count_lbl = tk.Label(title_bar, text="",
                                   bg=self.colors["accent"], fg="white", font=("Arial", 9))
        self.count_lbl.pack(side="left", padx=8)
        tk.Checkbutton(title_bar, text="In-Universe Language", variable=self.in_universe_var,
                       bg=self.colors["accent"], fg="white", selectcolor=self.colors["accent"],
                       activebackground=self.colors["accent"],
                       command=self._update_counters).pack(side="right", padx=10)

        # Body: left list + right editor + right-side sidebar
        body = tk.Frame(self, bg=self.colors["bg"])
        body.pack(fill="both", expand=True)

        # ── Sidebar ──
        side = tk.Frame(body, bg=self.colors["sidebar_bg"], width=320)
        side.pack(side="right", fill="both")
        side.pack_propagate(False)

        # Toggle bar at the top
        side_ctrl = tk.Frame(side, bg=self.colors["sidebar_bg"], pady=2)
        side_ctrl.pack(fill="x")
        
        tk.Button(side_ctrl, text="Context", command=lambda: self.toggle_pane("ctx"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], font=("Arial", 8, "bold"),
                  relief="flat", padx=10).pack(side="left", padx=5)
        
        tk.Button(side_ctrl, text="AI Assistant", command=lambda: self.toggle_pane("ai"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], font=("Arial", 8, "bold"),
                  relief="flat", padx=10).pack(side="left")

        self.side_pane = tk.PanedWindow(side, orient="vertical", bg=self.colors["sidebar_bg"],
                                         sashwidth=4, bd=0)
        self.side_pane.pack(fill="both", expand=True)

        # --- Pane 1: Context ---
        self.pane_ctx = tk.Frame(self.side_pane, bg=self.colors["sidebar_bg"])
        self.side_pane.add(self.pane_ctx, height=250)

        tk.Label(self.pane_ctx, text="Adjacent Context", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        
        self.adj_prev_txt = tk.Text(self.pane_ctx, height=4, font=("Consolas", 9),
                                    bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                    state="disabled", bd=0, padx=6, pady=4, relief="flat", wrap="word")
        self.adj_prev_txt.pack(fill="x")
        
        tk.Frame(self.pane_ctx, bg=self.colors["label_fg"], height=1).pack(fill="x", pady=4)
        
        self.adj_next_txt = tk.Text(self.pane_ctx, height=4, font=("Consolas", 9),
                                    bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                    state="disabled", bd=0, padx=6, pady=4, relief="flat", wrap="word")
        self.adj_next_txt.pack(fill="x")

        # --- Pane 2: AI Assistant ---
        self.pane_ai = tk.Frame(self.side_pane, bg=self.colors["sidebar_bg"])
        self.side_pane.add(self.pane_ai)

        ai_hdr = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        ai_hdr.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(ai_hdr, text="AI Assistant", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(side="left")

        chat_ctrl = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        chat_ctrl.pack(fill="x", padx=5, pady=5)
        
        self.chat_model_var = tk.StringVar(value=self.cm.config.get("selected_openrouter_model", "openrouter/auto"))
        models = self.cm.config.get("openrouter_models", ["openrouter/auto"])
        self.chat_model_combo = ttk.Combobox(chat_ctrl, textvariable=self.chat_model_var, values=models, state="readonly", width=18)
        self.chat_model_combo.pack(side="left", fill="x", expand=True)
        self.chat_model_combo.bind("<<ComboboxSelected>>", self._save_selected_model)
        
        tk.Button(chat_ctrl, text="↻", command=self.refresh_model_list,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=4).pack(side="right", padx=(4, 0))

        self.chat_history = tk.Text(self.pane_ai, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                    bd=0, highlightthickness=0, font=("Arial", 9),
                                    wrap="word", state="disabled", padx=6, pady=4)
        self.chat_history.pack(fill="both", expand=True)

        chat_input_f = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        chat_input_f.pack(fill="x", padx=5, pady=5)

        self.chat_input = tk.Text(chat_input_f, height=3, font=("Arial", 9),
                                  bg=self.colors["text_bg"], fg=self.colors["fg"],
                                  insertbackground=self.colors["fg"], undo=True)
        self.chat_input.pack(fill="x", pady=(0, 5))
        self.chat_input.bind("<Return>", self._chat_on_return)

        chat_btns = tk.Frame(chat_input_f, bg=self.colors["sidebar_bg"])
        chat_btns.pack(fill="x")
        
        self.btn_chat_send = tk.Button(chat_btns, text="Send", command=self.send_ai_chat,
                                       bg=self.colors["accent"], fg="white", relief="flat")
        self.btn_chat_send.pack(side="right")
        
        tk.Button(chat_btns, text="+ Context", command=self.add_chat_context,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], relief="flat").pack(side="left")
        
        tk.Button(chat_btns, text="Clear", command=self.clear_chat,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], relief="flat").pack(side="left", padx=5)

        # ── Left: row list ──
        list_frame = tk.Frame(body, bg=self.colors["sidebar_bg"], width=300)
        list_frame.pack(side="left", fill="y")
        list_frame.pack_propagate(False)

        list_hdr = tk.Frame(list_frame, bg=self.colors["sidebar_bg"])
        list_hdr.pack(fill="x", padx=6, pady=4)
        tk.Checkbutton(list_hdr, text="Show translated", variable=self.show_translated_var,
                       bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                       selectcolor=self.colors["sidebar_bg"],
                       activebackground=self.colors["sidebar_bg"],
                       command=self._on_filter_changed).pack(side="left")

        list_scroll = tk.Scrollbar(list_frame, orient="vertical")
        list_scroll.pack(side="right", fill="y")
        self.row_listbox = tk.Listbox(
            list_frame, yscrollcommand=list_scroll.set,
            bg=self.colors["untranslated_bg"], fg=self.colors["untranslated_fg"],
            selectbackground=self.colors["active_bg"],
            selectforeground=self.colors["active_fg"],
            font=("Consolas", 9), bd=0, highlightthickness=0, activestyle="none")
        self.row_listbox.pack(fill="both", expand=True)
        list_scroll.config(command=self.row_listbox.yview)
        self.row_listbox.bind("<<ListboxSelect>>", self._on_list_select)

        # ── Right: editor ──
        right = tk.Frame(body, bg=self.colors["bg"])
        right.pack(side="left", fill="both", expand=True, padx=8, pady=4)

        # Speaker bar
        spk_frame = tk.Frame(right, bg=self.colors["bg"])
        spk_frame.pack(fill="x", pady=(2, 0))
        tk.Label(spk_frame, text="Speaker:", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        self.speaker_lbl = tk.Label(spk_frame, text="—",
                                    fg=self.colors["counter_fg"], bg=self.colors["bg"],
                                    font=("Arial", 9, "bold"))
        self.speaker_lbl.pack(side="left", padx=(4, 14))
        tk.Label(spk_frame, text="Archetype:", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        arch_opts = self.lore_engine.get_archetype_options()
        arch_labels = ["(none)"] + [o[1] for o in arch_opts]
        self.archetype_keys = [None] + [o[0] for o in arch_opts]
        self.archetype_var = tk.StringVar(value="(none)")
        self.archetype_combo = ttk.Combobox(spk_frame, textvariable=self.archetype_var,
                                            values=arch_labels, state="disabled", width=26)
        self.archetype_combo.pack(side="left", padx=(4, 6))
        tk.Button(spk_frame, text="Save", command=self._save_archetype,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=6).pack(side="left")

        # Entry type row
        et_frame = tk.Frame(right, bg=self.colors["bg"])
        et_frame.pack(fill="x", pady=(2, 0))
        tk.Label(et_frame, text="Entry Type:", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        known_types = [""] + sorted(self.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_combo = ttk.Combobox(et_frame, textvariable=self.entry_type_var,
                                             values=known_types, width=30)
        self.entry_type_combo.pack(side="left", padx=(4, 6))
        for ev in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
            self.entry_type_combo.bind(ev, self._on_entry_type_changed)
        self.entry_type_badge = tk.Label(et_frame, text="", fg="white", bg="#2980b9",
                                         font=("Arial", 8, "bold"), padx=5, pady=1)
        self.entry_type_badge.pack(side="left", padx=(2, 4))
        self.et_rules_lbl = tk.Label(et_frame, text="", fg=self.colors["label_fg"],
                                     bg=self.colors["bg"], font=("Arial", 8, "italic"))
        self.et_rules_lbl.pack(side="left", padx=(6, 0))

        # EN editor
        tk.Label(right, text="English", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w", pady=(4, 0))
        en_outer = tk.Frame(right, bg=self.colors["bg"])
        en_outer.pack(fill="x")
        self._txt_yscroll_wid = tk.Scrollbar(en_outer, orient="vertical")
        self._txt_yscroll_wid.pack(side="right", fill="y")
        self.cnt_lbl = tk.Text(en_outer, font=("Consolas", 12), width=4, height=6,
                               bg=self.colors["bg"], fg=self.colors["counter_fg"],
                               state="disabled", bd=0, highlightthickness=0, padx=0, pady=4)
        self.cnt_lbl.pack(side="right", fill="y", padx=(2, 0))
        en_inner = tk.Frame(en_outer, bg=self.colors["bg"])
        en_inner.pack(side="left", fill="x")
        txt_xscroll = tk.Scrollbar(en_inner, orient="horizontal")
        txt_xscroll.pack(side="bottom", fill="x")
        self.txt = tk.Text(en_inner, height=6, font=("Consolas", 12),
                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                           insertbackground=self.colors["insert_color"],
                           bd=0, padx=6, pady=4, wrap="none",
                           relief="flat", selectbackground=self.colors["accent"],
                           selectforeground="white", undo=True,
                           yscrollcommand=self._sync_txt_scroll,
                           xscrollcommand=txt_xscroll.set)
        self.txt.pack(fill="x")
        txt_xscroll.config(command=self.txt.xview)
        self._txt_yscroll_wid.config(command=self.txt.yview)
        self.txt.bind("<KeyRelease>",
                      lambda e: [self._update_counters(), self._update_preview()])
        self.txt.bind("<<Paste>>",
                      lambda e: self.after(0, lambda: [self._update_counters(), self._update_preview()]))

        # Preview
        prev_hdr = tk.Frame(right, bg=self.colors["bg"])
        prev_hdr.pack(fill="x", pady=(4, 0))
        tk.Label(prev_hdr, text="In-Game Preview:", bg=self.colors["bg"],
                 fg=self.colors["label_fg"]).pack(side="left")
        self._preview_box_var = tk.StringVar(value="dialogue")
        for val, lbl in (("dialogue", "Dialogue"), ("choice", "Choice")):
            tk.Radiobutton(prev_hdr, text=lbl, value=val, variable=self._preview_box_var,
                           bg=self.colors["bg"], fg=self.colors["fg"],
                           selectcolor=self.colors["bg"], activebackground=self.colors["bg"],
                           font=("Arial", 9),
                           command=self._update_preview).pack(side="left", padx=4)
        tk.Label(prev_hdr, text="  Font:", bg=self.colors["bg"],
                 fg=self.colors["label_fg"], font=("Arial", 9)).pack(side="left")
        self._prev_font_sz_var = tk.StringVar()
        tk.Spinbox(prev_hdr, from_=6, to=48, width=3, textvariable=self._prev_font_sz_var,
                   bg=self.colors["text_bg"], fg=self.colors["fg"],
                   relief="flat", font=("Arial", 9)).pack(side="left", padx=(2, 8))
        tk.Label(prev_hdr, text="Spacing:", bg=self.colors["bg"],
                 fg=self.colors["label_fg"], font=("Arial", 9)).pack(side="left")
        self._prev_spacing_var = tk.StringVar()
        tk.Spinbox(prev_hdr, from_=0, to=30, width=3, textvariable=self._prev_spacing_var,
                   bg=self.colors["text_bg"], fg=self.colors["fg"],
                   relief="flat", font=("Arial", 9)).pack(side="left", padx=(2, 0))

        # Box meta (mirrors ReviewEditor)
        _pf = self.cm.config.get("preview_font", {})
        self._box_meta = {
            "dialogue": {
                "crop": (27, 171, 480, 333), "pad": 20, "fg": "#2f2b2b",
                "font_sz":      _pf.get("dialogue", {}).get("font_sz",      18),
                "line_spacing": _pf.get("dialogue", {}).get("line_spacing",  1),
            },
            "choice": {
                "crop": (246, 17, 481, 151), "pad": 10, "fg": "#ffffff",
                "font_sz":      _pf.get("choice", {}).get("font_sz",      12),
                "line_spacing": _pf.get("choice", {}).get("line_spacing",  1),
            },
        }
        self._preview_images = {}
        self._preview_base_images = {}
        self._preview_font_objs = {}
        _DLG_W, _DLG_H = 453, 162
        self.preview_canvas = tk.Canvas(right, width=_DLG_W, height=_DLG_H,
                                        bg=self.colors["bg"], highlightthickness=0)
        self.preview_canvas.pack(anchor="w", pady=2)
        self._prev_W, self._prev_H = _DLG_W, _DLG_H

        _asset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        _font_path = next((p for p in [
            os.path.join(_asset_dir, "DDONfont.otf"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "DDONfont.otf"),
        ] if os.path.exists(p)), None)
        _box_style = {
            "dialogue": {"bg": (242, 238, 220), "border": (180, 160, 100)},
            "choice":   {"bg": (30, 25, 45),    "border": (120, 100, 200)},
        }
        if _PIL_OK:
            for key, meta in self._box_meta.items():
                crop = meta["crop"]
                box_w, box_h = crop[2] - crop[0], crop[3] - crop[1]
                fnt = None
                if _font_path:
                    try:
                        fnt = ImageFont.truetype(_font_path, meta["font_sz"])
                        self._preview_font_objs[key] = fnt
                    except Exception:
                        pass
                if fnt:
                    bbox = fnt.getbbox("あ")
                    meta["line_h"] = (bbox[3] - bbox[1]) + meta.get("line_spacing", 1)
                else:
                    meta["line_h"] = meta["font_sz"] + 3
                png_path = os.path.join(_asset_dir, f"{key}_box.png")
                final_base = None
                if os.path.exists(png_path):
                    try:
                        raw_img = Image.open(png_path).convert("RGBA")
                        cropped = raw_img.crop(meta["crop"])
                        rgb_vals = self.winfo_rgb(self.colors["bg"])
                        bg_rgb = tuple(c >> 8 for c in rgb_vals) + (255,)
                        bg_layer = Image.new("RGBA", cropped.size, bg_rgb)
                        bg_layer.paste(cropped, mask=cropped.split()[3])
                        final_base = bg_layer.convert("RGB")
                    except Exception:
                        pass
                if final_base is None:
                    style = _box_style[key]
                    final_base = Image.new("RGB", (box_w, box_h), style["bg"])
                    d = ImageDraw.Draw(final_base)
                    d.rectangle([0, 0, box_w-1, box_h-1], outline=style["border"], width=2)
                    d.rectangle([3, 3, box_w-4, box_h-4], outline=style["border"], width=1)
                self._preview_base_images[key] = final_base
                self._preview_images[key] = ImageTk.PhotoImage(final_base)
                meta["img_w"] = final_base.width
                meta["img_h"] = final_base.height

        # JP source
        jp_hdr = tk.Frame(right, bg=self.colors["bg"])
        jp_hdr.pack(fill="x", pady=(6, 0))
        tk.Label(jp_hdr, text="Japanese Source", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(side="left")
        self.deepl_btn = tk.Button(jp_hdr, text="Translate (DeepL)", command=self.translate_with_deepl,
                                   bg=self.colors["btn_bg"], fg=self.colors["fg"],
                                   font=("Arial", 8), relief="flat", padx=8)
        self.deepl_btn.pack(side="right")
        self.jp_txt = tk.Text(right, height=3, font=("Meiryo", 11),
                              bg=self.colors["jp_bg"], fg=self.colors["fg"],
                              insertbackground=self.colors["insert_color"],
                              state="disabled", bd=0, padx=6, pady=4, relief="flat")
        self.jp_txt.pack(fill="x")

        tk.Label(right, text="DeepL Suggestion (Click to paste)",
                 fg=self.colors["label_fg"], bg=self.colors["bg"],
                 font=("Arial", 8, "italic")).pack(anchor="w", pady=(4, 0))
        self.deepl_box = tk.Text(right, height=2, font=("Consolas", 10),
                                 bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                 bd=0, padx=6, pady=4, relief="flat", wrap="word",
                                 cursor="hand2")
        self.deepl_box.pack(fill="x", pady=(0, 5))
        self.deepl_box.insert(tk.END, "Ready.")
        self.deepl_box.config(state="disabled")
        self.deepl_box.bind("<Button-1>", self.click_deepl_suggestion)

        # Button bar
        btns = tk.Frame(self, bg=self.colors["bg"], pady=8)
        btns.pack(side="bottom", fill="x", padx=12)
        tk.Button(btns, text="← Prev", command=self._prev_item,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=8, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="Skip →", command=self._next_item,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=8, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="✓  Save", command=self._save_item,
                  bg=self.colors["apply_bg"], fg="white",
                  width=14, relief="flat",
                  font=("Arial", 10, "bold")).pack(side="left", padx=4)
        tk.Button(btns, text="―― → ...", command=lambda: self._replace_dashes("..."),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="―― → —", command=lambda: self._replace_dashes("—"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
        self.override_var = tk.BooleanVar(value=False)
        tk.Checkbutton(btns, text="Force Save (Ignore Limits)", variable=self.override_var,
                       bg=self.colors["bg"], fg=self.colors["label_fg"],
                       selectcolor=self.colors["bg"],
                       font=("Arial", 9, "bold")).pack(side="right", padx=10)

        # Sync font spinboxes with stored values
        box_key = self._preview_box_var.get()
        meta = self._box_meta.get(box_key, {})
        self._prev_font_sz_var.set(str(meta.get("font_sz", 12)))
        self._prev_spacing_var.set(str(meta.get("line_spacing", 1)))

    # ── list management ───────────────────────────────────────────────────
    def _populate_list(self):
        self.row_listbox.delete(0, tk.END)
        for orig_idx, row in self._visible_rows():
            speaker    = row[8].strip() if len(row) > 8 else ""
            jp_preview = row[2].replace("\n", " ")
            if len(jp_preview) > 38:
                jp_preview = jp_preview[:38] + "…"
            translated = self._is_translated(row)
            label = f"{'✓ ' if translated else '  '}[{orig_idx}] {speaker}: {jp_preview}"
            self.row_listbox.insert(tk.END, label)
            if translated:
                self.row_listbox.itemconfig(
                    tk.END,
                    fg=self.colors["translated_fg"],
                    bg=self.colors["translated_bg"])
        total = len(self.data_rows)
        done  = sum(1 for _, r in self.data_rows if self._is_translated(r))
        self.count_lbl.config(text=f"{done}/{total} translated")

    def _on_filter_changed(self):
        self._populate_list()
        self._load_by_list_idx(0)

    def _on_list_select(self, event):
        sel = self.row_listbox.curselection()
        if not sel:
            return
        list_idx = sel[0]
        visible = self._visible_rows()
        if list_idx >= len(visible):
            return
        self.current_list_idx = list_idx
        orig_idx, row = visible[list_idx]
        self._load_row(orig_idx, row)

    def _load_by_list_idx(self, list_idx):
        visible = self._visible_rows()
        if not visible:
            self._clear_editor()
            return
        list_idx = max(0, min(list_idx, len(visible) - 1))
        self.current_list_idx = list_idx
        self.row_listbox.selection_clear(0, tk.END)
        self.row_listbox.selection_set(list_idx)
        self.row_listbox.see(list_idx)
        orig_idx, row = visible[list_idx]
        self._load_row(orig_idx, row)

    # ── row loading ───────────────────────────────────────────────────────
    def _load_row(self, orig_idx, row):
        self._current_row_idx = orig_idx
        jp = row[2] if len(row) > 2 else ""
        en = row[3] if len(row) > 3 else ""
        self.jp_source    = jp
        self.speaker_name = row[8].strip() if len(row) > 8 else ""
        self.entry_type   = row[9].strip() if len(row) > 9 else ""

        self.txt.delete(1.0, tk.END)
        self.txt.insert(tk.END, en)
        self.txt.edit_reset()
        self.txt.focus_set()

        self.jp_txt.config(state="normal")
        self.jp_txt.delete(1.0, tk.END)
        self.jp_txt.insert(tk.END, jp)
        self.jp_txt.config(state="disabled")

        if self.speaker_name:
            self.speaker_lbl.config(text=self.speaker_name, fg=self.colors["counter_fg"])
            self.archetype_combo.config(state="readonly")
            saved_key = self.cm.config.get("speaker_archetypes", {}).get(self.speaker_name)
            if saved_key:
                self.archetype_var.set(self.lore_engine.get_archetype_label(saved_key))
            else:
                self.archetype_var.set("(none)")
        else:
            self.speaker_lbl.config(text="—", fg=self.colors["label_fg"])
            self.archetype_combo.config(state="disabled")
            self.archetype_var.set("(none)")

        self.entry_type_var.set(self.entry_type)
        et_rules = self.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        self.effective_limit = et_rules.get("char_limit") or self.limit
        self._refresh_et_display()
        self._update_adjacent()
        self._update_counters()
        self._update_preview()
        
        # Auto-translation on load
        self.translate_with_deepl()

    def _clear_editor(self):
        self.txt.delete(1.0, tk.END)
        self.jp_txt.config(state="normal")
        self.jp_txt.delete(1.0, tk.END)
        self.jp_txt.config(state="disabled")

    def _update_adjacent(self):
        for widget, offset, arrow in [
            (self.adj_prev_txt, -1, "▲ "),
            (self.adj_next_txt, +1, "▼ "),
        ]:
            widget.config(state="normal")
            widget.delete(1.0, tk.END)
            target = self._current_row_idx + offset
            if 0 < target < len(self.all_rows):
                adj = self.all_rows[target]
                adj_jp = (adj[2] if len(adj) > 2 else "").replace("\n", " ")
                adj_en = (adj[3] if len(adj) > 3 else "").replace("\n", " ")
                widget.insert(tk.END, arrow,           "adj_arrow")
                widget.insert(tk.END, adj_jp + "\n",   "adj_jp")
                widget.insert(tk.END, "   " + adj_en,  "adj_en")
            else:
                widget.insert(tk.END, f"{arrow}—")
            widget.tag_config("adj_arrow", foreground=self.colors["label_fg"])
            widget.tag_config("adj_jp",    foreground=self.colors["counter_fg"])
            widget.tag_config("adj_en",    foreground=self.colors["fg"])
            widget.config(state="disabled")

    # ── entry type ────────────────────────────────────────────────────────
    def _refresh_et_display(self):
        et_rules = self.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        if self.entry_type:
            disp_label = et_rules.get("label", self.entry_type)
            flags = []
            if et_rules.get("no_linebreak"):      flags.append("no auto-wrap")
            if et_rules.get("char_limit"):        flags.append(f"{et_rules['char_limit']} chars")
            if et_rules.get("no_trailing_punct"): flags.append("no trailing " + "/".join(et_rules["no_trailing_punct"]))
            badge_bg = "#c0392b" if flags else ("#2980b9" if et_rules else "#7f8c8d")
            self.entry_type_badge.config(text=f"  {disp_label}  ", bg=badge_bg)
            self.et_rules_lbl.config(text="  ·  ".join(flags))
        else:
            self.entry_type_badge.config(text="", bg=self.colors["bg"])
            self.et_rules_lbl.config(text="")

    def _on_entry_type_changed(self, event=None):
        self.entry_type = self.entry_type_var.get().strip()
        et_rules = self.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        self.effective_limit = et_rules.get("char_limit") or self.limit
        self._refresh_et_display()
        self._update_counters()

    # ── archetype ─────────────────────────────────────────────────────────
    def _save_archetype(self):
        if not self.speaker_name:
            return
        label = self.archetype_var.get()
        archs = self.cm.config.setdefault("speaker_archetypes", {})
        if label == "(none)":
            archs.pop(self.speaker_name, None)
        else:
            vals = list(self.archetype_combo["values"])
            idx  = vals.index(label) if label in vals else -1
            key  = self.archetype_keys[idx] if idx >= 0 else None
            if key:
                archs[self.speaker_name] = key
        self.cm.save_all()

    # ── counters / preview ────────────────────────────────────────────────
    def _sync_txt_scroll(self, *args):
        self._txt_yscroll_wid.set(*args)
        first, _ = self.txt.yview()
        self.cnt_lbl.yview_moveto(first)

    def _update_counters(self, e=None):
        content = self.txt.get("1.0", tk.END).splitlines()
        self.cnt_lbl.config(state="normal")
        self.cnt_lbl.delete("1.0", tk.END)
        for i, line in enumerate(content):
            sim = self.engine.get_simulated_len(line)
            tag = f"over_{i}"
            self.cnt_lbl.insert(tk.END, f"{sim:3}\n", tag)
            color = "#ff5555" if sim > self.effective_limit else self.colors["counter_fg"]
            self.cnt_lbl.tag_config(tag, foreground=color)
        self.cnt_lbl.config(state="disabled")

        self.txt.tag_remove("anachronism", "1.0", tk.END)
        self.anach_ranges = []
        if self.in_universe_var.get():
            from lore_engine import IN_UNIVERSE_VOCAB
            hits = self.lore_engine.scan_anachronisms(self.txt.get("1.0", tk.END))
            for found, _ in hits:
                word_lower = found.lower()
                suggestions = [(IN_UNIVERSE_VOCAB[word_lower], "primary")] \
                    if word_lower in IN_UNIVERSE_VOCAB and IN_UNIVERSE_VOCAB[word_lower] else []
                pos = "1.0"
                while True:
                    pos = self.txt.search(found, pos, stopindex=tk.END, nocase=True)
                    if not pos:
                        break
                    end = f"{pos}+{len(found)}c"
                    cb = self.txt.get(f"{pos}-1c", pos)
                    ca = self.txt.get(end, f"{end}+1c")
                    if (not cb or not cb.isalnum() and cb != "'") and \
                       (not ca or not ca.isalnum() and ca != "'"):
                        self.txt.tag_add("anachronism", pos, end)
                        self.anach_ranges.append((pos, end, found, suggestions))
                    pos = end
            self.txt.tag_config("anachronism", foreground="#ff8800", underline=True)

    # ── editing actions ───────────────────────────────────────────────────
    def _rewrap(self):
        text = self.txt.get(1.0, tk.END).strip()
        wrapped = self.engine.master_tag_wrap(text, self.effective_limit)
        if wrapped != text:
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, wrapped)
            self._update_counters()
            self._update_preview()

    def _replace_dashes(self, replacement):
        text = self.txt.get(1.0, tk.END)
        fixed = re.sub(r'[-–—―]{2,}', replacement, text)
        if replacement == "...":
            fixed = re.sub(r'\.\.\.(\w)', r'... \1', fixed)
        if fixed != text:
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, fixed)
            self._update_counters()
            self._update_preview()

    def _save_item(self):
        if self._current_row_idx < 0:
            return
        new_val = self.txt.get(1.0, tk.END).strip()
        lines   = new_val.splitlines()

        et_rules = self.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        if et_rules.get("no_trailing_punct") and new_val and \
                new_val[-1] in et_rules["no_trailing_punct"]:
            messagebox.showerror("Trailing Punctuation",
                f"Entry type '{self.entry_type}' does not allow trailing '{new_val[-1]}'.",
                parent=self)
            return

        if not self.override_var.get():
            overlong = [i+1 for i, l in enumerate(lines)
                        if self.engine.get_simulated_len(l) > self.effective_limit]
            if overlong:
                messagebox.showerror("Line Too Long",
                    f"Line(s) {', '.join(str(n) for n in overlong)} exceed "
                    f"the {self.effective_limit}-char limit.", parent=self)
                return
            if len(lines) >= self.wall_limit:
                messagebox.showerror("Too Many Lines",
                    f"{len(lines)} lines — limit is {self.wall_limit - 1}.", parent=self)
                return

        # Write back to in-memory rows
        row = self.all_rows[self._current_row_idx]
        while len(row) <= 9:
            row.append("")
        row[3] = new_val
        row[9] = self.entry_type_var.get().strip()

        try:
            with open(self.csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f, self.dialect).writerows(self.all_rows)
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)
            return

        self._populate_list()
        self._next_item()

    def _next_item(self):
        self._load_by_list_idx(self.current_list_idx + 1)

    def _prev_item(self):
        self._load_by_list_idx(self.current_list_idx - 1)

    # ── anachronism tooltip (mirrors ReviewEditor) ────────────────────────

    def toggle_pane(self, name):
        """Toggle visibility of a sidebar pane."""
        if name == "ctx":
            if self.pane_ctx.winfo_ismapped():
                self.side_pane.forget(self.pane_ctx)
            else:
                self.side_pane.add(self.pane_ctx, before=self.pane_ai, height=250)
        elif name == "ai":
            if self.pane_ai.winfo_ismapped():
                self.side_pane.forget(self.pane_ai)
            else:
                self.side_pane.add(self.pane_ai)

    # --- API INTEGRATIONS (Mirrored from ReviewEditor) ---

    def _is_chatting_setter(self, value):
        self._is_chatting = value
        btn_state = "disabled" if value else "normal"
        self.btn_chat_send.config(state=btn_state)


