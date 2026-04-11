import sys
sys.dont_write_bytecode = True

import csv
import os
import re
import threading
import tkinter as tk
from collections import Counter
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
from gloss_engine import GlossEngine, GLOSS_AVAILABLE


class EditorWindow(SharedEditorMixin, tk.Toplevel):
    """
    Unified translation/review editor.

    mode="review"
        Opens a queue-driven review session.  Requires: tag_queue, wall_queue,
        dash_queue, anach_queue, limit, wall_limit, tag_map, callback.

    mode="translate"
        Opens a single CSV (or virtual search-result set) for translation.
        Pass virtual_rows=[...] to skip the file-open dialog.
    """

    def __init__(self, parent, mode="review", *,
                 # review-mode args
                 tag_queue=None, wall_queue=None, dash_queue=None, anach_queue=None,
                 limit=50, wall_limit=7, tag_map=None, callback=None,
                 # translate-mode args
                 virtual_rows=None):

        self.mode = mode

        # ── translate mode: resolve file path before creating window ──
        if mode == "translate":
            self._virtual_mode = virtual_rows is not None
            if not self._virtual_mode:
                path = filedialog.askopenfilename(
                    title="Open CSV for Translation",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
                if not path:
                    return
            else:
                path = None

        super().__init__(parent.root if mode == "review" else parent.root
                         if hasattr(parent, "root") else parent)

        self.parent = parent
        self.cm = parent.cm

        # ── mode-specific data setup ──
        if mode == "review":
            self.title("Dialogue Reviewer v5.3")
            self.geometry("1100x850")
            self.limit      = limit
            self.wall_limit = wall_limit
            self.tag_map    = tag_map or {}
            self.callback   = callback
            self.queues = {
                "Tag Issues (Complex Tags)": tag_queue or {},
                "Line Limit":               wall_queue or {},
                "Double Dashes":            dash_queue or {},
                "Possible Anachronisms":    anach_queue or {},
            }
            self.current_category = next(
                (cat for cat in self.queues if self.queues[cat]),
                "Tag Issues (Complex Tags)")
            self.current_texts = list(self.queues[self.current_category].keys())
            self.current_idx   = 0
            self.engine = TranslationEngine(self.tag_map)

        else:  # translate
            self.csv_path = path
            if self._virtual_mode:
                self._virtual_rows = virtual_rows
                self.title(f"Search Results — {len(virtual_rows)} entries")
                self.all_rows  = []
                self.dialect   = None
                self.data_rows = [(i, vr["row"]) for i, vr in enumerate(virtual_rows)]
            else:
                self.title(f"Translate — {os.path.basename(path)}")
                self.raw, self.dialect, self.all_rows = _read_csv(path)
                self.data_rows = [(i, r) for i, r in enumerate(self.all_rows)
                                  if i > 0 and len(r) > 2 and r[2].strip()]
            self.geometry("1200x820")
            presets      = self.cm.config.get("presets",      {"Standard": 50})
            wall_presets = self.cm.config.get("wall_presets", {"Standard": 7})
            self.limit      = list(presets.values())[0]
            self.wall_limit = list(wall_presets.values())[0]
            self.engine     = TranslationEngine(self.cm.config.get("tag_map", {}))
            self.show_translated_var = tk.BooleanVar(value=False)
            self.current_list_idx    = 0
            self._current_row_idx    = -1

        # ── shared state ──
        self.effective_limit = self.limit
        self.jp_source    = ""
        self.speaker_name = ""
        self.entry_type   = ""
        self.entry_type_var  = tk.StringVar()
        self.in_universe_var = tk.BooleanVar(value=self.cm.config.get("in_universe", False))

        self.lore_engine = LoreEngine(self.cm.config.get("archetypes"))
        self.lore_engine.load_data(
            self.cm.config.get("bible_path",    ""),
            self.cm.config.get("glossary_path", ""))

        self.anach_ranges   = []
        self._hovered_range = None
        self._tip_visible   = False
        self._tip_label     = tk.Label(self)

        # Gloss engine — shares the lore map so project terms take priority
        self._gloss_engine  = GlossEngine(self.lore_engine.lore_map)
        self._gloss_job_id  = 0   # incremented on each new load to cancel stale callbacks

        self._is_translating = False
        self._is_chatting    = False

        self.dark_mode = self.cm.config.get("dark_mode", False)
        self._apply_colors()
        self._setup_ui()

        if mode == "review":
            self.load_item()
            from lore_engine import IN_UNIVERSE_VOCAB
            self.lore_engine.prefetch_definitions(list(IN_UNIVERSE_VOCAB.keys()))
        else:
            self._populate_list()
            self._load_by_list_idx(0)

        self._bind_tooltip()
        self.txt.bind("<Tab>", self._tab_insert_suggestion)

        self.bind("<Control-Return>", lambda e: self._save_item())
        self.bind("<Control-Right>",  lambda e: self._next_item())
        self.bind("<Control-r>",      lambda e: self.rewrap_text())
        self.bind("<Control-d>",      lambda e: self.replace_dashes("—"))
        self.bind("<Control-D>",      lambda e: self.replace_dashes("..."))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_close(self):
        if self.mode == "review":
            self.parent.flush_csv_writes()
        self.destroy()

    # ------------------------------------------------------------------
    # Dark mode (review mode only, but harmless to call in translate)
    # ------------------------------------------------------------------

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.cm.config["dark_mode"] = self.dark_mode
        self.cm.save_all()
        self._apply_colors()
        for w in self.winfo_children():
            w.destroy()
        self._setup_ui()
        if self.mode == "review":
            self.load_item()
        else:
            self._populate_list()
            self._load_by_list_idx(self.current_list_idx)
        self._bind_tooltip()
        self.txt.bind("<Tab>", self._tab_insert_suggestion)

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def reload_glossary(self):
        """Refresh glossary data from disk and update dependent engines."""
        self.lore_engine.load_data(
            self.cm.config.get("bible_path",    ""),
            self.cm.config.get("glossary_path", ""))
        self._gloss_engine.update_lore_map(self.lore_engine.lore_map)
        # Re-populate current item to reflect changes in current view
        if hasattr(self, "jp_source") and self.jp_source:
            self._populate_editor(self.jp_source)

    def _setup_ui(self):
        self.configure(bg=self.colors["bg"])

        # ── Top control bar ──
        ctrl = tk.Frame(self, bg=self.colors["accent"], pady=6)
        ctrl.pack(fill="x")

        if self.mode == "review":
            self.cat_combo = ttk.Combobox(ctrl, values=list(self.queues.keys()),
                                          state="readonly", width=32)
            self.cat_combo.set(self.current_category)
            self.cat_combo.pack(side="left", padx=10)
            self.cat_combo.bind("<<ComboboxSelected>>", self._change_category)

            tk.Checkbutton(ctrl, text="In-Universe Language", variable=self.in_universe_var,
                           bg=self.colors["accent"], fg="white",
                           selectcolor=self.colors["accent"],
                           activebackground=self.colors["accent"],
                           command=self._update_counters).pack(side="left", padx=(10, 0))

            tk.Button(ctrl, text="🌙" if not self.dark_mode else "☀️",
                      command=self.toggle_dark_mode,
                      bg=self.colors["accent"], fg="white", bd=0,
                      font=("Arial", 12),
                      activebackground=self.colors["accent"]).pack(side="right", padx=8)

        else:  # translate
            display_name = "Search Results" if self._virtual_mode \
                           else os.path.basename(self.csv_path or "")
            tk.Label(ctrl, text=f"Translating: {display_name}",
                     bg=self.colors["accent"], fg="white",
                     font=("Arial", 11, "bold")).pack(side="left", padx=12)
            self.count_lbl = tk.Label(ctrl, text="",
                                      bg=self.colors["accent"], fg="white", font=("Arial", 9))
            self.count_lbl.pack(side="left", padx=8)

            tk.Checkbutton(ctrl, text="In-Universe Language", variable=self.in_universe_var,
                           bg=self.colors["accent"], fg="white",
                           selectcolor=self.colors["accent"],
                           activebackground=self.colors["accent"],
                           command=self._update_counters).pack(side="right", padx=10)

        # Sidebar toggle buttons — right side of top bar (both modes)
        tk.Button(ctrl, text="AI Assistant", command=lambda: self.toggle_pane("ai"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], font=("Arial", 8, "bold"),
                  relief="flat", padx=8).pack(side="right", padx=2)
        tk.Button(ctrl, text="Context", command=lambda: self.toggle_pane("ctx"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], font=("Arial", 8, "bold"),
                  relief="flat", padx=8).pack(side="right", padx=2)
        tk.Frame(ctrl, bg="white", width=1, height=20).pack(side="right", padx=6, fill="y")

        # ── Button bar (anchors to bottom before body) ──
        btns = tk.Frame(self, bg=self.colors["bg"], pady=10)
        btns.pack(side="bottom", fill="x", padx=14)

        if self.mode == "translate":
            tk.Button(btns, text="← Prev", command=self._prev_item,
                      bg=self.colors["btn_bg"], fg=self.colors["fg"],
                      width=8, relief="flat").pack(side="left", padx=4)

        tk.Button(btns, text="Skip →", command=self._next_item,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)

        save_label = "✓  Apply" if self.mode == "review" else "✓  Save"
        tk.Button(btns, text=save_label, command=self._save_item,
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
                       bg=self.colors["bg"], fg=self.colors["label_fg"],
                       selectcolor=self.colors["bg"], activebackground=self.colors["bg"],
                       font=("Arial", 9, "bold")).pack(side="right", padx=10)

        # ── Body ──
        body = tk.Frame(self, bg=self.colors["bg"])
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Row listbox — translate mode only, far left
        if self.mode == "translate":
            list_frame = tk.Frame(body, bg=self.colors["sidebar_bg"], width=300)
            list_frame.pack(side="left", fill="y")
            list_frame.pack_propagate(False)
            list_hdr = tk.Frame(list_frame, bg=self.colors["sidebar_bg"])
            list_hdr.pack(fill="x", padx=6, pady=4)
            tk.Checkbutton(list_hdr, text="Show translated",
                           variable=self.show_translated_var,
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

        # Main area — sidebar right, editor left
        main = tk.Frame(body, bg=self.colors["bg"])
        main.pack(side="left", fill="both", expand=True)

        # ── Sidebar (right) ──
        side = tk.Frame(main, bg=self.colors["sidebar_bg"], width=400)
        side.pack(side="right", fill="both", expand=(self.mode == "review"))
        side.pack_propagate(False)

        self.side_pane = tk.PanedWindow(side, orient="vertical", bg=self.colors["sidebar_bg"],
                                        sashwidth=4, bd=0)
        self.side_pane.pack(fill="both", expand=True)

        # Pane 1: References + Archetype Notes
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
                                      wrap="word", state="disabled", height=6, padx=6, pady=4)
        self.archetype_hint.pack(fill="x")

        # Pane 2: AI Assistant
        self.pane_ai = tk.Frame(self.side_pane, bg=self.colors["sidebar_bg"])
        self.side_pane.add(self.pane_ai)
        self.pane_ai.grid_rowconfigure(0, weight=0)
        self.pane_ai.grid_rowconfigure(1, weight=0)
        self.pane_ai.grid_rowconfigure(2, weight=1)
        self.pane_ai.grid_rowconfigure(3, weight=0)
        self.pane_ai.grid_columnconfigure(0, weight=1)

        ai_top = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        ai_top.grid(row=0, column=0, sticky="ew", padx=5, pady=(4, 2))
        tk.Label(ai_top, text="AI Assistant", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(side="left")
        self.chat_model_var = tk.StringVar(
            value=self.cm.config.get("selected_openrouter_model", "openrouter/auto"))
        models = self.cm.config.get("openrouter_models", ["openrouter/auto"])
        tk.Button(ai_top, text="↻", command=self.refresh_model_list,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=4).pack(side="right")
        self.chat_model_combo = ttk.Combobox(ai_top, textvariable=self.chat_model_var,
                                             values=models, state="readonly", width=32)
        self.chat_model_combo.pack(side="right", padx=(0, 4), fill="x", expand=True)
        self.chat_model_combo.bind("<<ComboboxSelected>>", self._save_selected_model)

        qf = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        qf.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 2))
        for lbl, tmpl in [
            ("Translate ↓", "Translate this dialogue from Japanese:\n{jp}"),
            ("Rephrase ↓",  "Rephrase in period-appropriate archaic English:\n{en}"),
            ("Archaize ↓",  "Rewrite using more archaic vocabulary (keep meaning):\n{en}"),
            ("Check ↓",     "Check this translation for accuracy and style:\nJP: {jp}\nEN: {en}"),
        ]:
            tk.Button(qf, text=lbl, font=("Arial", 7), relief="flat",
                      bg=self.colors["btn_bg"], fg=self.colors["fg"],
                      command=lambda t=tmpl: self._quick_prompt(t),
                      padx=3, pady=1).pack(side="left", padx=(0, 2))

        hist_frame = tk.Frame(self.pane_ai, bg=self.colors["text_bg"])
        hist_frame.grid(row=2, column=0, sticky="nsew")
        chat_scroll = tk.Scrollbar(hist_frame)
        chat_scroll.pack(side="right", fill="y")
        self.chat_history = tk.Text(hist_frame, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                    bd=0, highlightthickness=0, font=("Arial", 9),
                                    wrap="word", state="disabled", padx=6, pady=4,
                                    yscrollcommand=chat_scroll.set)
        self.chat_history.pack(side="left", fill="both", expand=True)
        chat_scroll.config(command=self.chat_history.yview)

        chat_input_f = tk.Frame(self.pane_ai, bg=self.colors["sidebar_bg"])
        chat_input_f.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        self.chat_input = tk.Text(chat_input_f, height=3, font=("Arial", 9),
                                  bg=self.colors["text_bg"], fg=self.colors["fg"],
                                  insertbackground=self.colors["fg"], undo=True)
        self.chat_input.pack(fill="x", pady=(0, 3))
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
        self._bind_chat_extras()

        # ── Editor panel (left of sidebar) ──
        left_f = tk.Frame(main, bg=self.colors["bg"])
        left_f.pack(side="left", fill="both", expand=True, padx=14, pady=4)

        # Info label — review mode shows queue position; translate shows nothing here
        # (translate puts count in the top bar)
        if self.mode == "review":
            self.info_lbl = tk.Label(left_f, text="",
                                     fg=self.colors["accent"], bg=self.colors["bg"],
                                     font=("Arial", 10, "bold"))
            self.info_lbl.pack(pady=(4, 0))

        # ── Speaker / Archetype bar ──
        spk_frame = tk.Frame(left_f, bg=self.colors["bg"], padx=0, pady=3)
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
        arch_opts   = self.lore_engine.get_archetype_options()
        arch_labels = ["(none)"] + [o[1] for o in arch_opts]
        self.archetype_keys  = [None] + [o[0] for o in arch_opts]
        self.archetype_var   = tk.StringVar(value="(none)")
        self.archetype_combo = ttk.Combobox(spk_frame, textvariable=self.archetype_var,
                                            values=arch_labels, state="disabled", width=28)
        self.archetype_combo.pack(side="left", padx=(4, 6))
        self.archetype_combo.bind("<<ComboboxSelected>>", self.on_archetype_selected)
        tk.Button(spk_frame, text="Save", command=self.save_archetype,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=6).pack(side="left")
        spk_lbl("Note:").pack(side="left", padx=(14, 2))
        self.speaker_note_var   = tk.StringVar()
        self.speaker_note_entry = tk.Entry(spk_frame, textvariable=self.speaker_note_var,
                                           width=26, font=("Arial", 9),
                                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                                           insertbackground=self.colors["fg"], relief="flat",
                                           state="disabled")
        self.speaker_note_entry.pack(side="left")
        self.make_context_menu(self.speaker_note_entry)
        self.speaker_note_entry.bind("<FocusOut>", lambda e: self.save_archetype())
        self.speaker_note_entry.bind("<Return>",   lambda e: self.save_archetype())

        # ── Entry type row ──
        et_frame = tk.Frame(left_f, bg=self.colors["bg"], padx=0, pady=2)
        et_frame.pack(fill="x")
        tk.Label(et_frame, text="Entry Type:", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        known_types = [""] + sorted(self.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_combo = ttk.Combobox(et_frame, textvariable=self.entry_type_var,
                                             values=known_types, width=36)
        self.entry_type_combo.pack(side="left", padx=(4, 6))
        for ev in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
            self.entry_type_combo.bind(ev, self._on_entry_type_changed)
        self.entry_type_badge = tk.Label(et_frame, text="", fg="white", bg="#2980b9",
                                         font=("Arial", 8, "bold"), padx=5, pady=1)
        self.entry_type_badge.pack(side="left", padx=(2, 4))
        tk.Button(et_frame, text="Save Type", command=self._save_entry_type,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=6).pack(side="left")
        self.et_rules_lbl = tk.Label(et_frame, text="", fg=self.colors["label_fg"],
                                     bg=self.colors["bg"], font=("Arial", 8, "italic"))
        self.et_rules_lbl.pack(side="left", padx=(10, 0))

        # ── English text box ──
        tk.Label(left_f, text="English", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w")

        en_outer = tk.Frame(left_f, bg=self.colors["bg"])
        en_outer.pack(fill="x")
        en_inner = tk.Frame(en_outer, bg=self.colors["bg"])
        en_inner.pack(fill="x", expand=True)

        self.cnt_lbl = tk.Text(en_inner, font=("Consolas", 12), width=4, height=6,
                               bg=self.colors["bg"], fg=self.colors["counter_fg"],
                               state="disabled", bd=0, highlightthickness=0, padx=0, pady=4)
        self.cnt_lbl.pack(side="right", fill="y", padx=(2, 0))

        txt_yscroll = tk.Scrollbar(en_inner, orient="vertical")
        txt_yscroll.pack(side="right", fill="y")

        self.txt = tk.Text(en_inner, height=6, font=("Consolas", 12),
                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                           insertbackground=self.colors["insert_color"],
                           bd=0, padx=6, pady=4, wrap="none", relief="flat",
                           selectbackground=self.colors["accent"],
                           selectforeground="white", undo=True,
                           yscrollcommand=self._sync_txt_scroll)
        self.make_context_menu(self.txt)
        txt_xscroll = tk.Scrollbar(en_inner, orient="horizontal", command=self.txt.xview)
        self.txt.configure(xscrollcommand=txt_xscroll.set)
        self.txt.pack(fill="x")
        txt_xscroll.pack(fill="x")
        txt_yscroll.config(command=self.txt.yview)
        self._txt_yscroll = txt_yscroll
        self.txt.bind("<KeyRelease>",
                      lambda e: [self._update_counters(e), self._update_preview(e)])
        self.txt.bind("<<Paste>>",
                      lambda e: self.after(0, lambda: [self._update_counters(), self._update_preview()]))

        # ── DeepL suggestion ──
        tk.Label(left_f, text="DeepL Suggestion (Click to paste)", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "italic")).pack(anchor="w", pady=(4, 0))
        self.deepl_box = tk.Text(left_f, height=2, font=("Consolas", 10),
                                  bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                  bd=0, padx=6, pady=4, relief="flat", wrap="word", cursor="hand2")
        self.deepl_box.pack(fill="x", pady=(0, 5))
        self.deepl_box.insert(tk.END, "Ready.")
        self.deepl_box.config(state="disabled")
        self.deepl_box.bind("<Button-1>", self.click_deepl_suggestion)

        # ── In-game preview ──
        self._build_preview_controls(left_f)

        # ── Japanese Source ──
        tk.Label(left_f, text="Japanese Source", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w", pady=(8, 0))
        self.jp_txt = tk.Text(left_f, height=4, font=("Meiryo", 11),
                              bg=self.colors["jp_bg"], fg=self.colors["fg"],
                              insertbackground=self.colors["insert_color"],
                              state="disabled", bd=0, padx=6, pady=4, relief="flat")
        self.make_context_menu(self.jp_txt)
        self.jp_txt.pack(fill="both", expand=True)

        # ── Gloss panel ──
        gloss_hdr = tk.Frame(left_f, bg=self.colors["bg"])
        gloss_hdr.pack(fill="x", pady=(6, 0))
        tk.Label(gloss_hdr, text="Gloss", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(side="left")
        self._gloss_status_lbl = tk.Label(
            gloss_hdr, text="" if GLOSS_AVAILABLE else "⚠ janome/jamdict not installed",
            fg=self.colors["label_fg"], bg=self.colors["bg"], font=("Arial", 8, "italic"))
        self._gloss_status_lbl.pack(side="left", padx=6)

        gloss_outer = tk.Frame(left_f, bg=self.colors["jp_bg"],
                               highlightthickness=1,
                               highlightbackground=self.colors["sidebar_bg"])
        gloss_outer.pack(fill="x", pady=(0, 4))
        gloss_scroll = tk.Scrollbar(gloss_outer, orient="horizontal")
        gloss_scroll.pack(side="bottom", fill="x")
        self.gloss_txt = tk.Text(
            gloss_outer, height=3, font=("Consolas", 9),
            bg=self.colors["jp_bg"], fg=self.colors["fg"],
            bd=0, padx=6, pady=4, relief="flat",
            wrap="none", state="disabled", cursor="arrow",
            xscrollcommand=gloss_scroll.set)
        gloss_scroll.config(command=self.gloss_txt.xview)
        self.gloss_txt.pack(fill="x")
        tk.Frame(left_f, bg=self.colors["label_fg"], height=1).pack(fill="x", pady=(4, 0))
        tk.Label(left_f, text="Context", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w")
        self.adj_prev_txt = tk.Text(left_f, height=2, font=("Consolas", 9),
                                    bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                    state="disabled", bd=0, padx=4, pady=2,
                                    relief="flat", wrap="word")
        self.adj_prev_txt.pack(fill="x", pady=(0, 1))
        self.adj_next_txt = tk.Text(left_f, height=2, font=("Consolas", 9),
                                    bg=self.colors["sidebar_bg"], fg=self.colors["fg"],
                                    state="disabled", bd=0, padx=4, pady=2,
                                    relief="flat", wrap="word")
        self.adj_next_txt.pack(fill="x")

    # ==================================================================
    # Navigation
    # ==================================================================

    def _next_item(self):
        if self.mode == "review":
            self.current_idx += 1
            self.load_item()
        else:
            self._load_by_list_idx(self.current_list_idx + 1)

    def _prev_item(self):
        """Translate mode only."""
        self._load_by_list_idx(self.current_list_idx - 1)

    def _change_category(self, e):
        """Review mode only."""
        self.current_category = self.cat_combo.get()
        self.current_texts    = list(self.queues[self.current_category].keys())
        self.current_idx      = 0
        self.load_item()

    # ==================================================================
    # Item loading — review mode
    # ==================================================================

    def load_item(self):
        """Review mode: load next item from the current queue category."""
        if self.current_idx >= len(self.current_texts):
            for cat, queue in self.queues.items():
                if cat != self.current_category and queue:
                    self.current_category = cat
                    self.cat_combo.set(cat)
                    self.current_texts = list(queue.keys())
                    self.current_idx   = 0
                    break
            else:
                self._on_close()
                return

        txt = self.current_texts[self.current_idx].replace("\r", "")
        self.override_var.set(False)
        self.info_lbl.config(text=f"REVIEWING: {self.current_idx+1}/{len(self.current_texts)}")
        self.txt.delete(1.0, tk.END)
        self.txt.insert(tk.END, txt)
        self.txt.edit_reset()
        self.txt.focus_set()

        first_inst = self.queues[self.current_category][txt][0]
        try:
            _, _, rows = _read_csv(first_inst['path'])
            row_data          = rows[first_inst['row_idx']]
            jp_source         = (row_data[2] if len(row_data) > 2 else "").replace("\r", "")
            self.speaker_name = row_data[8].strip() if len(row_data) > 8 else ""
            self.entry_type   = row_data[9].strip() if len(row_data) > 9 \
                                else first_inst.get('entry_type', "")
            self._adj_path    = first_inst['path']
            self._adj_row_idx = first_inst['row_idx']
        except Exception:
            jp_source         = "Source Error"
            self.speaker_name = ""
            self._adj_path    = None
            self._adj_row_idx = -1

        self._populate_editor(jp_source, txt)

        # Review-specific sidebar content
        self._populate_review_sidebar(txt)

        self.lore_list.config(state="disabled")
        self.jp_txt.config(state="disabled")
        self._update_adjacent()
        self._update_preview()
        self._update_counters()
        self.translate_with_deepl()

    # ==================================================================
    # Item loading — translate mode
    # ==================================================================

    def _is_translated(self, row):
        en = row[3].strip() if len(row) > 3 else ""
        jp = row[2].strip() if len(row) > 2 else ""
        return bool(en) and en != jp

    def _visible_rows(self):
        if self._virtual_mode:
            rows = [(i, vr["row"]) for i, vr in enumerate(self._virtual_rows)]
            return rows if self.show_translated_var.get() \
                   else [(i, r) for i, r in rows if not self._is_translated(r)]
        if self.show_translated_var.get():
            return self.data_rows
        return [(i, r) for i, r in self.data_rows if not self._is_translated(r)]

    def _populate_list(self):
        self.row_listbox.delete(0, tk.END)
        if self._virtual_mode:
            for i, vr in enumerate(self._virtual_rows):
                row        = vr["row"]
                speaker    = row[8].strip() if len(row) > 8 else ""
                jp_preview = row[2].replace("\n", " ")
                if len(jp_preview) > 30:
                    jp_preview = jp_preview[:30] + "…"
                translated = self._is_translated(row)
                src   = os.path.basename(vr["path"])
                label = f"{'✓ ' if translated else '  '}[{src}] {speaker}: {jp_preview}"
                self.row_listbox.insert(tk.END, label)
                if translated:
                    self.row_listbox.itemconfig(tk.END,
                        fg=self.colors["translated_fg"], bg=self.colors["translated_bg"])
            total = len(self._virtual_rows)
            done  = sum(1 for vr in self._virtual_rows if self._is_translated(vr["row"]))
        else:
            for orig_idx, row in self._visible_rows():
                speaker    = row[8].strip() if len(row) > 8 else ""
                jp_preview = row[2].replace("\n", " ")
                if len(jp_preview) > 38:
                    jp_preview = jp_preview[:38] + "…"
                translated = self._is_translated(row)
                label = f"{'✓ ' if translated else '  '}[{orig_idx}] {speaker}: {jp_preview}"
                self.row_listbox.insert(tk.END, label)
                if translated:
                    self.row_listbox.itemconfig(tk.END,
                        fg=self.colors["translated_fg"], bg=self.colors["translated_bg"])
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
        visible  = self._visible_rows()
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

    def _load_row(self, orig_idx, row):
        """Translate mode: populate editor from a CSV row."""
        self._current_row_idx = orig_idx
        jp = (row[2] if len(row) > 2 else "").replace("\r", "")
        en = (row[3] if len(row) > 3 else "").replace("\r", "")
        self.speaker_name = row[8].strip() if len(row) > 8 else ""
        self.entry_type   = row[9].strip() if len(row) > 9 else ""

        self.txt.delete(1.0, tk.END)
        self.txt.insert(tk.END, en)
        self.txt.edit_reset()
        self.txt.focus_set()

        self._populate_editor(jp, en)

        self.lore_list.config(state="disabled")
        self.jp_txt.config(state="disabled")
        self._update_adjacent()
        self._update_counters()
        self._update_preview()
        self.translate_with_deepl()

    def _clear_editor(self):
        self.txt.delete(1.0, tk.END)
        self.jp_txt.config(state="normal")
        self.jp_txt.delete(1.0, tk.END)
        self.jp_txt.config(state="disabled")

    # ==================================================================
    # Shared editor population
    # ==================================================================

    def _populate_editor(self, jp_source, en_text):
        """Fill all shared editor widgets from jp/en content.
        Called by both load_item (review) and _load_row (translate)."""

        # Speaker / archetype bar
        if self.speaker_name:
            self.speaker_lbl.config(text=self.speaker_name, fg=self.colors["counter_fg"])
            self.archetype_combo.config(state="readonly")
            self.speaker_note_entry.config(state="normal")
            saved_key = self.cm.config.get("speaker_archetypes", {}).get(self.speaker_name)
            if saved_key:
                self.archetype_var.set(self.lore_engine.get_archetype_label(saved_key))
            else:
                self.archetype_var.set("(none)")
            self.update_archetype_hint()
            saved_note = self.cm.config.get("speaker_notes", {}).get(self.speaker_name, "")
            self.speaker_note_var.set(saved_note)
        else:
            self.speaker_lbl.config(text="—", fg=self.colors["label_fg"])
            self.archetype_combo.config(state="disabled")
            self.speaker_note_entry.config(state="disabled")
            self.speaker_note_var.set("")
            self.archetype_var.set("(none)")
        self.update_archetype_hint()

        # Entry type
        et_keys = [""] + sorted(self.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_combo.config(values=et_keys)
        self.entry_type_var.set(self.entry_type)
        et_rules = self.cm.config.get("entry_type_rules", {}).get(self.entry_type, {})
        self.effective_limit = et_rules.get("char_limit") or self.limit
        self._refresh_et_display()

        # JP source
        self.jp_txt.config(state="normal")
        self.jp_txt.delete(1.0, tk.END)
        self.jp_txt.insert(tk.END, jp_source)
        self.jp_source = jp_source

        # Lore references
        self.lore_list.config(state="normal")
        self.lore_list.delete(1.0, tk.END)

        if jp_source:
            matches     = self.lore_engine.scan_text(jp_source)
            tag_display = self.cm.config.get("tag_display", {})
            for jp, en in matches:
                self.lore_list.insert(tk.END, f"• {jp}:  ", f"lore_label_{hash(jp)}")
                
                # Split multi-suggestion strings (comma, semicolon, pipe, newline, slash)
                suggestions = re.split(r'\s*[,;\|\n/]\s*', en)
                suggestions = [s.strip() for s in suggestions if s.strip()]
                # Filter out headers like "less common:"
                suggestions = [s for s in suggestions if not re.match(r'^(less|lesser|lesson)\s+common:?$', s, re.I)]
                
                for i, sug in enumerate(suggestions):
                    en_tag = f"lore_en_{hash(jp)}_{i}"
                    self.lore_list.insert(tk.END, sug, en_tag)
                    self.lore_list.tag_config(en_tag, foreground="#6fb3ff", underline=True)
                    self.lore_list.tag_bind(en_tag, "<Button-1>",
                                            lambda e, w=sug: self.quick_insert(w))
                    if i < len(suggestions) - 1:
                        self.lore_list.insert(tk.END, " | ")
                
                self.lore_list.insert(tk.END, "\n")
                
                # Clicking the highlighted Japanese word in the source box inserts the first suggestion
                j_insert = suggestions[0] if suggestions else en
                jtag = f"lore_{hash(jp)}"
                self.jp_txt.tag_config(jtag, foreground="#6fb3ff", underline=True)
                self.jp_txt.tag_bind(jtag, "<Button-1>", lambda e, w=j_insert: self.quick_insert(w))
                self._apply_tag_to_text(jp, jtag)
            if tag_display:
                shown = set()
                for tag_key, display_text in tag_display.items():
                    if f"<{tag_key}>" in jp_source and tag_key not in shown:
                        shown.add(tag_key)
                        self.lore_list.insert(tk.END,
                            f"  <{tag_key}>  =  \"{display_text}\"\n", "tag_disp")
                self.lore_list.tag_config("tag_disp", foreground="#aaaaaa",
                                          font=("Arial", 9, "italic"))
            if matches:
                self.lore_list.config(height=max(3, min(len(matches) + 1, 12)))

        # JP hover tooltip
        self._jp_tip_map = {}
        if jp_source:
            for jp, en in self.lore_engine.scan_text(jp_source):
                pos = "1.0"
                while True:
                    pos = self.jp_txt.search(jp, pos, stopindex=tk.END)
                    if not pos:
                        break
                    end_pos = f"{pos}+{len(jp)}c"
                    self._jp_tip_map[(pos, end_pos)] = en
                    pos = end_pos

        def _jp_motion(event):
            idx = self.jp_txt.index(f"@{event.x},{event.y}")
            for (s, e_), en_text in self._jp_tip_map.items():
                if self.jp_txt.compare(s, "<=", idx) and self.jp_txt.compare(idx, "<", e_):
                    self._tip_label.config(text=f"→  {en_text}")
                    self._tip_label.place(
                        x=event.x_root - self.winfo_rootx() + 20,
                        y=event.y_root - self.winfo_rooty() + 10)
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

        # Kick off async gloss for the new JP source
        self._load_gloss(jp_source)

    # ==================================================================
    # Gloss panel
    # ==================================================================

    # Tag colours for POS categories (light/dark aware via fallback)
    _GLOSS_POS_FG = {
        "noun":    "#6fb3ff",
        "verb":    "#7ddb8a",
        "adj":     "#f0b429",
        "adv":     "#e88aff",
        "interj":  "#ff8a80",
        "other":   "#cccccc",
    }

    def _load_gloss(self, jp_text: str) -> None:
        """Start an async gloss lookup and schedule _render_gloss on completion."""
        # Clear + show spinner
        self.gloss_txt.config(state="normal")
        self.gloss_txt.delete(1.0, tk.END)
        if GLOSS_AVAILABLE and jp_text and jp_text.strip():
            self.gloss_txt.insert(tk.END, "  analysing…")
            self._gloss_status_lbl.config(text="")
        self.gloss_txt.config(state="disabled")

        if not GLOSS_AVAILABLE or not jp_text or not jp_text.strip():
            return

        # Bump job counter so a stale thread's callback becomes a no-op
        self._gloss_job_id += 1
        job_id = self._gloss_job_id

        def _callback(tokens):
            # Schedule render on the Tk thread; discard if a newer job superseded this one
            self.after(0, lambda: self._render_gloss(tokens, job_id))

        self._gloss_engine.gloss_async(jp_text, _callback)

    def _render_gloss(self, tokens, job_id: int) -> None:
        """Populate gloss_txt with clickable, colour-coded morpheme spans."""
        if job_id != self._gloss_job_id:
            return  # superseded by a newer load

        self.gloss_txt.config(state="normal")
        self.gloss_txt.delete(1.0, tk.END)

        # Remove any previously registered gloss click/hover bindings
        stale_tags = [t for t in self.gloss_txt.tag_names() if t.startswith("_gt_")]
        for tag in stale_tags:
            self.gloss_txt.tag_delete(tag)

        # Tooltip label (reuse window-level _tip_label)
        tip = self._tip_label

        for i, tok in enumerate(tokens):
            surface = tok.surface
            cands   = tok.candidates

            if not cands or not surface.strip():
                # Non-glossable spacer — render as plain dim text
                plain_tag = f"_gt_plain_{i}"
                self.gloss_txt.insert(tk.END, surface, plain_tag)
                self.gloss_txt.tag_config(plain_tag,
                                          foreground=self.colors["label_fg"])
                continue

            # Colour by POS; lore terms get a distinct tint
            base_fg = "#e8c56a" if tok.is_lore else \
                      self._GLOSS_POS_FG.get(tok.pos, self._GLOSS_POS_FG["other"])

            tag_name = f"_gt_{i}"
            insert_str = f"{surface}[{cands[0]}]"
            if len(cands) > 1:
                insert_str += f"  "   # breathing room between tokens

            self.gloss_txt.insert(tk.END, insert_str, tag_name)
            self.gloss_txt.tag_config(tag_name, foreground=base_fg,
                                       underline=(len(cands) > 1))

            # Click → paste first candidate into English box
            def _on_click(e, c=cands[0]):
                self.txt.insert(tk.INSERT, c)
            self.gloss_txt.tag_bind(tag_name, "<Button-1>", _on_click)

            # Hover → show all candidates in tooltip
            all_cands_str = "  /  ".join(cands)

            def _on_enter(e, s=all_cands_str, is_lore=tok.is_lore):
                label = f"{'★ lore  ' if is_lore else ''}{s}"
                tip.config(text=label,
                           bg="#2d2d2d", fg="white",
                           font=("Arial", 9), bd=1, relief="solid", padx=4, pady=2)
                tip.place(x=e.x_root - self.winfo_rootx() + 16,
                          y=e.y_root - self.winfo_rooty() + 14)
                tip.lift()

            def _on_leave(e):
                tip.place_forget()

            self.gloss_txt.tag_bind(tag_name, "<Enter>", _on_enter)
            self.gloss_txt.tag_bind(tag_name, "<Leave>", _on_leave)

        self.gloss_txt.config(state="disabled")

    # ==================================================================
    # Review-mode sidebar content
    # ==================================================================

    def _populate_review_sidebar(self, txt):
        """Append review-specific annotations to lore_list after shared content."""
        if self.current_category == "Tag Issues (Complex Tags)":
            instances = self.queues["Tag Issues (Complex Tags)"].get(txt, [])
            if instances:
                inst         = instances[0]
                reason       = inst.get('tag_reason', '')
                seen_tags    = list(dict.fromkeys(inst.get('unknown_tags', [])))

                self.lore_list.insert(tk.END, "── Tag Issue ──\n", "tag_issue_hdr")
                self.lore_list.tag_config("tag_issue_hdr", foreground="#e94560",
                                          font=("Arial", 9, "bold"))
                if reason in ('overflow_after_wrap', 'unmapped_tags_overflow'):
                    body = (
                        "  Line-breaking ran but a line still overflows.\n"
                        "  The unmapped tags below are treated as zero-\n"
                        "  width, causing the limit to be miscalculated.\n\n"
                        if seen_tags else
                        "  Line-breaking ran but a line still overflows.\n"
                        "  All tags are mapped — the translation is\n"
                        "  simply too long. Shorten it.\n\n"
                    )
                elif reason == 'memory_overflow':
                    body = ("  A previously saved fix for this line now\n"
                            "  exceeds the character limit. Edit and re-apply.\n\n")
                else:
                    body = ("  This entry exceeded the character limit\n"
                            "  after line-breaking.\n\n")
                self.lore_list.insert(tk.END, body, "tag_reason_txt")
                self.lore_list.tag_config("tag_reason_txt", foreground=self.colors["fg"])

                if seen_tags:
                    self.lore_list.insert(tk.END, "  Unmapped tags:\n", "tag_issue_sub")
                    self.lore_list.tag_config("tag_issue_sub",
                                              foreground=self.colors["label_fg"],
                                              font=("Arial", 9, "bold"))
                    for tag in seen_tags:
                        self.lore_list.insert(tk.END, f"    <{tag}>\n", "tag_unknown")
                    self.lore_list.tag_config("tag_unknown", foreground="#e94560",
                                              font=("Consolas", 10))
                    self.lore_list.insert(tk.END,
                        "\n  Add these in Options → Tag Length Mapping\n"
                        "  to let the tool calculate their width.\n", "tag_tip")
                    self.lore_list.tag_config("tag_tip", foreground=self.colors["label_fg"],
                                              font=("Arial", 8, "italic"))

        if self.current_category == "Double Dashes":
            found_dashes = re.findall(r'[-–—―]{2,}', txt)
            if found_dashes:
                self.lore_list.insert(tk.END, "── Dash Issues ──\n", "dash_hdr")
                self.lore_list.tag_config("dash_hdr", foreground="#ff8c00",
                                          font=("Arial", 9, "bold"))
                seen = set()
                for d in found_dashes:
                    if d in seen:
                        continue
                    seen.add(d)
                    self.lore_list.insert(tk.END, f"  Found: \"{d}\"\n", "dash_found")
                    self.lore_list.insert(tk.END,
                        "  Suggest: \"...\" (trailing off) or \"—\" (break)\n", "dash_suggest")
                    for label, replacement in [("Insert ...", "..."), ("Insert —", "—")]:
                        self.lore_list.insert(tk.END, f"  [{label}]", f"dash_btn_{label}")
                        self.lore_list.tag_config(f"dash_btn_{label}",
                                                  foreground="#6fb3ff", underline=True)
                        self.lore_list.tag_bind(f"dash_btn_{label}", "<Button-1>",
                                                lambda e, r=replacement: self.quick_insert(r))
                    self.lore_list.insert(tk.END, "\n")
                self.lore_list.tag_config("dash_found",   foreground="#ff5555")
                self.lore_list.tag_config("dash_suggest", foreground=self.colors["label_fg"])

        from lore_engine import IN_UNIVERSE_VOCAB
        if self.current_category == "Possible Anachronisms":
            instances   = self.queues["Possible Anachronisms"].get(txt, [])
            stored_hits = instances[0].get("hits", []) if instances else []
            if not stored_hits:
                stored_hits = self.lore_engine.scan_anachronisms(txt)
        else:
            stored_hits = self.lore_engine.scan_anachronisms(txt)

        if stored_hits:
            self.lore_list.insert(tk.END, "── Possible Anachronisms ──\n", "anach_hdr")
            self.lore_list.tag_config("anach_hdr", foreground="#ff8c00",
                                      font=("Arial", 9, "bold"))
            seen_words = set()
            for found, _ in stored_hits:
                word_lower = found.lower()
                if word_lower in seen_words:
                    continue
                seen_words.add(word_lower)
                val = IN_UNIVERSE_VOCAB.get(word_lower)
                if val is not None:
                    override_key = f"{word_lower}→{val.lower()}"
                    defn = (self.lore_engine.get_definition(override_key) or
                            self.lore_engine.get_definition(val.lower()) or "")
                else:
                    defn = ""
                defn_str = f"  — {defn}" if defn else ""
                if val is not None:
                    self.lore_list.insert(tk.END,
                        f"  \"{found}\"  →  {val}{defn_str}\n", "anach_item")
                else:
                    self.lore_list.insert(tk.END,
                        f"  \"{found}\"  — no direct replacement{defn_str}\n", "anach_flag")
            self.lore_list.tag_config("anach_item", foreground="#ffa040")
            self.lore_list.tag_config("anach_flag", foreground=self.colors["label_fg"])

    # ==================================================================
    # Adjacent context
    # ==================================================================

    def _update_adjacent(self):
        if not hasattr(self, 'adj_prev_txt'):
            return
        for widget, offset, arrow in [
            (self.adj_prev_txt, -1, "▲ "),
            (self.adj_next_txt, +1, "▼ "),
        ]:
            widget.config(state="normal")
            widget.delete(1.0, tk.END)

            if self.mode == "review":
                if self._adj_path and self._adj_row_idx >= 0:
                    try:
                        _, _, rows = _read_csv(self._adj_path)
                        target = self._adj_row_idx + offset
                        if 0 < target < len(rows):
                            adj    = rows[target]
                            adj_jp = (adj[2] if len(adj) > 2 else "").replace("\n", " ")
                            adj_en = (adj[3] if len(adj) > 3 else "").replace("\n", " ")
                            widget.insert(tk.END, arrow,          "adj_arrow")
                            widget.insert(tk.END, adj_jp + "\n",  "adj_jp")
                            widget.insert(tk.END, "   " + adj_en, "adj_en")
                        else:
                            widget.insert(tk.END, f"{arrow}—")
                    except Exception:
                        widget.insert(tk.END, f"{arrow}(error)")
                else:
                    widget.insert(tk.END, f"{arrow}—")

            else:  # translate
                target = self._current_row_idx + offset
                if self._virtual_mode:
                    if 0 <= target < len(self._virtual_rows):
                        vr     = self._virtual_rows[target]
                        adj    = vr["row"]
                        adj_jp = (adj[2] if len(adj) > 2 else "").replace("\n", " ")
                        adj_en = (adj[3] if len(adj) > 3 else "").replace("\n", " ")
                        src    = os.path.basename(vr["path"])
                        widget.insert(tk.END, f"{arrow}[{src}] ", "adj_arrow")
                        widget.insert(tk.END, adj_jp + "\n",       "adj_jp")
                        widget.insert(tk.END, "   " + adj_en,      "adj_en")
                    else:
                        widget.insert(tk.END, f"{arrow}—")
                else:
                    if 0 < target < len(self.all_rows):
                        adj    = self.all_rows[target]
                        adj_jp = (adj[2] if len(adj) > 2 else "").replace("\n", " ")
                        adj_en = (adj[3] if len(adj) > 3 else "").replace("\n", " ")
                        widget.insert(tk.END, arrow,          "adj_arrow")
                        widget.insert(tk.END, adj_jp + "\n",  "adj_jp")
                        widget.insert(tk.END, "   " + adj_en, "adj_en")
                    else:
                        widget.insert(tk.END, f"{arrow}—")

            widget.tag_config("adj_arrow", foreground=self.colors["label_fg"])
            widget.tag_config("adj_jp",    foreground=self.colors["counter_fg"])
            widget.tag_config("adj_en",    foreground=self.colors["fg"])
            widget.config(state="disabled")

    # ==================================================================
    # Save
    # ==================================================================

    def _save_item(self):
        new_val = self.txt.get(1.0, tk.END).strip()
        lines   = new_val.splitlines()

        # Blocker 0: entry type restrictions
        current_et      = self.entry_type_var.get().strip()
        et_rules        = self.cm.config.get("entry_type_rules", {}).get(current_et, {})
        forbidden_punct = et_rules.get("no_trailing_punct", [])
        if forbidden_punct and new_val and new_val[-1] in forbidden_punct:
            messagebox.showerror("Trailing Punctuation",
                f"Entry type '{current_et}' does not allow trailing '{new_val[-1]}'.\n"
                f"Remove it before saving.", parent=self)
            return

        # Blocker 1: line length
        if not self.override_var.get():
            overlong = [i + 1 for i, l in enumerate(lines)
                        if self.engine.get_simulated_len(l) > self.effective_limit]
            if overlong:
                ln_str = ", ".join(str(n) for n in overlong)
                messagebox.showerror("Line Too Long",
                    f"Line{'s' if len(overlong) > 1 else ''} {ln_str} "
                    f"exceed{'s' if len(overlong) == 1 else ''} "
                    f"the {self.effective_limit}-char limit. Fix before saving.", parent=self)
                return

        # Blocker 2: too many lines
        if not self.override_var.get() and len(lines) >= self.wall_limit:
            messagebox.showerror("Too Many Lines",
                f"Text has {len(lines)} lines — limit is {self.wall_limit - 1}. "
                f"Split or shorten before saving.", parent=self)
            return

        # Blocker 3: tag mismatch (review mode only — translate mode doesn't have
        # a definitive JP source to validate against in the same strict way)
        if self.mode == "review":
            def extract_non_col_tags(text):
                return [t for t in re.findall(r'<([^>]+)>', text)
                        if not t.upper().startswith('COL') and t.upper() != '/COL']
            jp_counts = Counter(extract_non_col_tags(self.jp_source))
            en_counts = Counter(extract_non_col_tags(new_val))
            missing   = list((jp_counts - en_counts).elements())
            extra     = list((en_counts - jp_counts).elements())
            if missing or extra:
                parts = []
                if missing: parts.append(f"Missing: {', '.join(f'<{t}>' for t in missing)}")
                if extra:   parts.append(f"Extra: {', '.join(f'<{t}>' for t in extra)}")
                if not messagebox.askyesno("Tag Mismatch",
                        "Tag mismatch vs Japanese source.\n" + "\n".join(parts) +
                        "\n\nSave anyway?", parent=self):
                    return

        new_type = self.entry_type_var.get().strip()
        self._save_entry_type()

        if self.mode == "review":
            old_val = self.current_texts[self.current_idx]
            self.callback(self.queues[self.current_category][old_val], new_val, old_val)
            self._next_item()

        else:  # translate
            if self._current_row_idx < 0:
                return
            if self._virtual_mode:
                vr  = self._virtual_rows[self._current_row_idx]
                row = vr["row"]
                while len(row) <= 9:
                    row.append("")
                row[3] = new_val
                row[9] = new_type
                try:
                    _, dialect, file_rows = _read_csv(vr["path"])
                    r_idx = vr["row_idx"]
                    while len(file_rows[r_idx]) <= 9:
                        file_rows[r_idx].append("")
                    file_rows[r_idx][3] = new_val
                    file_rows[r_idx][9] = new_type
                    with open(vr["path"], "w", encoding="utf-8-sig", newline="") as fh:
                        csv.writer(fh, dialect).writerows(file_rows)
                except Exception as e:
                    messagebox.showerror("Save Error", str(e), parent=self)
                    return
            else:
                row = self.all_rows[self._current_row_idx]
                while len(row) <= 9:
                    row.append("")
                row[3] = new_val
                row[9] = new_type
                try:
                    with open(self.csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f, self.dialect).writerows(self.all_rows)
                except Exception as e:
                    messagebox.showerror("Save Error", str(e), parent=self)
                    return
            self._populate_list()
            self._next_item()

    def _save_entry_type(self):
        """Write current entry_type_var value to col 9."""
        new_type = self.entry_type_var.get().strip()
        self.entry_type = new_type
        self._refresh_et_display()

        if self.mode == "review":
            txt       = self.current_texts[self.current_idx]
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

        else:  # translate
            if self._current_row_idx < 0:
                return
            if self._virtual_mode:
                vr  = self._virtual_rows[self.current_list_idx]
                row = vr["row"]
                while len(row) <= 9:
                    row.append("")
                row[9] = new_type
                _, dialect, all_f_rows = _read_csv(vr["path"])
                all_f_rows[vr["row_idx"]] = row
                try:
                    with open(vr["path"], 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f, dialect).writerows(all_f_rows)
                except Exception as e:
                    messagebox.showerror("Save Error", str(e), parent=self)
            else:
                row = self.all_rows[self._current_row_idx]
                while len(row) <= 9:
                    row.append("")
                row[9] = new_type
                try:
                    with open(self.csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f, self.dialect).writerows(self.all_rows)
                except Exception as e:
                    messagebox.showerror("Save Error", str(e), parent=self)
