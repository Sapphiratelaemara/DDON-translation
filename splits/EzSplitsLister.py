import csv
import sys
import os

# Ensure the script was called with at least one file path argument
if len(sys.argv) < 2:
    print("Usage: drag and drop CSV files onto this script.")
    sys.exit(1)

# Function to count entries in the "MsgEn" column
def count_entries_in_msgen_column(file_path):
    count = 0
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.DictReader(infile)
            if 'MsgEn' not in reader.fieldnames:
                print(f"Warning: 'MsgEn' column not found in '{file_path}'. Available columns: {', '.join(reader.fieldnames)}")
                return None
            for row in reader:
                if row['MsgEn'].strip():  # Count non-empty entries
                    count += 1
    except Exception as e:
        print(f"Error processing file '{file_path}': {e}")
        return None
    return count

# Collect results for each file
results = []

for input_file in sys.argv[1:]:
    # Check if the input file exists
    if not os.path.isfile(input_file):
        print(f"Error: File '{input_file}' not found.")
        continue
    
    # Count entries in the "MsgEn" column
    entry_count = count_entries_in_msgen_column(input_file)
    if entry_count is not None:
        results.append((input_file, entry_count))

# Check if results are empty
if not results:
    print("No valid entries found. Check if 'MsgEn' column exists and contains data.")
else:
    # Sort results by the number of entries, high to low
    results.sort(key=lambda x: x[1], reverse=True)

    # Write the results to a .txt file
    output_file = 'results.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        for file, count in results:
            f.write(f"File: {file} | Number of entries in 'MsgEn' column: {count}\n")

    print(f"Results have been saved to '{output_file}'")

# Keep the window open until the user 
