import csv
import sys
import os

def process_csv(file_path):
    # Output file with "_modified" added to the original file name
    base, ext = os.path.splitext(file_path)
    output_file = base + "_modified" + ext

    # Read and process the CSV file
    with open(file_path, 'r', newline='', encoding='utf-8') as infile:
        reader = csv.reader(infile)
        rows = [ [' ' + entry + ' ' for entry in row] for row in reader ]

    # Write the processed data to a new file
    with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.writer(outfile)
        writer.writerows(rows)

    print(f"Processed file saved as: {output_file}")

if __name__ == "__main__":
    # Check if a file was dragged onto the script
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        process_csv(file_path)
    else:
        print("Please drag and drop a CSV file onto the script.")
