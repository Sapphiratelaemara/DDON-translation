import csv
import io as _io
import os

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
