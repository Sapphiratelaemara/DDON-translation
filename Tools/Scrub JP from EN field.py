import csv
import re
import sys
import os

# Function to check if a string contains Japanese text or Japanese-style special characters
def contains_japanese(text):
    # This regex pattern matches Japanese characters (Hiragana, Katakana, Kanji)
    # and common Japanese symbols, including a broader range of punctuation.
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF【】「」『』（）：―！、。・？]', text))

# Function to check if a string contains only punctuation or special characters
def contains_only_punctuation(text):
    # This regex matches strings that contain only punctuation or special characters
    return bool(re.fullmatch(r'[^\w\s]+', text))

# Function to check if a string contains only numbers
def contains_only_numbers(text):
    # This checks if the string consists only of digits (0-9)
    return text.isdigit()

# Function to check if a string is empty, contains only spaces, or just a line break
def is_empty_or_line_break(text):
    # This checks if the string is empty, only spaces, or just line breaks
    return text.strip() == ''  # strip removes spaces and line breaks

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
                text = row[3].strip()  # Strip spaces and line breaks from both ends
                # If the fourth column contains Japanese text, only punctuation, only numbers, or is empty/line break, clear the entire entry
                if contains_japanese(text) or contains_only_punctuation(text) or contains_only_numbers(text) or is_empty_or_line_break(text):
                    row[3] = ''  # Clear the entire string in the fourth column
            
            # Write the updated row to the temporary file
            writer.writerow(row)

    # Replace the original file with the processed temporary file
    os.replace(temp_file, input_file)

    print(f"Processed file saved as {input_file}")

print("All files have been processed.")

# Keep the window open until the user presses Enter (for running from file explorer)
input("Press Enter to exit...")
