import sys
sys.dont_write_bytecode = True

import csv
import io as _io
import os
import re
import threading
import tkinter as tk
from collections import Counter, defaultdict
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


# CRITICAL IMPORTS
try:
    from config_manager import ConfigManager
    from translator_engine import TranslationEngine
    from lore_engine import LoreEngine
    from options_module import OptionsMenu
    from api_handler import DeepLClient, OpenRouterClient
except ImportError as e:
    print(f"CRITICAL ERROR: Missing module file! {e}")
    input("Press Enter to close...")
    exit()


# -------------------------
# CSV helper functions
# -------------------------
def _get_csv_files(folders):
    csvs = []
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if fn.lower().endswith(".csv"):
                csvs.append(os.path.join(folder, fn))
    return csvs

def _read_csv(path):
    """Read a CSV file, sniffing the delimiter but always using doublequote=True."""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        raw = f.read()
    try:
        dialect = csv.Sniffer().sniff(raw[:4096])
        dialect.doublequote = True
    except csv.Error:
        dialect = csv.excel
    return raw, dialect, list(csv.reader(_io.StringIO(raw), dialect))


class SearchWindow(tk.Toplevel):
    def __init__(self, parent, cm, app):
        super().__init__(parent)
        self.title("Global Database Search")
        self.geometry("900x500")
        self.cm = cm
        self.app = app
        
        self.configure(bg="#f5f6fa" if not app.dark_mode else "#1a1a2e")
        fg = "#2c2c3e" if not app.dark_mode else "#e0e0e0"
        
        top = tk.Frame(self, bg=self["bg"])
        top.pack(fill="x", padx=10, pady=10)
        
        tk.Label(top, text="Search Term:", bg=self["bg"], fg=fg).pack(side="left")
        self.entry = tk.Entry(top, width=40)
        self.entry.pack(side="left", padx=5)
        self.entry.bind("<Return>", lambda e: self.do_search())
        
        self.lang_var = tk.StringVar(value="Both")
        ttk.Combobox(top, textvariable=self.lang_var, values=["Both", "English", "Japanese"], state="readonly", width=12).pack(side="left", padx=5)
        
        tk.Button(top, text="Search Splits", command=self.do_search).pack(side="left", padx=10)
        
        self.lbl_status = tk.Label(top, text="", bg=self["bg"], fg=fg)
        self.lbl_status.pack(side="left")
        
        cols = ("file", "row", "jp", "en")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("file", text="File")
        self.tree.heading("row", text="Line")
        self.tree.heading("jp", text="Japanese")
        self.tree.heading("en", text="English")
        self.tree.column("file", width=150)
        self.tree.column("row", width=50)
        self.tree.column("jp", width=350)
        self.tree.column("en", width=350)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.tree.bind("<Double-1>", self.on_double_click)
        self.results_data = []

    def do_search(self):
        query = self.entry.get().strip().lower()
        if not query: return
            
        csv_files = _get_csv_files(self.cm.config.get("folders", []))
        if not csv_files:
            messagebox.showinfo("Error", "No folders loaded in Options!")
            return
            
        self.tree.delete(*self.tree.get_children())
        self.results_data.clear()
        self.lbl_status.config(text="Searching...")
        self.update_idletasks()
        
        mode = self.lang_var.get()
        count = 0
        
        for file in csv_files:
            try:
                _, _, rows = _read_csv(file)
                for i, row in enumerate(rows):
                    if i == 0 or len(row) < 6: continue
                    en = row[3]
                    jp = row[5]
                    
                    match = False
                    if mode in ["Both", "English"] and query in en.lower(): match = True
                    if mode in ["Both", "Japanese"] and query in jp.lower(): match = True
                    
                    if match:
                        display_name = os.path.basename(file)
                        idx = count
                        self.results_data.append({"path": file, "row_idx": i, "en": en, "jp": jp})
                        self.tree.insert("", "end", iid=str(idx), values=(display_name, i+1, jp.replace('\n', ' '), en.replace('\n', ' ')))
                        count += 1
            except Exception: pass
            
        self.lbl_status.config(text=f"Found {count} results. Double-click to edit.")

    def on_double_click(self, e):
        sel = self.tree.selection()
        if not sel: return
        data = self.results_data[int(sel[0])]
        
        pseudo_queue = {
            "Search Result": {
                data["en"]: [{
                    "path": data["path"],
                    "row_idx": data["row_idx"],
                    "tag_reason": "search_result"
                }]
            }
        }
        
        ReviewEditor(self.app, pseudo_queue, self.app.engine, self.cm, self.app.lore_engine, callback=self.app.propagate_fix).open_window()


class ReviewEditor(tk.Toplevel):
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

    def _build_suggestion_text(self, word):
        """Return tooltip text: archaic alternatives + cached definition.
        Checks 'modern→archaic' context override first, then falls back to archaic definition."""
        from lore_engine import IN_UNIVERSE_VOCAB
        word_lower = word.lower()
        options = []
        if word_lower in IN_UNIVERSE_VOCAB:
            val = IN_UNIVERSE_VOCAB[word_lower]
            if val:
                options.append(val)
        if not options:
            return f"⚠ \"{word}\" — no direct replacement (flag only)"
        opts_str = "  /  ".join(options)
        tip = f"⚠ \"{word}\"  →  {opts_str}   (Tab to insert)"
        # Check context-specific override first (e.g. "are→art"), then generic archaic definition
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
        """Bind tooltip to the txt widget. Safe to call multiple times (e.g. after dark mode toggle)."""
        # (Re)create the tooltip label — destroy old one if present
        if hasattr(self, '_tip_label') and self._tip_label.winfo_exists():
            self._tip_label.destroy()
        self._tip_label = tk.Label(
            self, text="", bg="#ffffe0", fg="black",
            relief="solid", borderwidth=1, font=("Arial", 9),
            wraplength=400, justify="left"
        )
        self._tip_visible = False
        self._hovered_range = None

        def on_motion(event):
            idx = self.txt.index(f"@{event.x},{event.y}")
            for entry in self.anach_ranges:
                start, end, word, _ = entry
                if self.txt.compare(start, "<=", idx) and self.txt.compare(idx, "<", end):
                    tip = self._build_suggestion_text(word)
                    self._tip_label.config(text=tip)
                    rx = event.x_root - self.winfo_rootx() + 20
                    ry = event.y_root - self.winfo_rooty() + 10
                    self._tip_label.place(x=rx, y=ry)
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
        """On Tab: replace the hovered word (if tooltip is showing) or the word
        under the text cursor. Hover takes priority so mouse workflow feels natural."""
        # Prefer the hovered word — so hovering + Tab works without moving the cursor
        if self._hovered_range:
            start, end, word, suggestions = self._hovered_range
        else:
            # Fall back to cursor position
            idx = self.txt.index(tk.INSERT)
            match = next(
                ((s, e, w, sg) for s, e, w, sg in self.anach_ranges
                 if self.txt.compare(s, "<=", idx) and self.txt.compare(idx, "<=", e)),
                None
            )
            if not match:
                return None   # not on a highlight — allow normal Tab
            start, end, word, suggestions = match

        if not suggestions:
            return "break"

        replacement = suggestions[0][0]
        matched = self.txt.get(start, end)
        first_alpha_orig = next((c for c in matched if c.isalpha()), None)
        first_alpha_idx  = next((i for i, c in enumerate(replacement) if c.isalpha()), None)
        if first_alpha_orig and first_alpha_orig.isupper() and first_alpha_idx is not None:
            replacement = (replacement[:first_alpha_idx]
                           + replacement[first_alpha_idx].upper()
                           + replacement[first_alpha_idx+1:])
        self.txt.delete(start, end)
        self.txt.insert(start, replacement)
        # Explicitly clear the tag on the replaced span — the indices shift after insert,
        # so recalculate end based on replacement length before update_counters re-scans
        new_end = f"{start}+{len(replacement)}c"
        self.txt.tag_remove("anachronism", start, new_end)
        # Hide tooltip
        if self._tip_visible:
            self._tip_label.place_forget()
            self._tip_visible = False
        self._hovered_range = None
        self.update_counters()
        return "break"

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
                       command=self.update_counters).pack(side="right", padx=10)

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
        self.txt.bind("<KeyRelease>", lambda e: [self.update_counters(e), self.update_preview(e)])
        self.txt.bind("<<Paste>>", lambda e: self.after(0, lambda: [self.update_counters(), self.update_preview()]))

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
                           command=lambda: [self._sync_preview_font_controls(), self.update_preview()]).pack(side="left", padx=4)

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
    
    def update_preview(self, e=None):
        # --- fnt MUST be defined before you use it ---
        box_key = self._preview_box_var.get()
        meta    = self._box_meta.get(box_key)
        base_img = self._preview_base_images.get(box_key)

        fnt = self._preview_font_objs.get(box_key)
        if fnt is None:
            print("NO FONT FOR BOX:", box_key)
            return

        vis_text = self.txt.get(1.0, tk.END).strip("\n")
        vis_text = re.sub(r'<[^>]+>', '', vis_text)
        lines = vis_text.splitlines()

        img_w = meta.get("img_w", self._prev_W)
        img_h = meta.get("img_h", self._prev_H)
        c = self.preview_canvas
        c.config(width=img_w, height=img_h)

        if not base_img or not _PIL_OK:
            c.delete("all")
            fill = "#2b2d2f" if box_key == "choice" else "#f2efdd"
            c.create_rectangle(0, 0, img_w, img_h, fill=fill, outline="")
            return

        render_img = base_img.copy()
        draw = ImageDraw.Draw(render_img)

        pad      = meta["pad"]
        text_col = meta["fg"]
        tx, ty   = pad, pad
        tw, th   = img_w - 2 * pad, img_h - 2 * pad

        COMPRESS = 0.90

        # --- wrap using compressed width ---
        wrapped = []
        for line in lines:
            buf = ""
            for word in line.split():
                test = buf + (" " if buf else "") + word
                if fnt.getlength(test) * COMPRESS > tw:
                    wrapped.append(buf)
                    buf = word
                else:
                    buf = test
            if buf:
                wrapped.append(buf)

        visible_lines = wrapped[:6]

        line_h = meta["line_h"]
        LEFT_PAD = 15

        # --- render lines directly ---
        for i, line in enumerate(visible_lines):
            y = ty + i * line_h
            draw.text((tx + LEFT_PAD, y), line, font=fnt, fill=text_col)

        if len(wrapped) > 6:
            draw.text(
                (tx + LEFT_PAD, ty + 6 * line_h - 12),
                f"▼ +{len(wrapped) - 6} lines clipped",
                fill="#ff4444"
            )

        self._current_preview_tk = ImageTk.PhotoImage(render_img)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._current_preview_tk)


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
        self.update_preview()
        self.update_counters()
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
        self.update_counters()

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
            self.update_counters()
            self.update_preview()

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
        self.update_preview()

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
            self.update_counters()
            self.update_preview()

    def quick_insert(self, text):
        self.txt.insert(tk.INSERT, text)
        self.update_counters()
        self.update_preview()

    def _apply_tag_to_text(self, search_term, tag_name):
        start = "1.0"
        while True:
            start = self.jp_txt.search(search_term, start, stopindex=tk.END)
            if not start: break
            end = f"{start}+{len(search_term)}c"
            self.jp_txt.tag_add(tag_name, start, end)
            start = end

    def update_counters(self, e=None):
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

    def click_deepl_suggestion(self, event=None):
        """Paste the DeepL suggestion into the main editor."""
        suggestion = self.deepl_box.get(1.0, tk.END).strip()
        if suggestion and suggestion != "Translating..." and not suggestion.startswith("ERROR"):
            current = self.txt.get(1.0, tk.END).strip()
            if current and not messagebox.askyesno("Overwrite", "Overwrite current English text with DeepL suggestion?", parent=self):
                return
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, suggestion)
            self.update_counters()
            self.update_preview()

    def change_category(self, e): 
        self.current_category = self.cat_combo.get()
        self.current_texts = list(self.queues[self.current_category].keys())
        self.current_idx = 0
        self.load_item()

    # --- API INTEGRATIONS ---

    def translate_with_deepl(self):
        source_text = self.jp_txt.get(1.0, tk.END).strip()
        if not source_text or self._is_translating: return

        # Check Cache first
        cached = self.parent.cm.get_cached("deepl", source_text)
        if cached:
            self.deepl_box.config(state="normal")
            self.deepl_box.delete(1.0, tk.END)
            self.deepl_box.insert(tk.END, cached)
            self.deepl_box.config(state="disabled")
            return

        key = self.parent.cm.get_key("deepl_api_key")
        if not key: return # Silently skip if no key, user can set it in options

        self._is_translating = True
        self.deepl_box.config(state="normal")
        self.deepl_box.delete(1.0, tk.END)
        self.deepl_box.insert(tk.END, "Translating...")
        self.deepl_box.config(state="disabled")
        
        def worker():
            client = DeepLClient(key)
            target_lang = self.parent.cm.config.get("deepl_target_lang", "EN-US")
            res = client.translate(source_text, target_lang=target_lang)
            
            def finalize():
                self.deepl_box.config(state="normal")
                self.deepl_box.delete(1.0, tk.END)
                if "text" in res:
                    self.deepl_box.insert(tk.END, res["text"])
                    self.parent.cm.set_cached("deepl", source_text, res["text"])
                else:
                    self.deepl_box.insert(tk.END, f"ERROR: {res.get('error')}")
                self.deepl_box.config(state="disabled")
                self._is_translating = False

            self.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def _save_selected_model(self, e=None):
        model = self.chat_model_var.get()
        self.parent.cm.config["selected_openrouter_model"] = model
        self.parent.cm.save_all()

    def clear_chat(self):
        self.chat_history.config(state="normal")
        self.chat_history.delete(1.0, tk.END)
        self.chat_history.config(state="disabled")

    def add_chat_context(self):
        jp = self.jp_txt.get(1.0, tk.END).strip()
        en = self.txt.get(1.0, tk.END).strip()
        context = f"\n[Context]\nJP: {jp}\nEN: {en}\n"
        self.chat_input.insert(tk.END, context)
        self.chat_input.see(tk.END)

    def _chat_on_return(self, e):
        if not e.state & 0x1: # No Shift held
            self.send_ai_chat()
            return "break"

    def _is_chatting_setter(self, value):
        self._is_chatting = value
        btn_state = "disabled" if value else "normal"
        self.btn_chat_send.config(state=btn_state)

    def refresh_model_list(self):
        """Reload the model list from config (updated in Options)."""
        models = self.parent.cm.config.get("openrouter_models", ["openrouter/auto"])
        self.chat_model_combo.config(values=models)
        # Verify current selection still exists
        current = self.chat_model_var.get()
        if current not in models:
            self.chat_model_var.set("openrouter/auto")
        messagebox.showinfo("AI Assistant", "Model list reloaded from configuration.")

    def send_ai_chat(self):
        if self._is_chatting: return
        key = self.parent.cm.get_key("openrouter_api_key")
        if not key:
            messagebox.showwarning("OpenRouter", "No OpenRouter API key found in Options.")
            return

        user_msg = self.chat_input.get(1.0, tk.END).strip()
        if not user_msg: return

        model = self.chat_model_var.get()
        
        # Check Cache (keyed by model + prompt)
        cache_key = f"{model}::{user_msg}"
        cached = self.parent.cm.get_cached("openrouter", cache_key)
        if cached:
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user") # Still show user msg
            self.chat_history.tag_config("user", foreground=self.colors["counter_fg"], font=("Arial", 9, "bold"))
            self.chat_history.insert(tk.END, f"\nAI: {cached}\n", "ai")
            self.chat_history.tag_config("ai", foreground=self.colors["fg"])
            self.chat_history.see(tk.END)
            self.chat_history.config(state="disabled")
            self.chat_input.delete(1.0, tk.END)
            return

        # UI Update (Not in cache)
        self._is_chatting = True
        self.btn_chat_send.config(state="disabled", text="...")
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
        self.chat_history.tag_config("user", foreground=self.colors["counter_fg"], font=("Arial", 9, "bold"))
        self.chat_history.see(tk.END)
        self.chat_history.config(state="disabled")
        self.chat_input.delete(1.0, tk.END)
        def worker():
            client = OpenRouterClient(key)
            # Simple system prompt for DDON localization
            messages = [
                {"role": "system", "content": "You are a DDON localization assistant. Help the user translate or refine dialogue while respecting the game's medieval fantasy tone and character archetypes."},
                {"role": "user", "content": user_msg}
            ]
            res = client.chat(messages, model=model)
            
            def finalize():
                self.chat_history.config(state="normal")
                if "text" in res:
                    self.chat_history.insert(tk.END, f"\nAI: {res['text']}\n", "ai")
                    self.chat_history.tag_config("ai", foreground=self.colors["fg"])
                    self.parent.cm.set_cached("openrouter", cache_key, res["text"])
                else:
                    self.chat_history.insert(tk.END, f"\nERROR: {res.get('error')}\n", "error")
                    self.chat_history.tag_config("error", foreground="#ff4444")
                
                self.chat_history.see(tk.END)
                self.chat_history.config(state="disabled")
                self._is_chatting = False
                self.btn_chat_send.config(state="normal", text="Send")

            self.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

class CSVTranslationWindow(tk.Toplevel):
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

        # Separate context text removed as it moved to sidebar
        # (This block was already modified in previous turn but cleaning up leftovers if any)

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

    def _update_preview(self, e=None):
        box_key  = self._preview_box_var.get()
        meta     = self._box_meta.get(box_key)
        base_img = self._preview_base_images.get(box_key)
        fnt      = self._preview_font_objs.get(box_key)
        if not fnt or not _PIL_OK or not base_img:
            return
        vis_text = re.sub(r'<[^>]+>', '', self.txt.get(1.0, tk.END).strip("\n"))
        lines    = vis_text.splitlines()
        img_w    = meta.get("img_w", self._prev_W)
        img_h    = meta.get("img_h", self._prev_H)
        self.preview_canvas.config(width=img_w, height=img_h)
        render   = base_img.copy()
        draw     = ImageDraw.Draw(render)
        pad, fg  = meta["pad"], meta["fg"]
        tw       = img_w - 2 * pad
        COMPRESS = 0.90
        wrapped  = []
        for line in lines:
            buf = ""
            for word in line.split():
                test = buf + (" " if buf else "") + word
                if fnt.getlength(test) * COMPRESS > tw:
                    wrapped.append(buf); buf = word
                else:
                    buf = test
            if buf:
                wrapped.append(buf)
        line_h = meta["line_h"]
        for i, line in enumerate(wrapped[:6]):
            draw.text((pad + 15, pad + i * line_h), line, font=fnt, fill=fg)
        if len(wrapped) > 6:
            draw.text((pad + 15, pad + 6 * line_h - 12),
                      f"▼ +{len(wrapped) - 6} lines clipped", fill="#ff4444")
        self._current_preview_tk = ImageTk.PhotoImage(render)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self._current_preview_tk)

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
    def _build_suggestion_text(self, word):
        from lore_engine import IN_UNIVERSE_VOCAB
        word_lower = word.lower()
        val = IN_UNIVERSE_VOCAB.get(word_lower)
        if not val:
            return f"⚠ \"{word}\" — no direct replacement (flag only)"
        tip  = f"⚠ \"{word}\"  →  {val}   (Tab to insert)"
        defn = self.lore_engine.get_definition(f"{word_lower}→{val.lower()}") or \
               self.lore_engine.get_definition(val.lower())
        if defn:
            tip += f"\n{defn}"
        return tip

    def _bind_tooltip(self):
        if hasattr(self, '_tip_label') and self._tip_label.winfo_exists():
            self._tip_label.destroy()
        self._tip_label = tk.Label(
            self, text="", bg="#ffffe0", fg="black",
            relief="solid", borderwidth=1, font=("Arial", 9),
            wraplength=400, justify="left")
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
                        y=event.y_root - self.winfo_rooty() + 10)
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
        if self._hovered_range:
            start, end, word, suggestions = self._hovered_range
        else:
            idx   = self.txt.index(tk.INSERT)
            match = next(
                ((s, e, w, sg) for s, e, w, sg in self.anach_ranges
                 if self.txt.compare(s, "<=", idx) and self.txt.compare(idx, "<=", e)), None)
            if not match:
                return None
            start, end, word, suggestions = match
        if not suggestions:
            return "break"
        replacement     = suggestions[0][0]
        matched         = self.txt.get(start, end)
        first_orig      = next((c for c in matched     if c.isalpha()), None)
        first_repl_idx  = next((i for i, c in enumerate(replacement) if c.isalpha()), None)
        if first_orig and first_orig.isupper() and first_repl_idx is not None:
            replacement = (replacement[:first_repl_idx]
                           + replacement[first_repl_idx].upper()
                           + replacement[first_repl_idx+1:])
        self.txt.delete(start, end)
        self.txt.insert(start, replacement)
        self.txt.tag_remove("anachronism", start, f"{start}+{len(replacement)}c")
        if self._tip_visible:
            self._tip_label.place_forget()
            self._tip_visible = False
        self._update_counters()
        return "break"

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

    def click_deepl_suggestion(self, event=None):
        """Paste the DeepL suggestion into the main editor."""
        suggestion = self.deepl_box.get(1.0, tk.END).strip()
        if suggestion and suggestion != "Translating..." and not suggestion.startswith("ERROR"):
            current = self.txt.get(1.0, tk.END).strip()
            if current and not messagebox.askyesno("Overwrite", "Overwrite current English text with DeepL suggestion?", parent=self):
                return
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, suggestion)
            self._update_counters()
            self._update_preview()

    # --- API INTEGRATIONS (Mirrored from ReviewEditor) ---

    def translate_with_deepl(self):
        source_text = self.jp_txt.get(1.0, tk.END).strip()
        if not source_text or self._is_translating: return

        # Check Cache first
        cached = self.cm.get_cached("deepl", source_text)
        if cached:
            self.deepl_box.config(state="normal")
            self.deepl_box.delete(1.0, tk.END)
            self.deepl_box.insert(tk.END, cached)
            self.deepl_box.config(state="disabled")
            return

        key = self.cm.get_key("deepl_api_key")
        if not key: return

        self._is_translating = True
        self.deepl_box.config(state="normal")
        self.deepl_box.delete(1.0, tk.END)
        self.deepl_box.insert(tk.END, "Translating...")
        self.deepl_box.config(state="disabled")
        
        def worker():
            from api_handler import DeepLClient
            client = DeepLClient(key)
            target_lang = self.cm.config.get("deepl_target_lang", "EN-US")
            res = client.translate(source_text, target_lang=target_lang)
            
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
        context = f"\n[Context]\nJP: {jp}\nEN: {en}\n"
        self.chat_input.insert(tk.END, context)
        self.chat_input.see(tk.END)

    def _chat_on_return(self, e):
        if not e.state & 0x1: # No Shift held
            self.send_ai_chat()
            return "break"

    def _is_chatting_setter(self, value):
        self._is_chatting = value
        btn_state = "disabled" if value else "normal"
        self.btn_chat_send.config(state=btn_state)

    def refresh_model_list(self):
        """Reload the model list from config (updated in Options)."""
        models = self.cm.config.get("openrouter_models", ["openrouter/auto"])
        self.chat_model_combo.config(values=models)
        current = self.chat_model_var.get()
        if current not in models:
            self.chat_model_var.set("openrouter/auto")
        messagebox.showinfo("AI Assistant", "Model list reloaded from configuration.")

    def send_ai_chat(self):
        if self._is_chatting: return
        key = self.cm.get_key("openrouter_api_key")
        source_text = self.jp_txt.get(1.0, tk.END).strip()
        user_msg = self.chat_input.get(1.0, tk.END).strip()
        if not user_msg: return
        
        if not key:
            messagebox.showwarning("OpenRouter", "No OpenRouter API key found in Options.")
            return

        model = self.chat_model_var.get()

        # Check Cache (keyed by model + prompt)
        cache_key = f"{model}::{user_msg}"
        cached = self.cm.get_cached("openrouter", cache_key)
        if cached:
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
            self.chat_history.tag_config("user", foreground=self.colors["counter_fg"], font=("Arial", 9, "bold"))
            self.chat_history.insert(tk.END, f"\nAI: {cached}\n", "ai")
            self.chat_history.tag_config("ai", foreground=self.colors["fg"])
            self.chat_history.see(tk.END)
            self.chat_history.config(state="disabled")
            self.chat_input.delete(1.0, tk.END)
            return

        # UI Update (Not in cache)
        self._is_chatting = True
        self.btn_chat_send.config(state="disabled", text="...")
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
        self.chat_history.tag_config("user", foreground=self.colors["counter_fg"], font=("Arial", 9, "bold"))
        self.chat_history.see(tk.END)
        self.chat_history.config(state="disabled")
        self.chat_input.delete(1.0, tk.END)

        def worker():
            from api_handler import OpenRouterClient
            client = OpenRouterClient(key)
            messages = [
                {"role": "system", "content": "You are a DDON localization assistant. Help the user translate or refine dialogue while respecting the game's medieval fantasy tone and character archetypes."},
                {"role": "user", "content": user_msg}
            ]
            res = client.chat(messages, model=model)
            
            def finalize():
                self.chat_history.config(state="normal")
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


class CSVProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DDON CSV Batch Processor")
        self.cm = ConfigManager()
        self.dark_mode = self.cm.config.get("dark_mode", False)
        self.preset_names = list(self.cm.config.get("presets", {"Standard": 50}).keys())
        self.wall_preset_names = list(self.cm.config.get("wall_presets", {"Standard": 7}).keys())
        self.preset_var = tk.StringVar(value=self.preset_names[0] if self.preset_names else "Standard")
        saved_wall = self.cm.config.get("wall_preset", self.wall_preset_names[0] if self.wall_preset_names else "Standard")
        self.wall_preset_var = tk.StringVar(value=saved_wall if saved_wall in self.wall_preset_names else (self.wall_preset_names[0] if self.wall_preset_names else "Standard"))
        self.prev_var = tk.BooleanVar(value=True)
        self.in_universe_var = tk.BooleanVar(value=self.cm.config.get("in_universe", False))
        self.status_var = tk.StringVar(value="Ready.")
        self.prog_var = tk.DoubleVar(value=0.0)
        self.tag_q, self.wall_q, self.dash_q, self.anach_q = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        self.engine = TranslationEngine(self.cm.config.get("tag_map", {}))
        self.apply_theme_colors()
        self.setup_ui()

    def setup_ui(self):
        self.root.configure(bg=self.colors["bg"])

        # ── Dashboard row ──
        dashboard_frame = tk.Frame(self.root, bg=self.colors["bg"])
        dashboard_frame.pack(fill="x", padx=10, pady=5)
        
        self.btn_search = tk.Button(dashboard_frame, text="Search Database (🔍)", command=self.open_search,
                                    bg=self.colors["btn_bg"], fg=self.colors["fg"], relief="flat", padx=10)
        self.btn_search.pack(side="left", padx=5)
        
        self.btn_analytics = tk.Button(dashboard_frame, text="Calculate Progress", command=self.calculate_progress,
                                       bg=self.colors["btn_bg"], fg=self.colors["fg"], relief="flat", padx=10)
        self.btn_analytics.pack(side="left", padx=5)

        self.btn_translate = tk.Button(dashboard_frame, text="✏ Translate CSV", command=self.open_translation_mode,
                                       bg=self.colors["accent"], fg="white", relief="flat", padx=10)
        self.btn_translate.pack(side="left", padx=5)
        
        self.lbl_progress = tk.Label(dashboard_frame, text="Translated: ---%", bg=self.colors["bg"], fg=self.colors["fg"])
        self.lbl_progress.pack(side="left", padx=10)

        self.root.minsize(750, 600)

        # ── Title bar ──
        title_bar = tk.Frame(self.root, bg=self.colors["accent"], pady=8)
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="DDON CSV Batch Processor",
                 bg=self.colors["accent"], fg="white",
                 font=("Arial", 13, "bold")).pack(side="left", padx=16)
        tk.Button(title_bar, text="🌙" if not self.dark_mode else "☀️",
                  command=self.toggle_global_dark_mode,
                  bg=self.colors["accent"], fg="white", bd=0,
                  font=("Arial", 12), activebackground=self.colors["accent"]).pack(side="right", padx=8)
        tk.Button(title_bar, text="⚙ Options",
                  command=self.open_options,
                  bg=self.colors["accent"], fg="white", bd=0,
                  font=("Arial", 10), activebackground=self.colors["accent"]).pack(side="right", padx=4)

        # ── Folders + Triggers ──
        top = tk.Frame(self.root, padx=12, pady=8, bg=self.colors["bg"])
        top.pack(fill="x")

        f_box = tk.LabelFrame(top, text=" Folders ", bg=self.colors["bg"], fg=self.colors["fg"],
                              font=("Arial", 9, "bold"))
        f_box.pack(side="left", fill="both", expand=True, padx=4)
        self.f_list = tk.Listbox(f_box, height=3, bg=self.colors["list_bg"],
                                 fg=self.colors["fg"], bd=0, selectbackground=self.colors["accent"],
                                 selectforeground="white", font=("Consolas", 9))
        self.f_list.pack(fill="both", padx=4, pady=2)
        for f in self.cm.config.get("folders", []): self.f_list.insert(tk.END, f)
        fb = tk.Frame(f_box, bg=self.colors["bg"])
        fb.pack(fill="x", padx=4, pady=2)
        for txt, cmd in [("+ Add", self.add_folder), ("− Remove", self.rem_folder)]:
            tk.Button(fb, text=txt, command=cmd, bg=self.colors["btn_bg"],
                      fg=self.colors["fg"], relief="flat", padx=6).pack(side="left", padx=2)

        t_box = tk.LabelFrame(top, text=" Triggers ", bg=self.colors["bg"], fg=self.colors["fg"],
                              font=("Arial", 9, "bold"))
        t_box.pack(side="right", fill="both", expand=True, padx=4)
        self.t_list = tk.Listbox(t_box, height=3, bg=self.colors["list_bg"],
                                 fg=self.colors["fg"], bd=0, selectbackground=self.colors["accent"],
                                 selectforeground="white", font=("Consolas", 9))
        self.t_list.pack(fill="both", padx=4, pady=2)
        for t in self.cm.config.get("triggers", []): self.t_list.insert(tk.END, t)
        tb = tk.Frame(t_box, bg=self.colors["bg"])
        tb.pack(fill="x", padx=4, pady=2)
        for txt, cmd in [("+ Add", self.add_trigger), ("− Remove", self.rem_trigger)]:
            tk.Button(tb, text=txt, command=cmd, bg=self.colors["btn_bg"],
                      fg=self.colors["fg"], relief="flat", padx=6).pack(side="left", padx=2)

        # ── Settings bar ──
        set_f = tk.Frame(self.root, bg=self.colors["bg"], padx=12, pady=6)
        set_f.pack(fill="x")
        for lbl, var, names in [
            ("Char limit:", self.preset_var, self.preset_names),
            ("Line limit:", self.wall_preset_var, self.wall_preset_names),
        ]:
            tk.Label(set_f, text=lbl, bg=self.colors["bg"], fg=self.colors["fg"],
                     font=("Arial", 9)).pack(side="left")
            cb = ttk.Combobox(set_f, textvariable=var, values=names, state="readonly", width=14)
            cb.pack(side="left", padx=(2, 10))
            if lbl.startswith("Char"):
                self.preset_menu = cb
            else:
                self.wall_preset_menu = cb

        sep = tk.Frame(set_f, bg=self.colors["btn_bg"], width=1, height=20)
        sep.pack(side="left", padx=8, fill="y")

        for txt, var in [("Preview Mode", self.prev_var), ("In-Universe Language", self.in_universe_var)]:
            tk.Checkbutton(set_f, text=txt, variable=var,
                           bg=self.colors["bg"], fg=self.colors["fg"],
                           selectcolor=self.colors["bg"],
                           activebackground=self.colors["bg"],
                           font=("Arial", 9)).pack(side="left", padx=4)

        # ── Log ──
        log_frame = tk.Frame(self.root, bg=self.colors["bg"], padx=12)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))
        tk.Label(log_frame, text="Scan Log", bg=self.colors["bg"], fg=self.colors["fg"],
                 font=("Arial", 9, "bold"), anchor="w").pack(fill="x")
        self.log_box = tk.Text(log_frame, height=10, bg=self.colors["log_bg"],
                               fg=self.colors["log_fg"], font=("Consolas", 9),
                               bd=1, relief="flat", padx=6, pady=4)
        self.log_box.pack(fill="both", expand=True)

        # ── Run button + progress ──
        bottom = tk.Frame(self.root, bg=self.colors["bg"], padx=12, pady=8)
        bottom.pack(fill="x", side="bottom")
        self.btn_run = tk.Button(bottom, text="▶  EXECUTE BATCH SCAN",
                                 bg=self.colors["run_bg"], fg="white",
                                 font=("Arial", 11, "bold"), height=2,
                                 bd=0, relief="flat", command=self.start_thread)
        self.btn_run.pack(fill="x", pady=(0, 4))
        self.progress = ttk.Progressbar(bottom, length=700)
        self.progress.pack(fill="x")

    def run_batch(self):
        selected_preset = self.preset_var.get()
        limit = self.cm.config.get("presets", {}).get(selected_preset, 50)
        selected_wall_preset = self.wall_preset_var.get()
        wall_limit = self.cm.config.get("wall_presets", {}).get(selected_wall_preset, 7)
        self.cm.config["wall_preset"] = selected_wall_preset
        self.cm.config["in_universe"] = self.in_universe_var.get()
        triggers = self.cm.config.get("triggers", [])
        do_in_universe = self.in_universe_var.get()
        self.cm.save_all()

        # Build replacement table once (only if needed)
        lore_engine = LoreEngine(self.cm.config.get("archetypes"))
        lore_engine.load_data(
            self.cm.config.get("bible_path", ""),
            self.cm.config.get("glossary_path", "")
        )
        in_universe_replacements = lore_engine.get_in_universe_replacements() if do_in_universe else {}

        self.tag_q.clear()
        self.wall_q.clear()
        self.dash_q.clear()

        # Dash pattern: two or more hyphens, OR two or more em-dashes
        _DASH_RE = re.compile(r'[-–—―]{2,}')

        all_files = []
        for folder in self.cm.config.get("folders", []):
            if os.path.exists(folder):
                all_files.extend([os.path.join(r, n) for r, d, fs in os.walk(folder) for n in fs if n.endswith('.csv')])

        if not all_files:
            self.root.after(0, self.finish_batch, limit, wall_limit)
            return

        def log(msg):
            self.root.after(0, lambda m=msg: (
                self.log_box.insert(tk.END, m + "\n"),
                self.log_box.see(tk.END)
            ))

        auto_fixed = 0
        reviewed   = 0

        # --- Hoist these outside the row loop for performance ---
        from collections import Counter
        known_tags = set(self.cm.config.get("tag_map", {}).keys())
        entry_type_rules = self.cm.config.get("entry_type_rules", {})

        # Pre-compile find & replace rules — skip disabled ones
        _compiled_rules = []
        for rule in self.cm.config.get("replace_rules", []):
            if not rule.get("enabled", True):
                continue
            find = rule.get("find", "")
            if not find:
                continue
            flags = 0 if rule.get("match_case") else re.IGNORECASE
            if rule.get("whole_word"):
                pattern = r'\b' + re.escape(find) + r'\b'
            else:
                pattern = re.escape(find)
            _compiled_rules.append({
                "pattern":             re.compile(pattern, flags),
                "replace":             rule.get("replace", ""),
                "include_speakers":    set(rule.get("include_speakers", [])),
                "exclude_speakers":    set(rule.get("exclude_speakers", [])),
                "include_entry_types": set(rule.get("include_entry_types", [])),
                "exclude_entry_types": set(rule.get("exclude_entry_types", [])),
            })

        def apply_replace_rules(text, speaker, entry_type):
            for rule in _compiled_rules:
                if rule["include_speakers"]    and speaker    not in rule["include_speakers"]:    continue
                if rule["exclude_speakers"]    and speaker    in  rule["exclude_speakers"]:       continue
                if rule["include_entry_types"] and entry_type not in rule["include_entry_types"]: continue
                if rule["exclude_entry_types"] and entry_type in  rule["exclude_entry_types"]:   continue
                text = rule["pattern"].sub(rule["replace"], text)
            return text

        _COL_NAME_RE = re.compile(r'(?i)<(?:COL(?: [A-F0-9]+)?|/COL)>|\[NAME\]')
        _TAG_RE      = re.compile(r'<([^>]+)>')

        def strip_known_tags(text):
            t = _COL_NAME_RE.sub('', text)
            def _strip(m):
                return '' if m.group(1).strip() in known_tags else m.group(0)
            return _TAG_RE.sub(_strip, t)

        def non_col_tags(text):
            return [t for t in _TAG_RE.findall(text)
                    if not t.upper().startswith('COL') and t.upper() != '/COL'
                    and t.strip() not in known_tags]

        for i, f_path in enumerate(all_files):
            pct = ((i + 1) / len(all_files)) * 100
            self.root.after(0, lambda v=pct: self.progress.configure(value=v))
            file_modded = False
            output_rows = []

            try:
                raw, dialect, current_file_data = _read_csv(f_path)

                for r_idx, row in enumerate(current_file_data):
                    # 1. Structural preservation
                    if len(row) <= 3:
                        output_rows.append(row)
                        continue

                    # 2. Trigger check
                    if triggers and not any(tr in "|".join(row) for tr in triggers):
                        output_rows.append(row)
                        continue

                    orig_text = row[3]
                    proposed_text = orig_text
                    needs_review = False
                    queue_type = None
                    wall_wrapped_text = ""

                    # Read entry type from col 9 (zero-indexed) and look up rules
                    entry_type = row[9].strip() if len(row) > 9 else ""
                    speaker    = row[8].strip() if len(row) > 8 else ""
                    et_rules = entry_type_rules.get(entry_type, {})
                    no_linebreak = et_rules.get("no_linebreak", False)
                    # Per-type char limit overrides the global preset when set
                    effective_limit = et_rules.get("char_limit") or limit

                    # 2b. Dash scan — skip if this text is already queued for mandatory review
                    if _DASH_RE.search(orig_text) and orig_text not in self.tag_q and orig_text not in self.wall_q:
                        self.dash_q[orig_text].append({'path': f_path, 'row_idx': r_idx, 'entry_type': entry_type})

                    # 2c. Anachronism scan — likewise skip if already in mandatory queues
                    anach_hits = lore_engine.scan_anachronisms(orig_text)
                    if anach_hits and orig_text not in self.tag_q and orig_text not in self.wall_q:
                        self.anach_q[orig_text].append({'path': f_path, 'row_idx': r_idx, 'hits': anach_hits, 'entry_type': entry_type})

                    # 3. Memory Branch
                    if orig_text in self.cm.memory:
                        learned = self.cm.memory[orig_text]
                        lines = learned.split('\n')
                        max_w = max((self.engine.get_simulated_len(l) for l in lines), default=0)
                        if max_w > effective_limit:
                            needs_review = True
                            queue_type = 'tag'
                            tag_reason = 'memory_overflow'
                            unknown_tags_found = []
                        else:
                            proposed_text = learned

                    # 4. Auto-Processing Branch
                    else:
                        jp_source = row[2] if len(row) > 2 else ""

                        # Strip COL, [NAME], and any registered tag_map tag before complexity check
                        clean_txt = strip_known_tags(orig_text)
                        is_complex = '<' in clean_txt

                        # --- Auto Tag Fix ---
                        if jp_source and is_complex:
                            jp_tags = non_col_tags(jp_source)
                            en_tags = non_col_tags(orig_text)
                            if Counter(jp_tags) != Counter(en_tags):
                                stripped = re.sub(r'<(?![Cc][Oo][Ll])[^>]+>', '', orig_text).strip()
                                if jp_tags:
                                    total_len = max(len(stripped), 1)
                                    repaired = stripped
                                    offset = 0
                                    for k, tag in enumerate(jp_tags):
                                        insert_pos = int((k + 1) / (len(jp_tags) + 1) * total_len) + offset
                                        insert_pos = min(insert_pos, len(repaired))
                                        repaired = repaired[:insert_pos] + f"<{tag}>" + repaired[insert_pos:]
                                        offset += len(f"<{tag}>")
                                    proposed_text = repaired
                                    orig_text = repaired
                                    is_complex = bool(non_col_tags(repaired))

                        # --- In-Universe replacements —
                        text_for_wrap = orig_text
                        if do_in_universe:
                            text_for_wrap = self.engine.apply_in_universe(orig_text, in_universe_replacements)

                        # --- Scoped find & replace rules ---
                        if _compiled_rules:
                            text_for_wrap = apply_replace_rules(text_for_wrap, speaker, entry_type)

                        # --- Auto-Processing Branch variables ---
                        tag_reason = ''
                        unknown_tags_found = []

                        # Respect no_linebreak — don't wrap if entry type forbids it
                        if no_linebreak:
                            wrapped = text_for_wrap
                        else:
                            wrapped = self.engine.master_tag_wrap(text_for_wrap, effective_limit)
                        wrap_lines = wrapped.split('\n')
                        wrap_max_w = max((self.engine.get_simulated_len(l) for l in wrap_lines), default=0)

                        if wrap_max_w > effective_limit:
                            needs_review = True
                            queue_type = 'tag'
                            # If there are unmapped tags, they're likely why wrapping failed
                            unknown_tags_found = non_col_tags(wrapped)
                            tag_reason = 'overflow_after_wrap' if not unknown_tags_found else 'unmapped_tags_overflow'
                        elif not no_linebreak and len(wrap_lines) >= wall_limit:
                            needs_review = True
                            queue_type = 'linelimit'
                            wall_wrapped_text = wrapped
                        elif wrapped != row[3]:
                            proposed_text = wrapped

                    # 5. Application
                    if needs_review:
                        if queue_type == 'tag':
                            self.tag_q[orig_text].append({
                                'path': f_path, 'row_idx': r_idx, 'entry_type': entry_type,
                                'tag_reason': tag_reason,
                                'unknown_tags': unknown_tags_found,
                            })
                        elif queue_type == 'linelimit':
                            self.wall_q[orig_text].append({'path': f_path, 'row_idx': r_idx, 'wrapped': wall_wrapped_text, 'entry_type': entry_type})
                    else:
                        if row[3] != proposed_text:
                            row[3] = proposed_text
                            file_modded = True

                    output_rows.append(row)

                # 6. Safety Write
                if file_modded and not self.prev_var.get() and len(output_rows) == len(current_file_data):
                    with open(f_path, 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f, dialect).writerows(output_rows)

                row_fixes = sum(1 for r in output_rows if r != current_file_data[output_rows.index(r)]) if file_modded else 0
                queued = sum(1 for t in [self.tag_q, self.wall_q, self.dash_q] 
                             for v in t.values() if any(inst['path'] == f_path for inst in v))
                if file_modded or queued:
                    log(f"{'[FIXED]' if file_modded else '[QUEUED]'} {os.path.basename(f_path)}"
                        + (f" — {queued} item(s) queued for review" if queued else ""))
                if file_modded:
                    auto_fixed += 1
                if queued:
                    reviewed += 1

            except Exception as e:
                self.root.after(0, lambda p=f_path, err=e: (
                    self.log_box.insert(tk.END, f"CRITICAL ERROR {os.path.basename(p)}: {err}\n"),
                    self.log_box.see(tk.END)
                ))
                continue

        log(f"─── Scan complete — {auto_fixed} file(s) auto-fixed, "
            f"{sum(len(v) for v in self.tag_q.values()) + sum(len(v) for v in self.wall_q.values()) + sum(len(v) for v in self.dash_q.values()) + sum(len(v) for v in self.anach_q.values())} item(s) queued for review ───")
        self.root.after(0, self.finish_batch, limit, wall_limit)

    def start_thread(self):
        self.btn_run.config(state="disabled")
        self.tag_q.clear(); self.wall_q.clear(); self.dash_q.clear(); self.anach_q.clear()
        self.log_box.delete(1.0, tk.END)
        threading.Thread(target=self.run_batch, daemon=True).start()

    def finish_batch(self, limit, wall_limit):
        self.btn_run.config(state="normal")
        if self.tag_q or self.wall_q or self.dash_q or self.anach_q:
            ReviewEditor(self, self.tag_q, self.wall_q, self.dash_q, self.anach_q,
                         limit, wall_limit, self.cm.config.get("tag_map", {}), self.propagate_fix)
        else:
            messagebox.showinfo("Done", "No issues found!")

    def toggle_global_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.cm.config["dark_mode"] = self.dark_mode
        self.cm.save_all()
        self.apply_theme_colors()
        for w in self.root.winfo_children(): w.destroy()
        self.setup_ui()

    def apply_theme_colors(self):
        if self.dark_mode:
            self.colors = {
                "bg":       "#1a1a2e",   # deep navy
                "fg":       "#e0e0e0",
                "list_bg":  "#16213e",
                "btn_bg":   "#0f3460",
                "log_bg":   "#0d0d1a",
                "log_fg":   "#c8c8d0",
                "accent":   "#e94560",
                "run_bg":   "#e94560",
            }
        else:
            self.colors = {
                "bg":       "#f5f6fa",
                "fg":       "#2c2c3e",
                "list_bg":  "#ffffff",
                "btn_bg":   "#dfe4ea",
                "log_bg":   "#ffffff",
                "log_fg":   "#2c2c3e",
                "accent":   "#3867d6",
                "run_bg":   "#20bf6b",
            }

    def propagate_fix(self, instances, new_text, orig_text):
        # Always update the in-memory fix dictionary
        self.cm.memory[orig_text] = new_text

        # Respect Preview Mode — don't write to disk if user is just reviewing
        if self.prev_var.get():
            return

        if not hasattr(self, 'pending_csv_writes'):
            self.pending_csv_writes = {}

        for inst in instances:
            self.pending_csv_writes.setdefault(inst['path'], []).append((inst['row_idx'], new_text))

    def flush_csv_writes(self):
        self.cm.save_memory()
        if not hasattr(self, 'pending_csv_writes') or not self.pending_csv_writes:
            return
            
        for path, writes in self.pending_csv_writes.items():
            try:
                raw, dialect, rows = _read_csv(path)
                for r_idx, new_text in writes:
                    if r_idx < len(rows):
                        rows[r_idx][3] = new_text
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    csv.writer(f, dialect).writerows(rows)
            except Exception as e:
                print(f"Error flushing CSV {path}: {e}")
        self.pending_csv_writes.clear()

    def open_search(self):
        SearchWindow(self.root, self.cm, self)
        
    def calculate_progress(self):
        csv_files = _get_csv_files(self.cm.config.get("folders", []))
        if not csv_files:
            messagebox.showinfo("Analytics", "No folders added. Go to Options to add folders.")
            return
            
        self.lbl_progress.config(text="Calculating...")
        self.root.update_idletasks()
        
        total_lines = 0
        translated = 0
        
        for file in csv_files:
            try:
                _, _, rows = _read_csv(file)
                for i, row in enumerate(rows):
                    if i == 0 or len(row) < 6:
                        continue
                    en_text = row[3].strip()
                    jp_text = row[5].strip()
                    if not jp_text: 
                        continue
                    total_lines += 1
                    if en_text and en_text != jp_text:
                        translated += 1
            except Exception:
                pass
                
        if total_lines == 0: 
            self.lbl_progress.config(text="No valid dialogue lines found.")
            return
            
        pct = (translated / total_lines) * 100
        self.lbl_progress.config(text=f"Translated: {translated:,}/{total_lines:,} ({pct:.1f}%)")

    def open_translation_mode(self):
        CSVTranslationWindow(self)

    def open_options(self):
        opt_win = OptionsMenu(self.root, self.cm).open_window()
        self.root.wait_window(opt_win)
        self.refresh_ui()

    def refresh_ui(self):
        self.preset_names = list(self.cm.config.get("presets", {"Standard": 50}).keys())
        self.wall_preset_names = list(self.cm.config.get("wall_presets", {"Standard": 7}).keys())
        self.f_list.delete(0, tk.END)
        for f in self.cm.config.get("folders", []): self.f_list.insert(tk.END, f)
        self.t_list.delete(0, tk.END)
        for t in self.cm.config.get("triggers", []): self.t_list.insert(tk.END, t)
        self.preset_menu.config(values=self.preset_names)
        self.wall_preset_menu.config(values=self.wall_preset_names)
        if self.preset_var.get() not in self.preset_names and self.preset_names:
            self.preset_var.set(self.preset_names[0])

    def add_folder(self):
        f = filedialog.askdirectory()
        if f: self.cm.config.setdefault("folders", []).append(f); self.f_list.insert(tk.END, f); self.cm.save_all()

    def rem_folder(self):
        sel = self.f_list.curselection()
        if sel: idx = sel[0]; self.f_list.delete(idx); self.cm.config["folders"].pop(idx); self.cm.save_all()

    def add_trigger(self):
        t = simpledialog.askstring("Trig", "Enter trigger:")
        if t: self.cm.config.setdefault("triggers", []).append(t); self.t_list.insert(tk.END, t); self.cm.save_all()

    def rem_trigger(self):
        sel = self.t_list.curselection()
        if sel: idx = sel[0]; self.t_list.delete(idx); self.cm.config["triggers"].pop(idx); self.cm.save_all()

if __name__ == "__main__":
    root = tk.Tk()
    app = CSVProcessorApp(root)
    root.mainloop()

