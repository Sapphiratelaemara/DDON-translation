import csv
import os
import re
import json
import tkinter as tk
from tkinter import messagebox, filedialog, ttk, simpledialog, scrolledtext
from collections import defaultdict

# --- CONFIGURATION ---
CONFIG_FILE = "formatter_config.json"
CHAR_MAP_FILE = "character_map.json"

class ReviewEditor(tk.Toplevel):
    def __init__(self, parent, queues, config, callback, config_save_cb):
        super().__init__(parent)
        self.title("DDON Dialogue Reviewer v7.8")
        self.geometry("1400x950")
        
        self.config, self.queues, self.callback, self.config_save_cb = config, queues, callback, config_save_cb
        
        # Data Loading
        self.char_map = self.load_json(CHAR_MAP_FILE, {})
        self.bible_data = self.load_bible(self.config.get("bible_path", "DDON_BIBLE_V2.txt"))
        self.glossary = self.load_glossary(self.config.get("glossary_path", ""))
        self.presets = self.config.get("named_presets", {"Standard": 50})

        self.archetype_info = {
            "Standard": {"desc": "Default DD1 style. Balanced.", "vocation": "Villagers, Fighters"},
            "Warm (A)": {"desc": "Kind/Protective. 'Pray', 'Take heart'.", "vocation": "Mages, Healers"},
            "Rough (B)": {"desc": "Blunt. Curt sentences. 'Bah!', 'Strike!'.", "vocation": "Warriors, Bandits"},
            "Cheerful (C)": {"desc": "Energetic. 'Ho!', 'Let's away!'.", "vocation": "Striders, Rangers"},
            "Timid (D)": {"desc": "Hesitant. Frequent '...' pauses.", "vocation": "Scholars, Civilians"},
            "Formal (E)": {"desc": "Stoic. Highly respectful. 'This one'.", "vocation": "Knights, Nobles"}
        }

        # Initialize Queue
        self.current_category = "To Review"
        self.current_texts = list(self.queues[self.current_category].keys())
        self.current_idx = 0
        self.suggestion_index = 0
        self.current_suggestions = []

        if not self.current_texts:
            messagebox.showwarning("Empty", "No lines found to review in this file.")
            self.destroy()
            return

        self.setup_ui()
        self.load_item()

    def load_json(self, path, default):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f: return json.load(f)
            except: return default
        return default

    def load_bible(self, path):
        bible = {"conflicts": {}, "archaic": {}}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                archaic = re.findall(r'([a-z\']+)\s+—\s+([a-z /]+)', content)
                for arc, modern in archaic: bible["archaic"][modern.strip().lower()] = arc.strip()
        return bible

    def load_glossary(self, path):
        gloss = {}
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2: gloss[row[0].strip()] = row[1].strip()
        return gloss

    def setup_ui(self):
        # Header
        self.header = tk.Frame(self, bg="#f0f0f0", pady=10); self.header.pack(fill="x")
        
        arch_f = tk.Frame(self.header, bg="#f0f0f0")
        arch_f.pack(side="left", padx=20)
        self.speaker_lbl = tk.Label(arch_f, text="SPEAKER: Unknown", font=("Arial", 10, "bold"), bg="#f0f0f0")
        self.speaker_lbl.pack(anchor="w")
        self.arch_combo = ttk.Combobox(arch_f, values=list(self.archetype_info.keys()), state="readonly", width=15)
        self.arch_combo.pack(side="left")
        self.arch_combo.bind("<<ComboboxSelected>>", self.on_arch_change)
        
        self.arch_meta_lbl = tk.Label(self.header, text="", font=("Arial", 8), fg="#444", bg="#f0f0f0", wraplength=400, justify="left")
        self.arch_meta_lbl.pack(side="left", padx=10)

        # Preset Switcher
        tk.Label(self.header, text="Limit:").pack(side="left", padx=(20, 2))
        self.preset_combo = ttk.Combobox(self.header, values=list(self.presets.keys()), state="readonly", width=12)
        if self.presets: self.preset_combo.set(list(self.presets.keys())[0])
        self.preset_combo.pack(side="left")
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_key_release)

        # Glossary Panel
        self.side_panel = tk.Frame(self, width=280, bg="#e8e8e8", padx=10); self.side_panel.pack(side="right", fill="y")
        tk.Label(self.side_panel, text="Glossary Search", bg="#e8e8e8", font=("Arial", 10, "bold")).pack(pady=5)
        self.search_var = tk.StringVar(); self.search_var.trace("w", self.update_glossary_view)
        tk.Entry(self.side_panel, textvariable=self.search_var).pack(fill="x", pady=5)
        self.glossary_list = tk.Listbox(self.side_panel, font=("Arial", 9)); self.glossary_list.pack(fill="both", expand=True)
        self.glossary_list.bind("<Double-Button-1>", self.insert_glossary_term)

        # Editor
        self.paned = tk.PanedWindow(self, orient=tk.VERTICAL, sashwidth=6); self.paned.pack(fill="both", expand=True, padx=20)
        self.text_area = scrolledtext.ScrolledText(self.paned, font=("Consolas", 12), undo=True); self.paned.add(self.text_area, height=450)
        self.source_area = tk.Text(self.paned, font=("MS Gothic", 12), bg="#f4f4f4"); self.paned.add(self.source_area, height=200)
        
        self.counter_label = tk.Label(self, font=("Consolas", 11), pady=5); self.counter_label.pack()
        self.suggestion_tip = tk.Label(self, bg="#fff3cd", relief="solid", borderwidth=1)

        btns = tk.Frame(self, pady=15); btns.pack()
        tk.Button(btns, text="Save & Next", command=self.save_item, bg="#d1ecf1", width=25, font=("Arial", 10, "bold")).pack(side="left", padx=10)
        tk.Button(btns, text="Skip", command=self.next_item, width=10).pack(side="left", padx=10)

        # Bindings
        self.text_area.bind("<KeyRelease>", self.handle_typing)
        self.text_area.bind("<Return>", self.accept_suggestion)
        self.text_area.bind("<Up>", self.cycle_suggestion_up)
        self.text_area.bind("<Down>", self.cycle_suggestion_down)

    def on_arch_change(self, e=None):
        arch = self.arch_combo.get()
        info = self.archetype_info.get(arch, {})
        self.arch_meta_lbl.config(text=f"INFO: {info.get('desc')}\nVOCATIONS: {info.get('vocation')}")
        self.char_map[self.current_speaker] = arch
        with open(CHAR_MAP_FILE, "w", encoding="utf-8") as f: json.dump(self.char_map, f, indent=4)

    def load_item(self):
        if self.current_idx < len(self.current_texts):
            txt = self.current_texts[self.current_idx]
            data = self.queues[self.current_category][txt][0]
            self.current_speaker = data.get('speaker', 'Unknown')
            self.speaker_lbl.config(text=f"SPEAKER: {self.current_speaker}")
            self.arch_combo.set(self.char_map.get(self.current_speaker, "Standard"))
            self.on_arch_change()
            self.text_area.delete(1.0, tk.END); self.text_area.insert(tk.END, txt)
            self.source_area.delete(1.0, tk.END); self.source_area.insert(tk.END, data.get('source', ''))
            self.on_key_release()
        else:
            messagebox.showinfo("Done", "File complete!")
            self.destroy()

    def handle_typing(self, e=None):
        if e and e.keysym in ["Up", "Down", "Return"]: return
        self.on_key_release()
        src_ja = self.source_area.get(1.0, tk.END)
        word = self.text_area.get("insert -1c wordstart", "insert").lower().strip(".,!?;")
        self.current_suggestions = []
        if "——" in src_ja: self.current_suggestions = ["... ", "—! ", "— "]
        hit = self.bible_data["archaic"].get(word)
        if hit: self.current_suggestions.append(hit)
        if self.current_suggestions: self.suggestion_index = 0; self.show_tip()
        else: self.hide_tip()

    def show_tip(self):
        text = self.current_suggestions[self.suggestion_index]
        pos = self.text_area.bbox(tk.INSERT)
        if pos:
            self.suggestion_tip.config(text=text)
            self.suggestion_tip.place(x=pos[0] + 50, y=pos[1] + 60)

    def hide_tip(self): self.suggestion_tip.place_forget()

    def cycle_suggestion_up(self, e):
        if self.current_suggestions:
            self.suggestion_index = (self.suggestion_index - 1) % len(self.current_suggestions)
            self.show_tip(); return "break"

    def cycle_suggestion_down(self, e):
        if self.current_suggestions:
            self.suggestion_index = (self.suggestion_index + 1) % len(self.current_suggestions)
            self.show_tip(); return "break"

    def accept_suggestion(self, e):
        if not self.current_suggestions: return None
        sel = self.current_suggestions[self.suggestion_index]
        if any(p in sel for p in ["...", "—"]): self.text_area.insert(tk.INSERT, sel)
        else:
            self.text_area.delete("insert -1c wordstart", "insert")
            self.text_area.insert(tk.INSERT, sel)
        self.hide_tip(); return "break"

    def on_key_release(self, e=None):
        limit = self.presets.get(self.preset_combo.get(), 50)
        content = self.text_area.get(1.0, tk.END).strip()
        length = len(re.sub(r'<[^>]*>', '', content))
        self.counter_label.config(text=f"Chars: {length} / {limit}", fg="red" if length > limit else "black")

    def update_glossary_view(self, *args):
        q = self.search_var.get().lower()
        self.glossary_list.delete(0, tk.END)
        if q:
            matches = [f"{k} -> {v}" for k, v in self.glossary.items() if q in k.lower() or q in v.lower()]
            for m in matches[:50]: self.glossary_list.insert(tk.END, m)

    def insert_glossary_term(self, e):
        sel = self.glossary_list.curselection()
        if sel: 
            term = self.glossary_list.get(sel[0]).split(" -> ")[1]
            self.text_area.insert(tk.INSERT, term)

    def save_item(self):
        new_text = self.text_area.get(1.0, tk.END).strip()
        orig_text = self.current_texts[self.current_idx]
        self.callback(orig_text, new_text)
        self.next_item()

    def next_item(self): self.current_idx += 1; self.load_item()

class CSVProcessorApp:
    def __init__(self, root):
        self.root = root; self.root.title("DDON CSV Formatter v7.8")
        self.config = self.load_config()
        self.working_data = []
        self.file_path = ""

        main_frame = tk.Frame(root, padx=30, pady=30)
        main_frame.pack()

        tk.Label(main_frame, text="Dragon's Dogma Online Tool", font=("Arial", 14, "bold")).pack(pady=10)
        
        btn_f = tk.Frame(main_frame)
        btn_f.pack(pady=20)
        tk.Button(btn_f, text="📁 Open Folder", command=self.load_folder, width=20).pack(pady=5)
        tk.Button(btn_f, text="📄 Open Single CSV", command=self.load_csv, width=20, bg="#e1f5fe").pack(pady=5)
        
        tk.Button(root, text="Configure Bible/Glossary Paths", command=self.open_settings, font=("Arial", 8)).pack(side="bottom", pady=10)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        return {"named_presets": {"Standard": 50}}

    def open_settings(self):
        b_path = filedialog.askopenfilename(title="Select Bible")
        if b_path: self.config["bible_path"] = b_path
        g_path = filedialog.askopenfilename(title="Select Glossary")
        if g_path: self.config["glossary_path"] = g_path
        with open(CONFIG_FILE, "w") as f: json.dump(self.config, f)

    def load_folder(self):
        folder = filedialog.askdirectory()
        if not folder: return
        for file in os.listdir(folder):
            if file.endswith(".csv"):
                self.process_single_file(os.path.join(folder, file))

    def load_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if path: self.process_single_file(path)

    def process_single_file(self, path):
        self.file_path = path
        self.working_data = []
        queues = defaultdict(dict)
        
        with open(path, 'r', encoding='utf-8') as f:
            reader = list(csv.reader(f))
            self.working_data = reader
            for i, row in enumerate(reader):
                if len(row) > 9:
                    # Index 3: English, 4: Japanese, 9: Speaker
                    queues["To Review"][row[3]] = [{"source": row[4], "speaker": row[9], "row_index": i}]
        
        if queues["To Review"]:
            ReviewEditor(self.root, queues, self.config, self.save_to_file, self.save_cfg)

    def save_to_file(self, original_eng, new_eng):
        for i, row in enumerate(self.working_data):
            if row[3] == original_eng:
                self.working_data[i][3] = new_eng
                break
        with open(self.file_path, 'w', encoding='utf-8', newline='') as f:
            csv.writer(f).writerows(self.working_data)

    def save_cfg(self, c):
        self.config = c
        with open(CONFIG_FILE, "w") as f: json.dump(self.config, f)

if __name__ == "__main__":
    root = tk.Tk(); app = CSVProcessorApp(root); root.mainloop()