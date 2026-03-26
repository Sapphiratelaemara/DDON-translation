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
        self.jp_source = ""
        self.speaker_name = ""
        self.in_universe_var = tk.BooleanVar(value=self.parent.cm.config.get("in_universe", False))
        self.engine = TranslationEngine(tag_map)
        self.lore_engine = LoreEngine()
        self.lore_engine.load_data(
            self.parent.cm.config.get("bible_path", ""), 
            self.parent.cm.config.get("glossary_path", "")
        )

        self.queues = {
            "Tag Issues (Complex Tags)": tag_queue,
            "Line Limit": wall_queue,
            "Double Dashes": dash_queue,
            "Anachronisms": anach_queue,
        }
        self.current_category = next((cat for cat in self.queues if self.queues[cat]), "Tag Issues (Complex Tags)")
        self.current_texts = list(self.queues[self.current_category].keys())
        self.current_idx = 0
        self.anach_ranges = []   # list of (start_idx, end_idx, word, [(suggestion, label), ...])
        self.tooltip_window = None

        self.dark_mode = self.parent.cm.config.get("dark_mode", False)
        self.apply_theme_colors()
        self.setup_ui()
        self.load_item()

        # Single tooltip instance — bound once, reads self.anach_ranges dynamically
        self._bind_tooltip()
        # Tab inserts suggestion at cursor
        self.txt.bind("<Tab>", self._tab_insert_suggestion)

    def _build_suggestion_text(self, word):
        """Return all vocab entries whose key matches this word (case-insensitive),
        formatted as a tooltip string showing every option."""
        from lore_engine import IN_UNIVERSE_VOCAB
        word_lower = word.lower()
        # Collect exact key match first, then look for synonym group
        options = []
        if word_lower in IN_UNIVERSE_VOCAB:
            val = IN_UNIVERSE_VOCAB[word_lower]
            if val:
                options.append(val)
        # Deduplicate preserving order
        seen = set()
        unique = [o for o in options if not (o in seen or seen.add(o))]
        if not unique:
            return f"⚠ \"{word}\" — no direct replacement (flag only)"
        opts_str = "  /  ".join(unique)
        return f"⚠ \"{word}\"  →  {opts_str}   (Tab to insert)"

    def _bind_tooltip(self):
        """Bind tooltip to the txt widget itself using Motion/Leave.
        tag_bind("<Motion>") is unreliable on tk.Text — widget-level bindings
        fire consistently and we do the hit-test ourselves."""
        def on_motion(event):
            idx = self.txt.index(f"@{event.x},{event.y}")
            for start, end, word, _ in self.anach_ranges:
                if self.txt.compare(start, "<=", idx) and self.txt.compare(idx, "<", end):
                    tip = self._build_suggestion_text(word)
                    if self.tooltip_window:
                        # Reposition; update label text in case we moved to a different word
                        self.tooltip_window.geometry(f"+{event.x_root+20}+{event.y_root+10}")
                        for child in self.tooltip_window.winfo_children():
                            child.config(text=tip)
                    else:
                        self._show_tooltip(event.x_root, event.y_root, tip)
                    return
            # Not over any highlight
            self._hide_tooltip()

        def on_leave(event):
            self._hide_tooltip()

        self.txt.bind("<Motion>", on_motion, add="+")
        self.txt.bind("<Leave>",  on_leave,  add="+")

    def _show_tooltip(self, x_root, y_root, text):
        if self.tooltip_window:
            # Already showing — just reposition and update text if needed
            self.tooltip_window.geometry(f"+{x_root+20}+{y_root+10}")
            return
        tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.wm_transient(self)
        tw.geometry(f"+{x_root+20}+{y_root+10}")
        tk.Label(tw, text=text, bg="#ffffe0", fg="black",
                 relief="solid", borderwidth=1, font=("Arial", 9),
                 wraplength=400, justify="left").pack()
        self.tooltip_window = tw

    def _hide_tooltip(self):
        if self.tooltip_window:
            try: self.tooltip_window.destroy()
            except: pass
            self.tooltip_window = None

    def _tab_insert_suggestion(self, event):
        """On Tab: if cursor is inside an anachronism range, insert the first suggestion."""
        idx = self.txt.index(tk.INSERT)
        for start, end, word, suggestions in self.anach_ranges:
            if self.txt.compare(start, "<=", idx) and self.txt.compare(idx, "<=", end):
                if not suggestions:
                    return "break"
                replacement = suggestions[0][0]
                # Preserve capitalisation of the original word
                matched = self.txt.get(start, end)
                first_alpha_orig = next((c for c in matched if c.isalpha()), None)
                first_alpha_idx  = next((i for i, c in enumerate(replacement) if c.isalpha()), None)
                if first_alpha_orig and first_alpha_orig.isupper() and first_alpha_idx is not None:
                    replacement = (replacement[:first_alpha_idx]
                                   + replacement[first_alpha_idx].upper()
                                   + replacement[first_alpha_idx+1:])
                self.txt.delete(start, end)
                self.txt.insert(start, replacement)
                self._hide_tooltip()
                self.update_counters()
                return "break"   # prevent default Tab behaviour
        return None  # not on a highlight — allow normal Tab

    def update_counters(self, e=None):
        content = self.txt.get("1.0", tk.END).splitlines()
        self.cnt_lbl.config(state="normal")
        self.cnt_lbl.delete("1.0", tk.END)
        for i, line in enumerate(content):
            sim = self.engine.get_simulated_len(line)
            tag = f"over_{i}"
            self.cnt_lbl.insert(tk.END, f"{sim:3}\n", tag)
            color = "#ff5555" if sim > self.limit else self.colors["counter_fg"]
            self.cnt_lbl.tag_config(tag, foreground=color)
        self.cnt_lbl.config(state="disabled")

    def apply_theme_colors(self):
        if self.dark_mode:
            self.colors = {"bg": "#1e1e1e", "fg": "#d4d4d4", "text_bg": "#252526", "jp_bg": "#1a1a1b", 
                           "sidebar_bg": "#2d2d2d", "btn_bg": "#3c3c3c", "label_fg": "#858585", 
                           "counter_fg": "#4ec9b0", "insert_color": "white"}
        else:
            self.colors = {"bg": "#f0f0f0", "fg": "#000000", "text_bg": "#ffffff", "jp_bg": "#ffffff", 
                           "sidebar_bg": "#f0f0f0", "btn_bg": "#e1e1e1", "label_fg": "gray", 
                           "counter_fg": "#0056b3", "insert_color": "black"}

    def setup_ui(self):
        self.configure(bg=self.colors["bg"])
        ctrl = tk.Frame(self, bg=self.colors["bg"], pady=10)
        ctrl.pack(fill="x", padx=20)
        
        self.cat_combo = ttk.Combobox(ctrl, values=list(self.queues.keys()), state="readonly", width=35)
        self.cat_combo.set(self.current_category)
        self.cat_combo.pack(side="left", padx=10)
        self.cat_combo.bind("<<ComboboxSelected>>", self.change_category)

        tk.Button(ctrl, text="🌙" if not self.dark_mode else "☀️", command=self.toggle_dark_mode,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], bd=0, padx=10).pack(side="right")
        tk.Checkbutton(ctrl, text="In-Universe Language", variable=self.in_universe_var,
                       bg=self.colors["bg"], fg=self.colors["fg"], selectcolor=self.colors["bg"],
                       command=self.update_counters).pack(side="right", padx=10)
        
        self.info_lbl = tk.Label(self, text="", fg="#bb86fc" if self.dark_mode else "purple", bg=self.colors["bg"], font=("Arial", 10, "bold"))
        self.info_lbl.pack()

        # --- Speaker / Archetype bar ---
        spk_frame = tk.Frame(self, bg=self.colors["bg"], padx=20, pady=4)
        spk_frame.pack(fill="x")
        tk.Label(spk_frame, text="Speaker:", fg=self.colors["label_fg"], bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        self.speaker_lbl = tk.Label(spk_frame, text="—", fg=self.colors["counter_fg"], bg=self.colors["bg"], font=("Arial", 9, "bold"))
        self.speaker_lbl.pack(side="left", padx=(4, 20))
        tk.Label(spk_frame, text="Archetype:", fg=self.colors["label_fg"], bg=self.colors["bg"], font=("Arial", 9)).pack(side="left")
        archetype_options = self.lore_engine.get_archetype_options()
        archetype_labels = ["(none)"] + [opt[1] for opt in archetype_options]
        self.archetype_keys = [None] + [opt[0] for opt in archetype_options]
        self.archetype_var = tk.StringVar(value="(none)")
        self.archetype_combo = ttk.Combobox(spk_frame, textvariable=self.archetype_var,
                                             values=archetype_labels, state="disabled", width=30)
        self.archetype_combo.pack(side="left", padx=(4, 10))
        self.archetype_combo.bind("<<ComboboxSelected>>", self.on_archetype_selected)
        tk.Button(spk_frame, text="Save Assignment", command=self.save_archetype,
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], font=("Arial", 8)).pack(side="left")
        tk.Label(spk_frame, text="Note:", fg=self.colors["label_fg"], bg=self.colors["bg"], font=("Arial", 9)).pack(side="left", padx=(16, 2))
        self.speaker_note_var = tk.StringVar()
        self.speaker_note_entry = tk.Entry(spk_frame, textvariable=self.speaker_note_var,
                                           width=28, font=("Arial", 9),
                                           bg=self.colors["text_bg"], fg=self.colors["fg"],
                                           insertbackground=self.colors["fg"], relief="flat",
                                           state="disabled")
        self.speaker_note_entry.pack(side="left", padx=(0, 6))
        self.speaker_note_entry.bind("<FocusOut>", lambda e: self.save_archetype())
        self.speaker_note_entry.bind("<Return>",   lambda e: self.save_archetype())
        
        main = tk.Frame(self, bg=self.colors["bg"])
        main.pack(fill="both", expand=True, padx=20)

        left_f = tk.Frame(main, bg=self.colors["bg"])
        left_f.pack(side="left", fill="y")

        tk.Label(left_f, text="English Editor:", fg=self.colors["label_fg"], bg=self.colors["bg"]).pack(anchor="w")
        self.txt = tk.Text(left_f, height=15, width=64, font=("Consolas", 12), bg=self.colors["text_bg"], 
                           fg=self.colors["fg"], insertbackground=self.colors["insert_color"], bd=0)
        self.txt.pack(fill="y", expand=True)
        self.txt.bind("<KeyRelease>", self.update_counters)

        tk.Label(left_f, text="Japanese Source:", fg=self.colors["label_fg"], bg=self.colors["bg"]).pack(anchor="w", pady=(10, 0))
        self.jp_txt = tk.Text(left_f, height=12, width=64, font=("MS Gothic", 12), bg=self.colors["jp_bg"], 
                              fg=self.colors["fg"], insertbackground=self.colors["insert_color"], state="disabled", bd=0)
        self.jp_txt.pack(fill="y", expand=True)

        self.cnt_lbl = tk.Text(main, font=("Consolas", 11), width=4, bg=self.colors["bg"], 
                               fg=self.colors["counter_fg"], state="disabled", bd=0, highlightthickness=0)
        self.cnt_lbl.pack(side="left", fill="y", pady=20, padx=(2, 5))

        side = tk.Frame(main, bg=self.colors["sidebar_bg"])
        side.pack(side="right", fill="both", expand=True)
        self.lore_list = tk.Text(side, bg=self.colors["text_bg"], fg=self.colors["fg"], bd=0, 
                                 highlightthickness=0, font=("Arial", 10), wrap="word", state="disabled")
        self.lore_list.pack(fill="x")
        tk.Frame(side, bg=self.colors["label_fg"], height=1).pack(fill="x", pady=4)
        self.archetype_hint = tk.Text(side, bg=self.colors["text_bg"], fg=self.colors["fg"], bd=0,
                                      highlightthickness=0, font=("Arial", 9), wrap="word",
                                      state="disabled", height=6)
        self.archetype_hint.pack(fill="both", expand=True)

        btns = tk.Frame(self, bg=self.colors["bg"], pady=20)
        btns.pack(side="bottom")
        tk.Button(btns, text="Skip", command=self.next_item, width=12, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="left", padx=5)
        tk.Button(btns, text="Apply", command=self.save_item, bg="#03dac6" if self.dark_mode else "#d1ecf1", fg="black", width=20).pack(side="left", padx=5)
        tk.Button(btns, text="Dashes → …", command=lambda: self.replace_dashes("…"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], width=12).pack(side="left", padx=5)
        tk.Button(btns, text="Dashes → —", command=lambda: self.replace_dashes("—"),
                  bg=self.colors["btn_bg"], fg=self.colors["fg"], width=12).pack(side="left", padx=5)
    
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
            with open(first_inst['path'], 'r', encoding='utf-8-sig') as f:
                rows = list(csv.reader(f))
                row_data = rows[first_inst['row_idx']]
                jp_source = row_data[2] if len(row_data) > 2 else ""
                self.speaker_name = row_data[8].strip() if len(row_data) > 8 else ""
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

        self.jp_txt.config(state="normal")
        self.jp_txt.delete(1.0, tk.END)
        self.jp_txt.insert(tk.END, jp_source)
        self.jp_source = jp_source  # Store for validation in save_item
        self.lore_list.config(state="normal")
        self.lore_list.delete(1.0, tk.END)

        if jp_source:
            matches = self.lore_engine.scan_text(jp_source)
            for jp, en in matches:
                self.lore_list.insert(tk.END, f"• {jp}: {en}\n")
                tag = f"lore_{hash(jp)}"
                self.jp_txt.tag_config(tag, foreground="#6fb3ff", underline=True)
                self.jp_txt.tag_bind(tag, "<Button-1>", lambda e, w=en: self.quick_insert(w))
                self._apply_tag_to_text(jp, tag)
            if matches:
                height = max(3, min(len(matches) + 1, 12))
                self.lore_list.config(height=height)

        # Dash category sidebar
        if self.current_category == "Double Dashes":
            _DASH_RE = re.compile(r'--+|——+|—-|-—')
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

        # Anachronisms category sidebar — use the hits stored in the queue instance
        if self.current_category == "Anachronisms":
            from lore_engine import IN_UNIVERSE_VOCAB
            # Pull stored hits from the first queue instance for this text
            instances = self.queues["Anachronisms"].get(txt, [])
            stored_hits = instances[0].get("hits", []) if instances else []
            # Fall back to re-scanning if stored hits are missing (e.g. older queue entries)
            if not stored_hits:
                stored_hits = self.lore_engine.scan_anachronisms(txt)
            if stored_hits:
                self.lore_list.insert(tk.END, "── Anachronisms ──\n", "anach_hdr")
                self.lore_list.tag_config("anach_hdr", foreground="#ff8c00", font=("Arial", 9, "bold"))
                seen_words = set()
                for found, suggestion in stored_hits:
                    word_lower = found.lower()
                    if word_lower in seen_words:
                        continue
                    seen_words.add(word_lower)
                    # Get the replacement value directly from vocab (suggestion may be None)
                    val = IN_UNIVERSE_VOCAB.get(word_lower)
                    if val is not None:
                        self.lore_list.insert(tk.END, f"  \"{found}\"  →  {val}\n", "anach_item")
                    else:
                        self.lore_list.insert(tk.END, f"  \"{found}\"  — no direct replacement\n", "anach_flag")
                self.lore_list.tag_config("anach_item", foreground="#ffa040")
                self.lore_list.tag_config("anach_flag", foreground=self.colors["label_fg"])
            else:
                self.lore_list.insert(tk.END, "No anachronisms detected.\n", "anach_flag")
                self.lore_list.tag_config("anach_flag", foreground=self.colors["label_fg"])

        self.lore_list.config(state="disabled")
        self.jp_txt.config(state="disabled")
        self.update_counters()

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
        """Replace all double-dash / double-em-dash patterns in the editor with replacement."""
        current = self.txt.get(1.0, tk.END)
        fixed = re.sub(r'--+|——+|—-|-—', replacement, current)
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
            color = "#ff5555" if sim > self.limit else self.colors["counter_fg"]
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

        # --- Blocker 1: Line length ---
        overlong = [i + 1 for i, l in enumerate(lines) if self.engine.get_simulated_len(l) > self.limit]
        if overlong:
            ln_str = ", ".join(str(n) for n in overlong)
            messagebox.showerror("Line Too Long",
                f"Line{'s' if len(overlong) > 1 else ''} {ln_str} exceed{'s' if len(overlong) == 1 else ''} "
                f"the {self.limit}-char limit. Fix before saving.", parent=self)
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
        top = tk.Frame(self.root, padx=15, pady=10, bg=self.colors["bg"])
        top.pack(fill="x")
        
        f_box = tk.LabelFrame(top, text=" Folders ", bg=self.colors["bg"], fg=self.colors["fg"])
        f_box.pack(side="left", fill="both", expand=True, padx=5)
        self.f_list = tk.Listbox(f_box, height=4, bg=self.colors["list_bg"], fg=self.colors["fg"], bd=0)
        self.f_list.pack(fill="both")
        for f in self.cm.config.get("folders", []): self.f_list.insert(tk.END, f)
        
        fb = tk.Frame(f_box, bg=self.colors["bg"])
        fb.pack(fill="x")
        tk.Button(fb, text="Add", command=self.add_folder, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="left")
        tk.Button(fb, text="Rem", command=self.rem_folder, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="left")

        t_box = tk.LabelFrame(top, text=" Triggers ", bg=self.colors["bg"], fg=self.colors["fg"])
        t_box.pack(side="right", fill="both", expand=True, padx=5)
        self.t_list = tk.Listbox(t_box, height=4, bg=self.colors["list_bg"], fg=self.colors["fg"], bd=0)
        self.t_list.pack(fill="both")
        for t in self.cm.config.get("triggers", []): self.t_list.insert(tk.END, t)

        tb = tk.Frame(t_box, bg=self.colors["bg"])
        tb.pack(fill="x")
        tk.Button(tb, text="Add", command=self.add_trigger, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="left")
        tk.Button(tb, text="Rem", command=self.rem_trigger, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="left")

        set_f = tk.LabelFrame(self.root, text=" Settings ", padx=15, pady=5, bg=self.colors["bg"], fg=self.colors["fg"])
        set_f.pack(fill="x", padx=15)
        tk.Label(set_f, text="Char limit:", bg=self.colors["bg"], fg=self.colors["fg"]).pack(side="left")
        self.preset_menu = ttk.Combobox(set_f, textvariable=self.preset_var, values=self.preset_names, state="readonly", width=14)
        self.preset_menu.pack(side="left", padx=(2, 10))
        tk.Label(set_f, text="Line limit:", bg=self.colors["bg"], fg=self.colors["fg"]).pack(side="left")
        self.wall_preset_menu = ttk.Combobox(set_f, textvariable=self.wall_preset_var, values=self.wall_preset_names, state="readonly", width=14)
        self.wall_preset_menu.pack(side="left", padx=(2, 10))
        tk.Checkbutton(set_f, text="Preview Mode", variable=self.prev_var, bg=self.colors["bg"], fg=self.colors["fg"], selectcolor=self.colors["bg"]).pack(side="left")
        tk.Checkbutton(set_f, text="In-Universe Language", variable=self.in_universe_var,
                       bg=self.colors["bg"], fg=self.colors["fg"], selectcolor=self.colors["bg"]).pack(side="left", padx=(10, 0))
        
        tk.Button(set_f, text="🌙" if not self.dark_mode else "☀️", command=self.toggle_global_dark_mode, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="right", padx=5)
        tk.Button(set_f, text="Options...", command=self.open_options, bg=self.colors["btn_bg"], fg=self.colors["fg"]).pack(side="right")

        self.log_box = tk.Text(self.root, height=12, bg=self.colors["log_bg"], fg=self.colors["log_fg"], font=("Consolas", 10), bd=0)
        self.log_box.pack(padx=15, pady=10, fill="both", expand=True)
        
        self.btn_run = tk.Button(self.root, text="EXECUTE BATCH SCAN", bg="#28a745", fg="white", command=self.start_thread, height=2, bd=0)
        self.btn_run.pack(padx=15, fill="x", pady=5)
        self.progress = ttk.Progressbar(self.root, length=700)
        self.progress.pack(pady=5)

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
        lore_engine = LoreEngine()
        lore_engine.load_data(
            self.cm.config.get("bible_path", ""),
            self.cm.config.get("glossary_path", "")
        )
        in_universe_replacements = lore_engine.get_in_universe_replacements() if do_in_universe else {}

        self.tag_q.clear()
        self.wall_q.clear()
        self.dash_q.clear()

        # Dash pattern: two or more hyphens, OR two or more em-dashes
        _DASH_RE = re.compile(r'--+|——+|—-|-—')

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

        for i, f_path in enumerate(all_files):
            pct = ((i + 1) / len(all_files)) * 100
            self.root.after(0, lambda v=pct: self.progress.configure(value=v))
            file_modded = False
            output_rows = []

            try:
                with open(f_path, 'r', encoding='utf-8-sig', newline='') as f:
                    current_file_data = list(csv.reader(f))

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

                    # 2b. Dash scan (independent of other processing)
                    if _DASH_RE.search(orig_text):
                        self.dash_q[orig_text].append({'path': f_path, 'row_idx': r_idx})

                    # 2c. Anachronism scan (independent — always runs, not gated on in_universe toggle)
                    anach_hits = lore_engine.scan_anachronisms(orig_text)
                    if anach_hits:
                        self.anach_q[orig_text].append({'path': f_path, 'row_idx': r_idx, 'hits': anach_hits})

                    # 3. Memory Branch
                    if orig_text in self.cm.memory:
                        learned = self.cm.memory[orig_text]
                        lines = learned.split('\n')
                        max_w = max((self.engine.get_simulated_len(l) for l in lines), default=0)
                        if max_w > limit:
                            needs_review = True
                            queue_type = 'tag'
                        else:
                            proposed_text = learned

                    # 4. Auto-Processing Branch
                    else:
                        jp_source = row[2] if len(row) > 2 else ""

                        clean_txt = re.sub(r'(?i)<(?:COL(?: [A-F0-9]+)?|/COL)>|\[NAME\]', '', orig_text)
                        is_complex = '<' in clean_txt or '[' in clean_txt

                        # --- Auto Tag Fix ---
                        def non_col_tags(text):
                            return [t for t in re.findall(r'<([^>]+)>', text)
                                    if not t.upper().startswith('COL') and t.upper() != '/COL']

                        if jp_source and is_complex:
                            from collections import Counter
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
                        # Only applied to auto-fixed rows, NOT to rows going into review queues.
                        # Anachronism queue already stores the original text for human review.
                        text_for_wrap = orig_text
                        if do_in_universe:
                            text_for_wrap = self.engine.apply_in_universe(orig_text, in_universe_replacements)

                        lines = text_for_wrap.split('\n')
                        max_w = max((self.engine.get_simulated_len(l) for l in lines), default=0)

                        if is_complex and max_w > (limit * 0.9):
                            needs_review = True
                            queue_type = 'tag'
                        else:
                            wrapped = self.engine.master_tag_wrap(text_for_wrap, limit)
                            wrap_lines = wrapped.split('\n')
                            wrap_max_w = max((self.engine.get_simulated_len(l) for l in wrap_lines), default=0)

                            if wrap_max_w > limit:
                                needs_review = True
                                queue_type = 'tag'
                            elif len(wrap_lines) >= wall_limit:
                                needs_review = True
                                queue_type = 'linelimit'
                                wall_wrapped_text = wrapped
                            elif wrapped != row[3]:
                                proposed_text = wrapped

                    # 5. Application
                    if needs_review:
                        if queue_type == 'tag':
                            self.tag_q[orig_text].append({'path': f_path, 'row_idx': r_idx})
                        elif queue_type == 'linelimit':
                            self.wall_q[orig_text].append({'path': f_path, 'row_idx': r_idx, 'wrapped': wall_wrapped_text})
                    else:
                        if row[3] != proposed_text:
                            row[3] = proposed_text
                            file_modded = True

                    output_rows.append(row)

                # 6. Safety Write
                if file_modded and not self.prev_var.get() and len(output_rows) == len(current_file_data):
                    with open(f_path, 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f).writerows(output_rows)

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
            self.colors = {"bg": "#1e1e1e", "fg": "#d4d4d4", "list_bg": "#252526", 
                           "btn_bg": "#333333", "log_bg": "#121212", "log_fg": "#d4d4d4"}
        else:
            self.colors = {"bg": "#f0f0f0", "fg": "#000000", "list_bg": "#ffffff", 
                           "btn_bg": "#e1e1e1", "log_bg": "#ffffff", "log_fg": "#000000"}

    def propagate_fix(self, instances, new_text, orig_text):
        # Update the RAM dictionary
        self.cm.memory[orig_text] = new_text
        
        # CRITICAL: Force the ConfigManager to write the dictionary to learned_fixes.json
        self.cm.save_all() 
        
        # Update the physical CSV files
        for inst in instances:
            try:
                with open(inst['path'], 'r', encoding='utf-8-sig', newline='') as f:
                    rows = list(csv.reader(f))
                
                if inst['row_idx'] < len(rows):
                    rows[inst['row_idx']][3] = new_text
                    
                    with open(inst['path'], 'w', encoding='utf-8-sig', newline='') as f:
                        csv.writer(f).writerows(rows)
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