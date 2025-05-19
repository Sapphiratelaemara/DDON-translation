import os
import csv
import json
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

# --- Configuration Persistence ---

CONFIG_FILENAME = "last_archive_folder.txt"

def load_last_archive_folder():
    try:
        with open(CONFIG_FILENAME, "r", encoding="utf-8") as f:
            folder = f.read().strip()
            if os.path.isdir(folder):
                return folder
    except Exception:
        pass
    return ""

def save_last_archive_folder(folder):
    try:
        with open(CONFIG_FILENAME, "w", encoding="utf-8") as f:
            f.write(folder)
    except Exception:
        pass

# --- JSON Archive Indexing and Caching ---

def build_json_index(archive_dir):
    """
    Recursively walks through archive_dir and builds a dictionary mapping each JSON filename 
    (e.g. "q00000012.mss.json") to its full file path.
    """
    json_index = {}
    for root, dirs, files in os.walk(archive_dir):
        for f in files:
            if f.lower().endswith('.json'):
                json_index[f] = os.path.join(root, f)
    return json_index

def find_json_file_in_index(json_index, target_filename):
    """
    Looks up target_filename in the prebuilt json_index and returns its full path (or None).
    """
    return json_index.get(target_filename)

# --- Helper Functions ---

def get_npc_value(json_data, csv_gmd_index):
    """
    Given parsed JSON data and a desired GmdIndex, attempt the following:
    
      1. If the JSON contains a "NativeMsgGroupArray" (typical for quest files),
         iterate over each group and its "MsgData" array. When a message with
         "GmdIndex" equal to csv_gmd_index is found, return the group's English NPC name
         (from "NpcName" → "En"). If that is empty but the group has a nonempty "NpcId", return that.
      2. Otherwise, check for a direct "MsgData" list or a top‐level "NpcName"/"NpcId".
    
    Returns an empty string only if neither is found.
    """
    if isinstance(json_data, dict):
        if "NativeMsgGroupArray" in json_data and isinstance(json_data["NativeMsgGroupArray"], list):
            for group in json_data["NativeMsgGroupArray"]:
                if "MsgData" in group and isinstance(group["MsgData"], list):
                    for msg in group["MsgData"]:
                        if msg.get("GmdIndex") == csv_gmd_index:
                            npc_name = ""
                            if "NpcName" in group and isinstance(group["NpcName"], dict):
                                npc_name = (group["NpcName"].get("En") or "").strip()
                            if npc_name:
                                return npc_name
                            npc_id = group.get("NpcId")
                            if npc_id not in [None, ""]:
                                return str(npc_id)
                            return ""
        if "MsgData" in json_data and isinstance(json_data["MsgData"], list):
            for rec in json_data["MsgData"]:
                if rec.get("GmdIndex") == csv_gmd_index:
                    npc_name = ""
                    if "NpcName" in rec and isinstance(rec["NpcName"], dict):
                        npc_name = (rec["NpcName"].get("En") or "").strip()
                    if npc_name:
                        return npc_name
                    if "NpcName" in json_data and isinstance(json_data["NpcName"], dict):
                        top_name = (json_data["NpcName"].get("En") or "").strip()
                        if top_name:
                            return top_name
                    npc_id = json_data.get("NpcId")
                    if npc_id not in [None, ""]:
                        return str(npc_id)
                    return ""
    elif isinstance(json_data, list):
        for rec in json_data:
            if rec.get("GmdIndex") == csv_gmd_index:
                npc_name = ""
                if "NpcName" in rec and isinstance(rec["NpcName"], dict):
                    npc_name = (rec["NpcName"].get("En") or "").strip()
                if npc_name:
                    return npc_name
                npc_id = rec.get("NpcId")
                if npc_id not in [None, ""]:
                    return str(npc_id)
                return ""
    return ""

def process_single_csv(csv_file, archive_dir, ui_queue, json_index, file_index, total_files):
    """
    Process one CSV file and overwrite it.
    
    Modes:
      • Normal Mode:
        When the first row has at least 7 columns and the 7th column (index 6) ends with ".arc".
        For each row:
          - Ensure at least 9 columns exist.
          - Skip processing if the third column (index 2) is empty.
          - If the speaker column (index 8) is already filled, leave it unchanged.
          - Otherwise, use the arc identifier (without ".arc") to look up the JSON file via json_index.
            Extract the GmdIndex from column 8 and update the speaker column from the JSON.
      • Fallback Mode:
        When the first row does not have a valid arc identifier.
        In this case, the CSV file’s name is used to derive a base id; two extra columns ("english" and "speaker")
        are appended to the header. For data rows, skip processing if the first column (index 0) is empty.
        Then, using a fallback gmd index (based on row order), only update the speaker column if not already filled.
    
    Progress events are sent via ui_queue:
      - "current_file": filename of the current CSV.
      - "file_progress": current file progress percentage (0–100).
      - "overall_progress": overall job progress percentage (0–100).
    """
    ui_queue.put(("current_file", os.path.basename(csv_file)))
    json_cache = {}

    try:
        with open(csv_file, newline="", encoding="utf-8") as infile:
            reader = csv.reader(infile)
            rows = list(reader)
    except Exception as e:
        ui_queue.put(("log", f"Error reading CSV file {csv_file}: {e}"))
        return

    if not rows:
        ui_queue.put(("log", f"CSV file {csv_file} is empty."))
        return

    # Determine the mode.
    first_row = rows[0]
    if len(first_row) >= 7 and first_row[6].strip().lower().endswith(".arc"):
        mode = "normal"
    else:
        mode = "fallback"

    if mode == "normal":
        total_rows = len(rows)
        for i, row in enumerate(rows):
            while len(row) < 9:
                row.append("")
            # Skip processing if the third column is empty.
            if len(row) < 3 or not row[2].strip():
                pass
            # Skip updating if the speaker column (index 8) is already filled.
            elif row[8].strip():
                pass
            else:
                arc_entry = row[6].strip()
                if arc_entry.lower().endswith(".arc"):
                    base_id = arc_entry[:-4]
                    json_filename = base_id + ".mss.json"
                    json_filepath = find_json_file_in_index(json_index, json_filename)
                    if not json_filepath:
                        ui_queue.put(("log", f"File not found: {json_filename} (from {arc_entry})"))
                    else:
                        if json_filepath in json_cache:
                            json_data = json_cache[json_filepath]
                        else:
                            try:
                                with open(json_filepath, encoding="utf-8") as json_file:
                                    json_data = json.load(json_file)
                                    json_cache[json_filepath] = json_data
                            except Exception as e:
                                ui_queue.put(("log", f"Error reading JSON file {json_filepath}: {e}"))
                                json_data = {}
                        try:
                            csv_gmd_index = int(row[7].strip())
                        except Exception:
                            ui_queue.put(("log", f"Invalid gmd index in CSV: {row[7]}"))
                            csv_gmd_index = None
                        if csv_gmd_index is not None:
                            npc_value = get_npc_value(json_data, csv_gmd_index)
                            if not row[8].strip():
                                row[8] = npc_value
            file_progress = int(100 * (i + 1) / total_rows)
            overall_progress = int(100 * ((file_index + file_progress / 100) / total_files))
            ui_queue.put(("file_progress", file_progress))
            ui_queue.put(("overall_progress", overall_progress))
    else:
        base_id = os.path.splitext(os.path.basename(csv_file))[0]
        json_filename = base_id + ".mss.json"
        json_filepath = find_json_file_in_index(json_index, json_filename)
        if not json_filepath:
            ui_queue.put(("log", f"JSON file not found: {json_filename} for {csv_file}."))
            json_data = {}
        else:
            if json_filepath in json_cache:
                json_data = json_cache[json_filepath]
            else:
                try:
                    with open(json_filepath, encoding="utf-8") as json_file:
                        json_data = json.load(json_file)
                        json_cache[json_filepath] = json_data
                except Exception as e:
                    ui_queue.put(("log", f"Error reading JSON file {json_filepath}: {e}"))
                    json_data = {}
        if rows:
            rows[0].extend(["english", "speaker"])
        total_rows = len(rows) - 1
        for j in range(1, len(rows)):
            row = rows[j]
            while len(row) < len(rows[0]):
                row.append("")
            if not row[0].strip():
                pass
            elif not row[-1].strip():
                gmd_index = j - 1
                npc_value = get_npc_value(json_data, gmd_index)
                row[-1] = npc_value
            file_progress = int(100 * j / (total_rows if total_rows > 0 else 1))
            overall_progress = int(100 * ((file_index + file_progress / 100) / total_files))
            ui_queue.put(("file_progress", file_progress))
            ui_queue.put(("overall_progress", overall_progress))
    
    try:
        with open(csv_file, "w", newline="", encoding="utf-8") as outfile:
            writer = csv.writer(outfile)
            writer.writerows(rows)
        ui_queue.put(("log", f"Replaced original file: {csv_file}"))
    except Exception as e:
        ui_queue.put(("log", f"Error writing modified CSV for {csv_file}: {e}"))
    ui_queue.put(("file_progress", 100))

# --- Tkinter User Interface ---

class CSVProcessorApp:
    def __init__(self, master):
        self.master = master
        master.title("CSV Processor for NPC Extraction")
        self.csv_files = []
        self.archive_dir = load_last_archive_folder()
        self.ui_queue = queue.Queue()

        # UI Buttons.
        self.select_csv_button = tk.Button(master, text="Select CSV Files", command=self.select_csv_files)
        self.select_csv_button.grid(row=0, column=0, padx=5, pady=5)

        self.select_csv_folder_button = tk.Button(master, text="Select CSV Folder", command=self.select_csv_folder)
        self.select_csv_folder_button.grid(row=0, column=1, padx=5, pady=5)

        self.select_archive_button = tk.Button(master, text="Select JSON Archive Directory", command=self.select_archive_directory)
        self.select_archive_button.grid(row=0, column=2, padx=5, pady=5)

        self.process_button = tk.Button(master, text="Run", command=self.start_processing)
        self.process_button.grid(row=0, column=3, padx=5, pady=5)

        # Label for current file.
        self.current_file_label = tk.Label(master, text="Current file: None")
        self.current_file_label.grid(row=3, column=0, columnspan=4, pady=(5,0))

        # Progress Bar for current file.
        self.file_progress_bar = ttk.Progressbar(master, orient="horizontal", mode="determinate", length=400)
        self.file_progress_bar.grid(row=4, column=0, columnspan=4, padx=10, pady=(5,0))
        self.file_progress_label = tk.Label(master, text="File Progress: 0%")
        self.file_progress_label.grid(row=5, column=0, columnspan=4, pady=(0,10))

        # Progress Bar for overall job.
        self.overall_progress_bar = ttk.Progressbar(master, orient="horizontal", mode="determinate", length=400)
        self.overall_progress_bar.grid(row=6, column=0, columnspan=4, padx=10, pady=(5,0))
        self.overall_progress_label = tk.Label(master, text="Overall Progress: 0%")
        self.overall_progress_label.grid(row=7, column=0, columnspan=4, pady=(0,10))

        # Log Output.
        self.log_text = tk.Text(master, wrap=tk.WORD, height=15, width=90)
        self.log_text.grid(row=1, column=0, columnspan=4, padx=10, pady=10)

        # Start polling the UI queue.
        self.poll_ui_queue()

    def poll_ui_queue(self):
        try:
            while True:
                msg_type, content = self.ui_queue.get_nowait()
                if msg_type == "log":
                    self.log(content)
                elif msg_type == "file_progress":
                    self.file_progress_bar.config(value=content)
                    self.file_progress_label.config(text=f"File Progress: {content}%")
                elif msg_type == "overall_progress":
                    self.overall_progress_bar.config(value=content)
                    self.overall_progress_label.config(text=f"Overall Progress: {content}%")
                elif msg_type == "current_file":
                    self.current_file_label.config(text=f"Current file: {content}")
        except queue.Empty:
            pass
        self.master.after(100, self.poll_ui_queue)

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def select_csv_files(self):
        # Let the user pick individual CSV files.
        files = filedialog.askopenfilenames(title="Select CSV Files",
                                            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if files:
            self.csv_files = list(files)
            self.log("Selected CSV files:")
            for f in self.csv_files:
                self.log(f)

    def select_csv_folder(self):
        # Let the user pick a folder and then collect all CSV files (including subfolders).
        folder = filedialog.askdirectory(title="Select CSV Folder",
                                         initialdir=(os.path.dirname(self.csv_files[0])
                                                     if self.csv_files else None))
        if folder:
            found_files = []
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".csv"):
                        found_files.append(os.path.join(root, f))
            self.csv_files = found_files
            self.log(f"Selected CSV folder: {folder}")
            self.log(f"Found {len(self.csv_files)} CSV files:")
            for f in self.csv_files:
                self.log(f)

    def select_archive_directory(self):
        directory = filedialog.askdirectory(initialdir=(self.archive_dir or None), title="Select JSON Archive Directory")
        if directory:
            self.archive_dir = directory
            save_last_archive_folder(directory)
            self.log(f"Selected JSON archive directory: {directory}")

    def start_processing(self):
        if not self.csv_files:
            messagebox.showerror("Error", "No CSV files selected. Please select one or more CSV files or a folder.")
            return
        if not self.archive_dir:
            messagebox.showerror("Error", "No JSON archive directory selected. Please select a directory.")
            return
        self.json_index = build_json_index(self.archive_dir)
        self.process_button.config(state="disabled")
        threading.Thread(target=self.process_all_files, daemon=True).start()

    def process_all_files(self):
        total_files = len(self.csv_files)
        for index, csv_file in enumerate(self.csv_files):
            self.ui_queue.put(("log", f"Starting processing for {csv_file}..."))
            process_single_csv(csv_file, self.archive_dir, self.ui_queue, self.json_index, index, total_files)
        self.ui_queue.put(("log", "All CSV files have been processed."))
        self.master.after(0, lambda: self.process_button.config(state="normal"))

if __name__ == "__main__":
    root = tk.Tk()
    app = CSVProcessorApp(root)
    root.mainloop()
