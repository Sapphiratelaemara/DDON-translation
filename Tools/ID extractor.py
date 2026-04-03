#!/usr/bin/env python3
import json
import os
import re
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext

# ---------------- Presets storage ----------------

def get_script_dir():
    return os.path.dirname(os.path.abspath(__file__))

def get_presets_path():
    return os.path.join(get_script_dir(), "presets.json")

def load_presets():
    path = get_presets_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}

def save_presets(presets):
    path = get_presets_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save presets.json: {e}")

# ---------------- Core logic ----------------

def extract_value(obj, path):
    parts = path.split(".")
    for p in parts:
        if isinstance(obj, dict) and p in obj:
            obj = obj[p]
        else:
            return None
    return obj

def flatten_fields(obj, prefix=""):
    fields = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = k if prefix == "" else prefix + "." + k
            if isinstance(v, dict):
                fields.extend(flatten_fields(v, full))
            else:
                fields.append(full)
    return fields

def process_file_data(data, list_field, id_field, name_field, prefix, separator):
    items = data
    for part in list_field.split("."):
        if isinstance(items, dict):
            items = items.get(part, [])
        else:
            items = []
            break

    if not isinstance(items, list):
        raise ValueError("List field does not point to a list.")

    output_lines = []

    for entry in items:
        if not isinstance(entry, dict):
            continue

        id_val = extract_value(entry, id_field)
        name_val = extract_value(entry, name_field)

        if id_val is None or name_val is None:
            continue

        pfx = prefix if prefix else ""
        line = f"\"{pfx}{id_val}\"{separator} \"{name_val}\","
        output_lines.append(line)

    return "\n".join(output_lines)

# ---------------- CSV logic ----------------

def process_csv_data(path, id_field, name_field, prefix, separator):
    output_lines = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            npc_id = row.get(id_field)
            npc_name = row.get(name_field)

            if not npc_id or not npc_name:
                continue

            key = f"\"{prefix}{npc_id}\"" if prefix else f"\"{npc_id}\""
            value = f"\"{npc_name}\""

            output_lines.append(f"{key}{separator} {value},")

    return "\n".join(output_lines)

def load_csv_fields(path):
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames

def auto_detect_lists(data):
    candidates = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                candidates.append(k)
    return candidates

# ---------------- Syntax highlighting ----------------

class JsonHighlighter:
    def __init__(self, text_widget):
        self.text = text_widget
        self._setup_tags()

    def _setup_tags(self):
        self.text.tag_configure("key", foreground="#0077aa")
        self.text.tag_configure("string", foreground="#aa5500")
        self.text.tag_configure("number", foreground="#aa00aa")
        self.text.tag_configure("bool", foreground="#0055aa")
        self.text.tag_configure("null", foreground="#555555")
        self.text.tag_configure("brace", foreground="#555555")

    def highlight(self, content):
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)

        for tag in ("key", "string", "number", "bool", "null", "brace"):
            self.text.tag_remove(tag, "1.0", tk.END)

        key_pattern = re.compile(r'"([^"\\]*(\\.[^"\\]*)*)"\s*:')
        string_pattern = re.compile(r'"([^"\\]*(\\.[^"\\]*)*)"')
        number_pattern = re.compile(r'\b-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?\b')
        bool_pattern = re.compile(r'\b(true|false)\b')
        null_pattern = re.compile(r'\bnull\b')
        brace_pattern = re.compile(r'[{}\[\]]')

        text = content

        for match in key_pattern.finditer(text):
            start = self._index_from_pos(match.start(1))
            end = self._index_from_pos(match.end(1))
            self.text.tag_add("key", start, end)

        for match in string_pattern.finditer(text):
            start = self._index_from_pos(match.start(0))
            end = self._index_from_pos(match.end(0))
            if not self._has_tag_in_range("key", start, end):
                self.text.tag_add("string", start, end)

        for match in number_pattern.finditer(text):
            self.text.tag_add("number",
                self._index_from_pos(match.start(0)),
                self._index_from_pos(match.end(0)))

        for match in bool_pattern.finditer(text):
            self.text.tag_add("bool",
                self._index_from_pos(match.start(0)),
                self._index_from_pos(match.end(0)))

        for match in null_pattern.finditer(text):
            self.text.tag_add("null",
                self._index_from_pos(match.start(0)),
                self._index_from_pos(match.end(0)))

        for match in brace_pattern.finditer(text):
            self.text.tag_add("brace",
                self._index_from_pos(match.start(0)),
                self._index_from_pos(match.end(0)))

        self.text.configure(state="disabled")

    def _index_from_pos(self, pos):
        text = self.text.get("1.0", tk.END)
        line = text.count("\n", 0, pos) + 1
        if line == 1:
            col = pos
        else:
            last_nl = text.rfind("\n", 0, pos)
            col = pos - last_nl - 1
        return f"{line}.{col}"

    def _has_tag_in_range(self, tag, start, end):
        ranges = self.text.tag_ranges(tag)
        for i in range(0, len(ranges), 2):
            s = ranges[i]
            e = ranges[i + 1]
            if self.text.compare(s, "<", end) and self.text.compare(e, ">", start):
                return True
        return False

# ---------------- GUI ----------------

class App:
    def __init__(self, root):
        self.root = root
        root.title("JSON/CSV Extractor Tool")

        self.data = None
        self.presets = load_presets()

        main = ttk.Frame(root, padding=10)
        main.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        top_frame = ttk.Frame(main)
        top_frame.grid(row=0, column=0, sticky="ew")
        top_frame.columnconfigure(1, weight=1)

        ttk.Label(top_frame, text="Input File:").grid(row=0, column=0, sticky="w")
        self.input_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.input_var, width=50).grid(row=0, column=1, sticky="ew")
        ttk.Button(top_frame, text="Browse", command=self.browse_input).grid(row=0, column=2, padx=5)

        ttk.Label(top_frame, text="Preset:").grid(row=1, column=0, sticky="w")
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            top_frame,
            textvariable=self.preset_var,
            state="readonly",
            values=list(self.presets.keys())
        )
        self.preset_combo.grid(row=1, column=1, sticky="w")
        ttk.Button(top_frame, text="Apply Preset", command=self.apply_preset).grid(row=1, column=2, padx=5)
        ttk.Button(top_frame, text="Save Current as Preset", command=self.save_current_as_preset).grid(row=1, column=3, padx=5)

        mid_frame = ttk.Frame(main)
        mid_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        main.rowconfigure(1, weight=1)
        mid_frame.columnconfigure(0, weight=1)
        mid_frame.columnconfigure(1, weight=1)
        mid_frame.columnconfigure(2, weight=0)

        left_frame = ttk.LabelFrame(mid_frame, text="File Preview")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        mid_frame.rowconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        self.preview = scrolledtext.ScrolledText(left_frame, width=60, height=25)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.highlighter = JsonHighlighter(self.preview)

        sel_frame = ttk.Frame(left_frame)
        sel_frame.grid(row=1, column=0, sticky="ew", pady=5)
        ttk.Button(sel_frame, text="Use Selection as ID Field", command=self.set_id_field).grid(row=0, column=0, padx=2)
        ttk.Button(sel_frame, text="Use Selection as Name Field", command=self.set_name_field).grid(row=0, column=1, padx=2)
        ttk.Button(sel_frame, text="Use Selection as List Root", command=self.set_list_field).grid(row=0, column=2, padx=2)

        right_frame = ttk.LabelFrame(mid_frame, text="Configuration & Output")
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(1, weight=1)
        right_frame.rowconfigure(7, weight=1)

        ttk.Label(right_frame, text="List Field (JSON only):").grid(row=0, column=0, sticky="w")
        self.list_var = tk.StringVar(value="")
        self.list_combo = ttk.Combobox(right_frame, textvariable=self.list_var, width=30)
        self.list_combo.grid(row=0, column=1, sticky="ew")
        ttk.Button(right_frame, text="Auto-detect Lists", command=self.autodetect_lists).grid(row=0, column=2, padx=5)

        ttk.Label(right_frame, text="ID Field:").grid(row=1, column=0, sticky="w")
        self.id_var = tk.StringVar(value="")
        ttk.Entry(right_frame, textvariable=self.id_var, width=30).grid(row=1, column=1, sticky="w")

        ttk.Label(right_frame, text="Name Field:").grid(row=2, column=0, sticky="w")
        self.name_var = tk.StringVar(value="")
        ttk.Entry(right_frame, textvariable=self.name_var, width=30).grid(row=2, column=1, sticky="w")

        ttk.Label(right_frame, text="Output Format").grid(row=3, column=0, sticky="w", pady=(10,0))

        ttk.Label(right_frame, text="Prefix (optional):").grid(row=4, column=0, sticky="w")
        self.prefix_var = tk.StringVar(value="")
        ttk.Entry(right_frame, textvariable=self.prefix_var, width=30).grid(row=4, column=1, sticky="w")

        ttk.Label(right_frame, text="Separator:").grid(row=5, column=0, sticky="w")
        self.separator_var = tk.StringVar(value=":")
        ttk.Entry(right_frame, textvariable=self.separator_var, width=5).grid(row=5, column=1, sticky="w")

        ttk.Label(right_frame, text="Output Preview:").grid(row=6, column=0, sticky="w", pady=(5, 0))
        self.output_preview = scrolledtext.ScrolledText(right_frame, width=60, height=10, state="disabled")
        self.output_preview.grid(row=7, column=0, columnspan=3, sticky="nsew")
        ttk.Button(right_frame, text="Update Preview", command=self.update_preview).grid(row=8, column=0, pady=5, sticky="w")

        field_frame = ttk.LabelFrame(mid_frame, text="Available Fields")
        field_frame.grid(row=0, column=2, sticky="ns", padx=5)

        self.field_listbox = tk.Listbox(field_frame, height=25, width=30)
        self.field_listbox.grid(row=0, column=0, columnspan=2, sticky="nsew")

        ttk.Button(field_frame, text="Use as ID", command=self.use_selected_as_id).grid(row=1, column=0, sticky="ew")
        ttk.Button(field_frame, text="Use as Name", command=self.use_selected_as_name).grid(row=1, column=1, sticky="ew")
        ttk.Button(field_frame, text="Use as List Root", command=self.use_selected_as_list).grid(row=2, column=0, columnspan=2, sticky="ew")

        bottom_frame = ttk.Frame(main)
        bottom_frame.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        bottom_frame.columnconfigure(1, weight=1)

        ttk.Label(bottom_frame, text="Output Text File:").grid(row=0, column=0, sticky="w")
        self.output_var = tk.StringVar()
        ttk.Entry(bottom_frame, textvariable=self.output_var, width=50).grid(row=0, column=1, sticky="ew")
        ttk.Button(bottom_frame, text="Browse", command=self.browse_output).grid(row=0, column=2, padx=5)
        ttk.Button(bottom_frame, text="Generate", command=self.run).grid(row=0, column=3, padx=5)

    # -------- File handling --------

    def browse_input(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("JSON or CSV", "*.json *.csv"),
                ("JSON Files", "*.json"),
                ("CSV Files", "*.csv"),
                ("All Files", "*.*")
            ]
        )
        if path:
            self.input_var.set(path)
            self.load_preview(path)

    def load_preview(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()

            # CSV preview = plain text
            if path.lower().endswith(".csv"):
                self.data = None
                self.preview.configure(state="normal")
                self.preview.delete("1.0", tk.END)
                self.preview.insert("1.0", text)
                self.preview.configure(state="disabled")
                return

            # JSON preview
            try:
                data = json.loads(text)
                self.data = data
                pretty = json.dumps(data, indent=2, ensure_ascii=False)
                self.highlighter.highlight(pretty)
            except Exception:
                self.data = None
                self.preview.configure(state="normal")
                self.preview.delete("1.0", tk.END)
                self.preview.insert("1.0", text)
                self.preview.configure(state="disabled")

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def browse_output(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt")
        if path:
            self.output_var.set(path)

    # -------- Selection helpers --------

    def get_selection(self):
        try:
            sel = self.preview.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
            return sel.strip('"').strip().strip(",")
        except tk.TclError:
            return ""

    def set_id_field(self):
        sel = self.get_selection()
        if sel:
            self.id_var.set(sel)

    def set_name_field(self):
        sel = self.get_selection()
        if sel:
            self.name_var.set(sel)

    def set_list_field(self):
        sel = self.get_selection()
        if sel:
            self.list_var.set(sel)
            self.list_combo.set(sel)

    # -------- Auto-detect lists --------

    def autodetect_lists(self):
        if self.data is None:
            if not self.input_var.get():
                messagebox.showerror("Error", "No JSON loaded.")
                return
            try:
                with open(self.input_var.get(), "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                messagebox.showerror("Error", str(e))
                return

        candidates = auto_detect_lists(self.data)
        if not candidates:
            messagebox.showinfo("Info", "No list-of-object fields detected at top level.")
            return

        self.list_combo["values"] = candidates
        self.list_combo.set(candidates[0])
        self.list_var.set(candidates[0])

        first_obj = None
        for obj in self.data[candidates[0]]:
            if isinstance(obj, dict):
                first_obj = obj
                break

        if first_obj is None:
            messagebox.showerror("Error", "No valid objects found in list.")
            return

        fields = flatten_fields(first_obj)

        self.field_listbox.delete(0, tk.END)
        for f in fields:
            self.field_listbox.insert(tk.END, f)

    # -------- Field list actions --------

    def get_selected_field(self):
        try:
            idx = self.field_listbox.curselection()
            if not idx:
                return None
            return self.field_listbox.get(idx[0])
        except:
            return None

    def use_selected_as_id(self):
        f = self.get_selected_field()
        if f:
            self.id_var.set(f)

    def use_selected_as_name(self):
        f = self.get_selected_field()
        if f:
            self.name_var.set(f)

    def use_selected_as_list(self):
        f = self.get_selected_field()
        if f:
            self.list_var.set(f)
            self.list_combo.set(f)

    # -------- Presets --------

    def apply_preset(self):
        name = self.preset_var.get()
        if not name or name not in self.presets:
            return
        p = self.presets[name]
        self.list_var.set(p.get("list", ""))
        self.list_combo.set(p.get("list", ""))
        self.id_var.set(p.get("id", ""))
        self.name_var.set(p.get("name", ""))
        self.prefix_var.set(p.get("prefix", ""))
        self.separator_var.set(p.get("separator", ":"))

    def save_current_as_preset(self):
        name = simpledialog.askstring("Preset Name", "Enter a name for this preset:")
        if not name:
            return
        name = name.strip()
        if not name:
            return

        self.presets[name] = {
            "list": self.list_var.get(),
            "id": self.id_var.get(),
            "name": self.name_var.get(),
            "prefix": self.prefix_var.get(),
            "separator": self.separator_var.get()
        }
        save_presets(self.presets)
        self.preset_combo["values"] = list(self.presets.keys())
        self.preset_var.set(name)
        messagebox.showinfo("Preset Saved", f"Preset '{name}' saved to presets.json.")

    # -------- Preview & Generate --------

    def update_preview(self):
        path = self.input_var.get()
        if not path:
            messagebox.showerror("Error", "No input file selected.")
            return

        id_field = self.id_var.get()
        name_field = self.name_var.get()
        prefix = self.prefix_var.get()
        separator = self.separator_var.get()

        # CSV preview
        if path.lower().endswith(".csv"):
            try:
                result = process_csv_data(path, id_field, name_field, prefix, separator)
            except Exception as e:
                result = f"ERROR: {e}"

            self.output_preview.configure(state="normal")
            self.output_preview.delete("1.0", tk.END)
            self.output_preview.insert("1.0", result)
            self.output_preview.configure(state="disabled")
            return

        # JSON preview
        if self.data is None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                messagebox.showerror("Error", str(e))
                return

        list_field = self.list_var.get()

        try:
            result = process_file_data(self.data, list_field, id_field, name_field, prefix, separator)
        except Exception as e:
            result = f"ERROR: {e}"

        self.output_preview.configure(state="normal")
        self.output_preview.delete("1.0", tk.END)
        self.output_preview.insert("1.0", result)
        self.output_preview.configure(state="disabled")

    def run(self):
        input_path = self.input_var.get()
        output_path = self.output_var.get()

        if not input_path or not output_path:
            messagebox.showerror("Error", "Please select input and output files.")
            return

        id_field = self.id_var.get()
        name_field = self.name_var.get()
        prefix = self.prefix_var.get()
        separator = self.separator_var.get()

        try:
            if input_path.lower().endswith(".csv"):
                result = process_csv_data(
                    input_path,
                    id_field,
                    name_field,
                    prefix,
                    separator
                )
            else:
                with open(input_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                list_field = self.list_var.get()

                result = process_file_data(
                    data,
                    list_field,
                    id_field,
                    name_field,
                    prefix,
                    separator
                )

        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(result)
            messagebox.showinfo("Success", "File generated successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to write output file:\n{e}")

def main():
    root = tk.Tk()
    App(root)
    root.geometry("1400x750")
    root.mainloop()

if __name__ == "__main__":
    main()