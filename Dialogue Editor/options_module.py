import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog, ttk

class OptionsMenu:
    def __init__(self, parent, config_manager):
        self.parent = parent
        self.cm = config_manager # Uses the ConfigManager from core
        
    def open_window(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title("Advanced Configuration")
        self.win.geometry("640x720")
        self.win.resizable(True, True)

        # Scrollable container
        canvas = tk.Canvas(self.win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.win, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas)

        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # All content goes into scroll_frame instead of self.win
        w = self.scroll_frame
        
        # --- SECTION 1: Tag Length Mapping ---
        tag_frame = tk.LabelFrame(w, text=" Tag Length Mapping ", padx=10, pady=10)
        tag_frame.pack(fill="x", padx=15, pady=5)
        
        self.tag_lb = tk.Listbox(tag_frame, height=5)
        self.tag_lb.pack(side="left", fill="both", expand=True)
        self.refresh_tags()

        t_btns = tk.Frame(tag_frame)
        t_btns.pack(side="right", padx=5)
        tk.Button(t_btns, text="Add/Edit", width=10, command=self.edit_tag).pack(pady=2)
        tk.Button(t_btns, text="Delete", width=10, command=self.delete_tag).pack(pady=2)

        # --- SECTION 2: Line Limit Presets ---
        lim_frame = tk.LabelFrame(w, text=" Line Limit Presets (characters) ", padx=10, pady=10)
        lim_frame.pack(fill="x", padx=15, pady=5)
        
        self.lim_lb = tk.Listbox(lim_frame, height=5)
        self.lim_lb.pack(side="left", fill="both", expand=True)
        self.refresh_limits()

        l_btns = tk.Frame(lim_frame)
        l_btns.pack(side="right", padx=5)
        tk.Button(l_btns, text="Add/Edit", width=10, command=self.edit_limit).pack(pady=2)
        tk.Button(l_btns, text="Delete", width=10, command=self.delete_limit).pack(pady=2)

        # --- SECTION 3: Wall of Text Presets ---
        wall_frame = tk.LabelFrame(w, text=" Wall of Text Presets (max lines) ", padx=10, pady=10)
        wall_frame.pack(fill="x", padx=15, pady=5)

        self.wall_lb = tk.Listbox(wall_frame, height=4)
        self.wall_lb.pack(side="left", fill="both", expand=True)
        self.refresh_wall_presets()

        w_btns = tk.Frame(wall_frame)
        w_btns.pack(side="right", padx=5)
        tk.Button(w_btns, text="Add/Edit", width=10, command=self.edit_wall_preset).pack(pady=2)
        tk.Button(w_btns, text="Delete", width=10, command=self.delete_wall_preset).pack(pady=2)

        # --- SECTION 4: External References ---
        ref_frame = tk.LabelFrame(w, text=" External Reference Paths ", padx=10, pady=10)
        ref_frame.pack(fill="x", padx=15, pady=5)

        # Bible Path
        tk.Label(ref_frame, text="Bible Path:").grid(row=0, column=0, sticky="w")
        self.bible_ent = tk.Entry(ref_frame, width=50)
        self.bible_ent.insert(0, self.cm.config.get("bible_path", ""))
        self.bible_ent.grid(row=0, column=1)
        tk.Button(ref_frame, text="...", command=lambda: self.pick_file("bible_path", self.bible_ent)).grid(row=0, column=2)

        # Glossary Path
        tk.Label(ref_frame, text="Glossary Path:").grid(row=1, column=0, sticky="w")
        self.gloss_ent = tk.Entry(ref_frame, width=50)
        self.gloss_ent.insert(0, self.cm.config.get("glossary_path", ""))
        self.gloss_ent.grid(row=1, column=1, pady=5)
        tk.Button(ref_frame, text="...", command=lambda: self.pick_file("glossary_path", self.gloss_ent)).grid(row=1, column=2)

        # --- SECTION 5: Archetypes ---
        arch_frame = tk.LabelFrame(w, text=" Archetypes ", padx=10, pady=10)
        arch_frame.pack(fill="x", padx=15, pady=5)

        self.arch_lb = tk.Listbox(arch_frame, height=6)
        self.arch_lb.pack(side="left", fill="both", expand=True)
        self.refresh_archetypes()

        a_btns = tk.Frame(arch_frame)
        a_btns.pack(side="right", padx=5)
        tk.Button(a_btns, text="Add",    width=10, command=self.add_archetype).pack(pady=2)
        tk.Button(a_btns, text="Edit",   width=10, command=self.edit_archetype).pack(pady=2)
        tk.Button(a_btns, text="Delete", width=10, command=self.delete_archetype).pack(pady=2)
        tk.Button(a_btns, text="Reset\nDefaults", width=10, command=self.reset_archetypes).pack(pady=2)

        # --- SECTION 6: Regex Sandbox ---
        regex_frame = tk.LabelFrame(w, text=" Regex Playground ", padx=10, pady=10)
        regex_frame.pack(fill="x", padx=15, pady=5)
        
        tk.Label(regex_frame, text="Regex Pattern:").grid(row=0, column=0, sticky="w")
        self.reg_pattern = tk.Entry(regex_frame, width=30)
        self.reg_pattern.grid(row=0, column=1, sticky="w", padx=5)
        
        tk.Label(regex_frame, text="Replacement:").grid(row=0, column=2, sticky="w")
        self.reg_repl = tk.Entry(regex_frame, width=20)
        self.reg_repl.grid(row=0, column=3, sticky="w", padx=5)
        
        tk.Label(regex_frame, text="Test Input:").grid(row=1, column=0, sticky="nw", pady=5)
        self.reg_in = tk.Text(regex_frame, height=2, width=50)
        self.reg_in.grid(row=1, column=1, columnspan=3, sticky="w", pady=5)
        
        tk.Label(regex_frame, text="Result:").grid(row=2, column=0, sticky="nw")
        self.reg_out = tk.Text(regex_frame, height=2, width=50, state="disabled", bg="#e8e8e8")
        self.reg_out.grid(row=2, column=1, columnspan=3, sticky="w")
        
        for widget in (self.reg_pattern, self.reg_repl):
            widget.bind("<KeyRelease>", self._run_sandbox)
        self.reg_in.bind("<KeyRelease>", self._run_sandbox)

        # --- SECTION 7: API Settings ---
        api_frame = tk.LabelFrame(w, text=" API Settings (DeepL & OpenRouter) ", padx=10, pady=10)
        api_frame.pack(fill="x", padx=15, pady=5)

        # DeepL Key
        tk.Label(api_frame, text="DeepL API Key:").grid(row=0, column=0, sticky="w")
        self.deepl_key_ent = tk.Entry(api_frame, width=40, show="*")
        self.deepl_key_ent.insert(0, self.cm.get_key("deepl_api_key"))
        self.deepl_key_ent.grid(row=0, column=1, sticky="w", padx=5)
        tk.Button(api_frame, text="Test", command=self.test_deepl).grid(row=0, column=2, padx=2)

        # DeepL Target Lang
        tk.Label(api_frame, text="Target Lang:").grid(row=1, column=0, sticky="w")
        self.deepl_lang_ent = tk.Entry(api_frame, width=10)
        self.deepl_lang_ent.insert(0, self.cm.config.get("deepl_target_lang", "EN-US"))
        self.deepl_lang_ent.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        tk.Label(api_frame, text="(e.g. EN-US, PT-BR)", font=("Arial", 8, "italic")).grid(row=1, column=2, sticky="w")

        # OpenRouter Key
        tk.Label(api_frame, text="OpenRouter Key:").grid(row=2, column=0, sticky="w")
        self.or_key_ent = tk.Entry(api_frame, width=40, show="*")
        self.or_key_ent.insert(0, self.cm.get_key("openrouter_api_key"))
        self.or_key_ent.grid(row=2, column=1, sticky="w", padx=5)
        tk.Button(api_frame, text="Test", command=self.test_openrouter).grid(row=2, column=2, padx=2)

        # OpenRouter Models Row
        tk.Label(api_frame, text="AI Models:").grid(row=3, column=0, sticky="w")
        self.show_paid_var = tk.BooleanVar(value=False)
        tk.Checkbutton(api_frame, text="Show Paid", variable=self.show_paid_var).grid(row=3, column=1, sticky="w")
        tk.Button(api_frame, text="Refresh Models List", command=self.refresh_openrouter_models).grid(row=3, column=1, sticky="e", padx=(0, 32))

        tk.Button(w, text="SAVE ALL CHANGES", bg="#d1ecf1", height=2, command=self.save_and_close).pack(pady=20)
        
        return self.win # CRITICAL: Allows main.py to wait for this window

    def _run_sandbox(self, e=None):
        import re
        pattern = self.reg_pattern.get()
        repl = self.reg_repl.get()
        text_in = self.reg_in.get("1.0", tk.END).strip("\n")
        
        self.reg_out.config(state="normal")
        self.reg_out.delete("1.0", tk.END)
        if not pattern:
            self.reg_out.insert("1.0", text_in)
        else:
            try:
                res = re.sub(pattern, repl, text_in)
                self.reg_out.insert("1.0", res)
            except Exception as ex:
                self.reg_out.insert("1.0", f"Error: {ex}")
        self.reg_out.config(state="disabled")

    # --- TAG LOGIC ---
    def refresh_tags(self):
        self.tag_lb.delete(0, tk.END)
        for k, v in self.cm.config.get("tag_map", {}).items():
            display = self.cm.config.get("tag_display", {}).get(k, "")
            if display:
                self.tag_lb.insert(tk.END, f"{k}  ({display})  → {v} chars")
            else:
                self.tag_lb.insert(tk.END, f"{k} : {v}")

    def edit_tag(self):
        res = simpledialog.askstring(
            "Tag Map",
            "Format:  TagName : Display Text\n"
            "e.g.  PLAYER_NAME : Arisen\n\n"
            "The character length will be measured automatically\n"
            "from the display text. You can also enter\n"
            "TagName : number  to set a manual length."
        )
        if not res or ":" not in res:
            return
        parts = res.split(":", 1)
        tag_name = parts[0].strip()
        value    = parts[1].strip()
        if not tag_name:
            return
        # If the value is a plain integer, store it directly (manual override)
        try:
            length = int(value)
            display_text = ""
        except ValueError:
            # Measure character length of the display text
            display_text = value
            length = len(display_text)
        if "tag_map" not in self.cm.config:
            self.cm.config["tag_map"] = {}
        if "tag_display" not in self.cm.config:
            self.cm.config["tag_display"] = {}
        self.cm.config["tag_map"][tag_name] = length
        if display_text:
            self.cm.config["tag_display"][tag_name] = display_text
        elif tag_name in self.cm.config.get("tag_display", {}):
            del self.cm.config["tag_display"][tag_name]
        self.refresh_tags()

    def delete_tag(self):
        sel = self.tag_lb.curselection()
        if sel:
            # Key is the first token before space or colon
            raw = self.tag_lb.get(sel[0])
            key = raw.split(" ")[0].split(":")[0].strip()
            if "tag_map" in self.cm.config and key in self.cm.config["tag_map"]:
                del self.cm.config["tag_map"][key]
            if "tag_display" in self.cm.config and key in self.cm.config["tag_display"]:
                del self.cm.config["tag_display"][key]
            self.refresh_tags()

    # --- LIMIT LOGIC ---
    def refresh_limits(self):
        self.lim_lb.delete(0, tk.END)
        # Only show presets that actually exist in the config
        presets = self.cm.config.get("presets", {})
        for k, v in presets.items():
            self.lim_lb.insert(tk.END, f"{k} : {v}")

    def edit_limit(self):
        res = simpledialog.askstring("Preset", "Format: Name:Limit (e.g. Wide:80)")
        if res and ":" in res:
            try:
                name, val = res.split(":")
                if "presets" not in self.cm.config: self.cm.config["presets"] = {}
                self.cm.config["presets"][name.strip()] = int(val.strip())
                self.refresh_limits()
            except ValueError: messagebox.showerror("Error", "Limit must be a number.")

    def delete_limit(self):
        sel = self.lim_lb.curselection()
        if not sel:
            return
        item_text = self.lim_lb.get(sel[0])
        key = item_text.split(" : ")[0].strip()
        if "presets" in self.cm.config and key in self.cm.config["presets"]:
            del self.cm.config["presets"][key]
        self.lim_lb.delete(sel[0])
        self.refresh_limits()

    # --- WALL PRESET LOGIC ---
    def refresh_wall_presets(self):
        self.wall_lb.delete(0, tk.END)
        for k, v in self.cm.config.get("wall_presets", {}).items():
            self.wall_lb.insert(tk.END, f"{k} : {v}")

    def edit_wall_preset(self):
        res = simpledialog.askstring("Wall Preset", "Format: Name:MaxLines (e.g. Standard:7)")
        if res and ":" in res:
            try:
                name, val = res.split(":", 1)
                if "wall_presets" not in self.cm.config:
                    self.cm.config["wall_presets"] = {}
                self.cm.config["wall_presets"][name.strip()] = int(val.strip())
                self.refresh_wall_presets()
            except ValueError:
                messagebox.showerror("Error", "Max lines must be a whole number.")

    def delete_wall_preset(self):
        sel = self.wall_lb.curselection()
        if not sel:
            return
        key = self.wall_lb.get(sel[0]).split(" : ")[0].strip()
        if "wall_presets" in self.cm.config and key in self.cm.config["wall_presets"]:
            del self.cm.config["wall_presets"][key]
        self.wall_lb.delete(sel[0])
        self.refresh_wall_presets()

    # --- ARCHETYPE LOGIC ---
    def refresh_archetypes(self):
        self.arch_lb.delete(0, tk.END)
        for key, data in sorted(self.cm.config.get("archetypes", {}).items()):
            self.arch_lb.insert(tk.END, f"{key}: {data.get('name', '')}")

    def _archetype_dialog(self, title, key="", name="", professions="", notes="", pawn_map=""):
        """Open a multi-field dialog for adding/editing an archetype.
        Returns (key, name, professions_list, notes, pawn_map) or None if cancelled."""
        dlg = tk.Toplevel(self.win)
        dlg.title(title)
        dlg.geometry("520x480")
        dlg.grab_set()

        def lbl(text, row):
            tk.Label(dlg, text=text, anchor="w").grid(row=row, column=0, sticky="w", padx=10, pady=4)

        lbl("Key (e.g. A1, B, H):", 0)
        key_var = tk.StringVar(value=key)
        tk.Entry(dlg, textvariable=key_var, width=10).grid(row=0, column=1, sticky="w", padx=10)

        lbl("Name:", 1)
        name_var = tk.StringVar(value=name)
        tk.Entry(dlg, textvariable=name_var, width=40).grid(row=1, column=1, sticky="ew", padx=10)

        lbl("Professions\n(comma-separated):", 2)
        prof_var = tk.StringVar(value=professions)
        tk.Entry(dlg, textvariable=prof_var, width=40).grid(row=2, column=1, sticky="ew", padx=10)

        lbl("Pawn map:", 3)
        pawn_var = tk.StringVar(value=pawn_map)
        tk.Entry(dlg, textvariable=pawn_var, width=40).grid(row=3, column=1, sticky="ew", padx=10)

        lbl("Notes / Register:", 4)
        notes_txt = tk.Text(dlg, height=8, width=40, wrap="word", font=("Arial", 9))
        notes_txt.grid(row=4, column=1, sticky="ew", padx=10, pady=4)
        notes_txt.insert("1.0", notes)

        result = [None]

        def ok():
            k = key_var.get().strip()
            n = name_var.get().strip()
            if not k or not n:
                messagebox.showerror("Error", "Key and Name are required.", parent=dlg)
                return
            result[0] = (
                k, n,
                [p.strip() for p in prof_var.get().split(",") if p.strip()],
                notes_txt.get("1.0", tk.END).strip(),
                pawn_var.get().strip(),
            )
            dlg.destroy()

        def cancel():
            dlg.destroy()

        btn_row = tk.Frame(dlg)
        btn_row.grid(row=5, column=0, columnspan=2, pady=10)
        tk.Button(btn_row, text="OK",     width=12, command=ok).pack(side="left", padx=8)
        tk.Button(btn_row, text="Cancel", width=12, command=cancel).pack(side="left", padx=8)

        dlg.columnconfigure(1, weight=1)
        self.win.wait_window(dlg)
        return result[0]

    def add_archetype(self):
        res = self._archetype_dialog("Add Archetype")
        if not res:
            return
        key, name, profs, notes, pawn_map = res
        archetypes = self.cm.config.setdefault("archetypes", {})
        if key in archetypes:
            if not messagebox.askyesno("Overwrite?", f"Key '{key}' already exists. Overwrite?", parent=self.win):
                return
        archetypes[key] = {"name": name, "professions": profs, "notes": notes, "pawn_map": pawn_map}
        self.refresh_archetypes()

    def edit_archetype(self):
        sel = self.arch_lb.curselection()
        if not sel:
            return
        raw = self.arch_lb.get(sel[0])
        key = raw.split(":")[0].strip()
        archetypes = self.cm.config.get("archetypes", {})
        data = archetypes.get(key, {})
        res = self._archetype_dialog(
            f"Edit Archetype — {key}",
            key=key,
            name=data.get("name", ""),
            professions=", ".join(data.get("professions", [])),
            notes=data.get("notes", ""),
            pawn_map=data.get("pawn_map", ""),
        )
        if not res:
            return
        new_key, name, profs, notes, pawn_map = res
        # Handle key rename
        if new_key != key and key in archetypes:
            del archetypes[key]
            # Update any speaker assignments using the old key
            for spk, assigned in self.cm.config.get("speaker_archetypes", {}).items():
                if assigned == key:
                    self.cm.config["speaker_archetypes"][spk] = new_key
        archetypes[new_key] = {"name": name, "professions": profs, "notes": notes, "pawn_map": pawn_map}
        self.refresh_archetypes()

    def delete_archetype(self):
        sel = self.arch_lb.curselection()
        if not sel:
            return
        raw = self.arch_lb.get(sel[0])
        key = raw.split(":")[0].strip()
        if not messagebox.askyesno("Delete?", f"Delete archetype '{key}'?\nSpeaker assignments using it will be cleared.", parent=self.win):
            return
        archetypes = self.cm.config.get("archetypes", {})
        archetypes.pop(key, None)
        # Clear speaker assignments pointing to this key
        for spk in list(self.cm.config.get("speaker_archetypes", {}).keys()):
            if self.cm.config["speaker_archetypes"][spk] == key:
                del self.cm.config["speaker_archetypes"][spk]
        self.refresh_archetypes()

    def reset_archetypes(self):
        if not messagebox.askyesno("Reset Archetypes?",
                "Replace all archetypes with the built-in defaults?\n"
                "Custom archetypes will be lost.", parent=self.win):
            return
        from lore_engine import DEFAULT_ARCHETYPES
        self.cm.config["archetypes"] = {k: dict(v) for k, v in DEFAULT_ARCHETYPES.items()}
        self.refresh_archetypes()

    # --- FILE PICKER ---
    def pick_file(self, key, entry_widget):
        # Added .txt and .log to the allowed types
        file_types = [
            ("Text files", "*.txt"),
            ("CSV files", "*.csv"),
            ("Log files", "*.log"),
            ("All files", "*.*")
        ]
        
        path = filedialog.askopenfilename(filetypes=file_types)
        
        if path:
            # Update the entry box immediately
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, path)
            # Update the internal config
            self.cm.config[key] = path

    def test_deepl(self):
        key = self.deepl_key_ent.get().strip()
        if not key:
            messagebox.showwarning("Warning", "Enter a DeepL key first.")
            return
        from api_handler import DeepLClient
        client = DeepLClient(key)
        res = client.translate("テスト")
        if "text" in res:
            messagebox.showinfo("Success", f"Connection OK!\nResult: {res['text']}")
        else:
            messagebox.showerror("Error", f"Failed: {res['error']}")

    def test_openrouter(self):
        key = self.or_key_ent.get().strip()
        if not key:
            messagebox.showwarning("Warning", "Enter an OpenRouter key first.")
            return
        from api_handler import OpenRouterClient
        client = OpenRouterClient(key)
        res = client.chat([{"role": "user", "content": "Respond with 'Connected'"}])
        if "text" in res:
            messagebox.showinfo("Success", f"Connection OK!\nResult: {res['text']}")
        else:
            messagebox.showerror("Error", f"Failed: {res['error']}")

    def refresh_openrouter_models(self):
        key = self.or_key_ent.get().strip()
        if not key:
            messagebox.showwarning("Warning", "Enter an OpenRouter key to fetch current models.")
            return
            
        from api_handler import OpenRouterClient
        client = OpenRouterClient(key)
        
        # Show busy state
        orig_title = self.win.title()
        self.win.title("Fetching Models... Please wait...")
        self.win.config(cursor="watch")
        self.win.update()
        
        try:
            free_only = not self.show_paid_var.get()
            models = client.fetch_models(free_only=free_only)
            if models:
                self.cm.config["openrouter_models"] = models
                messagebox.showinfo("Success", f"Updated! Found {len(models)} models.")
            else:
                messagebox.showerror("Error", "No models found.")
        except Exception as e:
            messagebox.showerror("Error", f"Fetch failed: {e}")
        finally:
            self.win.title(orig_title)
            self.win.config(cursor="")

    def save_and_close(self):
        self.cm.config["bible_path"] = self.bible_ent.get()
        self.cm.config["glossary_path"] = self.gloss_ent.get()
        self.cm.set_key("deepl_api_key", self.deepl_key_ent.get().strip())
        self.cm.config["deepl_target_lang"] = self.deepl_lang_ent.get().strip() or "EN-US"
        self.cm.set_key("openrouter_api_key", self.or_key_ent.get().strip())
        
        if "presets" not in self.cm.config:
            self.cm.config["presets"] = {"Standard": 50}
        if "wall_presets" not in self.cm.config:
            self.cm.config["wall_presets"] = {"Standard": 7}
        if "tag_display" not in self.cm.config:
            self.cm.config["tag_display"] = {}
        self.cm.save_all()
        messagebox.showinfo("Success", "Configuration saved!")
        self.win.destroy()