#!/usr/bin/env python3
"""
This script examines the fourth column (index 3) of one or more CSV files and 
looks for tag delimiters (< and >) that are immediately adjacent to letters.
It does so by extracting all substrings that look like full tags (i.e. text
enclosed within "<" and ">"). For each tag found, it checks whether the character
directly preceding the tag or directly following the tag is an alphabetical letter.

**Exclusion Rule:**
Any tag whose content (when converted to uppercase) contains the substring "COL"
will be excluded (treated as "invisible") from reporting, regardless of any delimiter issues.

Any problematic occurrences (with file name, row number, problematic tag, and context)
are written to a file named "problematic_tag_limiters.txt".

Usage:
    python check_tag_limiters_exclude.py file1.csv file2.csv ...
or drag and drop one or more CSV files onto this script.
"""

import csv
import sys
import os
import re

def process_csv(csv_path, output_handle, context_length=10):
    output_handle.write(f"Processing file: {csv_path}\n{'-' * 40}\n")
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as csvfile:
            reader = list(csv.reader(csvfile))
    except Exception as e:
        output_handle.write(f"Error reading {csv_path}: {e}\n\n")
        return

    # Regular expression to extract full tags: any substring starting with '<' and ending with '>'
    tag_regex = re.compile(r'(<[^<>]+>)')
    
    row_number = 0
    for row in reader:
        row_number += 1        
        if len(row) < 4:
            continue
        
        cell = row[3]
        problematic_matches = []
        for m in tag_regex.finditer(cell):
            tag_span = m.span()
            tag_str = m.group(0)
            
            # Determine the tag content in uppercase.
            # Here we remove the delimiters "<" and ">" and any surrounding whitespace.
            tag_content = tag_str[1:-1].strip().upper()  # Entire tag content in uppercase
            
            # Exclude any tag that contains "COL"
            if "COL" in tag_content:
                continue
            
            # Check the character immediately before the tag (if it exists)
            pre_char = cell[tag_span[0] - 1] if tag_span[0] > 0 else None
            # Check the character immediately after the tag (if it exists)
            post_char = cell[tag_span[1]] if tag_span[1] < len(cell) else None
            
            adjacent_problem = False
            if pre_char and pre_char.isalpha():
                adjacent_problem = True
            if post_char and post_char.isalpha():
                adjacent_problem = True
            
            if adjacent_problem:
                # Create a context snippet (context_length characters before and after the match position)
                start_ctx = max(tag_span[0] - context_length, 0)
                end_ctx = min(tag_span[1] + context_length, len(cell))
                snippet = cell[start_ctx:end_ctx]
                problematic_matches.append(f"Tag: {tag_str} | Context: {repr(snippet)}")
        
        # If any problematic match(es) found, log them.
        if problematic_matches:
            output_handle.write(f"File: {os.path.basename(csv_path)}, Row: {row_number}\n")
            for match in problematic_matches:
                output_handle.write(f"    {match}\n")
            output_handle.write("\n")
    output_handle.write("\n")

def main():
    if len(sys.argv) < 2:
        print("Usage: Drag and drop CSV files onto this script or run it from the command line with file names.")
        sys.exit(1)
    
    output_filename = "problematic_tag_limiters.txt"
    with open(output_filename, "w", encoding="utf-8") as output_handle:
        for file_path in sys.argv[1:]:
            if os.path.isfile(file_path):
                process_csv(file_path, output_handle)
            else:
                output_handle.write(f"File not found: {file_path}\n\n")
    
    print(f"Processing complete. Check {output_filename} for problematic tag limiters.")
    
if __name__ == '__main__':
    main()
