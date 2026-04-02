# extract_right_hand_side.py

import re

# Input file with your mapping
input_file = "Untitled-1.txt"
# Output file for right-hand side terms
output_file = "right_hand_side_terms.txt"

right_terms = []

with open(input_file, "r", encoding="utf-8") as f:
    for line in f:
        # Match the right-hand side: "value" part after colon
        match = re.search(r':\s*"([^"]+)"', line)
        if match:
            right_terms.append(match.group(1))

# Write to output file, one entry per line
with open(output_file, "w", encoding="utf-8") as f:
    for term in right_terms:
        f.write(term + "\n")

print(f"Extracted {len(right_terms)} right-hand side terms to {output_file}")