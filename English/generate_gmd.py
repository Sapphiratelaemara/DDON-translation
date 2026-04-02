import argparse
import re
import csv
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Forbidden symbol replacements
FORBIDDEN_SYMBOLS = {
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "~": "～"
}

# Date pattern to update in 254.csv
DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")


def validate_first_column(file_path):
    """Validate that the first column is #Index or a number."""
    # Use utf-8-sig to strip BOM if present at start of file
    with open(file_path, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.reader(csvfile)
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            # Ensure BOM removed from the first column and trim whitespace
            first_column = row[0].strip().lstrip('\ufeff')
            if first_column == "#Index":
                continue
            if not first_column.isdigit():
                message = (
                    f"\n❌ CSV Validation Failed!\n"
                    f"File: {file_path}\n"
                    f"Row: {row_number}\n"
                    f"Offending value in first column: '{first_column}'\n"
                )
                print(message)
                sys.exit(1)


def validate_folder(folder):
    """Validate all CSVs in a folder recursively, excluding specific directories."""
    # Define the exact names of folders to skip
    EXCLUDED_NAMES = {
        "gmd staging",
        "Terms and references directory",
        "Tools"
    }

    print(f"\nValidating {folder} ...")
    for csv_file in folder.rglob("*.csv"):
        # Check if any parent directory of the file is in the exclusion list
        if any(part in EXCLUDED_NAMES for part in csv_file.parts):
            continue

        validate_first_column(csv_file)

    print(f"{folder} passed validation (ignored: {', '.join(EXCLUDED_NAMES)}).")


def get_changed_files():
    """Return list of changed CSV files in CI."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            capture_output=True, text=True, check=True
        )
        files = result.stdout.splitlines()
        return [f for f in files if f.endswith(".csv")]
    except Exception:
        return []


def replace_forbidden_symbols(file_path):
    """Replace forbidden symbols in the file and remove any BOM characters."""
    # Read with utf-8-sig to handle BOM at start, but also explicitly remove any BOM occurrences
    content = file_path.read_text(encoding='utf-8-sig')
    for old, new in FORBIDDEN_SYMBOLS.items():
        content = content.replace(old, new)
    # Remove any stray BOM characters that might remain
    content = content.replace('\ufeff', '')
    file_path.write_text(content, encoding='utf-8')


def modify_specific_entry():
    """Update 254.csv dates."""
    file_path = Path(__file__).parent / "Fully Translated" / "254.csv"
    if not file_path.exists():
        return

    current_date = datetime.now().strftime("%d/%m/%y")
    # Read with utf-8-sig to strip BOM if present
    content = file_path.read_text(encoding='utf-8-sig')
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if DATE_PATTERN.search(line):
            lines[i] = DATE_PATTERN.sub(current_date, line)
    # Ensure no BOM is written back
    file_path.write_text("\n".join(lines), encoding='utf-8')


def merge_english():
    """Merge Fully Translated + splits into gmd.csv for English."""
    english = Path(__file__).parent
    fully_translated = english / "Fully Translated"
    splits_folder = english / "splits"
    output_file = english / "gmd.csv"

    english.mkdir(parents=True, exist_ok=True)

    csv_files = list(fully_translated.glob("*.csv")) + list(splits_folder.glob("*.csv"))

    # Sort numerically by filename
    def numeric_sort_key(p):
        try:
            return int(p.stem)
        except ValueError:
            return 0

    csv_files = sorted(csv_files, key=numeric_sort_key)

    if not csv_files:
        print("No CSVs found in Fully Translated or splits!")
        return

    # Validate all CSVs first
    for csv_file in csv_files:
        validate_first_column(csv_file)

    # Merge CSVs
    with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerow([
            "#Index", "Key", "MsgJp", "MsgEn",
            "GmdPath", "ArcPath", "ArcName", "ReadIndex"
        ])
        for csv_file in csv_files:
            # Read with utf-8-sig so BOM at start of file is removed
            with open(csv_file, newline='', encoding='utf-8-sig') as infile:
                reader = csv.reader(infile)
                for row in reader:
                    if not row:
                        continue
                    # Explicitly remove BOM from the first column and trim whitespace
                    row[0] = row[0].lstrip('\ufeff').strip()
                    writer.writerow(row)

    print(f"English gmd.csv generated from {len(csv_files)} CSV files.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI validation mode (no gmd.csv generation)"
    )
    args = parser.parse_args()

    english_folder = Path(__file__).parent
    fully_translated = english_folder / "Fully Translated"
    splits_folder = english_folder / "splits"

    if not args.ci:
        # Local run: validate English only, generate gmd.csv
        for folder in [fully_translated, splits_folder]:
            if folder.exists():
                validate_folder(folder)
        modify_specific_entry()
        merge_english()
        print("\nLocal English validation + generation complete.")
        return

    # CI mode: validate only changed CSVs
    changed_files = get_changed_files()
    if not changed_files:
        print("No CSV changes detected.")
        return

    changed_folders = set()
    for file in changed_files:
        top_folder = Path(file).parts[0]
        changed_folders.add(top_folder)

    # English: only Fully Translated + splits
    if "English" in changed_folders:
        for folder in [fully_translated, splits_folder]:
            if folder.exists():
                validate_folder(folder)

    # Other languages: validate full folder if any file changed
    repo_root = english_folder.parent
    for folder_name in changed_folders:
        if folder_name != "English":
            folder_path = repo_root / folder_name
            if folder_path.exists():
                validate_folder(folder_path)

    print("\nCI validation complete.")


if __name__ == "__main__":
    main()