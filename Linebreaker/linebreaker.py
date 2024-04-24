import csv
import os
import sys

def add_newlines(text, max_length=50):
    lines = []
    for line in text.split("\n"):
        if len(line) > max_length:
            words = line.split()
            new_line = ''
            for word in words:
                if len(new_line) + len(word) + 1 <= max_length:
                    new_line += ' ' + word
                else:
                    lines.append(new_line.strip())
                    new_line = word
            lines.append(new_line.strip())
        else:
            lines.append(line.strip())
    return '\n'.join(lines)

def process_csv(input_file):
    output_file = os.path.splitext(input_file)[0] + "_processed.csv"
    
    with open(input_file, 'r', newline='', encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader)  # Read the header
        header[3] = add_newlines(header[3])  # Process the header text for the fourth column
        
        with open(output_file, 'w', newline='', encoding="utf-8") as output_csv:
            writer = csv.writer(output_csv)
            writer.writerow(header)  # Write the processed header back
            
            for row in reader:
                row[3] = add_newlines(row[3])  # Target the fourth column
                writer.writerow(row)

# Check if a file is dragged onto the script
if len(sys.argv) > 1:
    input_file = sys.argv[1]
    process_csv(input_file)
else:
    print("Please drag and drop a CSV file onto the script.")
