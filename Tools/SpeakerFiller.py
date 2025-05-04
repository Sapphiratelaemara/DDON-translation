import os
import csv
import json
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
    Recursively searches through root_dir (including subdirectories)
    to find the JSON file with the given target_filename.
    """
    for root, dirs, files in os.walk(root_dir):
        if target_filename in files:
            return os.path.join(root, target_filename)
    return None

def get_npc_value(json_data, csv_gmd_index):
    """
    Given JSON data and a desired GmdIndex, attempts the following:
    
      1. Check if the JSON (typical quest files) contains a "NativeMsgGroupArray."  
         For each group, iterate over its "MsgData" array; if any message’s "GmdIndex" equals csv_gmd_index,  
         then return the group’s English NPC name (from "NpcName" → "En").  
         If that is blank but the group’s "NpcId" is present, return the id (as a string).  
      2. Otherwise, check for a direct "MsgData" array or top-level "NpcName" and "NpcId."  
      
    Only if both the NPC name and NPC id are absent does an empty string get returned.
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

def process_single_csv(csv_file, archive_dir, log_callback, progress_bar):
    """
    Processes one CSV file and overwrites it. Two modes are implemented:
    
    • Normal Mode:  
      If the first row has at least seven columns and the value in column 7 (index 6) ends with ".arc",
      the file is treated as a normal file. Every row is processed (the header row is also a valid entry).  
      For each row the following is done:
         - Ensure the row has at least nine columns (padding if needed).
         - Use column 7 (index 6) as the arc identifier (after removing the trailing ".arc")  
           to search for the corresponding JSON file (searched recursively).  
         - Convert the value from column 8 (index 7) into an integer; this is the GmdIndex.  
         - Use get_npc_value() to retrieve the NPC name (or NPC id if the name is blank) and write it into column 9  
           (the “speaker” column).
    
    • Fallback Mode:  
      If the first row does not have a valid arc identifier, the file is assumed to be missing that info.  
      In fallback mode the CSV file’s name is used to derive the base id, and the corresponding JSON file is loaded.
      A new column labeled “speaker” is appended to the header (row 0). For each subsequent row the gmd index is  
      determined by its order (the first row after the header is considered index 0, the next index 1, etc.).  
      The resulting NPC info (via get_npc_value()) is appended as a new column.
      
    After processing, the CSV file is overwritten.
    """
    try:
        with open(csv_file, newline="", encoding="utf-8") as infile:
            reader = csv.reader(infile)
            rows = list(reader)
    except Exception as e:
        log_callback(f"Error reading CSV file {csv_file}: {e}")
        return

    if not rows:
        log_callback(f"CSV file {csv_file} is empty.")
        return

    # Determine processing mode based on the first row.
    # (We assume the file is in normal mode if row[6] exists and ends with ".arc".)
    first_row = rows[0]
    if len(first_row) >= 7 and first_row[6].strip().lower().endswith(".arc"):
        mode = "normal"
    else:
        mode = "fallback"

    update_progress = lambda: progress_bar.update_idletasks()

    if mode == "normal":
        log_callback(f"Processing '{csv_file}' in normal mode.")
        progress_bar["value"] = 0
        progress_bar["maximum"] = len(rows)
        # Process every row—even the header row is a valid entry.
        for i, row in enumerate(rows):
            # Ensure there are at least 9 columns (so that index 8 exists for speaker)
            while len(row) < 9:
                row.append("")
            arc_entry = row[6].strip()
            if not arc_entry.lower().endswith(".arc"):
                row[8] = ""
            else:
                base_id = arc_entry[:-4]
                json_filename = base_id + ".mss.json"
                json_filepath = find_json_file(archive_dir, json_filename)
                if not json_filepath:
                    log_callback(f"File not found: {json_filename} for row with identifier {arc_entry}")
                    row[8] = ""
                else:
                    try:
                        with open(json_filepath, encoding="utf-8") as json_file:
                            json_data = json.load(json_file)
                    except Exception as e:
                        log_callback(f"Error reading JSON file {json_filepath}: {e}")
                        row[8] = ""
                        progress_bar["value"] = i + 1
                        update_progress()
                        continue
                    try:
                        csv_gmd_index = int(row[7].strip())
                    except Exception:
                        log_callback(f"Invalid gmd index in CSV: {row[7]}")
                        row[8] = ""
                        progress_bar["value"] = i + 1
                        update_progress()
                        continue
                    npc_value = get_npc_value(json_data, csv_gmd_index)
                    row[8] = npc_value
            progress_bar["value"] = i + 1
            update_progress()
    else:
        log_callback(f"Processing '{csv_file}' in fallback mode (using file name for base id).")
        # Derive base id from the CSV file’s name (e.g. "q00000012" from "q00000012.csv")
        base_id = os.path.splitext(os.path.basename(csv_file))[0]
        json_filename = base_id + ".mss.json"
        json_filepath = find_json_file(archive_dir, json_filename)
        if not json_filepath:
            log_callback(f"JSON file not found: {json_filename} for {csv_file}.")
            try:
                json_data = {}
            except Exception:
                json_data = {}
        else:
            try:
                with open(json_filepath, encoding="utf-8") as json_file:
                    json_data = json.load(json_file)
            except Exception as e:
                log_callback(f"Error reading JSON file {json_filepath}: {e}")
                json_data = {}
        # In fallback mode, append one extra column "speaker" to the header.
        if rows:
            rows[0].append("speaker")
        progress_bar["value"] = 0
        progress_bar["maximum"] = len(rows) - 1
        update_progress()
        # For rows after the header, use the row order (starting at 0) as the gmd index.
        for j in range(1, len(rows)):
            row = rows[j]
            speaker_val = get_npc_value(json_data, j - 1)
            row.append(speaker_val)
            progress_bar["value"] = j
            update_progress()

    # Overwrite the original CSV file.
    try:
        with open(csv_file, "w", newline="", encoding="utf-8") as outfile:
            writer = csv.writer(outfile)
            writer.writerows(rows)
        log_callback(f"Replaced original file: {csv_file}")
    except Exception as e:
        log_callback(f"Error writing modified CSV for {csv_file}: {e}")
    progress_bar["value"] = 0
    update_progress()

# --- Tkinter User Interface ---

class CSVProcessorApp:
    def __init__(self, master):
        self.master = master
        master.title("CSV Processor for NPC Extraction")

        self.csv_files = []
        self.archive_dir = load_last_archive_folder()

        # UI Buttons
        self.select_csv_button = tk.Button(master, text="Select CSV Files", command=self.select_csv_files)
        self.select_csv_button.grid(row=0, column=0, padx=5, pady=5)

        self.select_archive_button = tk.Button(
            master,
            text="Select JSON Archive Directory",
            command=self.select_archive_directory
        )
        self.select_archive_button.grid(row=0, column=1, padx=5, pady=5)

        self.process_button = tk.Button(master, text="Run", command=self.process_files)
        self.process_button.grid(row=0, column=2, padx=5, pady=5)

        # Progress Bar
        self.progress_bar = ttk.Progressbar(master, orient="horizontal", mode="determinate", length=400)
        self.progress_bar.grid(row=2, column=0, columnspan=3, padx=10, pady=(5, 15))

        # Log Output
        self.log_text = tk.Text(master, wrap=tk.WORD, height=15, width=90)
        self.log_text.grid(row=1, column=0, columnspan=3, padx=10, pady=10)

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

    def process_files(self):
        if not self.csv_files:
            messagebox.showerror("Error", "No CSV files selected. Please select one or more CSV files.")
            return
        if not self.archive_dir:
            messagebox.showerror("Error", "No JSON archive directory selected. Please select a directory.")
            return

        for csv_file in self.csv_files:
            self.log(f"Starting processing for {csv_file}...")
            process_single_csv(csv_file, self.archive_dir, self.log, self.progress_bar)
        messagebox.showinfo("Done", "All CSV files have been processed.")

if __name__ == "__main__":
    root = tk.Tk()
    app = CSVProcessorApp(root)
    root.mainloop()
