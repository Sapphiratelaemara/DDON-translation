import argparse
import re
import csv
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import os

# ------------------------------------------------------------
# Forbidden symbol replacements (from script 1)
# ------------------------------------------------------------
FORBIDDEN_SYMBOLS = {
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "~": "～"
}

DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")

# ------------------------------------------------------------
# Bracket normalization rules (from script 2)
# ------------------------------------------------------------
ENGLISH_COLUMN = 3

BRACKET_MAP = {
    '＜': '[', '＞': ']',
    '【': '[', '】': ']',
    '《': '[', '》': ']',
    '«': '[', '»': ']',
    '‹': '[', '›': ']',
}

TARGET_CHARS = set(BRACKET_MAP.keys())

COL_TAG_PATTERN = re.compile(r'</?COL[^>]*>')


def normalize_brackets(text):
    return "".join(BRACKET_MAP.get(ch, ch) for ch in text)


def fix_text(text):
    if text is None:
        return text

    # --- 0. Extract COL regions so they are protected ---
    col_regions = []

    def col_replacer(match):
        col_regions.append(match.group(0))
        return f"__COL_BLOCK_{len(col_regions)-1}__"

    text = re.sub(r'<COL[^>]*>.*?</COL>', col_replacer, text, flags=re.DOTALL)

    # --- 1. Normalize bracket-like symbols ---
    text = normalize_brackets(text)

    # --- 2. Remove spaces directly inside brackets ---
    text = re.sub(r'\[\s+', '[', text)
    text = re.sub(r'\s+\]', ']', text)

    # --- 3. Move punctuation outside brackets ---
    text = re.sub(r'\[([^\[\]]+?)([.,!?;:])\]', r'[\1]\2', text)

    # --- 4. Insert missing space BEFORE '[' unless preceded by COL placeholder ---
    text = re.sub(
        r'(?<!__COL_BLOCK_\d__)(?<=\w)\[',
        r' [',
        text
    )

    # --- 5. Insert missing space AFTER ']' unless followed by punctuation/space/COL ---
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        out.append(ch)

        if ch == ']':
            if i + 1 < len(text):
                nxt = text[i+1]
                if nxt not in (' ', '\n', '\r', '\t', '.', ',', '!', '?', ':', ';'):
                    if not text.startswith("__COL_BLOCK_", i+1):
                        out.append(' ')
        i += 1

    text = ''.join(out)

    # --- 6. Restore COL regions ---
    for idx, block in enumerate(col_regions):
        text = text.replace(f"__COL_BLOCK_{idx}__", block)

    return text


# ------------------------------------------------------------
# Script 1: CSV validation + merging
# ------------------------------------------------------------
def validate_first_column(file_path):
    with open(file_path, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.reader(csvfile)
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            first_column = row[0].strip().lstrip('\ufeff')
            if first_column == "#Index":
                continue
            if not first_column.isdigit():
                print(
                    f"\n❌ CSV Validation Failed!\n"
                    f"File: {file_path}\n"
                    f"Row: {row_number}\n"
                    f"Offending value in first column: '{first_column}'\n"
                )
                sys.exit(1)


def validate_folder(folder):
    EXCLUDED_NAMES = {
        "gmd staging",
        "Terms and references directory",
        "Tools"
    }

    print(f"\nValidating {folder} ...")
    for csv_file in folder.rglob("*.csv"):
        if any(part in EXCLUDED_NAMES for part in csv_file.parts):
            continue
        validate_first_column(csv_file)

    print(f"{folder} passed validation (ignored: {', '.join(EXCLUDED_NAMES)}).")


def get_changed_files():
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
    content = file_path.read_text(encoding='utf-8-sig')
    for old, new in FORBIDDEN_SYMBOLS.items():
        content = content.replace(old, new)
    content = content.replace('\ufeff', '')
    file_path.write_text(content, encoding='utf-8')


def modify_specific_entry():
    file_path = Path(__file__).parent / "Fully Translated" / "254.csv"
    if not file_path.exists():
        return

    current_date = datetime.now().strftime("%d/%m/%y")
    content = file_path.read_text(encoding='utf-8-sig')
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if DATE_PATTERN.search(line):
            lines[i] = DATE_PATTERN.sub(current_date, line)
    file_path.write_text("\n".join(lines), encoding='utf-8')


def merge_english():
    english = Path(__file__).parent
    fully_translated = english / "Fully Translated"
    splits_folder = english / "splits"
    output_file = english / "gmd.csv"

    english.mkdir(parents=True, exist_ok=True)

    csv_files = list(fully_translated.glob("*.csv")) + list(splits_folder.glob("*.csv"))

    def numeric_sort_key(p):
        try:
            return int(p.stem)
        except ValueError:
            return 0

    csv_files = sorted(csv_files, key=numeric_sort_key)

    if not csv_files:
        print("No CSVs found in Fully Translated or splits!")
        return

    for csv_file in csv_files:
        validate_first_column(csv_file)

    with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerow([
            "#Index", "Key", "MsgJp", "MsgEn",
            "GmdPath", "ArcPath", "ArcName", "ReadIndex"
        ])
        for csv_file in csv_files:
            with open(csv_file, newline='', encoding='utf-8-sig') as infile:
                reader = csv.reader(infile)
                for row in reader:
                    if not row:
                        continue
                    row[0] = row[0].lstrip('\ufeff').strip()
                    writer.writerow(row)

    print(f"English gmd.csv generated from {len(csv_files)} CSV files.")


# ------------------------------------------------------------
# Script 2: Apply bracket/punctuation fixes ONLY inside English folder
# ------------------------------------------------------------
def process_english_csv(path):
    changed = False
    rows = []

    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) > ENGLISH_COLUMN:
                cell = row[ENGLISH_COLUMN]

                if any(c in cell for c in TARGET_CHARS):
                    fixed = fix_text(cell)
                    if fixed != cell:
                        row[ENGLISH_COLUMN] = fixed
                        changed = True

            rows.append(row)

    if not changed:
        return

    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerows(rows)


def walk_and_process_english(root):
    for folder, _, files in os.walk(root):
        for file in files:
            if file.lower().endswith('.csv'):
                process_english_csv(os.path.join(folder, file))


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args()

    english_folder = Path(__file__).parent
    fully_translated = english_folder / "Fully Translated"
    splits_folder = english_folder / "splits"

    if not args.ci:
        # Local run: validate English only, generate gmd.csv
        for folder in [fully_translated, splits_folder]:
            if folder.exists():
                validate_folder(folder)

        # Apply bracket/punctuation fixes ONLY inside English folder
        walk_and_process_english(english_folder)

        modify_specific_entry()
        merge_english()

        print("\nLocal English validation + generation complete.")
        return

    # CI mode
    changed_files = get_changed_files()
    if not changed_files:
        print("No CSV changes detected.")
        return

    changed_folders = {Path(f).parts[0] for f in changed_files}

    if "English" in changed_folders:
        for folder in [fully_translated, splits_folder]:
            if folder.exists():
                validate_folder(folder)

        walk_and_process_english(english_folder)

    repo_root = english_folder.parent
    for folder_name in changed_folders:
        if folder_name != "English":
            folder_path = repo_root / folder_name
            if folder_path.exists():
                validate_folder(folder_path)

    print("\nCI validation complete.")


if __name__ == "__main__":
    main()
