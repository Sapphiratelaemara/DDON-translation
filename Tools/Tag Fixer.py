#!/usr/bin/env python3
"""
This script processes CSV files and examines the fourth column (index 3) of each row.
It searches for “broken tags” that may be split across multiple lines—even if separated
by blank lines. A broken tag is defined as follows:

  • The first part is a line (after trimming trailing whitespace) that ends with one of
    the following tokens:
       <AREA, <COL, <HAVE, <ICON, <ITEM, <KC, <KCP, <KCT, <KCTP,
       <NAME, <NPC, <QCND, <QDEL, <QDEL NAME, <SPAI, <SPOT, <SQDI, <STG,
       <UNIT, <UNTN, <VAL

  • The second part is the next non‑blank line. From that line the fragment (from the
    very beginning up to and including the first occurrence of ">") is extracted.
    This fragment is appended (with a single preceding space) to the end of the first line.
    Moreover, if after removing the fragment the second part line is empty (or contains only whitespace),
    that line is deleted from the cell data; otherwise, its remaining content is preserved.

For each CSV file processed:
  • Rows where a fix is applied are logged (with row number, original cell, and fixed cell)
    into a log file named "results.txt".
  • Any modification is written back to the CSV file (the CSV is overwritten).

Usage:
    python fix_broken_tags.py file1.csv file2.csv ...
Or drag and drop one or more CSV files onto this script.
"""

import csv
import sys
import os
import re

# List of tokens that indicate that a broken tag is present.
TOKENS = [
    "<AREA", "<COL", "<HAVE", "<ICON", "<ITEM", "<KC", "<KCP", "<KCT", "<KCTP",
    "<NAME", "<NPC", "<QCND", "<QDEL", "<QDEL NAME", "<SPAI", "<SPOT", "<SQDI",
    "<STG", "<UNIT", "<UNTN", "<VAL"
]

def ends_with_token(line, tokens):
    """
    Returns the token if the given line (after rstripping) ends with one of the tokens.
    Otherwise, returns None.
    """
    stripped = line.rstrip()
    for token in tokens:
        if stripped.endswith(token):
            return token
    return None

def fix_broken_tags(text):
    """
    Scans a multi-line text (from a CSV's fourth column) for broken tags.

    When a line ends (after trimming trailing whitespace) with one of the tokens,
    the function skips over any blank lines until it reaches the next non-blank line.
    It then extracts from that next non-blank line a fragment (from the start of the line
    up to and including the first occurrence of ">"). The fragment is removed from that line
    and appended (preceded by a single space) to the end of the first line.

    Additionally, if after removing the fragment the candidate line is completely empty
    (or contains only whitespace), that line is deleted from the multi-line text.

    Returns:
      - modified_text: the updated multi‑line text.
      - changed: True if any fix was applied, otherwise False.
    """
    lines = text.splitlines()
    modified = False
    i = 0
    while i < len(lines):
        token = ends_with_token(lines[i], TOKENS)
        if token:
            # Look for the next non-blank line, skipping any blank ones.
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                candidate_line = lines[j]
                # Extract a fragment: from the start of candidate_line up to the first ">"
                m = re.match(r'^\s*(\S+?>)', candidate_line)
                if m:
                    fragment = m.group(1)  # Includes the ">"
                    new_line = lines[i].rstrip() + " " + fragment
                    if new_line != lines[i]:
                        lines[i] = new_line
                        modified = True
                        # Remove the matched fragment from candidate_line.
                        remainder = candidate_line[m.end():]
                        # If the remainder is completely empty (after stripping), delete that line.
                        if remainder.strip() == "":
                            del lines[j]
                        else:
                            lines[j] = remainder
        i += 1
    return "\n".join(lines), modified

def process_csv(csv_path, output_handle):
    """
    Processes a single CSV file:
      • Reads the CSV file.
      • For each row with at least 4 columns, applies fix_broken_tags() on the cell in column 4.
      • If a fix is applied, logs (row number, original and fixed cell) to output_handle.
      • Returns the updated rows and a flag indicating if any row was modified.
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
        print("Usage: Drag and drop CSV files onto this script or run it with file names as arguments.")
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
