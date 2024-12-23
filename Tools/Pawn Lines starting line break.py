import csv
import sys
import os

def insert_line_breaks_in_csv(file_path):
    # Create a new filename to save the modified CSV
    base, ext = os.path.splitext(file_path)
    new_file_path = f"{base}_with_linebreaks{ext}"

    with open(file_path, mode='r', newline='', encoding='utf-8') as infile, \
         open(new_file_path, mode='w', newline='', encoding='utf-8') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

        for row in reader:
            # Add a line break before each entry
            new_row = [f'\n{entry}' for entry in row]
            writer.writerow(new_row)

    print(f"Processed CSV saved as: {new_file_path}")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Drag and drop a CSV file onto this script.")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    insert_line_breaks_in_csv(csv_file)
