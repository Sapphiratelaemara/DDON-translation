import csv
import re
import sys
import os

# Function to check if a string contains Japanese text
def contains_japanese(text):
    # This regex pattern matches Japanese characters (Hiragana, Katakana, Kanji)
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

# Ensure the script was called with at least one file path argument
if len(sys.argv) < 2:
    print("Usage: drag and drop CSV files onto this script.")
    sys.exit(1)

# Process each file provided as a command-line argument
for input_file in sys.argv[1:]:
    # Check if the input file exists
    if not os.path.isfile(input_file):
        print(f"Error: File '{input_file}' not found.")
        continue
    
    # Create a temporary file to write the processed content
    temp_file = input_file + '.tmp'

    # Read the CSV file and process the fourth column
    with open(input_file, 'r', newline='', encoding='utf-8') as infile, \
         open(temp_file, 'w', newline='', encoding='utf-8') as outfile:

        reader = csv.reader(infile)
        writer = csv.writer(outfile)
        
        # Iterate through each row
        for row in reader:
            # Check if the fourth column exists
            if len(row) >= 4:
                # If the fourth column contains Japanese text, clear the entire entry
                if contains_japanese(row[3]):
                    row[3] = ''
            
            # Write the updated row to the temporary file
            writer.writerow(row)

    # Replace the original file with the processed temporary file
    os.replace(temp_file, input_file)

    print(f"Processed file saved as {input_file}")

print("All files have been processed.")
