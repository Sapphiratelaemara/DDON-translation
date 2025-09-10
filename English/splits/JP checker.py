import csv
import sys
import os
import shutil
import re

# Regex to detect Japanese characters (Hiragana, Katakana, Kanji)
jp_regex = re.compile(r'[\u3040-\u30ff\u4e00-\u9faf]')

# Ensure subfolder V exists
def ensure_v_folder():
    if not os.path.exists("V"):
        os.makedirs("V")

# Check if a cell is empty or contains Japanese
def is_japanese_or_empty(cell):
    return not cell.strip() or jp_regex.search(cell)

# Process a single CSV file
def check_csv(file_path):
    found = False
    with open(file_path, 'r', encoding='utf-8', newline='') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) >= 4 and is_japanese_or_empty(row[3]):
                found = True
                break

    if found:
        ensure_v_folder()
        destination = os.path.join("V", os.path.basename(file_path))
        shutil.move(file_path, destination)
        print(f"📁 Moved: {os.path.basename(file_path)} → V/")
    else:
        print(f"✅ OK: {os.path.basename(file_path)}")

# === Entry Point ===
if __name__ == '__main__':
    if len(sys.argv) < 2:
        input("❗ Drag and drop one or more CSV files onto this script.\nPress Enter to exit...")
        sys.exit()

    for file in sys.argv[1:]:
        if file.lower().endswith('.csv') and os.path.isfile(file):
            check_csv(file)
        else:
            print(f"❌ Skipping non-CSV file: {file}")

    input("\n✅ Done! Press Enter to exit.")
