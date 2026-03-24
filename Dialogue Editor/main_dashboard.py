import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
import threading
import csv
import os
import re
from translator_engine import TranslationEngine
from config_manager import ConfigManager

class MainDashboard:
    def __init__(self):
        self.cfg = ConfigManager()
        self.engine = TranslationEngine()
        self.root = tk.Tk()
        self.root.title("DDON Automated Formatter (Modular v1.0)")
        self.root.geometry("900x800")
        self.setup_ui()

    def setup_ui(self):
        # Folder Management
        f_frame = tk.LabelFrame(self.root, text=" Target Folders ", pady=10)
        f_frame.pack(fill="x", padx=15, pady=5)
        self.f_list = tk.Listbox(f_frame, height=4, font=("Consolas", 10))
        self.f_list.pack(side="left", fill="x", expand=True, padx=10)
        for f in self.cfg.config["folders"]: self.f_list.insert(tk.END, f)
        
        f_btns = tk.Frame(f_frame)
        f_btns.pack(side="right", padx=10)
        tk.Button(f_btns, text="Add Folder", width=12, command=self.add_folder).pack(pady=2)
        tk.Button(f_btns, text="Remove", width=12, command=self.remove_folder).pack(pady=2)

        # Settings Configuration
        s_frame = tk.LabelFrame(self.root, text=" Global Configuration ", pady=10)
        s_frame.pack(fill="x", padx=15, pady=5)
        
        tk.Label(s_frame, text="Scan Trigger:").grid(row=0, column=0, sticky="w", padx=10)
        self.trig_ent = tk.Entry(s_frame, width=45)
        self.trig_ent.insert(0, self.cfg.config["triggers"][0])
        self.trig_ent.grid(row=0, column=1, pady=5, sticky="w")

        tk.Label(s_frame, text="Char Limit:").grid(row=1, column=0, sticky="w", padx=10)
        self.lim_ent = tk.Entry(s_frame, width=10)
        self.lim_ent.insert(0, str(self.cfg.config["presets"]["Standard"]))
        self.lim_ent.grid(row=1, column=1, sticky="w")

        # Progress and Execution
        self.log_text = scrolledtext.ScrolledText(self.root, height=10, font=("Consolas", 9), bg="#f8f9fa")
        self.log_text.pack(fill="both", expand=True, padx=15, pady=10)

        self.btn_run = tk.Button(self.root, text="RUN AUTOMATION", bg="#28a745", fg="white", 
                                 font=("Arial", 12, "bold"), height=2, command=self.start_task)
        self.btn_run.pack(fill="x", padx=20, pady=15)

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.cfg.config["folders"].append(folder)
            self.f_list.insert(tk.END, folder)
            self.cfg.save_config()

    def remove_folder(self):
        selection = self.f_list.curselection()
        if selection:
            self.cfg.config["folders"].pop(selection[0])
            self.f_list.delete(selection[0])
            self.cfg.save_config()

    def start_task(self):
        self.cfg.config["triggers"] = [self.trig_ent.get()]
        self.cfg.config["presets"]["Standard"] = int(self.lim_ent.get())
        self.cfg.save_config()
        self.log_text.delete(1.0, tk.END)
        self.btn_run.config(state="disabled", bg="#6c757d")
        
        thread = threading.Thread(target=self.execute_logic)
        thread.daemon = True
        thread.start()

    def execute_logic(self):
        limit = self.cfg.config["presets"]["Standard"]
        trigger = self.cfg.config["triggers"][0]
        manual_pile = []
        total_mods = 0

        for folder in self.cfg.config["folders"]:
            for root, _, files in os.walk(folder):
                for f_name in [f for f in files if f.endswith('.csv')]:
                    path = os.path.join(root, f_name)
                    try:
                        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                            rows = list(csv.reader(f))
                        
                        modified = False
                        for idx, row in enumerate(rows):
                            if trigger in "|".join(row) and len(row) > 3:
                                orig = row[3]
                                if self.engine.has_non_col_tags(orig):
                                    manual_pile.append({"path": path, "row": idx, "text": orig, "jap": row[2]})
                                    continue

                                wrapped = self.engine.clean_and_wrap(orig, limit)
                                if wrapped != orig:
                                    row[3] = wrapped
                                    modified = True
                                    total_mods += 1

                        if modified:
                            with open(path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.writer(f)
                                writer.writerows(rows)
                            self.root.after(0, lambda n=f_name: self.log_text.insert(tk.END, f"[FIXED] {n}\n"))
                    except Exception as e:
                        self.root.after(0, lambda n=f_name, err=e: self.log_text.insert(tk.END, f"[ERROR] {n}: {err}\n"))

        self.root.after(0, lambda: self.finalize(total_mods, manual_pile))

    def finalize(self, count, manual_pile):
        self.btn_run.config(state="normal", bg="#28a745")
        messagebox.showinfo("Done", f"Auto-formatted {count} rows.")
        if manual_pile:
            ManualReviewWindow(self.root, manual_pile, self.cfg)

class ManualReviewWindow(tk.Toplevel):
    def __init__(self, parent, pile, cfg):
        super().__init__(parent)
        self.title("Manual Review Required")
        self.geometry("900x600")
        self.pile = pile
        self.cfg = cfg
        self.idx = 0
        self.setup_ui()
        self.load_item()

    def setup_ui(self):
        self.info = tk.Label(self, text="", font=("Arial", 10, "bold"))
        self.info.pack(pady=10)
        
        tk.Label(self, text="Japanese Source:").pack(anchor="w", padx=20)
        self.jap_area = tk.Text(self, height=4, bg="#f0f0f0", font=("MS Gothic", 11))
        self.jap_area.pack(fill="x", padx=20, pady=5)

        tk.Label(self, text="English Translation:").pack(anchor="w", padx=20)
        self.eng_area = scrolledtext.ScrolledText(self, height=8, font=("Consolas", 12))
        self.eng_area.pack(fill="both", expand=True, padx=20, pady=5)

        tk.Button(self, text="SAVE & NEXT", bg="#007bff", fg="white", height=2, command=self.save_next).pack(fill="x", padx=20, pady=20)

    def load_item(self):
        item = self.pile[self.idx]
        self.info.config(text=f"Item {self.idx + 1} of {len(self.pile)} | File: {os.path.basename(item['path'])}")
        self.jap_area.delete(1.0, tk.END); self.jap_area.insert(tk.END, item['jap'])
        self.eng_area.delete(1.0, tk.END); self.eng_area.insert(tk.END, item['text'])

    def save_next(self):
        item = self.pile[self.idx]
        new_text = self.eng_area.get(1.0, tk.END).strip()
        
        # Write individual fix back to CSV
        with open(item['path'], 'r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        rows[item['row']][3] = new_text
        with open(item['path'], 'w', encoding='utf-8', newline='') as f:
            csv.writer(f).writerows(rows)

        self.idx += 1
        if self.idx < len(self.pile): self.load_item()
        else: self.destroy()

if __name__ == "__main__":
    app = MainDashboard()
    app.root.mainloop()