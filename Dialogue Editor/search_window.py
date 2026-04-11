import os
import tkinter as tk
from tkinter import messagebox, ttk
from collections import defaultdict
from file_utils import _get_csv_files, _read_csv

# Maps UI label → column index (None = "all text", -1 = "custom index")
_FIELD_MAP = {
    "English (col 3)":    3,
    "Japanese (col 2)":   2,
    "Speaker (col 8)":    8,
    "Entry Type (col 9)": 9,
    "All Text Fields":    None,
    "Field Index…":       -1,
}


class SearchWindow(tk.Toplevel):
    def __init__(self, parent, cm, app):
        super().__init__(parent)
        self.title("Global Database Search")
        self.geometry("1000x540")
        self.cm = cm
        self.app = app

        bg = "#f5f6fa" if not app.dark_mode else "#1a1a2e"
        fg = "#2c2c3e" if not app.dark_mode else "#e0e0e0"
        accent = "#3867d6" if not app.dark_mode else "#e94560"
        self.configure(bg=bg)

        # ── Top bar ──────────────────────────────────────────────────────
        top = tk.Frame(self, bg=bg)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Search:", bg=bg, fg=fg).pack(side="left")
        self.entry = tk.Entry(top, width=36, font=("Consolas", 10))
        self.entry.pack(side="left", padx=5)
        self.entry.bind("<Return>", lambda e: self.do_search())
        self.entry.focus_set()

        tk.Label(top, text="in:", bg=bg, fg=fg).pack(side="left")
        self.lang_var = tk.StringVar(value="English (col 3)")
        field_opts = list(_FIELD_MAP.keys())
        self._field_combo = ttk.Combobox(top, textvariable=self.lang_var,
                                         values=field_opts, state="readonly", width=18)
        self._field_combo.pack(side="left", padx=(2, 5))
        self._field_combo.bind("<<ComboboxSelected>>", self._on_field_changed)

        # Hidden entry for "Field Index…" mode — shown on demand
        self._field_idx_var = tk.StringVar(value="0")
        self._field_idx_entry = tk.Entry(top, textvariable=self._field_idx_var,
                                         width=4, font=("Consolas", 10))

        tk.Button(top, text="Search", command=self.do_search,
                  bg=accent, fg="white", relief="flat", padx=8).pack(side="left", padx=4)

        tk.Button(top, text="Open all in Translator", command=self.open_all_in_translator,
                  bg=accent, fg="white", relief="flat", padx=8).pack(side="left", padx=4)

        self.lbl_status = tk.Label(top, text="", bg=bg, fg=fg, font=("Arial", 9))
        self.lbl_status.pack(side="left", padx=8)

        # ── Results tree ─────────────────────────────────────────────────
        tree_frame = tk.Frame(self, bg=bg)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")

        cols = ("file", "row", "field", "match", "en")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="browse",
                                 yscrollcommand=vsb.set,
                                 xscrollcommand=hsb.set)
        vsb.config(command=self.tree.yview)
        hsb.config(command=self.tree.xview)

        self.tree.heading("file",  text="File")
        self.tree.heading("row",   text="Row")
        self.tree.heading("field", text="Field")
        self.tree.heading("match", text="Matched Value")
        self.tree.heading("en",    text="English (col 3)")

        self.tree.column("file",  width=160, stretch=False)
        self.tree.column("row",   width=50,  stretch=False, anchor="center")
        self.tree.column("field", width=100, stretch=False, anchor="center")
        self.tree.column("match", width=340)
        self.tree.column("en",    width=320)

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.results_data = []

    # ── Field selector callback ───────────────────────────────────────────

    def _on_field_changed(self, _=None):
        if self.lang_var.get() == "Field Index…":
            self._field_idx_entry.pack(side="left", padx=(0, 4))
        else:
            self._field_idx_entry.pack_forget()

    def _resolve_col(self):
        """Return column index or None (= all text fields).
        Returns the sentinel False on a bad custom index."""
        label = self.lang_var.get()
        col   = _FIELD_MAP.get(label)
        if col == -1:
            try:
                col = int(self._field_idx_var.get())
            except ValueError:
                messagebox.showerror("Bad index",
                    "Enter a valid integer column index.", parent=self)
                return False
        return col   # None means "all fields"

    # ── Search ────────────────────────────────────────────────────────────

    def do_search(self):
        query = self.entry.get().strip()
        if not query:
            return
        query_lc = query.lower()

        csv_files = _get_csv_files(self.cm.config.get("folders", []))
        if not csv_files:
            messagebox.showinfo("Error", "No folders loaded in Options!", parent=self)
            return

        col = self._resolve_col()
        if col is False:
            return  # bad custom index, already reported

        self.tree.delete(*self.tree.get_children())
        self.results_data.clear()
        self.lbl_status.config(text="Searching…")
        self.update_idletasks()

        count = 0
        for file in csv_files:
            try:
                _, _, rows = _read_csv(file)
                for i, row in enumerate(rows):
                    if i == 0:
                        continue  # skip header row

                    if col is None:
                        # All text fields: report the first matching column per row
                        hits = [(ci, row[ci]) for ci in range(len(row))
                                if query_lc in row[ci].lower()]
                    else:
                        if col >= len(row):
                            continue
                        hits = [(col, row[col])] if query_lc in row[col].lower() else []

                    if not hits:
                        continue

                    matched_col, matched_val = hits[0]
                    en  = row[3] if len(row) > 3 else ""
                    jp  = row[2] if len(row) > 2 else ""
                    self.results_data.append({
                        "path":    file,
                        "row_idx": i,
                        "en":      en,
                        "jp":      jp,
                        "col":     matched_col,
                    })
                    self.tree.insert("", "end", iid=str(count), values=(
                        os.path.basename(file),
                        i + 1,
                        f"col {matched_col}",
                        matched_val.replace("\n", " ")[:300],
                        en.replace("\n", " ")[:300],
                    ))
                    count += 1

            except Exception:
                pass

        noun = "result" if count == 1 else "results"
        self.lbl_status.config(text=f"{count} {noun}. Double-click to edit.")

    # ── Open in editor ────────────────────────────────────────────────────

    def open_all_in_translator(self):
        """Build a virtual_rows list from current results and open in CSVTranslationWindow."""
        if not self.results_data:
            messagebox.showinfo("No results", "Run a search first.", parent=self)
            return

        # Cache file reads so we don't re-read the same CSV multiple times
        file_cache = {}
        virtual_rows = []
        for rd in self.results_data:
            path    = rd["path"]
            row_idx = rd["row_idx"]
            if path not in file_cache:
                try:
                    _, dialect, rows = _read_csv(path)
                    file_cache[path] = (dialect, rows)
                except Exception:
                    continue
            _dialect, rows = file_cache[path]
            if row_idx >= len(rows):
                continue
            virtual_rows.append({
                "path":    path,
                "row_idx": row_idx,
                "row":     rows[row_idx],   # live reference — mutations write through
            })

        if not virtual_rows:
            messagebox.showinfo("No results", "No valid rows to open.", parent=self)
            return

        from translation_window import CSVTranslationWindow
        CSVTranslationWindow(self.app, virtual_rows=virtual_rows)

    def on_double_click(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        data = self.results_data[int(sel[0])]

        tag_queue = defaultdict(list)
        tag_queue[data["en"]].append({
            "path":        data["path"],
            "row_idx":     data["row_idx"],
            "tag_reason":  "search_result",
            "unknown_tags": [],
        })

        presets      = self.cm.config.get("presets",      {"Standard": 50})
        wall_presets = self.cm.config.get("wall_presets", {"Standard": 7})

        from main import ReviewEditor
        ReviewEditor(
            self.app,
            tag_queue,
            defaultdict(list),
            defaultdict(list),
            defaultdict(list),
            list(presets.values())[0],
            list(wall_presets.values())[0],
            self.cm.config.get("tag_map", {}),
            self.app.propagate_fix,
        )
