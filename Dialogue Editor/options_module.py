import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog, ttk

class OptionsMenu:
    def __init__(self, parent, config_manager):
        self.parent = parent
        self.cm = config_manager # Uses the ConfigManager from core
        
    def open_window(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title("Advanced Configuration")
        self.win.geometry("600x700")
        
        # --- SECTION 1: Tag Length Mapping ---
        tag_frame = tk.LabelFrame(self.win, text=" Tag Length Mapping ", padx=10, pady=10)
        tag_frame.pack(fill="x", padx=15, pady=5)
        
        self.tag_lb = tk.Listbox(tag_frame, height=5)
        self.tag_lb.pack(side="left", fill="both", expand=True)
        self.refresh_tags()

        t_btns = tk.Frame(tag_frame)
        t_btns.pack(side="right", padx=5)
        tk.Button(t_btns, text="Add/Edit", width=10, command=self.edit_tag).pack(pady=2)
        tk.Button(t_btns, text="Delete", width=10, command=self.delete_tag).pack(pady=2)

        # --- SECTION 2: Line Limit Presets ---
        lim_frame = tk.LabelFrame(self.win, text=" Line Limit Presets (characters) ", padx=10, pady=10)
        lim_frame.pack(fill="x", padx=15, pady=5)
        
        self.lim_lb = tk.Listbox(lim_frame, height=5)
        self.lim_lb.pack(side="left", fill="both", expand=True)
        self.refresh_limits()

        l_btns = tk.Frame(lim_frame)
        l_btns.pack(side="right", padx=5)
        tk.Button(l_btns, text="Add/Edit", width=10, command=self.edit_limit).pack(pady=2)
        tk.Button(l_btns, text="Delete", width=10, command=self.delete_limit).pack(pady=2)

        # --- SECTION 3: Wall of Text Presets ---
        wall_frame = tk.LabelFrame(self.win, text=" Wall of Text Presets (max lines) ", padx=10, pady=10)
        wall_frame.pack(fill="x", padx=15, pady=5)

        self.wall_lb = tk.Listbox(wall_frame, height=4)
        self.wall_lb.pack(side="left", fill="both", expand=True)
        self.refresh_wall_presets()

        w_btns = tk.Frame(wall_frame)
        w_btns.pack(side="right", padx=5)
        tk.Button(w_btns, text="Add/Edit", width=10, command=self.edit_wall_preset).pack(pady=2)
        tk.Button(w_btns, text="Delete", width=10, command=self.delete_wall_preset).pack(pady=2)

        # --- SECTION 4: External References ---
        ref_frame = tk.LabelFrame(self.win, text=" External Reference Paths ", padx=10, pady=10)
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

        tk.Button(self.win, text="SAVE ALL CHANGES", bg="#d1ecf1", height=2, command=self.save_and_close).pack(pady=20)
        
        return self.win # CRITICAL: Allows main.py to wait for this window

    # --- TAG LOGIC ---
    def refresh_tags(self):
        self.tag_lb.delete(0, tk.END)
        for k, v in self.cm.config.get("tag_map", {}).items():
            self.tag_lb.insert(tk.END, f"{k} : {v}")

    def edit_tag(self):
        res = simpledialog.askstring("Tag Map", "Format: TagName:Length (e.g. HERO:8)")
        if res and ":" in res:
            try:
                name, val = res.split(":")
                if "tag_map" not in self.cm.config: self.cm.config["tag_map"] = {}
                self.cm.config["tag_map"][name.strip()] = int(val.strip())
                self.refresh_tags()
            except ValueError: messagebox.showerror("Error", "Length must be a number.")

    def delete_tag(self):
        sel = self.tag_lb.curselection()
        if sel:
            key = self.tag_lb.get(sel[0]).split(" : ")[0]
            if "tag_map" in self.cm.config:
                del self.cm.config["tag_map"][key]
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

    def save_and_close(self):
        self.cm.config["bible_path"] = self.bible_ent.get()
        self.cm.config["glossary_path"] = self.gloss_ent.get()
        if "presets" not in self.cm.config:
            self.cm.config["presets"] = {"Standard": 50}
        if "wall_presets" not in self.cm.config:
            self.cm.config["wall_presets"] = {"Standard": 7}
        self.cm.save_all()
        messagebox.showinfo("Success", "Configuration saved!")
        self.win.destroy()