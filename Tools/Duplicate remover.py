#!/usr/bin/env python
"""
This script is intended for drag‐and‐drop use. When you drag an archive folder of CSV files
onto it, it will perform a global duplicate check. For every row in every CSV file,
it uses all columns except the fourth (index 3) to decide if two rows are duplicates.
In duplicate groups it does the following:
  – For the fourth column: if one row has content and another is empty, the nonempty wins.
    If there is a mismatch between nonempty values, the conflict is logged to "mismatches.txt."
  – Then (if needed) it uses tie‐breaking by context: it looks at the previous and next rows’
    seventh column (index 6) in that file. The row whose seventh‐column “neighbors” match its
    own value is deemed to be correct (if there is a tie, the earliest row is kept).
The script then rewrites each CSV (with the same filename) with the duplicates removed.
"""

import os
import sys
import csv
import json

# =============================================================================
# Utility functions
# =============================================================================

def get_csv_files(folder):
    """Recursively scan folder for files ending in .csv"""
    csv_files = []
    for root, dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith('.csv'):
                csv_files.append(os.path.join(root, f))
    return csv_files

def load_csv_file(file_path):
    """Load a CSV file and return its rows as a list of lists"""
    rows = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)
    return rows

def write_csv_file(file_path, rows):
    """Overwrite the CSV file with given rows."""
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

# =============================================================================
# Duplicate resolution globals and helper (for a global analysis)
# =============================================================================

# We use the following indices (0-based):
# - Fourth column: index 3
# - Seventh column: index 6

def duplicate_key(row):
    """
    Create a key used for duplicate detection; it is a tuple of every column except the fourth.
    (Strip spaces so that extraneous whitespace is ignored.)
    """
    # Only use columns that exist; assume row indices: 0,1,2,3,4,...
    # Skip index 3.
    return tuple(row[i].strip() for i in range(len(row)) if i != 3)

def compute_context_score(file_rows, index, candidate_val):
    """
    Look at the previous and following row in file_rows.
    Return a score: +1 if the previous row's seventh column equals candidate_val,
    and +1 if the next row's seventh column equals candidate_val.
    If no previous/next row exists, ignore.
    """
    score = 0
    if index - 1 >= 0:
        prev = file_rows[index - 1]
        if len(prev) > 6 and prev[6].strip() == candidate_val:
            score += 1
    if index + 1 < len(file_rows):
        nxt = file_rows[index + 1]
        if len(nxt) > 6 and nxt[6].strip() == candidate_val:
            score += 1
    return score

# =============================================================================
# Main duplicate analysis and resolution
# =============================================================================

def analyze_duplicates(file_data, mismatch_log):
    """
    file_data is a dictionary mapping file path -> list of rows (each row is a list).
    This function builds a global dictionary of candidates:
       key -> list of candidate entries.
    A candidate entry is a dictionary:
         {"file": file_path,
          "row_index": i,
          "row": row,
          "col4": row[3].strip() if len(row) > 3 else "",
          "col7": row[6].strip() if len(row) > 6 else ""}
    Returns a dictionary mapping key -> candidate list.
    """
    dup_dict = {}
    for file, rows in file_data.items():
        for i, row in enumerate(rows):
            # Only process rows that have at least 7 columns (so that index 6 is available)
            if len(row) < 7:
                continue
            key = duplicate_key(row)
            candidate = {"file":file, "row_index":i, "row":row,
                         "col4": row[3].strip() if len(row) > 3 else "",
                         "col7": row[6].strip() if len(row) > 6 else ""}
            dup_dict.setdefault(key, []).append(candidate)
    return dup_dict

def resolve_group(group, file_data, mismatch_log):
    """
    Given a list of candidate entries (a duplicate group with the same key),
    decide which one to keep.
    The resolution is in two stages:
      1. Check the fourth column ("col4").
         – If one candidate has a nonempty col4 while others are empty, that one wins.
         – If multiple candidates have nonempty values and they are not all equal,
           record a mismatch and then continue to tie-break.
      2. Tie-break by "context":
         For each candidate, look at its file's previous and next row in the seventh column
         (index 6). The candidate with the highest score (1 point per neighbor match) wins.
         If there’s a tie, choose the one with the smallest row_index.
    Returns the candidate to keep, and a list of candidates (their file and row_index) to be deleted.
    """
    # Stage 1: Fourth-column resolution.
    non_empty = [c for c in group if c["col4"] != ""]
    # If any candidate has content, use those.
    if non_empty:
        # If more than one nonempty candidate, check if they are all identical.
        unique_vals = set(c["col4"] for c in non_empty)
        if len(unique_vals) > 1:
            # Log a mismatch and list the candidates.
            mismatch_entry = "Mismatch in fourth column for duplicate group:\n"
            for c in non_empty:
                mismatch_entry += f"  File: {c['file']}, Row: {c['row_index']+1}, col4: '{c['col4']}'\n"
            mismatch_log.append(mismatch_entry)
        group_to_tiebreak = non_empty
    else:
        group_to_tiebreak = group

    # Stage 2: Tie-break by checking adjacent context in column7.
    best_candidate = None
    best_score = -1
    for c in group_to_tiebreak:
        f = c["file"]
        i = c["row_index"]
        # Get the file's rows:
        rows = file_data[f]
        score = compute_context_score(rows, i, c["col7"])
        # Use row index as tie-breaker if scores equal.
        if score > best_score or (score == best_score and (best_candidate is None or i < best_candidate["row_index"])):
            best_score = score
            best_candidate = c
    # Mark all other candidates (from the whole group) for deletion.
    to_delete = []
    for c in group:
        if c != best_candidate:
            to_delete.append( (c["file"], c["row_index"]) )
    return best_candidate, to_delete

def process_all_duplicates(file_data):
    """
    Given a dictionary file_data (file -> list of rows),
    analyze duplicates across files.
    Returns a set of (file, row_index) tuples to delete and a list of mismatch log entries.
    """
    dup_dict = analyze_duplicates(file_data, [])
    deletion_set = set()
    mismatch_log = []
    for key, candidates in dup_dict.items():
        if len(candidates) > 1:
            # Resolve this duplicate group
            keep, to_delete = resolve_group(candidates, file_data, mismatch_log)
            for item in to_delete:
                deletion_set.add(item)
    return deletion_set, mismatch_log

# =============================================================================
# Main script – read all CSVs from an archive folder, process, and write back.
# =============================================================================

def main(archive_folder):
    # Get a list of all CSV files (recursively)
    csv_files = get_csv_files(archive_folder)
    if not csv_files:
        print(f"No CSV files found in {archive_folder}")
        return
    
    # Load each CSV file into a dictionary: file path -> list of rows.
    file_data = {}
    for f in csv_files:
        try:
            file_data[f] = load_csv_file(f)
        except Exception as e:
            print(f"Error loading {f}: {e}")
    
    # Perform global duplicate analysis
    deletion_set, mismatch_log = process_all_duplicates(file_data)
    
    # For each file, delete rows (if any) that are marked for deletion.
    for f, rows in file_data.items():
        # Build list of indices to delete from this file (if any)
        indices_to_delete = sorted([idx for (file_path, idx) in deletion_set if file_path == f], reverse=True)
        if indices_to_delete:
            for idx in indices_to_delete:
                # Remove the row from the list.
                if idx < len(rows):
                    del rows[idx]
            # Write back the file (overwrite)
            try:
                write_csv_file(f, rows)
                print(f"Replaced original file: {f} (removed {len(indices_to_delete)} duplicate row(s))")
            except Exception as e:
                print(f"Error writing {f}: {e}")
        else:
            print(f"No duplicates to remove in {f}")
    
    # Write any mismatches to a text file in the archive folder.
    if mismatch_log:
        mismatch_file = os.path.join(archive_folder, "mismatches.txt")
        try:
            with open(mismatch_file, "w", encoding="utf-8") as f:
                f.write("\n".join(mismatch_log))
            print(f"Wrote mismatch log to {mismatch_file}")
        except Exception as e:
            print(f"Error writing mismatch log: {e}")
    else:
        print("No fourth‐column mismatches found.")
    
    print("Processing complete.")

# =============================================================================
# Entry point – support drag-and-drop of the CSV archive folder
# =============================================================================

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: Drag an archive folder of CSV files onto this script.")
        sys.exit(1)
    archive_folder = sys.argv[1]
    if not os.path.isdir(archive_folder):
        print("The provided path is not a folder.")
        sys.exit(1)
    main(archive_folder)
