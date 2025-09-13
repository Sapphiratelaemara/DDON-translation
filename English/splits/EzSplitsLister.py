import csv
import sys
import os

# Ensure the script was called with at least one file path argument
if len(sys.argv) < 2:
    input("❗ Drag and drop one or more CSV files onto this script.\nPress Enter to exit...")
    sys.exit(1)

# Function to count non-empty entries in the 4th column (index 3)
def count_entries_in_fourth_field(file_path):
    count = 0
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row in reader:
                if len(row) >= 4 and row[3].strip():
                    count += 1
    except Exception as e:
        print(f"❌ Error processing '{file_path}': {e}")
        return None
    return count

# Collect results for each file
results = []

for input_file in sys.argv[1:]:
    if not os.path.isfile(input_file):
        print(f"❌ File not found: {input_file}")
        continue

    entry_count = count_entries_in_fourth_field(input_file)
    if entry_count is not None:
        results.append((input_file, entry_count))

# Output results
if not results:
    print("⚠️ No valid entries found (check the 4th column exists).")
else:
    results.sort(key=lambda x: x[1], reverse=True)

    output_file = 'results.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        for file, count in results:
            f.write(f"File: {file} | Non-empty entries in 4th column: {count}\n")

    print(f"\n✅ Results saved to '{output_file}'")

input("\nPress Enter to exit...")
