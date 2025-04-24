import csv
import sys
import os

# Function to replace characters
def replace_characters(text):
    text = text.replace('“', '"').replace('”', '"')  # Replace curly quotes with straight quotes
    text = text.replace('‘', "'").replace('’', "'")  # Replace curly single quotes with straight single quotes
    text = text.replace('~', '～')  # Replace tilde with fullwidth tilde
    return text

# Function to clean CSV (and overwrite original file)
def clean_csv(file_path):
    # Read original CSV, process, then overwrite
    with open(file_path, 'r', encoding='utf-8', newline='') as infile:
        reader = csv.reader(infile)
        rows = [row for row in reader]

    with open(file_path, 'w', encoding='utf-8', newline='') as outfile:
        writer = csv.writer(outfile)
        for row in rows:
            cleaned_row = [replace_characters(field) for field in row]
            writer.writerow(cleaned_row)

    print(f"✅ Cleaned and replaced: {os.path.basename(file_path)}")

# === Entry Point ===
if __name__ == '__main__':
    if len(sys.argv) < 2:
        input("❗ Drag and drop one or more CSV files onto this script.\nPress Enter to exit...")
        sys.exit()

    for file in sys.argv[1:]:
        if file.lower().endswith('.csv') and os.path.isfile(file):
            clean_csv(file)
        else:
            print(f"❌ Skipping non-CSV file: {file}")

    input("\n✅ All done! Press Enter to exit.")
