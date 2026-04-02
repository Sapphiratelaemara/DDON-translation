import csv, os, threading, re, tkinter as tk
from tkinter import messagebox, filedialog, ttk, simpledialog, scrolledtext
from datetime import datetime
from collections import defaultdict

# CRITICAL IMPORTS
try:
    from config_manager import ConfigManager
    from translator_engine import TranslationEngine
    from lore_engine import LoreEngine
    from options_module import OptionsMenu
except ImportError as e:
    print(f"CRITICAL ERROR: Missing module file! {e}")
    input("Press Enter to close...")
    exit()

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

        # Single tooltip instance — bound once, reads self.anach_ranges dynamically
        self._bind_tooltip()
        # Tab inserts suggestion at cursor
        self.txt.bind("<Tab>", self._tab_insert_suggestion)

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
            }

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
        self.speaker_note_entry.bind("<FocusOut>", lambda e: self.save_archetype())
        self.speaker_note_entry.bind("<Return>",   lambda e: self.save_archetype())

        # Entry type combobox — populated from configured type keys
        spk_lbl("Type:").pack(side="left", padx=(14, 2))
        et_keys = [""] + sorted(self.parent.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_combo = ttk.Combobox(spk_frame, textvariable=self.entry_type_var,
                                             values=et_keys, width=24)
        self.entry_type_combo.pack(side="left", padx=(0, 4))
        self.entry_type_combo.bind("<<ComboboxSelected>>", self._on_entry_type_changed)
        self.entry_type_combo.bind("<Return>",              self._on_entry_type_changed)
        self.entry_type_combo.bind("<FocusOut>",            self._on_entry_type_changed)

        # Restrictions badge — shown when the selected type has rules
        self.entry_type_badge = tk.Label(spk_frame, text="",
                                         fg="white", bg="#2980b9",
                                         font=("Arial", 8, "bold"), padx=5, pady=1)
        self.entry_type_badge.pack(side="left", padx=(2, 0))

        # Restriction summary text — e.g. "no auto-wrap  ·  no trailing .,
        self.et_rules_lbl = tk.Label(spk_frame, text="",
                                     fg=self.colors["label_fg"], bg=self.colors["bg"],
                                     font=("Arial", 8, "italic"))
        self.et_rules_lbl.pack(side="left", padx=(4, 0))

        # ── Entry type row ── (separate row below speaker bar)
        et_frame = tk.Frame(self, bg=self.colors["bg"], padx=16, pady=2)
        et_frame.pack(fill="x")
        tk.Label(et_frame, text="Entry Type:", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        known_types = [""] + sorted(self.parent.cm.config.get("entry_type_rules", {}).keys())
        self.entry_type_var = tk.StringVar()
        self.entry_type_combo = ttk.Combobox(et_frame, textvariable=self.entry_type_var,
                                             values=known_types, width=36)
        self.entry_type_combo.pack(side="left", padx=(4, 6))
        self.entry_type_combo.bind("<<ComboboxSelected>>", self._on_entry_type_changed)
        self.entry_type_combo.bind("<Return>", self._on_entry_type_changed)
        tk.Button(et_frame, text="Save Type", command=self.save_entry_type,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  font=("Arial", 8), relief="flat", padx=6).pack(side="left")
        self.et_rules_lbl = tk.Label(et_frame, text="", fg=self.colors["label_fg"],
                                     bg=self.colors["bg"], font=("Arial", 8, "italic"))
        self.et_rules_lbl.pack(side="left", padx=(10, 0))

        # ── Main body ──
        main = tk.Frame(self, bg=self.colors["bg"])
        main.pack(fill="both", expand=True, padx=14, pady=4)

        # Left: editor + JP source
        left_f = tk.Frame(main, bg=self.colors["bg"])
        left_f.pack(side="left", fill="y")

        tk.Label(left_f, text="English", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w")
        self.txt = tk.Text(left_f, height=15, width=62, font=("Consolas", 12),
                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                           insertbackground=self.colors["insert_color"],
                           bd=0, padx=6, pady=4,
                           relief="flat", selectbackground=self.colors["accent"],
                           selectforeground="white")
        self.txt.pack(fill="y", expand=True)
        self.txt.bind("<KeyRelease>", self.update_counters)
        self.txt.bind("<<Paste>>", lambda e: self.after(0, self.update_counters))

        tk.Label(left_f, text="Japanese Source", fg=self.colors["label_fg"],
                 bg=self.colors["bg"], font=("Arial", 8, "bold")).pack(anchor="w", pady=(8, 0))
        self.jp_txt = tk.Text(left_f, height=10, width=62, font=("MS Gothic", 12),
                              bg=self.colors["jp_bg"], fg=self.colors["fg"],
                              insertbackground=self.colors["insert_color"],
                              state="disabled", bd=0, padx=6, pady=4, relief="flat")
        self.jp_txt.pack(fill="y", expand=True)

        # Char counter strip
        self.cnt_lbl = tk.Text(main, font=("Consolas", 10), width=4,
                               bg=self.colors["bg"], fg=self.colors["counter_fg"],
                               state="disabled", bd=0, highlightthickness=0)
        self.cnt_lbl.pack(side="left", fill="y", pady=4, padx=(2, 4))

        # Sidebar
        side = tk.Frame(main, bg=self.colors["sidebar_bg"])
        side.pack(side="right", fill="both", expand=True)
        tk.Label(side, text="References", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(anchor="w", padx=6, pady=(4, 0))
        self.lore_list = tk.Text(side, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                 bd=0, highlightthickness=0, font=("Arial", 10),
                                 wrap="word", state="disabled", padx=6, pady=4)
        self.lore_list.pack(fill="both", expand=True)
        tk.Frame(side, bg=self.colors["label_fg"], height=1).pack(fill="x", pady=2)
        tk.Label(side, text="Archetype Notes", fg=self.colors["label_fg"],
                 bg=self.colors["sidebar_bg"], font=("Arial", 8, "bold")).pack(anchor="w", padx=6)
        self.archetype_hint = tk.Text(side, bg=self.colors["text_bg"], fg=self.colors["fg"],
                                      bd=0, highlightthickness=0, font=("Arial", 9),
                                      wrap="word", state="disabled", height=7,
                                      padx=6, pady=4)
        self.archetype_hint.pack(fill="x")

        # ── Button bar ──
        btns = tk.Frame(self, bg=self.colors["bg"], pady=10)
        btns.pack(side="bottom", fill="x", padx=14)
        tk.Button(btns, text="Skip →", command=self.next_item,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="✓  Apply", command=self.save_item,
                  bg=self.colors["apply_bg"], fg="white",
                  width=18, relief="flat", font=("Arial", 10, "bold")).pack(side="left", padx=4)
        tk.Button(btns, text="―― → …", command=lambda: self.replace_dashes("…"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
        tk.Button(btns, text="―― → —", command=lambda: self.replace_dashes("—"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"],
                  width=10, relief="flat").pack(side="left", padx=4)
    
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
                self.destroy()
                return
        txt = self.current_texts[self.current_idx]
        self.info_lbl.config(text=f"REVIEWING: {self.current_idx+1}/{len(self.current_texts)}")
        self.txt.delete(1.0, tk.END)
        self.txt.insert(tk.END, txt)
        
        first_inst = self.queues[self.current_category][txt][0]
        try:
            with open(first_inst['path'], 'r', encoding='utf-8-sig', newline='') as f:
                raw = f.read()
            try:
                dialect = csv.Sniffer().sniff(raw[:4096])
            except csv.Error:
                dialect = csv.excel
            import io
            rows = list(csv.reader(io.StringIO(raw), dialect))
            row_data = rows[first_inst['row_idx']]
            jp_source = row_data[2] if len(row_data) > 2 else ""
            self.speaker_name = row_data[8].strip() if len(row_data) > 8 else ""
            self.entry_type = row_data[9].strip() if len(row_data) > 9 else first_inst.get('entry_type', "")
        except:
            jp_source = "Source Error"
            self.speaker_name = ""

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
                    self.lore_list.insert(tk.END, "  Suggest: \"…\" (trailing off) or \"—\" (break)\n", "dash_suggest")
                    for label, replacement in [("Insert …", "…"), ("Insert —", "—")]:
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
        self.update_counters()

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
                with open(inst['path'], 'r', encoding='utf-8-sig', newline='') as f:
                    raw = f.read()
                try:
                    dialect = csv.Sniffer().sniff(raw[:4096])
                except csv.Error:
                    dialect = csv.excel
                import io
                rows = list(csv.reader(io.StringIO(raw), dialect))
                r_idx = inst['row_idx']
                if r_idx < len(rows):
                    # Extend row if needed so col 9 exists
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

    def replace_dashes(self, replacement):
        """Replace double-dash patterns with replacement.
        Covers: -- (hyphens), —— (em dash U+2014), ―― (horiz bar U+2015),
        –– (en dash U+2013), and any mixed combinations of two or more."""
        current = self.txt.get(1.0, tk.END)
        fixed = re.sub(r'[-–—―]{2,}', replacement, current)
        # If replacing with ellipsis, ensure a space before the next word/digit
        if replacement == "…":
            fixed = re.sub(r'…(\w)', r'… \1', fixed)
        if fixed != current:
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, fixed.rstrip("\n"))
            self.update_counters()

    def quick_insert(self, text):
        self.txt.insert(tk.INSERT, text)
        self.update_counters()

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
        overlong = [i + 1 for i, l in enumerate(lines) if self.engine.get_simulated_len(l) > self.effective_limit]
        if overlong:
            ln_str = ", ".join(str(n) for n in overlong)
            messagebox.showerror("Line Too Long",
                f"Line{'s' if len(overlong) > 1 else ''} {ln_str} exceed{'s' if len(overlong) == 1 else ''} "
                f"the {self.effective_limit}-char limit. Fix before saving.", parent=self)
            return

        # --- Blocker 2: Line limit (too many lines) ---
        if len(lines) >= self.wall_limit:
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
        from collections import Counter
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

    def change_category(self, e): 
        self.current_category = self.cat_combo.get()
        self.current_texts = list(self.queues[self.current_category].keys())
        self.current_idx = 0
        self.load_item()

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
        self.tag_q, self.wall_q, self.dash_q, self.anach_q = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        self.engine = TranslationEngine(self.cm.config.get("tag_map", {}))
        self.apply_theme_colors()
        self.setup_ui()

    def setup_ui(self):
        self.root.configure(bg=self.colors["bg"])
        self.root.title("DDON CSV Batch Processor")
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
                with open(f_path, 'r', encoding='utf-8-sig', newline='') as f:
                    raw = f.read()

                # Detect dialect from the first 4KB so we write back identically
                try:
                    dialect = csv.Sniffer().sniff(raw[:4096])
                except csv.Error:
                    dialect = csv.excel   # safe fallback

                import io
                current_file_data = list(csv.reader(io.StringIO(raw), dialect))

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
        self.cm.save_all()

        # Respect Preview Mode — don't write to disk if user is just reviewing
        if self.prev_var.get():
            return

        for inst in instances:
            try:
                with open(inst['path'], 'r', encoding='utf-8-sig', newline='') as f:
                    raw = f.read()
                try:
                    dialect = csv.Sniffer().sniff(raw[:4096])
                except csv.Error:
                    dialect = csv.excel
                import io
                rows = list(csv.reader(io.StringIO(raw), dialect))
                if inst['row_idx'] < len(rows):
                    rows[inst['row_idx']][3] = new_text
                    with open(inst['path'], 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f, dialect).writerows(rows)
            except Exception as e:
                print(f"Error updating CSV: {e}")

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
        # Refresh preset dropdown so newly added/removed presets appear immediately
        self.preset_names = list(self.cm.config.get("presets", {"Standard": 50}).keys())
        self.preset_menu.configure(values=self.preset_names)
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