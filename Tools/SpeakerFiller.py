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

# --- Helper Functions ---

def find_json_file(root_dir, target_filename):
    """
    Recursively search through root_dir (including subdirectories)
    to find the JSON file with the given target_filename.
    """
    for root, dirs, files in os.walk(root_dir):
        if target_filename in files:
            return os.path.join(root, target_filename)
    return None

def get_npc_value(json_data, csv_gmd_index):
    """
    Given parsed JSON data and a desired GmdIndex, perform the following:
    
      1. If the JSON dictionary contains a "NativeMsgGroupArray" (commonly used in quest files),
         iterate over each group and its "MsgData" array. On finding a message whose "GmdIndex"
         equals csv_gmd_index, return the group’s English NPC name (from "NpcName" → "En").
         If that value is empty but the group has a nonempty "NpcId", return it instead.
      2. Otherwise, check for a direct "MsgData" list or top‐level "NpcName" and "NpcId" as a fallback.
    
    Only if both the name and ID are not present will an empty string be returned.
    """
    if isinstance(json_data, dict):
        # Check NativeMsgGroupArray first.
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
        # Fallback: try a direct MsgData array.
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

def process_single_csv(csv_file, archive_dir, ui_queue):
    """
    Process one CSV file and overwrite it. Two modes are supported:
    
    • Normal Mode:  
      If the first row has at least seven columns and column 7 (index 6) ends with ".arc",
      then every row is processed as a valid entry (i.e. the header is included). For each row:
         - Ensure at least nine columns exist.
         - If the speaker column (column 9, index 8) is already filled out, leave it intact.
         - Otherwise, use the arc identifier (after stripping the trailing ".arc") to find the corresponding
           JSON file (searched recursively via archive_dir). Convert column 8 (index 7) to an integer,
           use it as GmdIndex, and then use get_npc_value() to retrieve the matching NPC info.
         - The returned value is written into the speaker column.
    
    • Fallback Mode:  
      If the first row does not have a valid arc identifier, then the file is assumed to be missing that info.
      In this case, the CSV file’s name is used to derive a base id; the corresponding JSON file is loaded.
      The header row is then extended with two columns ("english" and "speaker"). Then for each data row (rows 1…N),
      a fallback gmd index is computed based on the row order (first row after the header → 0, second → 1, etc.).
      Only the speaker column is updated (and only if that cell is empty).
    
    Progress information and log messages are sent via ui_queue for safe cross-thread UI updates.
    """
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

    # Determine processing mode based on the first row.
    first_row = rows[0]
    if len(first_row) >= 7 and first_row[6].strip().lower().endswith(".arc"):
        mode = "normal"
    else:
        mode = "fallback"

    if mode == "normal":
        ui_queue.put(("log", f"Processing '{csv_file}' in normal mode."))
        total = len(rows)
        for i, row in enumerate(rows):
            # Ensure row has at least 9 columns.
            while len(row) < 9:
                row.append("")
            # If speaker column already has a value, skip updating it.
            if row[8].strip():
                ui_queue.put(("progress", i + 1))
                continue
            arc_entry = row[6].strip()
            if not arc_entry.lower().endswith(".arc"):
                row[8] = ""
                ui_queue.put(("progress", i + 1))
                continue
            base_id = arc_entry[:-4]
            json_filename = base_id + ".mss.json"
            json_filepath = find_json_file(archive_dir, json_filename)
            if not json_filepath:
                ui_queue.put(("log", f"File not found: {json_filename} (from {arc_entry})"))
                row[8] = ""
                ui_queue.put(("progress", i + 1))
                continue
            try:
                with open(json_filepath, encoding="utf-8") as json_file:
                    json_data = json.load(json_file)
            except Exception as e:
                ui_queue.put(("log", f"Error reading JSON file {json_filepath}: {e}"))
                row[8] = ""
                ui_queue.put(("progress", i + 1))
                continue
            try:
                csv_gmd_index = int(row[7].strip())
            except Exception:
                ui_queue.put(("log", f"Invalid gmd index in CSV: {row[7]}"))
                row[8] = ""
                ui_queue.put(("progress", i + 1))
                continue
            npc_value = get_npc_value(json_data, csv_gmd_index)
            # Update speaker column only if not already filled.
            if not row[8].strip():
                row[8] = npc_value
            ui_queue.put(("progress", i + 1))
    else:
        ui_queue.put(("log", f"Processing '{csv_file}' in fallback mode (using file name for base id)."))
        # Derive base id from the CSV file’s name (e.g. "q00000012" from "q00000012.csv").
        base_id = os.path.splitext(os.path.basename(csv_file))[0]
        json_filename = base_id + ".mss.json"
        json_filepath = find_json_file(archive_dir, json_filename)
        if not json_filepath:
            ui_queue.put(("log", f"JSON file not found: {json_filename} for {csv_file}."))
            json_data = {}
        else:
            try:
                with open(json_filepath, encoding="utf-8") as json_file:
                    json_data = json.load(json_file)
            except Exception as e:
                ui_queue.put(("log", f"Error reading JSON file {json_filepath}: {e}"))
                json_data = {}

        # In fallback mode, append two extra columns ("english" and "speaker") to the header.
        if rows:
            rows[0].extend(["english", "speaker"])
        total = len(rows) - 1  # data rows count
        for j in range(1, len(rows)):
            row = rows[j]
            # Ensure the row has the same number of columns as the header.
            while len(row) < len(rows[0]):
                row.append("")
            # If the speaker field (assumed to be the new last column) is already nonempty, skip it.
            if row[-1].strip():
                ui_queue.put(("progress", j))
                continue
            # Fallback gmd index is given by (row index - 1)
            gmd_index = j - 1
            npc_value = get_npc_value(json_data, gmd_index)
            # Only update the speaker column (leave the english column untouched).
            row[-1] = npc_value
            ui_queue.put(("progress", j))
    # Overwrite the original CSV file.
    try:
        with open(csv_file, "w", newline="", encoding="utf-8") as outfile:
            writer = csv.writer(outfile)
            writer.writerows(rows)
        ui_queue.put(("log", f"Replaced original file: {csv_file}"))
    except Exception as e:
        ui_queue.put(("log", f"Error writing modified CSV for {csv_file}: {e}"))
    ui_queue.put(("progress", 0))

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

        self.select_archive_button = tk.Button(
            master,
            text="Select JSON Archive Directory",
            command=self.select_archive_directory
        )
        self.select_archive_button.grid(row=0, column=1, padx=5, pady=5)

        self.process_button = tk.Button(master, text="Run", command=self.start_processing)
        self.process_button.grid(row=0, column=2, padx=5, pady=5)

        # Progress Bar.
        self.progress_bar = ttk.Progressbar(master, orient="horizontal", mode="determinate", length=400)
        self.progress_bar.grid(row=2, column=0, columnspan=3, padx=10, pady=(5,15))

        # Log Output.
        self.log_text = tk.Text(master, wrap=tk.WORD, height=15, width=90)
        self.log_text.grid(row=1, column=0, columnspan=3, padx=10, pady=10)

        # Start polling the UI queue.
        self.poll_ui_queue()

    def poll_ui_queue(self):
        try:
            while True:
                msg_type, content = self.ui_queue.get_nowait()
                if msg_type == "log":
                    self.log(content)
                elif msg_type == "progress":
                    self.progress_bar.config(value=content)
                # 'done' messages could be used to re-enable buttons, etc.
        except queue.Empty:
            pass
        self.master.after(100, self.poll_ui_queue)

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def select_csv_files(self):
        files = filedialog.askopenfilenames(
            title="Select CSV Files",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if files:
            self.csv_files = list(files)
            self.log("Selected CSV files:")
            for f in self.csv_files:
                self.log(f)

    def select_archive_directory(self):
        directory = filedialog.askdirectory(
            initialdir=(self.archive_dir or None),
            title="Select JSON Archive Directory"
        )
        if directory:
            self.archive_dir = directory
            save_last_archive_folder(directory)
            self.log(f"Selected JSON archive directory: {directory}")

    def start_processing(self):
        if not self.csv_files:
            messagebox.showerror("Error", "No CSV files selected. Please select one or more CSV files.")
            return
        if not self.archive_dir:
            messagebox.showerror("Error", "No JSON archive directory selected. Please select a directory.")
            return
        # Disable the "Run" button while processing.
        self.process_button.config(state="disabled")
        threading.Thread(target=self.process_all_files, daemon=True).start()

    def process_all_files(self):
        for csv_file in self.csv_files:
            self.ui_queue.put(("log", f"Starting processing for {csv_file}..."))
            process_single_csv(csv_file, self.archive_dir, self.ui_queue)
        self.ui_queue.put(("log", "All CSV files have been processed."))
        # Re-enable the "Run" button after processing is done.
        self.master.after(0, lambda: self.process_button.config(state="normal"))

if __name__ == "__main__":
    root = tk.Tk()
    app = CSVProcessorApp(root)
    root.mainloop()
