#!/usr/bin/env python3
"""
This script processes CSV files and examines the fourth column (index 3) of each row.
It looks for “broken tags” that may span multiple lines—even if there are one or more
blank lines between the tag parts.

A broken tag is defined as follows:
  • The first part is a line (after trimming trailing whitespace) that ends with one of the tokens:
       <AREA, <COL, <HAVE, <ICON, <ITEM, <KC, <KCP, <KCT, <KCTP,
       <NAME, <NPC, <QCND, <QDEL, <QDEL NAME, <SPAI, <SPOT, <SQDI, <STG,
       <UNIT, <UNTN, <VAL
  • The second part (missing fragment) is expected to appear on the next non‑blank line.
    It is taken as all characters from the start of that line up to and including the first ">".
    That fragment is removed from that line and appended (with a single preceding space)
    to the first line.

For each CSV file processed:
  • Any rows that receive a fix are logged (with row number and the original and fixed cell)
    into a log file named "results.txt".
  • If any row is modified, the CSV file is overwritten with the corrected rows.

Usage:
    python fix_broken_tags.py file1.csv file2.csv ...
Or drag-and-drop one or more CSV files onto the script.
"""

import csv
import sys
import os
import re

# List of tokens that indicate the first part of a broken tag.
TOKENS = [
    "<AREA", "<COL", "<HAVE", "<ICON", "<ITEM", "<KC", "<KCP", "<KCT", "<KCTP",
    "<NAME", "<NPC", "<QCND", "<QDEL", "<QDEL NAME", "<SPAI", "<SPOT", "<SQDI",
    "<STG", "<UNIT", "<UNTN", "<VAL"
]

def ends_with_token(line, tokens):
    """
    If the given line (after rstripping) ends with one of the tokens, return that token.
    Otherwise, return None.
    """
    stripped = line.rstrip()
    for token in tokens:
        if stripped.endswith(token):
            return token
    return None

def fix_broken_tags(text):
    """
    Processes a multi‑line text (from the fourth CSV column) searching for broken tags.
    
    When a line ends (after rstrip) with one of the designated tokens, the function skips
    one or more blank lines until it finds the next non‑blank line. On that line, it uses a regex
    to extract a fragment from the beginning up to and including the first occurrence of ">".
    
    If found, the fragment is removed from that later line and is appended (with a single space)
    to the end of the first line.
    
    Returns a tuple:
      - modified_text: the revised multi‑line text.
      - changed: True if the text was modified, otherwise False.
    """
    lines = text.splitlines()
    modified = False
    i = 0
    while i < len(lines):
        token = ends_with_token(lines[i], TOKENS)
        if token:
            # Find the index of the next non-blank line (skip blank lines).
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                candidate_line = lines[j]
                # Extract, from the start of candidate_line, a fragment up to and including the first ">"
                m = re.match(r'^\s*(\S+?>)', candidate_line)
                if m:
                    fragment = m.group(1)  # Including the ">"
                    new_line = lines[i].rstrip() + " " + fragment
                    if new_line != lines[i]:
                        lines[i] = new_line
                        modified = True
                        # Remove the matched fragment from the beginning of candidate_line.
                        lines[j] = candidate_line[m.end():]
        i += 1
    return "\n".join(lines), modified

def process_csv(csv_path, output_handle):
    """
    Processes a CSV file:
      • Reads the CSV.
      • For every row with at least 4 columns, applies fix_broken_tags() on the cell in column 4.
      • If a fix is applied to a row, logs the row number, original cell, and fixed cell to output_handle.
      • Returns the updated list of rows and a Boolean indicating if any row was modified.
    """
    output_handle.write(f"Processing file: {csv_path}\n{'-' * 40}\n")
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as csvfile:
            reader = list(csv.reader(csvfile))
    except Exception as e:
        output_handle.write(f"Error reading {csv_path}: {e}\n\n")
        return None, False

    change_flag = False
    row_number = 0
    for row in reader:
        row_number += 1
        if len(row) < 4:
            continue
        original_cell = row[3]
        fixed_cell, changed = fix_broken_tags(original_cell)
        if changed:
            row[3] = fixed_cell
            change_flag = True
            output_handle.write(f"Row {row_number}:\n")
            output_handle.write(f"    Original: {repr(original_cell)}\n")
            output_handle.write(f"    Fixed:    {repr(fixed_cell)}\n\n")
    output_handle.write("\n")
    return reader, change_flag

def main():
    if len(sys.argv) < 2:
        print("Usage: Drag and drop CSV files onto this script or run from the command line with file names.")
        sys.exit(1)

    output_filename = "results.txt"
    overall_changes = False
    with open(output_filename, "w", encoding="utf-8") as output_handle:
        for file_path in sys.argv[1:]:
            if os.path.isfile(file_path):
                updated_rows, changed = process_csv(file_path, output_handle)
                if changed and updated_rows is not None:
                    try:
                        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
                            writer = csv.writer(csvfile)
                            writer.writerows(updated_rows)
                        output_handle.write(f"Updated file: {file_path}\n\n")
                        overall_changes = True
                    except Exception as e:
                        output_handle.write(f"Error writing {file_path}: {e}\n\n")
            else:
                output_handle.write(f"File not found: {file_path}\n\n")
    print(f"Processing complete. Results logged to {output_filename}.")

if __name__ == '__main__':
    main()
