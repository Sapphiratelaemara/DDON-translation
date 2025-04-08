import csv
import os
import sys

def remove_newlines(text):
    # Remove any existing line breaks and return the text as a single line
    return ' '.join(text.splitlines())

def process_csv(input_file):
    output_file = os.path.splitext(input_file)[0] + "_processed.csv"
    
    with open(input_file, 'r', newline='', encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader)  # Read the header
        header[3] = remove_newlines(header[3])  # Process the header text for the fourth column
        
        with open(output_file, 'w', newline='', encoding="utf-8") as output_csv:
            writer = csv.writer(output_csv)
            writer.writerow(header)  # Write the processed header back
            
            for row in reader:
                row[3] = remove_newlines(row[3])  # Target the fourth column
                writer.writerow(row)

# Check if a file is dragged onto the script
if len(sys.argv) > 1:
    input_file = sys.argv[1]
    process_csv(input_file)
else:
    print("Please drag and drop a CSV file onto the script.")
