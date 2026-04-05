import sys
sys.dont_write_bytecode = True

import csv
import os
import re
import threading
import tkinter as tk
from collections import defaultdict
from tkinter import filedialog, messagebox, simpledialog, ttk

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
    from file_utils import _get_csv_files, _read_csv
    from review_editor import ReviewEditor
    from translation_window import CSVTranslationWindow
    from search_window import SearchWindow
except ImportError as e:
    print(f"CRITICAL ERROR: Missing module file! {e}")
    input("Press Enter to close...")
    exit()


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

