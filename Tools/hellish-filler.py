#!/usr/bin/env python
import os
import sys
import csv
import io
import re
import tkinter as tk
from tkinter import filedialog, messagebox

# Global flag storing your decision on prefix removal (None means not yet set).
global_remove_prefixes = None

# --------------------------------------------------------
# CSV File Helpers
# --------------------------------------------------------
def get_csv_files(folder):
    """Recursively return a list of all CSV file paths under the given folder."""
    csv_files = []
    for root, dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".csv"):
                csv_files.append(os.path.join(root, f))
    return csv_files

def load_csv_file(file_path):
    """Reads the CSV file and returns its rows as a list of lists."""
    rows = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)
    return rows

def write_csv_file(file_path, rows):
    """Overwrites the CSV file at file_path with the provided rows."""
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

# --------------------------------------------------------
# Prefix Removal
# --------------------------------------------------------
def process_prefix(english_text):
    """
    Examines the extracted english_text for a character name prefix.
    
    - If the very first line consists solely of a name and a colon (ignoring surrounding whitespace),
      that entire line is removed.
    - If the first line begins with a name and a colon followed by dialogue,
      only the prefix (up through the colon and any following spaces) is removed.
    
    On the first detection a popup asks if you wish to remove such prefixes; the decision is stored globally.
    Returns the processed english_text (with internal newlines preserved).
    """
    global global_remove_prefixes
    lines = english_text.splitlines()
    if not lines:
        return english_text
    # Case 1: If the first line is solely a name followed by a colon:
    if re.fullmatch(r'\s*[^:]+:\s*', lines[0]):
        if global_remove_prefixes is None:
            answer = messagebox.askyesno(
                "Remove Character Name Prefix?",
                f"The following line appears to be a character name prefix:\n\n{lines[0]}\n\nRemove it (and similar prefixes)?"
            )
            global_remove_prefixes = answer
        if global_remove_prefixes:
            lines = lines[1:]
    else:
        # Case 2: If the first line begins with a prefix and then dialogue:
        m = re.match(r'^(\s*[^:]+:\s+)(.+)$', lines[0])
        if m:
            if global_remove_prefixes is None:
                answer = messagebox.askyesno(
                    "Remove Character Name Prefix?",
                    f"A character name prefix was detected:\n\n{m.group(1)}\n\nRemove it?"
                )
                global_remove_prefixes = answer
            if global_remove_prefixes:
                lines[0] = m.group(2).lstrip()
    return "\n".join(lines)

# --------------------------------------------------------
# TXT File Parsing
# --------------------------------------------------------
def parse_sections(txt_file_path):
    """
    Reads the entire TXT file and splits it into sections (groups of lines separated by blank lines).
    
    Each section is expected to follow one of these layouts:
    
      • Layout A (Target info on first line – single-line entries):
            Line 1: Target info (e.g., "6.............. n1004.arc,6")
            Lines 2 onward: A quoted CSV record (which may span multiple lines) where the second field is the English text.
      
      • Layout B (Target info on second line):
            Line 1: Header (ignored)
            Line 2: Target info (e.g., "n0014.arc,3")
            Lines 3 onward: Quoted CSV record, with override tokens possibly in the last line.
    
    Extraction Process:
      1. Determine target info:
         - First, try to see if the very last line contains override tokens (if so, use those).
         - Otherwise, if the first line contains a comma and a valid target pattern,
           use that (Layout A). Otherwise, use the second line (Layout B).
      2. For Layout A, let the block be the join of lines starting from line 2.
         For Layout B, let the block be the join of lines starting from line 3.
      3. In the block, find the first occurrence of a double quote and join all lines from that point.
      4. Apply the following regex pattern (with re.DOTALL) to capture two quoted fields:
             r'"((?:[^"]|"")*)","((?:[^"]|"")*)"(?=,|$)'
         This pattern:
             - Allows for internal escaped quotes (as double double-quotes).
             - Ends the English field only if a quote is immediately followed by a comma or end of string.
         Group 2 is taken as the full English text.
      5. Unescape any doubled quotes (i.e. replace '""' with '"') and pass the text to process_prefix().
    
    Returns a list of dictionaries, each with:
         "identifier", "read_index", "english_text", "original" (list of section lines), and "matched" (initially False).
    """
    with open(txt_file_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    # Split the file into sections by blank lines.
    sections = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                sections.append(current)
                current = []
        else:
            current.append(line)
    if current:
        sections.append(current)

    parsed_sections = []
    # Updated regex to capture two quoted fields, handling internal quotes:
    pattern = re.compile(r'"((?:[^"]|"")*)","((?:[^"]|"")*)"(?=,|$)', re.DOTALL)

    for sec in sections:
        if len(sec) < 1:
            continue

        identifier = ""
        read_index = ""
        block = ""

        # Try to use override tokens from the last line (works for one-line entries as well).
        last_line_tokens = [tok.strip() for tok in sec[-1].split(",") if tok.strip() != ""]
        if len(last_line_tokens) >= 2 and re.search(r'\b(n\d{4}\.arc)\b', last_line_tokens[-2]):
            identifier = re.search(r'\b(n\d{4}\.arc)\b', last_line_tokens[-2]).group(1)
            read_index = last_line_tokens[-1]
            block = "\n".join(sec)
        else:
            # Otherwise, if the first line contains target info use Layout A.
            if ',' in sec[0]:
                parts = sec[0].split(",")
                if len(parts) >= 2:
                    identifier = re.search(r'\b(n\d{4}\.arc)\b', parts[0]).group(1) if re.search(r'\b(n\d{4}\.arc)\b', parts[0]) else parts[0].strip()
                    read_index = parts[1].strip()
                    block = "\n".join(sec[1:])
                else:
                    continue
            else:
                # Otherwise, assume Layout B.
                if len(sec) < 2:
                    continue
                match_b = re.search(r'\b(n\d{4}\.arc)\b\s*,\s*(\d+)', sec[1])
                if match_b:
                    identifier = match_b.group(1)
                    read_index = match_b.group(2)
                else:
                    parts = sec[1].split(",")
                    if len(parts) >= 2:
                        identifier = parts[0].strip()
                        read_index = parts[1].strip()
                    else:
                        continue
                block = "\n".join(sec[2:])

        # From the block, find the first occurrence of a double quote and join from there.
        quote_idx = block.find('"')
        if quote_idx == -1:
            english_text = ""
        else:
            quoted_block = block[quote_idx:]
            m = pattern.search(quoted_block)
            if m:
                english_text = m.group(2)
            else:
                # Fallback: CSV reader on substring from the quote.
                f_io = io.StringIO(quoted_block)
                try:
                    reader = csv.reader(f_io)
                    row = next(reader, [])
                    english_text = row[1] if len(row) >= 2 else ""
                except Exception:
                    english_text = ""
        english_text = english_text.strip()
        # Unescape any doubled quotes.
        english_text = english_text.replace('""', '"')
        english_text = process_prefix(english_text)

        parsed_sections.append({
            "identifier": identifier,
            "read_index": read_index,
            "english_text": english_text,
            "original": sec,
            "matched": False
        })
    return parsed_sections

# --------------------------------------------------------
# Update CSV Files Using Parsed TXT Data
# --------------------------------------------------------
def update_csv_files(sections, archive_folder):
    """
    Recursively scans all CSV files in the archive_folder.
    For each CSV file:
      - Loads its rows.
      - For every row, if the row's 7th column (index 6) equals sec["identifier"]
        and its 8th column (index 7) equals sec["read_index"],
        updates the 4th column (index 3) with sec["english_text"] and marks that section as matched.
      - If any row is updated, overwrites the CSV file.
    """
    csv_files = get_csv_files(archive_folder)
    for csv_file in csv_files:
        updated = False
        rows = load_csv_file(csv_file)
        for row in rows:
            if len(row) < 8:
                continue
            for sec in sections:
                if sec["matched"]:
                    continue
                if row[6].strip() == sec["identifier"] and row[7].strip() == sec["read_index"]:
                    row[3] = sec["english_text"]
                    sec["matched"] = True
                    updated = True
                    break
        if updated:
            write_csv_file(csv_file, rows)
            print(f"Updated file: {csv_file}")

# --------------------------------------------------------
# Write Unmatched Sections and Generate Report
# --------------------------------------------------------
def write_unmatched(sections, txt_file):
    """
    Overwrites the input TXT file so that only unmatched sections remain.
    Also writes a separate report file (with _unmatched_report appended to the base name)
    listing all unmatched sections.
    """
    unmatched = [sec for sec in sections if not sec["matched"]]
    with open(txt_file, "w", encoding="utf-8") as f:
        for sec in unmatched:
            f.write("\n".join(sec["original"]) + "\n\n")
    report_file = os.path.splitext(txt_file)[0] + "_unmatched_report.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        for sec in unmatched:
            f.write("\n".join(sec["original"]) + "\n\n")
    print(f"Unmatched sections written to {report_file}")

# --------------------------------------------------------
# Main Procedure and Drag-and-Drop Support
# --------------------------------------------------------
def main(archive_folder, txt_file):
    print("Processing archive folder:", archive_folder)
    print("Using input TXT file:", txt_file)
    sections = parse_sections(txt_file)
    print(f"Found {len(sections)} sections in TXT file.")
    update_csv_files(sections, archive_folder)
    write_unmatched(sections, txt_file)
    print("Processing complete.")

if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()  # Hide the main Tkinter window.
    archive_folder = None
    txt_file = None
    args = sys.argv[1:]
    for a in args:
        if os.path.isdir(a):
            archive_folder = os.path.abspath(a)
        elif os.path.isfile(a) and a.lower().endswith(".txt"):
            txt_file = os.path.abspath(a)
    if not archive_folder:
        archive_folder = filedialog.askdirectory(title="Select CSV Archive Folder")
        if not archive_folder:
            sys.exit("No archive folder provided.")
    if not txt_file:
        txt_file = filedialog.askopenfilename(title="Select input TXT file", filetypes=[("TXT Files", "*.txt")])
        if not txt_file:
            sys.exit("No TXT file provided.")
    main(archive_folder, txt_file)
