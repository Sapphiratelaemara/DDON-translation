import argparse
import re
import csv
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import os

# ------------------------------------------------------------
# Forbidden symbol replacements
# ------------------------------------------------------------
FORBIDDEN_SYMBOLS = {
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "~": "～", "＋": "+",
}

DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")

# ------------------------------------------------------------
# Bracket normalization rules
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

# Keywords that disable spacing normalization
SKIP_SPACING_KEYWORDS = [
    "uGUIEntryBoard",
    "named_param",
    "uGUIPopFilter",
    "ana_om_warp",
    "EDIT_MSG_DIALOG_SAVE_",
    "EDIT_MSG_TYPE_",
    "QUEST_MSG_UI_REWARD_TRADE_",
    "OS_index_loginskip"
]

# ------------------------------------------------------------
# Minimum required entry count for the generated English gmd.csv
# ------------------------------------------------------------
MIN_ENTRY_COUNT = 131121


def normalize_brackets(text):
    return "".join(BRACKET_MAP.get(ch, ch) for ch in text)


def fix_text(text, skip_override=False):
    if text is None:
        return text

    skip_spacing = skip_override or any(key in text for key in SKIP_SPACING_KEYWORDS)

    # --- 0. Extract COL tags ---
    col_tags = []

    def col_tag_replacer(match):
        col_tags.append(match.group(0))
        return f"__COLTAG_{len(col_tags)-1}__"

    text = re.sub(r'</?COL[^>]*>', col_tag_replacer, text)

    # --- 1. Normalize bracket-like symbols ---
    text = normalize_brackets(text)

    # --- 1.5 Normalize full-width colon ---
    text = text.replace('：<', ': <')
    text = re.sub(r'：(?!<)', ':', text)

    # ------------------------------------------------------------
    # FINAL PYTHON‑LEGAL COLON RULE
    # Add space after colon if followed by a digit,
    # UNLESS colon is part of HH:MM (digit before + two digits after)
    # ------------------------------------------------------------
    text = re.sub(
        r':(?=\d)(?!\d{2})',
        ': ',
        text
    )

    # --- 2. Remove spaces inside brackets ---
    text = re.sub(r'\[\s+', '[', text)
    text = re.sub(r'\s+\]', ']', text)

    # --- 3. Move punctuation outside brackets except ellipsis ---
    text = re.sub(
        r'\[([^\[\]]+?)(?<!\.\.)([.!?;:])(?!\.)\]',
        r'[\1]\2',
        text
    )

    # --- 4 & 5. Spacing rules (skip if flagged) ---
    if not skip_spacing:
        text = re.sub(
            r'(?<!__COLTAG_\d__)(?<=\w)\[',
            r' [',
            text
        )

        out = []
        i = 0
        while i < len(text):
            ch = text[i]
            out.append(ch)

            if ch == ']':
                if i + 1 < len(text):
                    nxt = text[i+1]
                    if nxt not in (' ', '\n', '\r', '\t', '.', ',', '!', '?', ':', ';'):
                        if not text.startswith("__COLTAG_", i+1):
                            out.append(' ')
            i += 1

        text = ''.join(out)

    # --- 6. Restore COL tags ---
    for idx, tag in enumerate(col_tags):
        text = text.replace(f"__COLTAG_{idx}__", tag)

    # --- 7. COL spacing rules ---
    if not skip_spacing:
        text = re.sub(r'(?<=\w)(<COL[^>]*>)', r' \1', text)
        text = re.sub(r'(<COL[^>]*>)\s+\[', r'\1[', text)
        text = re.sub(r'\s+(</COL>)', r'\1', text)
        text = re.sub(r'\]\s+(</COL>)', r']\1', text)
        text = re.sub(r'(</COL>)(?=\w)', r'\1 ', text)
        text = re.sub(r' {2,}(?=\S)', ' ', text)

    # --- 8. Move punctuation outside COL blocks ---
    text = re.sub(r'(</COL>)[ ]*([.!?;:])(?!\.)', r'\1\2', text)

    # ------------------------------------------------------------
    # SAFE TIME‑UNIT RULE
    # Only insert space when a digit is glued to a unit
    # ------------------------------------------------------------
    text = re.sub(
        r'(\d)(?=(minutes?|mins?|minute|hours?|hrs?|hour|seconds?|secs?|second)\b)',
        r'\1 ',
        text
    )

    return text



# ------------------------------------------------------------
# Tag validation
# ------------------------------------------------------------

def validate_tags(text):
    """
    DDON tag validation:
    - Checks for unbalanced < and > characters.
      Ignores arrow symbols (<- and ->).
    - Only validates <COL> / </COL> matching.
    - Other tags such as <NPC 580>, <STG 443>, etc.
      are standalone markers and do not require closing tags.
    """
	
    # Ignore entries that consist only of a single arrow/bracket symbol
    if text.strip() in ("<", ">"):
        return None

    # Check basic angle bracket balance
    cleaned = re.sub(r"<-|->", "", text)

    # Check for unbalanced square brackets
    if text.count("[") != text.count("]"):
        return "Unbalanced square brackets"

    if cleaned.count("<") != cleaned.count(">"):
        return "Unbalanced angle brackets"

    # Validate only COL tags
    stack = []

    for tag in re.findall(r"</?COL[^>]*>", text):
        if tag.startswith("</"):
            if not stack:
                return "Unexpected closing tag </COL>"

            stack.pop()

        else:
            stack.append("COL")

    if stack:
        return "Missing closing tag for <COL>"

    return None

def validate_tag_folder(folder):
    errors = []

    for csv_file in folder.rglob("*.csv"):
        if csv_file.name.lower() == "gmd.csv":
            continue

        with open(csv_file, encoding="utf-8-sig", newline="") as f:
            for rnum, row in enumerate(csv.reader(f), start=1):
                if len(row) > 3:
                    err = validate_tags(row[3])

                    if err:
                        errors.append(
                            f"{csv_file}\n"
                            f" Row {rnum}, Entry {row[0]}:\n"
                            f"  {err}\n"
                            f"  {repr(row[3])}\n"
                        )

    if errors:
        print("\n===== TAG VALIDATION ERRORS =====\n")
        print("\n".join(errors))
        raise SystemExit(1)
# ------------------------------------------------------------
# CSV validation
# ------------------------------------------------------------
def validate_csv_file(file_path):
    errors = []

    with open(file_path, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.reader(csvfile)
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue

            first_column = row[0].strip().lstrip('\ufeff')
            if first_column == "#Index":
                continue

            if not first_column.isdigit():
                errors.append(
                    f"{file_path} (row {row_number}): Column 1 must be digits (got '{first_column}')"
                )

            if len(row) < 8:
                errors.append(
                    f"{file_path} (row {row_number}): Row has {len(row)} columns, expected 8"
                )
                continue

            gmd_path = row[4].strip()
            arc_path = row[5].strip()
            arc_name = row[6].strip()
            read_index = row[7].strip()

            if not gmd_path.endswith(".gmd"):
                errors.append(
                    f"{file_path} (row {row_number}): Column 5 must end with .gmd (got '{gmd_path}')"
                )

            if not arc_path.endswith(".arc") or "\\" not in arc_path:
                errors.append(
                    f"{file_path} (row {row_number}): Column 6 must end with .arc and contain '\\' (got '{arc_path}')"
                )

            if not arc_name.endswith(".arc"):
                errors.append(
                    f"{file_path} (row {row_number}): Column 7 must end with .arc (got '{arc_name}')"
                )

            if not read_index.isdigit():
                errors.append(
                    f"{file_path} (row {row_number}): Column 8 must be digits (got '{read_index}')"
                )

    return errors


def validate_folder(folder):
    EXCLUDED_NAMES = {
        "gmd staging",
        "Terms and references directory",
        "Tools"
    }

    print(f"\nValidating {folder} ...")
    all_errors = []

    for csv_file in folder.rglob("*.csv"):
        if any(part in EXCLUDED_NAMES for part in csv_file.parts):
            continue
        all_errors.extend(validate_csv_file(csv_file))

    if all_errors:
        print(f"\n❌ CSV Validation Failed in {folder}:\n")
        for err in all_errors:
            print(" - " + err)
        sys.exit(1)

    print(f"{folder} passed validation (ignored: {', '.join(EXCLUDED_NAMES)}).")


# ------------------------------------------------------------
# Entry-count validation
# ------------------------------------------------------------
def count_csv_entries(file_path):
    """
    Count actual CSV data entries (rows) in a file, not raw lines.
    Skips the header row (#Index) and any blank rows, and correctly
    handles rows whose fields contain embedded newlines.
    """
    count = 0
    with open(file_path, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if not row:
                continue
            first_column = row[0].strip().lstrip('\ufeff')
            if first_column == "#Index":
                continue
            count += 1
    return count


def validate_entry_count(file_path, minimum=MIN_ENTRY_COUNT):
    """
    Ensure the resulting CSV has at least `minimum` entries.
    Exits the process with an error if the file is missing or short.
    """
    if not file_path.exists():
        print(f"\n❌ Entry count validation failed: {file_path} does not exist.")
        sys.exit(1)

    entry_count = count_csv_entries(file_path)

    if entry_count < minimum:
        print(
            f"\n❌ Entry count validation failed for {file_path}: "
            f"found {entry_count} entries, expected at least {minimum}."
        )
        sys.exit(1)

    print(f"{file_path} passed entry count validation ({entry_count} entries, minimum {minimum}).")
    return entry_count


def get_changed_files():
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            capture_output=True, text=True, check=True
        )
        return [f for f in result.stdout.splitlines() if f.endswith(".csv")]
    except Exception:
        return []


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

    csv_files = list(fully_translated.glob("*.csv")) + list(splits_folder.glob("*.csv"))

    def numeric_sort_key(p):
        try:
            return int(p.stem)
        except ValueError:
            return 0

    csv_files = sorted(csv_files, key=numeric_sort_key)

    with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerow([
            "#Index", "Key", "MsgJp", "MsgEn",
            "GmdPath", "ArcPath", "ArcName", "ReadIndex"
        ])
        for csv_file in csv_files:
            with open(csv_file, newline='', encoding='utf-8-sig') as infile:
                for row in csv.reader(infile):
                    if row:
                        row[0] = row[0].lstrip('\ufeff').strip()
                        writer.writerow(row)

    print(f"English gmd.csv generated from {len(csv_files)} CSV files.")

    # Enforce the minimum entry-count requirement on the merged output.
    validate_entry_count(output_file)


def process_english_csv(path):
    changed = False
    rows = []

    with open(path, 'r', encoding='utf-8', newline='') as f:
        for row in csv.reader(f):

            row_text = ",".join(row)
            skip_row = any(key in row_text for key in SKIP_SPACING_KEYWORDS)

            if len(row) > ENGLISH_COLUMN:
                cell = row[ENGLISH_COLUMN]

                if any(c in cell for c in TARGET_CHARS) or '：' in cell or ':' in cell or '[' in cell or ']' in cell:
                    fixed = fix_text(cell, skip_override=skip_row)
                    if fixed != cell:
                        row[ENGLISH_COLUMN] = fixed
                        changed = True

            rows.append(row)

    if changed:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            csv.writer(f, quoting=csv.QUOTE_MINIMAL).writerows(rows)


def walk_and_process_english(root):
    for folder, _, files in os.walk(root):
        for file in files:
            if file.lower().endswith('.csv'):
                process_english_csv(os.path.join(folder, file))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args()

    english_folder = Path(__file__).parent
    fully_translated = english_folder / "Fully Translated"
    splits_folder = english_folder / "splits"
    gmd_output = english_folder / "gmd.csv"

    if not args.ci:
        for folder in [fully_translated, splits_folder]:
            if folder.exists():
                validate_folder(folder)

        walk_and_process_english(english_folder)
        validate_tag_folder(english_folder)
        validate_tag_folder(english_folder)
        modify_specific_entry()
        merge_english()  # also runs validate_entry_count() on gmd.csv internally

        print("\nLocal English validation + generation complete.")
        return

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
            validate_folder(repo_root / folder_name)

    # In CI mode we don't regenerate gmd.csv, but if it already exists in the
    # repo we still enforce the minimum entry-count requirement on it.
    if gmd_output.exists():
        validate_entry_count(gmd_output)

    print("\nCI validation complete.")


if __name__ == "__main__":
    main()