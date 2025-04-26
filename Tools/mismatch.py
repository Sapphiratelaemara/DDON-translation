import csv
import sys
import re
import os

IGNORE_COLUMNS = ['MsgEn']
CLEANUP_REGEX = r'[\"\'―,，\n\r\s]'  # Ignore special symbols & whitespace

def normalize(text):
    """Normalize text for comparison: remove symbols, line breaks, spaces."""
    return re.sub(CLEANUP_REGEX, '', text)

def read_csv(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = [row for row in reader]
        return headers, rows
    except Exception as e:
        print(f"❌ Failed to read {filepath}: {e}")
        sys.exit(1)

def row_signature(row, headers):
    sig = []
    for h in headers:
        if h in IGNORE_COLUMNS:
            continue
        value = normalize(row.get(h, ''))
        sig.append(value)
    return tuple(sig)

def compare_rows(rows1, rows2, headers):
    set1 = set(row_signature(row, headers) for row in rows1)
    set2 = set(row_signature(row, headers) for row in rows2)

    missing_in_2 = [row for row in rows1 if row_signature(row, headers) not in set2]
    missing_in_1 = [row for row in rows2 if row_signature(row, headers) not in set1]

    return missing_in_2, missing_in_1

def write_missing(filepath, missing_in_2, missing_in_1, headers):
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        if missing_in_2:
            f.write('# Missing in second file:\n')
            for row in missing_in_2:
                writer.writerow(row)
        
        if missing_in_1:
            f.write('\n# Missing in first file:\n')
            for row in missing_in_1:
                writer.writerow(row)

def main():
    if len(sys.argv) < 3:
        print("📂 Drag two CSV files onto this script.")
        input("Press Enter to exit...")
        return

    file1, file2 = sys.argv[1], sys.argv[2]
    headers1, rows1 = read_csv(file1)
    headers2, rows2 = read_csv(file2)

    common_headers = [h for h in headers1 if h in headers2 and h not in IGNORE_COLUMNS]

    missing_in_2, missing_in_1 = compare_rows(rows1, rows2, common_headers)

    output_file = os.path.join(os.path.dirname(file1), 'missing_entries.csv')
    write_missing(output_file, missing_in_2, missing_in_1, headers1)

    print(f"\n✅ Done! Output saved to: {output_file}")
    input("Press Enter to close...")

if __name__ == "__main__":
    main()