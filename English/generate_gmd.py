import argparse
import re
from pathlib import Path
from datetime import datetime

# Define forbidden symbol replacements
FORBIDDEN_SYMBOLS = {
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "~": "～"
}

# Define the pattern for a date in format dd/mm/yy (two-digit year)
DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")

def replace_forbidden_symbols(file_path):
    """Replace forbidden symbols in the file's content."""
    content = safe_read_text(file_path)
    if content:
        for old_symbol, new_symbol in FORBIDDEN_SYMBOLS.items():
            content = content.replace(old_symbol, new_symbol)
        file_path.write_text(content, encoding='utf-8')

def safe_read_text(file_path):
    """Try reading the file multiple times in case of transient errors."""
    for attempt in range(3):  # Retry up to 3 times
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore').strip()
            if content:
                return content
        except Exception as e:
            print(f"Attempt {attempt+1}: Error reading {file_path}: {e}")
    print(f"Failed to read {file_path} after 3 attempts, skipping.")
    return None  # Indicate failure

def modify_specific_entry():
    """Find and replace dates in Fully Translated/254.csv with the current date."""
    file_path = Path("Fully Translated/254.csv")
    if not file_path.exists():
        print(f"File {file_path} not found. Skipping modification.")
        return

    current_date = datetime.now().strftime("%d/%m/%y")

    lines = safe_read_text(file_path).splitlines() if safe_read_text(file_path) else []
    modified = False

    # Replace existing dates wherever they occur
    for i, line in enumerate(lines):
        if DATE_PATTERN.search(line):
            lines[i] = DATE_PATTERN.sub(current_date, line)
            modified = True

    if modified:
        file_path.write_text("\n".join(lines), encoding='utf-8')
        print(f"Updated dates in {file_path} to {current_date}")
    else:
        print(f"No matching dates found in {file_path}. No changes made.")

def numerical_sort_key(path):
    name = path.name
    parts = re.split(r'(\d+)', name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]

def clean_files(args):
    """Go through all splits and replace forbidden symbols."""
    for path in args.split_locations:
        directory = Path(path)
        for file in directory.glob("*.csv"):
            replace_forbidden_symbols(file)

def merge_splits(args):
    """Merge split CSV files into gmd.csv after cleaning."""
    splits = []
    for path in args.split_locations:
        directory = Path(path)
        splits.extend(directory.glob("*.csv"))

    if not splits:
        print("No splits to merge. Exiting.")
        return

    # Step 4: Sort files deterministically before merging
    splits = sorted(splits, key=lambda x: x.name.lower())

    # Debugging: Ensure all expected files are detected before merging
    print(f"Total CSV files detected for merging: {len(splits)}")
    for split in splits:
        print(f"Detected file: {split}")

    output_file = Path(args.output_dir) / "gmd.csv"
    written_entries = 0  # Step 2: Track number of entries written

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#Index,Key,MsgJp,MsgEn,GmdPath,ArcPath,ArcName,ReadIndex\n")

        for split in splits:
            content = safe_read_text(split)
            if content is None:
                continue  # Skip files that failed to be read
            
            # Normalize line breaks before merging
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            
            # Count rows before writing
            row_count_read = len(content.split("\n"))

            # Write content
            f.write(content + "\n")  # Ensure proper line separation
            
            # Count rows after writing to verify correctness
            with open(output_file, 'r', encoding='utf-8') as check_file:
                written_content = check_file.read().splitlines()
                row_count_written = len(written_content)

            # Compare read vs written row counts for verification
            if row_count_written < written_entries + row_count_read:
                print(f"Warning: Possible missing rows! Expected {written_entries + row_count_read}, got {row_count_written}. Retrying {split}...")
                continue  # Retry writing if mismatch detected

            written_entries += row_count_read
            print(f"Confirmed {split}: {row_count_read} rows written correctly")

    print(f"Total entries written to {output_file}: {written_entries}")
    print(f"Final merged file size: {output_file.stat().st_size} bytes")
    print(f"Generated {output_file}")

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--output_dir', default='.', help="Controls where gmd.csv will be written to")
    parser.add_argument('split_locations', nargs='+', type=str, help="List of directories to find splits")

    args = parser.parse_args()

    output_path = Path(args.output_dir)
    if not output_path.exists() or not output_path.is_dir():
        print(f"Invalid output path: {output_path}. Exiting.")
        return None
    
    for split_dir in args.split_locations:
        split_path = Path(split_dir)
        if not split_path.exists() or not split_path.is_dir():
            print(f"Invalid split path: {split_path}. Exiting.")
            return None

    return args

def main():
    args = parse_args()
    if args is None:
        return

    modify_specific_entry()  # First, update the target entry in Fully Translated/254.csv
    clean_files(args)  # Then, clean the files by replacing forbidden symbols
    merge_splits(args)  # Finally, merge the files

if __name__ == "__main__":
    main()
