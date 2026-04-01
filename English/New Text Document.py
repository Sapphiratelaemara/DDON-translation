import os
import csv
import re

def has_bom(path):
    with open(path, "rb") as f:
        return f.read(3) == b'\xef\xbb\xbf'

def clean_text(text):
    if not text:
        return text

    # Remove line breaks
    text = re.sub(r'[\r\n]+', ' ', text)

    # Collapse multiple spaces
    text = re.sub(r' {2,}', ' ', text)

    # Remove trailing punctuation (., , …)
    text = re.sub(r'[.,…]+$', '', text)

    # Remove content-level quotes only if both sides match
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    return text.strip()

def process_csv(file_path):
    original_has_bom = has_bom(file_path)

    with open(file_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return

    changed = False

    for row in rows:
        # Normalize slashes for detection
        normalized = [c.replace("\\", "/") if isinstance(c, str) else c for c in row]

        # Find the GMD path column
        gmd_col = None
        for i, cell in enumerate(normalized):
            if isinstance(cell, str) and cell.endswith(".gmd") and "quest_info" in cell:
                gmd_col = i
                break

        if gmd_col is None:
            continue

        # English text is always one column before the GMD path
        en_col = gmd_col - 1
        if en_col < 0:
            continue

        # type_name is always gmd_col + 5 (based on your fixed structure)
        type_col = gmd_col + 5
        if type_col >= len(row):
            continue

        type_value = row[type_col].strip()

        if type_value != "QUEST_TEXT_TYPE_PURPOSE":
            continue

        original_text = row[en_col]
        cleaned_text = clean_text(original_text)

        if cleaned_text != original_text:
            row[en_col] = cleaned_text
            changed = True

    if not changed:
        return

    write_encoding = "utf-8-sig" if original_has_bom else "utf-8"

    with open(file_path, "w", encoding=write_encoding, newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerows(rows)

    print(f"Modified: {file_path}")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith(".csv"):
                path = os.path.join(root, file)
                process_csv(path)

    print("Done.")

if __name__ == "__main__":
    main()