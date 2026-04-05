import os
import tkinter as tk
from tkinter import messagebox, ttk
from collections import defaultdict
from file_utils import _get_csv_files, _read_csv

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

        # Build a tag_queue with the single result; other queues are empty.
        tag_queue = defaultdict(list)
        tag_queue[data["en"]].append({
            "path":        data["path"],
            "row_idx":     data["row_idx"],
            "tag_reason":  "search_result",
            "unknown_tags": [],
        })

        presets      = self.cm.config.get("presets",      {"Standard": 50})
        wall_presets = self.cm.config.get("wall_presets", {"Standard": 7})
        limit        = list(presets.values())[0]
        wall_limit   = list(wall_presets.values())[0]

        from main import ReviewEditor
        ReviewEditor(
            self.app,
            tag_queue,
            defaultdict(list),   # wall_queue
            defaultdict(list),   # dash_queue
            defaultdict(list),   # anach_queue
            limit,
            wall_limit,
            self.cm.config.get("tag_map", {}),
            self.app.propagate_fix,
        )
