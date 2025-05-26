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
    content = file_path.read_text(encoding='utf-8')
    for old_symbol, new_symbol in FORBIDDEN_SYMBOLS.items():
        content = content.replace(old_symbol, new_symbol)
    file_path.write_text(content, encoding='utf-8')

def modify_specific_entry():
    """Find and replace dates in Fully Translated/104.csv with the current date."""
    file_path = Path("Fully Translated/254.csv")
    if not file_path.exists():
        print(f"File {file_path} not found. Skipping modification.")
        return

    current_date = datetime.now().strftime("%d/%m/%y")

    lines = file_path.read_text(encoding='utf-8').splitlines()
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
        for split in directory.glob("*.csv"):
            splits.append(split)

    if not splits:
        print("No splits to merge. Exiting.")
        return

    splits = sorted(splits, key=numerical_sort_key)

    output_file = Path(args.output_dir) / "gmd.csv"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#Index,Key,MsgJp,MsgEn,GmdPath,ArcPath,ArcName,ReadIndex\n")
        for split in splits:
            content = split.read_text(encoding='utf-8')
            f.write(content)

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

    modify_specific_entry()  # First, update the target entry in Fully Translated/104.csv
    clean_files(args)  # Then, clean the files by replacing forbidden symbols
    merge_splits(args)  # Finally, merge the files

if __name__ == "__main__":
    main()
