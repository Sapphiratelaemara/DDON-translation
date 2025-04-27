import csv
import sys
import os
import re

# Load the list of valid tags from tags_extracted.txt
def load_valid_tags(filepath):
    valid_tags = set()
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            valid_tags.add(line.strip())
    return valid_tags

# Check and fix broken tags in the CSV
def fix_broken_tags(file_path, valid_tags):
    fixed_rows = []
    suspicious_tags = []  # List to log suspicious tags
    
    # Regex to detect valid tags like <TAG> or <TAG 1234>
    tag_regex = re.compile(r'<([A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)*?)>')

    with open(file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        
        for row in reader:
            if len(row) < 4:
                fixed_rows.append(row)
                continue  # skip rows without a fourth field
                
            # Check the fourth column for broken tags
            cell = row[3]

            # If there’s a line break in the tag, move the break before the start of the tag,
            # unless it is already directly before the tag (no merging needed)
            if '\n' in cell:
                # Correct the line break position, move it before the tag itself
                # Only modify the tag if there is no line break directly preceding the tag
                if not cell.startswith('\n'):
                    cell = re.sub(r'(\n)(<[^>]+>)', r'\2', cell)  # Fix the tag format

            # Find all potential tags in the cell
            found_valid_tag = False
            found_tags = tag_regex.findall(cell)
            
            # Only process the tag if it's actually a valid tag from the list
            for found_tag in found_tags:
                # Add angle brackets back around the tag
                full_tag = f"<{found_tag}>"
                if full_tag in valid_tags:
                    found_valid_tag = True
                    break

            if not found_valid_tag:
                # If no valid tag is found, log it as suspicious
                suspicious_tags.append((cell, file_path))
                
            # Replace broken tag with fixed one in the row
            row[3] = cell
            fixed_rows.append(row)
    
    return fixed_rows, suspicious_tags

# Write the results to a new CSV
def write_fixed_csv(file_path, fixed_rows):
    with open(file_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(fixed_rows)

# Write suspicious tags to a log file
def log_suspicious_tags(suspicious_tags):
    with open('suspicious_tags_log.txt', 'w', encoding='utf-8') as log_file:
        for tag, file_path in suspicious_tags:
            log_file.write(f"Suspicious Tag: {tag} in {file_path}\n")

# Main logic
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("❗ No files were dragged and dropped. Please drag and drop CSV files onto this script.")
        input("Press Enter to exit...")  # Wait for user to press Enter
        sys.exit()
    
    valid_tags = load_valid_tags('tags_extracted.txt')

    # Process each CSV file dragged and dropped
    for csv_file in sys.argv[1:]:
        if os.path.isfile(csv_file) and csv_file.lower().endswith('.csv'):
            print(f"Processing file: {csv_file}")
            fixed_rows, suspicious_tags = fix_broken_tags(csv_file, valid_tags)
            write_fixed_csv(csv_file, fixed_rows)
            log_suspicious_tags(suspicious_tags)
            print(f"Finished processing: {csv_file}")
        else:
            print(f"❌ Skipping non-CSV file: {csv_file}")
    
    print("\n✅ All files processed.")
    
    # Keep the window open by waiting for a keypress
    input("Press Enter to exit...")  # Keeps the window open until Enter is pressed
