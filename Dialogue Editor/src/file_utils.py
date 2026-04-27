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
    """Read a CSV file, sniffing the delimiter but always using doublequote=True."""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        raw = f.read()
    try:
        dialect = csv.Sniffer().sniff(raw[:4096])
        dialect.doublequote = True
    except csv.Error:
        dialect = csv.excel
    return raw, dialect, list(csv.reader(_io.StringIO(raw), dialect))
