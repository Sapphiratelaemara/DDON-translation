import csv
import io as _io
import os

# Column indices for the dialogue CSV format (10 columns, 0-based).
# col0=id, col1=empty, col2=JP text, col3=EN text, col4=file path,
# col5=arc1, col6=arc2, col7=flag, col8=speaker, col9=entry_type.
# Centralized so the magic indices live in exactly one place. Do NOT use these
# for the glossary file (get_reference_entry), which has a different layout.
CSV_COL_ID = 0
CSV_COL_JP = 2
CSV_COL_EN = 3
CSV_COL_PATH = 4
CSV_COL_SPEAKER = 8
CSV_COL_ENTRY_TYPE = 9

def _get_csv_files(folders):
    csvs = []
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if fn.lower().endswith(".csv"):
                csvs.append(os.path.join(folder, fn))
    return csvs

def _read_csv(path):
    """Read a CSV file robustly.

    We sniff the delimiter, but force quote handling to match this project's CSVs.
    If quote parsing is wrong, commas inside dialogue (e.g. "Every day, we…") will
    incorrectly split fields and the editor will appear to "truncate" entries.
    """
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        raw = f.read()
    try:
        dialect = csv.Sniffer().sniff(raw[:4096])
        # Force correct quote behavior for dialogue fields with commas/newlines.
        dialect.quotechar = '"'
        dialect.doublequote = True
        dialect.quoting = csv.QUOTE_MINIMAL
    except csv.Error:
        dialect = csv.excel
        dialect.quotechar = '"'
        dialect.doublequote = True
        dialect.quoting = csv.QUOTE_MINIMAL
    return raw, dialect, list(csv.reader(_io.StringIO(raw), dialect))


def row_matches_triggers(row, triggers):
    """Return True if any trigger string is a substring of the joined row cells.

    Path separators are normalized so a trigger typed/pasted with '/' (or '\\')
    matches CSV data stored with the opposite separator. CSV paths use
    backslashes (e.g. "ui\\00_message\\quest\\q60200015.gmd"), but users often
    enter forward slashes — without normalization an existing entry key returns
    0 matched rows. Shared by batch run, pretranslate, and the scan loader so
    the same matching rule lives in exactly one place.
    """
    if not triggers:
        return True
    joined = "|".join(row).replace('/', '\\')
    return any(tr.replace('/', '\\') in joined for tr in triggers)
