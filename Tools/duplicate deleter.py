import csv
import sys
import re
import os

IGNORE_COLUMNS = ['MsgEn']
CLEANUP_REGEX = r'[\"\'―,，\n\r\s]'  # Normalize these characters

def normalize(text):
    return re.sub(CLEANUP_REGEX, '', text)

def row_signature(row, headers):
    return tuple(normalize(row.get(h, '')) for h in headers if h not in IGNORE_COLUMNS)

def read_csv(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
        return headers, rows
    except Exception as e:
        print(f"❌ Failed to read {filepath}: {e}")
        sys.exit(1)

def remove_duplicates(rows, headers):
    seen = set()
    unique_rows = []
    for row in rows:
        sig = row_signature(row, headers)
        if sig not in seen:
            seen.add(sig)
            unique_rows.append(row)
    return unique_rows

def write_cleaned_file(filepath, rows, headers):
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

def main():
    if len(sys.argv) < 2:
        print("📂 Drag a CSV file onto this script.")
        input("Press Enter to exit...")
        return

    file_path = sys.argv[1]
    headers, rows = read_csv(file_path)
    cleaned_rows = remove_duplicates(rows, headers)

    output_file = os.path.join(os.path.dirname(file_path), 'deduplicated.csv')
    write_cleaned_file(output_file, cleaned_rows, headers)

    print(f"\n✅ Done! Duplicates removed.")
    print(f"📝 Saved as: {output_file}")
    input("Press Enter to close...")

if __name__ == "__main__":
    main()
