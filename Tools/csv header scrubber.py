import sys
import csv
import os

def remove_header(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as infile:
            rows = list(csv.reader(infile))

        if len(rows) <= 1:
            print(f"⚠️ File skipped (too few rows): {filepath}")
            return

        with open(filepath, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.writer(outfile)
            writer.writerows(rows[1:])  # Write all rows except the first

        print(f"✅ Removed header from: {filepath}")

    except Exception as e:
        print(f"❌ Error processing {filepath}: {e}")

def main():
    if len(sys.argv) < 2:
        print("📂 Drag and drop one or more CSV files onto this script.")
        input("Press Enter to exit...")
        return

    for filepath in sys.argv[1:]:
        if filepath.lower().endswith('.csv'):
            remove_header(filepath)
        else:
            print(f"⚠️ Skipped non-CSV file: {filepath}")

    input("\nAll done! Press Enter to close...")

if __name__ == "__main__":
    main()
