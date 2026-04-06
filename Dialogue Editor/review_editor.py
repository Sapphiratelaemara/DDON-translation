import sys
sys.dont_write_bytecode = True

import csv
import os
import re
import threading
import tkinter as tk
from collections import Counter
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from translator_engine import TranslationEngine
from lore_engine import LoreEngine
from api_handler import DeepLClient, OpenRouterClient
from file_utils import _read_csv
from editor_mixin import SharedEditorMixin


class ReviewEditor(SharedEditorMixin, tk.Toplevel):
    def __init__(self, parent, tag_queue, wall_queue, dash_queue, anach_queue, limit, wall_limit, tag_map, callback):
        super().__init__(parent.root) 
        self.parent = parent 
        self.title("Dialogue Reviewer v5.3")
        self.geometry("1100x850")

        self.limit, self.wall_limit, self.tag_map, self.callback = limit, wall_limit, tag_map, callback
        self.effective_limit = limit   # may be overridden per-item by entry type char_limit
        self.jp_source = ""
        self.speaker_name = ""
        self.entry_type = ""
        self.entry_type_var = tk.StringVar()
        self.in_universe_var = tk.BooleanVar(value=self.parent.cm.config.get("in_universe", False))
        self.engine = TranslationEngine(tag_map)
        self.lore_engine = LoreEngine(self.parent.cm.config.get("archetypes"))
        self.lore_engine.load_data(
            self.parent.cm.config.get("bible_path", ""), 
            self.parent.cm.config.get("glossary_path", "")
        )

        self.queues = {
            "Tag Issues (Complex Tags)": tag_queue,
            "Line Limit": wall_queue,
            "Double Dashes": dash_queue,
            "Possible Anachronisms": anach_queue,
        }
        self.current_category = next((cat for cat in self.queues if self.queues[cat]), "Tag Issues (Complex Tags)")
        self.current_texts = list(self.queues[self.current_category].keys())
        self.current_idx = 0
        self.anach_ranges = []   # list of (start_idx, end_idx, word, [(suggestion, label), ...])
        self._hovered_range = None   # set by tooltip motion handler, read by Tab handler
        self._tip_visible = False
        # Dummy label created early so _jp_motion closures in load_item never hit AttributeError.
        # _bind_tooltip() replaces this with a properly styled label after setup_ui().
        self._tip_label = tk.Label(self)

        self.dark_mode = self.parent.cm.config.get("dark_mode", False)
        self.apply_theme_colors()
        self.setup_ui()
        self.load_item()

        # Prefetch definitions for all vocab words in the background (only fetches missing ones)
        from lore_engine import IN_UNIVERSE_VOCAB
        self.lore_engine.prefetch_definitions(list(IN_UNIVERSE_VOCAB.keys()))

        self._bind_tooltip()
        self.txt.bind("<Tab>", self._tab_insert_suggestion)
        
        self.bind("<Control-Return>", lambda e: self.save_item())
        self.bind("<Control-Right>", lambda e: self.next_item())
        self.bind("<Control-r>", lambda e: self.rewrap_text())
        self.bind("<Control-d>", lambda e: self.replace_dashes("—"))
        self.bind("<Control-D>", lambda e: self.replace_dashes("..."))

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.parent.flush_csv_writes()
        self.destroy()

    @property
    def cm(self):
        """Uniform access to ConfigManager — matches CSVTranslationWindow.cm."""
        return self.parent.cm

    def apply_theme_colors(self):
        if self.dark_mode:
            self.colors = {
                "bg":           "#1a1a2e",
                "fg":           "#e0e0e0",
                "text_bg":      "#16213e",
                "jp_bg":        "#0f1923",
                "sidebar_bg":   "#1e1e35",
                "btn_bg":       "#0f3460",
                "label_fg":     "#8888aa",
                "counter_fg":   "#4ec9b0",
                "insert_color": "#ffffff",
                "accent":       "#e94560",
                "apply_bg":     "#03dac6",
                "translated_bg": "#0d1f0d",
                "translated_fg": "#558855",
            }
        else:
            self.colors = {
                "bg":           "#f5f6fa",
                "fg":           "#2c2c3e",
                "text_bg":      "#ffffff",
                "jp_bg":        "#f0f4f8",
                "sidebar_bg":   "#eef0f7",
                "btn_bg":       "#dfe4ea",
                "label_fg":     "#7f8c8d",
                "counter_fg":   "#2980b9",
                "insert_color": "#000000",
                "accent":       "#3867d6",
                "apply_bg":     "#20bf6b",
                "translated_bg": "#f0fff0",
                "translated_fg": "#2d7a2d",
            }

    def make_context_menu(self, widget):
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Cut", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()
        def select_all():
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end")
            else:
                widget.select_range(0, tk.END)
            return "break"
        menu.add_command(label="Select All", command=select_all)
        
        def show_menu(e):
            menu.tk_popup(e.x_root, e.y_root)
        widget.bind("<Button-3>", show_menu)

    def setup_ui(self):
        self.configure(bg=self.colors["bg"])

        # ── Top control bar ──
        ctrl = tk.Frame(self, bg=self.colors["accent"], pady=6)
        ctrl.pack(fill="x")
        self.cat_combo = ttk.Combobox(ctrl, values=list(self.queues.keys()),
                                      state="readonly", width=32)
        self.cat_combo.set(self.current_category)
        self.cat_combo.pack(side="left", padx=10)
        self.cat_combo.bind("<<ComboboxSelected>>", self.change_category)

        tk.Button(ctrl, text="🌙" if not self.dark_mode else "☀️",
                  command=self.toggle_dark_mode,
                  bg=self.colors["accent"], fg="white",
                  bd=0, font=("Arial", 12),
                  activebackground=self.colors["accent"]).pack(side="right", padx=8)
        tk.Checkbutton(ctrl, text="In-Universe Language", variable=self.in_universe_var,
                       bg=self.colors["accent"], fg="white",
                       selectcolor=self.colors["accent"],
                       activebackground=self.colors["accent"],
                       command=self._update_counters).pack(side="right", padx=10)

        # Rate limiting / busy flags
        self._is_translating = False
        self._is_chatting = False

        self.info_lbl = tk.Label(self, text="",
                                 fg=self.colors["accent"], bg=self.colors["bg"],
                                 font=("Arial", 10, "bold"))
        self.info_lbl.pack(pady=(4, 0))

        # ── Speaker / Archetype bar ──
        spk_frame = tk.Frame(self, bg=self.colors["bg"], padx=16, pady=3)
        spk_frame.pack(fill="x")
        def spk_lbl(text):
            return tk.Label(spk_frame, text=text, fg=self.colors["label_fg"],
                            bg=self.colors["bg"], font=("Arial", 9))
        spk_lbl("Speaker:").pack(side="left")
        self.speaker_lbl = tk.Label(spk_frame, text="—",
                                    fg=self.colors["counter_fg"], bg=self.colors["bg"],
                                    font=("Arial", 9, "bold"))
        self.speaker_lbl.pack(side="left", padx=(4, 14))
        spk_lbl("Archetype:").pack(side="left")
        archetype_options = self.lore_engine.get_archetype_options()
        archetype_labels = ["(none)"] + [opt[1] for opt in archetype_options]
        self.archetype_keys = [None] + [opt[0] for opt in archetype_options]
        self.archetype_var = tk.StringVar(value="(none)")
        self.archetype_combo = ttk.Combobox(spk_frame, textvariable=self.archetype_var,
                                            values=archetype_labels, state="disabled", width=28)
        self.archetype_combo.pack(side="left", padx=(4, 6))
        self.archetype_combo.bind("<<ComboboxSelected>>", self.on_archetype_selected)
        tk.Button(spk_frame, text="Save", command=self.save_archetype,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=6).pack(side="left")
        spk_lbl("Note:").pack(side="left", padx=(14, 2))
        self.speaker_note_var = tk.StringVar()
        self.speaker_note_entry = tk.Entry(spk_frame, textvariable=self.speaker_note_var,
                                           width=26, font=("Arial", 9),
                                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                                           insertbackground=self.colors["fg"], relief="flat",
                                           state="disabled")
        self.speaker_note_entry.pack(side="left")
        self.make_context_menu(self.speaker_note_entry)
        self.speaker_note_entry.bind("<FocusOut>", lambda e: self.save_archetype())
        self.speaker_note_entry.bind("<Return>",   lambda e: self.save_archetype())

        # ── Entry type row ── (below speaker bar)
        et_frame = tk.Frame(self, bg=self.colors["bg"], padx=16, pady=2)
        et_frame.pack(fill="x")
        tk.Label(et_frame, text="Entry Type:", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        known_types = [""] + sorted(self.parent.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_combo = ttk.Combobox(et_frame, textvariable=self.entry_type_var,
                                             values=known_types, width=36)
        self.entry_type_combo.pack(side="left", padx=(4, 6))
        self.entry_type_combo.bind("<<ComboboxSelected>>", self._on_entry_type_changed)
        self.entry_type_combo.bind("<Return>",  self._on_entry_type_changed)
        self.entry_type_combo.bind("<FocusOut>", self._on_entry_type_changed)
        self.entry_type_badge = tk.Label(et_frame, text="",
                                         fg="white", bg="#2980b9",
                                         font=("Arial", 8, "bold"), padx=5, pady=1)
        self.entry_type_badge.pack(side="left", padx=(2, 4))
        tk.Button(et_frame, text="Save Type", command=self.save_entry_type,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=6).pack(side="left")
        self.et_rules_lbl = tk.Label(et_frame, text="", fg=self.colors["label_fg"],
                                     bg=self.colors["bg"], font=("Arial", 8, "italic"))
        self.et_rules_lbl.pack(side="left", padx=(10, 0))

        # ── Main body ──
        main = tk.Frame(self, bg=self.colors["bg"])
        main.pack(fill="both", expand=True, padx=14, pady=4)

        # Sidebar packs first (right) so it gets its preferred width;
        # counter strip packs second (right); left_f fills the remaining space.
        side = tk.Frame(main, bg=self.colors["sidebar_bg"], width=400)
        side.pack(side="right", fill="both")
        side.pack_propagate(False)

        # Toggle bar at the top of the sidebar
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

        # --- Pane 1: Context/References ---
        self.pane_ctx = tk.Frame(self.side_pane, bg=self.colors["sidebar_bg"])
        self.side_pane.add(self.pane_ctx, height=300)

        tk.Label(self.pane_ctx, text="References", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        lore_f = tk.Frame(self.pane_ctx, bg=self.colors["text_bg"])
        lore_f.pack(fill="both", expand=True)
        lore_scroll = tk.Scrollbar(lore_f)
        lore_scroll.pack(side="right", fill="y")
        self.lore_list = tk.Text(lore_f, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                 bd=0, highlightthickness=0, font=("Arial", 10),
                                 wrap="word", state="disabled", padx=6, pady=4,
                                 yscrollcommand=lore_scroll.set)
        self.lore_list.pack(side="left", fill="both", expand=True)
        lore_scroll.config(command=self.lore_list.yview)

        tk.Frame(self.pane_ctx, bg=self.colors["label_fg"], height=1).pack(fill="x", pady=2)
        tk.Label(self.pane_ctx, text="Archetype Notes", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(anchor="w", padx=6)
        self.archetype_hint = tk.Text(self.pane_ctx, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                      bd=0, highlightthickness=0, font=("Arial", 9),
                                      wrap="word", state="disabled", height=6,
                                      padx=6, pady=4)
        self.archetype_hint.pack(fill="x")

        # --- Pane 2: AI Assistant ---
        self.pane_ai = tk.Frame(self.side_pane, bg=self.colors["sidebar_bg"])
        self.side_pane.add(self.pane_ai)

        ai_hdr = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        ai_hdr.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(ai_hdr, text="AI Assistant", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(side="left")

        chat_ctrl = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        chat_ctrl.pack(fill="x", padx=5, pady=5)
        
        self.chat_model_var = tk.StringVar(value=self.parent.cm.config.get("selected_openrouter_model", "openrouter/auto"))
        models = self.parent.cm.config.get("openrouter_models", ["openrouter/auto"])
        self.chat_model_combo = ttk.Combobox(chat_ctrl, textvariable=self.chat_model_var, values=models, state="readonly", width=18)
        self.chat_model_combo.pack(side="left", fill="x", expand=True)
        self.chat_model_combo.bind("<<ComboboxSelected>>", self._save_selected_model)
        
        tk.Button(chat_ctrl, text="↻", command=self.refresh_model_list,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=4).pack(side="right", padx=(4, 0))

        chat_scroll = tk.Scrollbar(self.pane_ai)
        chat_scroll.pack(side="right", fill="y")
        self.chat_history = tk.Text(self.pane_ai, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                    bd=0, highlightthickness=0, font=("Arial", 9),
                                    wrap="word", state="disabled", padx=6, pady=4,
                                    yscrollcommand=chat_scroll.set)
        self.chat_history.pack(fill="both", expand=True)
        chat_scroll.config(command=self.chat_history.yview)

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

        # Left: editor + JP source — expands to fill all remaining space
        left_f = tk.Frame(main, bg=self.colors["bg"])
        left_f.pack(side="left", fill="both", expand=True)

        tk.Label(left_f, text="English", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w")

        en_outer = tk.Frame(left_f, bg=self.colors["bg"])
        en_outer.pack(fill="x")   # fixed height — do NOT expand

        self.cnt_lbl = tk.Text(en_outer, font=("Consolas", 12), width=4, height=6,
                               bg=self.colors["bg"], fg=self.colors["counter_fg"],
                               state="disabled", bd=0, highlightthickness=0,
                               padx=0, pady=4)  # pady=4 matches self.txt's internal pady
        self.cnt_lbl.pack(side="right", fill="y", padx=(2, 0))

        en_inner = tk.Frame(en_outer, bg=self.colors["bg"])
        en_inner.pack(side="left", fill="x")

        txt_yscroll = tk.Scrollbar(en_inner, orient="vertical")
        txt_yscroll.pack(side="right", fill="y")

        self.txt = tk.Text(en_inner, height=6, font=("Consolas", 12),
                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                           insertbackground=self.colors["insert_color"],
                           bd=0, padx=6, pady=4, wrap="none",
                           relief="flat", selectbackground=self.colors["accent"],
                           selectforeground="white", undo=True,
                           yscrollcommand=self._sync_txt_scroll)
        self.make_context_menu(self.txt)
        txt_xscroll = tk.Scrollbar(en_inner, orient="horizontal", command=self.txt.xview)
        self.txt.configure(xscrollcommand=txt_xscroll.set)
        self.txt.pack(fill="x")
        txt_xscroll.pack(fill="x")
        txt_yscroll.config(command=self.txt.yview)
        self._txt_yscroll = txt_yscroll
        self.txt.bind("<KeyRelease>", lambda e: [self._update_counters(e), self._update_preview(e)])
        self.txt.bind("<<Paste>>", lambda e: self.after(0, lambda: [self._update_counters(), self._update_preview()]))

        # DeepL Suggestion box (Directly under English)
        tk.Label(left_f, text="DeepL Suggestion (Click to paste)", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "italic")).pack(anchor="w", pady=(4, 0))
        self.deepl_box = tk.Text(left_f, height=2, font=("Consolas", 10),
                                  bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                  bd=0, padx=6, pady=4, relief="flat", wrap="word", cursor="hand2")
        self.deepl_box.pack(fill="x", pady=(0, 5))
        self.deepl_box.insert(tk.END, "Ready.")
        self.deepl_box.config(state="disabled")
        self.deepl_box.bind("<Button-1>", self.click_deepl_suggestion)

        # ── Visual Preview Canvas ──
        prev_hdr = tk.Frame(left_f, bg=self.colors["bg"])
        prev_hdr.pack(fill="x", pady=(5, 0))
        tk.Label(prev_hdr, text="In-Game Preview:", bg=self.colors["bg"],
                 fg=self.colors["label_fg"]).pack(side="left")
        # Manual box-type toggle
        self._preview_box_var = tk.StringVar(value="dialogue")
        for val, lbl in (("dialogue", "Dialogue"), ("choice", "Choice")):
            tk.Radiobutton(prev_hdr, text=lbl, value=val, variable=self._preview_box_var,
                           bg=self.colors["bg"], fg=self.colors["fg"],
                           selectcolor=self.colors["bg"], activebackground=self.colors["bg"],
                           font=("Arial", 9),
                           command=lambda: [self._sync_preview_font_controls(), self._update_preview()]).pack(side="left", padx=4)

        tk.Label(prev_hdr, text="  Font:", bg=self.colors["bg"], fg=self.colors["label_fg"],
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
        self._prev_spacing_spin.pack(side="left", padx=(2, 0))
        self._prev_spacing_spin.bind("<Return>",   lambda e: self._on_preview_font_changed())
        self._prev_spacing_spin.bind("<FocusOut>", lambda e: self._on_preview_font_changed())

        # Cropped box regions from the shared 504x359 transparent source canvas:
        #   choice   content bbox: (246,17,481,151)  => 235 x 134 px
        #   dialogue content bbox: (27,171,480,333)  => 453 x 162 px
        _pf = self.parent.cm.config.get("preview_font", {})
        _BOX_META = {
            "dialogue": {
                "crop":         (27, 171, 480, 333),
                "pad":          20,
                "fg":           "#2f2b2b",
                "font_sz":      _pf.get("dialogue", {}).get("font_sz",      18),
                "line_spacing": _pf.get("dialogue", {}).get("line_spacing",  1),
            },
            "choice": {
                "crop":         (246, 17, 481, 151),
                "pad":          10,
                "fg":           "#ffffff",
                "font_sz":      _pf.get("choice", {}).get("font_sz",      12),
                "line_spacing": _pf.get("choice", {}).get("line_spacing",  1),
            },
        }
        self._box_meta = _BOX_META
        self._sync_preview_font_controls()
        _SCALE = 1.0   # 1:1 — needed so 11 lines fit in the 122px inner area at font 9
        self._prev_scale = _SCALE
        _DLG_W = 480 - 27   # 453
        _DLG_H = 333 - 171  # 162
        self._prev_W = int(_DLG_W * _SCALE)
        self._prev_H = int(_DLG_H * _SCALE)

        self.preview_canvas = tk.Canvas(left_f,
                                        width=self._prev_W, height=self._prev_H,
                                        bg=self.colors["bg"], highlightthickness=0)
        self.preview_canvas.pack(anchor="w", pady=2)

        # Pre-load: crop each box, cache as both PhotoImage (for UI) and PIL Image (for rendering)
        self._preview_images = {}      # {key: PhotoImage}
        self._preview_base_images = {} # {key: PIL.Image}
        self._preview_font_objs = {}   # {key: ImageFont}
        
        _asset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        # Game font — look in assets/ first, then alongside the script
        _font_candidates = [
            os.path.join(_asset_dir, "DDONfont.otf"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "DDONfont.otf"),
        ]
        _font_path = next((p for p in _font_candidates if os.path.exists(p)), None)

        if _PIL_OK:
            _src_files = {"dialogue": "dialogue_box.png", "choice": "choice_box.png"}

            # Box colour palettes for procedural fallback
            _box_style = {
                "dialogue": {
                    "bg":     (242, 238, 220),
                    "border": (180, 160, 100),
                },
                "choice": {
                    "bg":     (30, 25, 45),
                    "border": (120, 100, 200),
                },
            }

            for key, meta in _BOX_META.items():
                crop = meta["crop"]
                box_w = crop[2] - crop[0]
                box_h = crop[3] - crop[1]

                # --- Load font and measure actual line height ---
                fnt = None
                if _font_path:
                    try:
                        fnt = ImageFont.truetype(_font_path, meta["font_sz"])
                        self._preview_font_objs[key] = fnt
                    except Exception:
                        pass

                # --- Compute line height (required for preview) ---
                if fnt:
                    # Measure actual glyph height instead of ascent/descent
                    bbox = fnt.getbbox("あ")  # representative glyph
                    glyph_h = bbox[3] - bbox[1]

                    # Now you can tighten spacing properly
                    meta["line_h"] = glyph_h + meta.get("line_spacing", 1)
                else:
                    meta["line_h"] = meta["font_sz"] + 3


                # --- Try to load PNG asset; fall back to procedural box ---
                png_path = os.path.join(_asset_dir, _src_files[key])
                if os.path.exists(png_path):
                    try:
                        raw = Image.open(png_path).convert("RGBA")
                        cropped = raw.crop(meta["crop"])
                        rgb_vals = self.winfo_rgb(self.colors["bg"])
                        bg_rgb = tuple(c >> 8 for c in rgb_vals) + (255,)
                        bg_layer = Image.new("RGBA", cropped.size, bg_rgb)
                        bg_layer.paste(cropped, mask=cropped.split()[3])
                        final_base = bg_layer.convert("RGB")
                    except Exception:
                        final_base = None
                else:
                    final_base = None

                if final_base is None:
                    # Procedural box: styled panel matching the game's UI tone
                    style = _box_style[key]
                    final_base = Image.new("RGB", (box_w, box_h), style["bg"])
                    d = ImageDraw.Draw(final_base)
                    d.rectangle([0, 0, box_w-1, box_h-1], outline=style["border"], width=2)
                    d.rectangle([3, 3, box_w-4, box_h-4], outline=style["border"], width=1)

                self._preview_base_images[key] = final_base
                self._preview_images[key] = ImageTk.PhotoImage(final_base)
                meta["img_w"] = final_base.width
                meta["img_h"] = final_base.height

        # Japanese Source (Label)
        tk.Label(left_f, text="Japanese Source", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w", pady=(8, 0))
        self.jp_txt = tk.Text(left_f, height=4, font=("Meiryo", 11),
                              bg=self.colors["jp_bg"], fg=self.colors["fg"],
                              insertbackground=self.colors["insert_color"],
                              state="disabled", bd=0, padx=6, pady=4, relief="flat")
        self.make_context_menu(self.jp_txt)
        self.jp_txt.pack(fill="both", expand=True)

        # ── Adjacent context ──
        tk.Frame(left_f, bg=self.colors["label_fg"], height=1).pack(fill="x", pady=(4, 0))
        tk.Label(left_f, text="Context", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w")
        self.adj_prev_txt = tk.Text(left_f, height=2, font=("Consolas", 9),
                                    bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                    state="disabled", bd=0, padx=4, pady=2, relief="flat",
                                    wrap="word")
        self.adj_prev_txt.pack(fill="x", pady=(0, 1))
        self.adj_next_txt = tk.Text(left_f, height=2, font=("Consolas", 9),
                                    bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                    state="disabled", bd=0, padx=4, pady=2, relief="flat",
                                    wrap="word")
        self.adj_next_txt.pack(fill="x")

        # ── Button bar ──
        btns = tk.Frame(self, bg=self.colors["bg"], pady=10)
        btns.pack(side="bottom", fill="x", padx=14)
        tk.Button(btns, text="Skip →", command=self.next_item,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="✓  Apply", command=self.save_item,
                  bg=self.colors["apply_bg"], fg="white",
                  width=18, relief="flat", font=("Arial", 10, "bold")).pack(side="left", padx=4)
        tk.Button(btns, text="―― → ...", command=lambda: self.replace_dashes("..."),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="―― → —", command=lambda: self.replace_dashes("—"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
                  
        self.override_var = tk.BooleanVar(value=False)
        tk.Checkbutton(btns, text="Force Save (Ignore Limits)", variable=self.override_var,
                       bg=self.colors["bg"], fg=self.colors["label_fg"], selectcolor=self.colors["bg"],
                       activebackground=self.colors["bg"], font=("Arial", 9, "bold")).pack(side="right", padx=10)


    def load_item(self):
        if self.current_idx >= len(self.current_texts):
            # Try to switch to the next non-empty category automatically
            for cat, queue in self.queues.items():
                if cat != self.current_category and queue:
                    self.current_category = cat
                    self.cat_combo.set(cat)
                    self.current_texts = list(queue.keys())
                    self.current_idx = 0
                    break
            else:
                # All categories exhausted — close the window
                self.on_close()
                return
        txt = self.current_texts[self.current_idx]
        self.override_var.set(False)
        self.info_lbl.config(text=f"REVIEWING: {self.current_idx+1}/{len(self.current_texts)}")
        self.txt.delete(1.0, tk.END)
        self.txt.insert(tk.END, txt)
        # Clear undo stack after loading new text so you can't undo into a blank box
        self.txt.edit_reset()
        # Set focus
        self.txt.focus_set()

        first_inst = self.queues[self.current_category][txt][0]
        try:
            _, _, rows = _read_csv(first_inst['path'])
            row_data = rows[first_inst['row_idx']]
            jp_source = row_data[2] if len(row_data) > 2 else ""
            self.speaker_name = row_data[8].strip() if len(row_data) > 8 else ""
            self.entry_type = row_data[9].strip() if len(row_data) > 9 else first_inst.get('entry_type', "")
            self._adj_path = first_inst['path']
            self._adj_row_idx = first_inst['row_idx']
        except:
            jp_source = "Source Error"
            self.speaker_name = ""
            self._adj_path = None
            self._adj_row_idx = -1

        # --- Update speaker / archetype bar ---
        if self.speaker_name:
            self.speaker_lbl.config(text=self.speaker_name, fg=self.colors["counter_fg"])
            self.archetype_combo.config(state="readonly")
            self.speaker_note_entry.config(state="normal")
            self.archetype_combo.event_generate("<<ComboboxSelected>>")  # force update hint box
            # Pre-fill archetype from saved assignments
            saved_key = self.parent.cm.config.get("speaker_archetypes", {}).get(self.speaker_name)
            if saved_key:
                label = self.lore_engine.get_archetype_label(saved_key)
                self.archetype_var.set(label)
            else:
                self.archetype_var.set("(none)")
            self.update_archetype_hint()  # FORCE refresh whenever speaker changes
            # Pre-fill note
            saved_note = self.parent.cm.config.get("speaker_notes", {}).get(self.speaker_name, "")
            self.speaker_note_var.set(saved_note)
        else:
            self.speaker_lbl.config(text="Unknown", fg=self.colors["label_fg"])
            self.archetype_combo.config(state="disabled")
            self.speaker_note_entry.config(state="disabled")
            self.speaker_note_var.set("")
            self.archetype_var.set("(none)")
        self.update_archetype_hint()

        # --- Entry type combobox + badge ---
        et_keys = [""] + sorted(self.parent.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_combo.config(values=et_keys)
        self.entry_type_var.set(self.entry_type)
        # Recompute effective char limit for this item
        et_rules_now = self.parent.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        self.effective_limit = et_rules_now.get("char_limit") or self.limit
        self._refresh_et_display()

        self.jp_txt.config(state="normal")
        self.jp_txt.delete(1.0, tk.END)
        self.jp_txt.insert(tk.END, jp_source)
        self.jp_source = jp_source  # Store for validation in save_item
        self.lore_list.config(state="normal")
        self.lore_list.delete(1.0, tk.END)

        if jp_source:
            matches = self.lore_engine.scan_text(jp_source)
            tag_display = self.parent.cm.config.get("tag_display", {})
            for jp, en in matches:
                # Insert JP term label
                self.lore_list.insert(tk.END, f"• {jp}:  ", f"lore_label_{hash(jp)}")
                # Insert clickable EN translation
                en_tag = f"lore_en_{hash(jp)}"
                self.lore_list.insert(tk.END, en, en_tag)
                self.lore_list.tag_config(en_tag, foreground="#6fb3ff", underline=True)
                self.lore_list.tag_bind(en_tag, "<Button-1>",
                                        lambda e, w=en: self.quick_insert(w))
                self.lore_list.insert(tk.END, "\n")
                # Highlight JP term in source panel
                jtag = f"lore_{hash(jp)}"
                self.jp_txt.tag_config(jtag, foreground="#6fb3ff", underline=True)
                self.jp_txt.tag_bind(jtag, "<Button-1>", lambda e, w=en: self.quick_insert(w))
                self._apply_tag_to_text(jp, jtag)
            # Show tag display text so translators know what <TAG_NAME> renders as
            if tag_display:
                shown = set()
                for tag_key, display_text in tag_display.items():
                    if f"<{tag_key}>" in jp_source and tag_key not in shown:
                        shown.add(tag_key)
                        self.lore_list.insert(tk.END, f"  <{tag_key}>  =  \"{display_text}\"\n", "tag_disp")
                self.lore_list.tag_config("tag_disp", foreground="#aaaaaa", font=("Arial", 9, "italic"))
            if matches:
                height = max(3, min(len(matches) + 1, 12))
                self.lore_list.config(height=height)

        # JP source hover tooltip — shows EN translation when hovering highlighted terms
        self._jp_tip_map = {}   # idx_range -> en_text, built below
        def _jp_motion(event):
            idx = self.jp_txt.index(f"@{event.x},{event.y}")
            for (s, e_), en_text in self._jp_tip_map.items():
                if self.jp_txt.compare(s, "<=", idx) and self.jp_txt.compare(idx, "<", e_):
                    self._tip_label.config(text=f"→  {en_text}")
                    rx = event.x_root - self.winfo_rootx() + 20
                    ry = event.y_root - self.winfo_rooty() + 10
                    self._tip_label.place(x=rx, y=ry)
                    self._tip_label.lift()
                    self._tip_visible = True
                    return
            if self._tip_visible:
                self._tip_label.place_forget()
                self._tip_visible = False
        def _jp_leave(event):
            if self._tip_visible:
                self._tip_label.place_forget()
                self._tip_visible = False
        self.jp_txt.bind("<Motion>", _jp_motion)
        self.jp_txt.bind("<Leave>",  _jp_leave)
        # Populate the map after jp_txt is filled
        if jp_source:
            for jp, en in self.lore_engine.scan_text(jp_source):
                pos = "1.0"
                while True:
                    pos = self.jp_txt.search(jp, pos, stopindex=tk.END)
                    if not pos: break
                    end_pos = f"{pos}+{len(jp)}c"
                    self._jp_tip_map[(pos, end_pos)] = en
                    pos = end_pos

        # Tag Issues sidebar — only when in that category
        if self.current_category == "Tag Issues (Complex Tags)":
            instances = self.queues["Tag Issues (Complex Tags)"].get(txt, [])
            if instances:
                inst = instances[0]
                reason = inst.get('tag_reason', '')
                unknown_tags = inst.get('unknown_tags', [])
                seen_tags = list(dict.fromkeys(unknown_tags))  # deduplicated, order preserved

                self.lore_list.insert(tk.END, "── Tag Issue ──\n", "tag_issue_hdr")
                self.lore_list.tag_config("tag_issue_hdr", foreground="#e94560",
                                          font=("Arial", 9, "bold"))

                if reason in ('overflow_after_wrap', 'unmapped_tags_overflow'):
                    if seen_tags:
                        self.lore_list.insert(tk.END,
                            "  Line-breaking ran but a line still overflows.\n"
                            "  The unmapped tags below are treated as zero-\n"
                            "  width, causing the limit to be miscalculated.\n\n",
                            "tag_reason_txt")
                    else:
                        self.lore_list.insert(tk.END,
                            "  Line-breaking ran but a line still overflows.\n"
                            "  All tags are mapped — the translation is\n"
                            "  simply too long. Shorten it.\n\n",
                            "tag_reason_txt")
                elif reason == 'memory_overflow':
                    self.lore_list.insert(tk.END,
                        "  A previously saved fix for this line now\n"
                        "  exceeds the character limit. Edit and re-apply.\n\n",
                        "tag_reason_txt")
                else:
                    self.lore_list.insert(tk.END,
                        "  This entry exceeded the character limit\n"
                        "  after line-breaking.\n\n",
                        "tag_reason_txt")
                self.lore_list.tag_config("tag_reason_txt", foreground=self.colors["fg"])

                if seen_tags:
                    self.lore_list.insert(tk.END, "  Unmapped tags:\n", "tag_issue_sub")
                    self.lore_list.tag_config("tag_issue_sub", foreground=self.colors["label_fg"],
                                              font=("Arial", 9, "bold"))
                    for tag in seen_tags:
                        self.lore_list.insert(tk.END, f"    <{tag}>\n", "tag_unknown")
                    self.lore_list.tag_config("tag_unknown", foreground="#e94560",
                                              font=("Consolas", 10))
                    self.lore_list.insert(tk.END,
                        "\n  Add these in Options → Tag Length Mapping\n"
                        "  to let the tool calculate their width.\n",
                        "tag_tip")
                    self.lore_list.tag_config("tag_tip", foreground=self.colors["label_fg"],
                                              font=("Arial", 8, "italic"))

        # Dash category sidebar
        if self.current_category == "Double Dashes":
            _DASH_RE = re.compile(r'[-–—―]{2,}')
            found_dashes = _DASH_RE.findall(txt)
            if found_dashes:
                self.lore_list.insert(tk.END, "── Dash Issues ──\n", "dash_hdr")
                self.lore_list.tag_config("dash_hdr", foreground="#ff8c00", font=("Arial", 9, "bold"))
                seen = set()
                for d in found_dashes:
                    if d in seen:
                        continue
                    seen.add(d)
                    self.lore_list.insert(tk.END, f"  Found: \"{d}\"\n", "dash_found")
                    self.lore_list.insert(tk.END, "  Suggest: \"...\" (trailing off) or \"—\" (break)\n", "dash_suggest")
                    for label, replacement in [("Insert ...", "..."), ("Insert —", "—")]:
                        self.lore_list.insert(tk.END, f"  [{label}]", f"dash_btn_{label}")
                        self.lore_list.tag_config(f"dash_btn_{label}", foreground="#6fb3ff", underline=True)
                        self.lore_list.tag_bind(f"dash_btn_{label}", "<Button-1>",
                                                lambda e, r=replacement: self.quick_insert(r))
                    self.lore_list.insert(tk.END, "\n")
                self.lore_list.tag_config("dash_found", foreground="#ff5555")
                self.lore_list.tag_config("dash_suggest", foreground=self.colors["label_fg"])

        # Possible Anachronisms sidebar — always run, regardless of category
        from lore_engine import IN_UNIVERSE_VOCAB
        if self.current_category == "Possible Anachronisms":
            instances = self.queues["Possible Anachronisms"].get(txt, [])
            stored_hits = instances[0].get("hits", []) if instances else []
            if not stored_hits:
                stored_hits = self.lore_engine.scan_anachronisms(txt)
        else:
            stored_hits = self.lore_engine.scan_anachronisms(txt)

        if stored_hits:
            self.lore_list.insert(tk.END, "── Possible Anachronisms ──\n", "anach_hdr")
            self.lore_list.tag_config("anach_hdr", foreground="#ff8c00", font=("Arial", 9, "bold"))
            seen_words = set()
            for found, suggestion in stored_hits:
                word_lower = found.lower()
                if word_lower in seen_words:
                    continue
                seen_words.add(word_lower)
                val = IN_UNIVERSE_VOCAB.get(word_lower)
                # Check context-specific override ("modern→archaic") before generic archaic def
                if val is not None:
                    override_key = f"{word_lower}→{val.lower()}"
                    defn = self.lore_engine.get_definition(override_key) or \
                           self.lore_engine.get_definition(val.lower()) or ""
                else:
                    defn = ""
                defn_str = f"  — {defn}" if defn else ""
                if val is not None:
                    self.lore_list.insert(tk.END, f"  \"{found}\"  →  {val}{defn_str}\n", "anach_item")
                else:
                    self.lore_list.insert(tk.END, f"  \"{found}\"  — no direct replacement{defn_str}\n", "anach_flag")
            self.lore_list.tag_config("anach_item", foreground="#ffa040")
            self.lore_list.tag_config("anach_flag", foreground=self.colors["label_fg"])

        self.lore_list.config(state="disabled")
        self.jp_txt.config(state="disabled")

        # Adjacent context
        self._update_adjacent()

        # Initial trigger
        self._update_preview()
        self._update_counters()
        self.translate_with_deepl()

    def _refresh_et_display(self):
        """Update the entry type badge and rules summary from self.entry_type."""
        et_rules = self.parent.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
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
        """Called when the entry type combobox value changes — refresh display and recompute limit."""
        self.entry_type = self.entry_type_var.get().strip()
        et_rules_now = self.parent.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        self.effective_limit = et_rules_now.get("char_limit") or self.limit
        self._refresh_et_display()
        self._update_counters()

    def save_entry_type(self):
        """Write the current entry_type value back to col 9 in all instances of this row."""
        new_type = self.entry_type_var.get().strip()
        self.entry_type = new_type
        self._refresh_et_display()
        txt = self.current_texts[self.current_idx]
        instances = self.queues[self.current_category].get(txt, [])
        for inst in instances:
            try:
                raw, dialect, rows = _read_csv(inst['path'])
                r_idx = inst['row_idx']
                if r_idx < len(rows):
                    while len(rows[r_idx]) <= 9:
                        rows[r_idx].append("")
                    rows[r_idx][9] = new_type
                    if not self.parent.prev_var.get():
                        with open(inst['path'], 'w', encoding='utf-8-sig', newline='') as f:
                            csv.writer(f, dialect).writerows(rows)
            except Exception as e:
                print(f"Error saving entry type: {e}")

    def on_archetype_selected(self, e=None):
        self.update_archetype_hint()

    def update_archetype_hint(self):
        self.archetype_hint.config(state="normal")
        self.archetype_hint.delete(1.0, tk.END)
        label = self.archetype_var.get()
        if label == "(none)" or not self.speaker_name:
            self.archetype_hint.insert(tk.END, "No archetype assigned.")
        else:
            # Find the key from the selected label
            idx = self.archetype_combo["values"].index(label) if label in self.archetype_combo["values"] else -1
            key = self.archetype_keys[idx] if idx >= 0 else None
            if key and key in self.lore_engine.archetypes:
                a = self.lore_engine.archetypes[key]
                #profs = ", ".join(a.get("professions", [])) or "—"
                notes = a.get("notes", "—")
                self.archetype_hint.insert(tk.END, f"[{key}] {a['name']}\n", "header")
                #self.archetype_hint.insert(tk.END, f"Typical roles: {profs}\n\n")
                self.archetype_hint.insert(tk.END, notes)
                self.archetype_hint.tag_config("header", font=("Arial", 9, "bold"),
                                               foreground=self.colors["counter_fg"])
        # Always show note if one exists for this speaker
        note_text = self.parent.cm.config.get("speaker_notes", {}).get(self.speaker_name, "") if self.speaker_name else ""
        if note_text:
            self.archetype_hint.insert(tk.END, f"\n\n📝 {note_text}", "note_tag")
            self.archetype_hint.tag_config("note_tag", foreground=self.colors["fg"], font=("Arial", 9, "italic"))
        self.archetype_hint.config(state="disabled")

    def save_archetype(self):
        if not self.speaker_name:
            return
        label = self.archetype_var.get()
        if label == "(none)":
            self.parent.cm.config.setdefault("speaker_archetypes", {}).pop(self.speaker_name, None)
        else:
            idx = list(self.archetype_combo["values"]).index(label) if label in self.archetype_combo["values"] else -1
            key = self.archetype_keys[idx] if idx >= 0 else None
            if key:
                self.parent.cm.config.setdefault("speaker_archetypes", {})[self.speaker_name] = key
        # Save note
        note_text = self.speaker_note_var.get().strip()
        if note_text:
            self.parent.cm.config.setdefault("speaker_notes", {})[self.speaker_name] = note_text
        else:
            self.parent.cm.config.setdefault("speaker_notes", {}).pop(self.speaker_name, None)
        self.parent.cm.save_all()
        self.update_archetype_hint()

    def _sync_txt_scroll(self, *args):
        """Keep the vertical scrollbar and the counter strip in sync with the text widget."""
        self._txt_yscroll.set(*args)
        # Scroll cnt_lbl to match txt's vertical position
        first, _ = self.txt.yview()
        self.cnt_lbl.yview_moveto(first)

    def _update_adjacent(self):
        """Populate the prev/next context panels with the lines on either side of the current item."""
        if not hasattr(self, 'adj_prev_txt'):
            return
        for widget, offset, arrow in [
            (self.adj_prev_txt, -1, "▲ "),
            (self.adj_next_txt, +1, "▼ "),
        ]:
            widget.config(state="normal")
            widget.delete(1.0, tk.END)
            if self._adj_path and self._adj_row_idx >= 0:
                try:
                    _, _, rows = _read_csv(self._adj_path)
                    target = self._adj_row_idx + offset
                    if 0 < target < len(rows):
                        adj = rows[target]
                        adj_jp = (adj[2] if len(adj) > 2 else "").replace("\n", " ")
                        adj_en = (adj[3] if len(adj) > 3 else "").replace("\n", " ")
                        widget.insert(tk.END, arrow,       "adj_arrow")
                        widget.insert(tk.END, adj_jp + "\n", "adj_jp")
                        widget.insert(tk.END, "   " + adj_en, "adj_en")
                    else:
                        widget.insert(tk.END, f"{arrow}—")
                except Exception:
                    widget.insert(tk.END, f"{arrow}(error)")
            else:
                widget.insert(tk.END, f"{arrow}—")
            widget.tag_config("adj_arrow", foreground=self.colors["label_fg"])
            widget.tag_config("adj_jp",    foreground=self.colors["counter_fg"])
            widget.tag_config("adj_en",    foreground=self.colors["fg"])
            widget.config(state="disabled")

    def rewrap_text(self):
        current_text = self.txt.get(1.0, tk.END).strip()
        wrapped = self.engine.master_tag_wrap(current_text, self.effective_limit)
        if wrapped != current_text:
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, wrapped)
            self._update_counters()
            self._update_preview()

    def _sync_preview_font_controls(self):
        """Update font-size and spacing spinboxes to reflect the currently selected box."""
        if not hasattr(self, '_prev_font_sz_var'):
            return
        box_key = self._preview_box_var.get()
        meta = self._box_meta.get(box_key, {})
        self._prev_font_sz_var.set(str(meta.get("font_sz", 12)))
        self._prev_spacing_var.set(str(meta.get("line_spacing", 1)))

    def _on_preview_font_changed(self, *args):
        """Save font size and line spacing for the current preview box, rebuild font, refresh preview."""
        box_key = self._preview_box_var.get()
        meta = self._box_meta.get(box_key)
        if meta is None:
            return
        try:
            new_sz = max(6, min(48, int(self._prev_font_sz_var.get())))
            new_sp = max(0, min(30, int(self._prev_spacing_var.get())))
        except (ValueError, tk.TclError):
            return
        meta["font_sz"] = new_sz
        meta["line_spacing"] = new_sp
        self._rebuild_preview_font(box_key)
        pf = self.parent.cm.config.setdefault("preview_font", {})
        pf.setdefault(box_key, {})["font_sz"] = new_sz
        pf.setdefault(box_key, {})["line_spacing"] = new_sp
        self.parent.cm.save_all()
        self._update_preview()

    def _rebuild_preview_font(self, box_key):
        """Recreate the PIL font object for box_key and recompute line_h from current meta."""
        if not _PIL_OK:
            return
        meta = self._box_meta.get(box_key)
        if meta is None:
            return
        _asset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        _font_candidates = [
            os.path.join(_asset_dir, "DDONfont.otf"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "DDONfont.otf"),
        ]
        _font_path = next((p for p in _font_candidates if os.path.exists(p)), None)
        fnt = None
        if _font_path:
            try:
                fnt = ImageFont.truetype(_font_path, meta["font_sz"])
            except Exception:
                pass
        if fnt:
            self._preview_font_objs[box_key] = fnt
            bbox = fnt.getbbox("あ")
            glyph_h = bbox[3] - bbox[1]
            meta["line_h"] = glyph_h + meta.get("line_spacing", 1)
        else:
            meta["line_h"] = meta["font_sz"] + 3

    def replace_dashes(self, replacement):
        """Replace double-dash patterns with replacement.
        Covers: -- (hyphens), —— (em dash U+2014), ―― (horiz bar U+2015),
        –– (en dash U+2013), and any mixed combinations of two or more."""
        current_text = self.txt.get(1.0, tk.END)
        fixed = re.sub(r'[-–—―]{2,}', replacement, current_text)
        # If replacing with ellipsis (...), ensure a space before the next word/digit
        if replacement == "...":
            fixed = re.sub(r'\.\.\.(\w)', r'... \1', fixed)
        if fixed != current_text:
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, fixed)
            self._update_counters()
            self._update_preview()

    def quick_insert(self, text):
        self.txt.insert(tk.INSERT, text)
        self._update_counters()
        self._update_preview()

    def _apply_tag_to_text(self, search_term, tag_name):
        start = "1.0"
        while True:
            start = self.jp_txt.search(search_term, start, stopindex=tk.END)
            if not start: break
            end = f"{start}+{len(search_term)}c"
            self.jp_txt.tag_add(tag_name, start, end)
            start = end

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

        # --- Anachronism highlighting (always runs when toggle is on) ---
        self.txt.tag_remove("anachronism", "1.0", tk.END)
        self.anach_ranges = []

        if self.in_universe_var.get():
            from lore_engine import IN_UNIVERSE_VOCAB
            full_text = self.txt.get("1.0", tk.END)
            hits = self.lore_engine.scan_anachronisms(full_text)

            for found, suggestion in hits:
                # Collect all possible suggestions for this word
                word_lower = found.lower()
                suggestions = []
                if word_lower in IN_UNIVERSE_VOCAB and IN_UNIVERSE_VOCAB[word_lower]:
                    suggestions.append((IN_UNIVERSE_VOCAB[word_lower], "primary"))

                pos = "1.0"
                while True:
                    pos = self.txt.search(found, pos, stopindex=tk.END, nocase=True)
                    if not pos:
                        break
                    end = f"{pos}+{len(found)}c"
                    # Word-boundary check: char before start and char after end must not be word chars
                    char_before = self.txt.get(f"{pos}-1c", pos)
                    char_after  = self.txt.get(end, f"{end}+1c")
                    is_word_start = not char_before or not char_before.isalnum() and char_before != "'"
                    is_word_end   = not char_after  or not char_after.isalnum()  and char_after  != "'"
                    if is_word_start and is_word_end:
                        self.txt.tag_add("anachronism", pos, end)
                        self.anach_ranges.append((pos, end, found, suggestions))
                    pos = end

            self.txt.tag_config("anachronism", foreground="#ff8800", underline=True)

    def save_item(self):
        new_val = self.txt.get(1.0, tk.END).strip()
        lines = new_val.splitlines()

        # --- Blocker 0: Entry type restrictions ---
        current_et = self.entry_type_var.get().strip()
        et_rules = self.parent.cm.config.get("entry_type_rules", {}).get(current_et, {})
        forbidden_punct = et_rules.get("no_trailing_punct", [])
        if forbidden_punct and new_val and new_val[-1] in forbidden_punct:
            messagebox.showerror("Trailing Punctuation",
                f"Entry type '{current_et}' does not allow trailing '{new_val[-1]}'.\n"
                f"Remove it before saving.", parent=self)
            return

        # --- Blocker 1: Line length ---
        if not self.override_var.get():
            overlong = [i + 1 for i, l in enumerate(lines) if self.engine.get_simulated_len(l) > self.effective_limit]
            if overlong:
                ln_str = ", ".join(str(n) for n in overlong)
                messagebox.showerror("Line Too Long",
                    f"Line{'s' if len(overlong) > 1 else ''} {ln_str} exceed{'s' if len(overlong) == 1 else ''} "
                    f"the {self.effective_limit}-char limit. Fix before saving.", parent=self)
                return

        # --- Blocker 2: Line limit (too many lines) ---
        if not self.override_var.get() and len(lines) >= self.wall_limit:
            messagebox.showerror("Too Many Lines",
                f"Text has {len(lines)} lines — line limit is {self.wall_limit - 1}. "
                f"Split or shorten before saving.", parent=self)
            return

        # --- Blocker 3: Missing tags vs Japanese source ---
        def extract_non_col_tags(text):
            return [t for t in re.findall(r'<([^>]+)>', text)
                    if not t.upper().startswith('COL') and t.upper() != '/COL']

        jp_tags = extract_non_col_tags(self.jp_source)
        en_tags = extract_non_col_tags(new_val)
        # Check as a multiset — same tag appearing N times in JP must appear N times in EN
        jp_counts, en_counts = Counter(jp_tags), Counter(en_tags)
        missing = list((jp_counts - en_counts).elements())
        extra   = list((en_counts - jp_counts).elements())
        if missing or extra:
            parts = []
            if missing: parts.append(f"Missing: {', '.join(f'<{t}>' for t in missing)}")
            if extra:   parts.append(f"Extra: {', '.join(f'<{t}>' for t in extra)}")
            if not messagebox.askyesno("Tag Mismatch",
                    f"Tag mismatch vs Japanese source.\n" + "\n".join(parts) +
                    "\n\nSave anyway?", parent=self):
                return

        old_val = self.current_texts[self.current_idx]
        # Write entry type (col 9) back to CSV if it changed
        self.save_entry_type()
        self.callback(self.queues[self.current_category][old_val], new_val, old_val)
        self.next_item()

    def next_item(self): self.current_idx += 1; self.load_item()
    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.parent.cm.config["dark_mode"] = self.dark_mode
        self.parent.cm.save_all()
        self.apply_theme_colors()
        for w in self.winfo_children(): w.destroy()
        self.setup_ui()
        self.load_item()
        # Rebind after UI rebuild — setup_ui recreates self.txt
        self._bind_tooltip()
        self.txt.bind("<Tab>", self._tab_insert_suggestion)

    def toggle_pane(self, name):
        """Toggle visibility of a sidebar pane."""
        if name == "ctx":
            if self.pane_ctx.winfo_ismapped():
                self.side_pane.forget(self.pane_ctx)
            else:
                self.side_pane.add(self.pane_ctx, before=self.pane_ai, height=300)
        elif name == "ai":
            if self.pane_ai.winfo_ismapped():
                self.side_pane.forget(self.pane_ai)
            else:
                self.side_pane.add(self.pane_ai)

    def change_category(self, e): 
        self.current_category = self.cat_combo.get()
        self.current_texts = list(self.queues[self.current_category].keys())
        self.current_idx = 0
        self.load_item()

    # --- API INTEGRATIONS ---

    def _is_chatting_setter(self, value):
        self._is_chatting = value
        btn_state = "disabled" if value else "normal"
        self.btn_chat_send.config(state=btn_state)

