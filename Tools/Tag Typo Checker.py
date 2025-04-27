#!/usr/bin/env python3
"""
This script examines the fourth column (index 3) of one or more CSV files and extracts
all substrings that appear as tags (i.e. enclosed in "<" and ">"). It then normalizes
these tags (collapsing any extra whitespace) and checks them against a list of valid tags
loaded from a text file called "tags_extracted.txt" (one valid tag per line).

Any tag that does not exactly match one of the valid tags (after normalization) is written
to an output file "invalid_tags.txt" along with the CSV file name and the row number where
it was found.

Usage:
    python find_invalid_tags.py file1.csv file2.csv ...
or drag-and-drop one or more CSV files onto this script.
"""

import csv
import sys
import os
import re

def load_valid_tags():
    """
    Loads valid tags from tags_extracted.txt, one tag per line.
    Each tag is normalized by stripping and collapsing any extra whitespace.
    Returns a set of valid tags.
    """
    valid_tags = set()
    try:
        with open("tags_extracted.txt", "r", encoding="utf-8") as f:
            for line in f:
                tag = line.strip()
                if tag:
                    # Normalize by collapsing all whitespace
                    normalized = " ".join(tag.split())
                    valid_tags.add(normalized)
    except Exception as e:
        print(f"Error reading tags_extracted.txt: {e}")
        sys.exit(1)
    return valid_tags

def process_csv(csv_path, valid_tags, output_handle):
    """
    Opens and processes a CSV file.
    It reads every row, and for each row, extracts any substrings (using regex) that look like tags 
    (i.e. text within "<" and ">") from the fourth column (if present).
    Each extracted tag is normalized (collapse whitespace) and then compared against valid_tags.
    If the tag is not found in valid_tags, a log entry is written to output_handle.
    """
    output_handle.write(f"Processing file: {csv_path}\n{'-' * 40}\n")
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as csvfile:
            reader = list(csv.reader(csvfile))
    except Exception as e:
        output_handle.write(f"Error reading {csv_path}: {e}\n\n")
        return

    # Regular expression for extracting tags: anything between < and >
    tag_regex = re.compile(r'(<[^<>]+>)')
    
    row_number = 0
    for row in reader:
        row_number += 1
        
        if len(row) < 4:
            continue
        
        cell = row[3]
        # Find all tags in the cell
        found_tags = tag_regex.findall(cell)
        for tag in found_tags:
            # Normalize the extracted tag.
            normalized_tag = " ".join(tag.split())
            if normalized_tag not in valid_tags:
                output_handle.write(f"File: {os.path.basename(csv_path)}, Row: {row_number} -> Invalid tag: {normalized_tag}\n")
    output_handle.write("\n")

def main():
    if len(sys.argv) < 2:
        print("Usage: Drag and drop CSV files onto this script or run it with file names as arguments.")
        sys.exit(1)
    
    valid_tags = load_valid_tags()
    
    output_filename = "invalid_tags.txt"
    with open(output_filename, "w", encoding="utf-8") as output_handle:
        for file_path in sys.argv[1:]:
            if os.path.isfile(file_path):
                process_csv(file_path, valid_tags, output_handle)
            else:
                output_handle.write(f"File not found: {file_path}\n")
    
    print(f"Processing complete. Check the file {output_filename} for invalid tags.")

if __name__ == '__main__':
    main()
