#!/usr/bin/env python3
# exhaustive_198_checker.py
# Run without arguments. This script performs an exhaustive, read-only diagnostic
# of the hard-coded file:
#   D:\DDON-translation\English\Fully Translated\198.csv
#
# It checks encoding/BOM, raw bytes (NULs, CR/LF), control characters, CSV parse errors,
# unbalanced quotes, single-column logical rows, non-numeric first columns, ui\00 splits,
# forbidden characters, duplicate keys, path fragments, unmatched brackets/quotes,
# suspicious punctuation, very long fields, inconsistent escaping, and more.
#
# Outputs:
#   - D:\DDON-translation\English\Fully Translated\198_diagnostic.json
#   - D:\DDON-translation\English\Fully Translated\198_diagnostic.log
#
# This script does NOT modify the CSV. It is intentionally exhaustive and verbose.

import csv
import codecs
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from collections import Counter, defaultdict

# -----------------------
# Configuration (no args; path hard-coded)
# -----------------------
CSV_PATH = Path(r"D:\DDON-translation\English\Fully Translated\198.csv")
OUT_JSON = CSV_PATH.with_name("198_diagnostic.json")
OUT_LOG = CSV_PATH.with_name("198_diagnostic.log")
MAX_ROWS = 5000000  # safety cap
SAMPLE_LIMIT = 1000  # how many examples to include per category in JSON/log

# Patterns and helpers
KEY_RE = re.compile(r"^q\d{7}_.+")
NUMERIC_RE = re.compile(r"^\d+$")
UI00_LITERAL = r"ui\\00"
UI00_MESSAGE_LITERAL = r"ui\\00_message"
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
FORBIDDEN_BYTES = [b"\x00"]  # NUL
FORBIDDEN_CHARS = ["\x00"]
UNMATCHED_OPENERS = {"\"": "\"", "“": "”", "‘": "’", "(": ")", "[": "]", "{": "}"}
SUSPICIOUS_LEAD = re.compile(r"^[\?\!]{1,3}")

def safe_read_bytes(path):
    try:
        return path.read_bytes()
    except Exception as e:
        return None

def detect_encodings(raw):
    # Try a set of encodings; record which succeed
    candidates = ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp932", "shift_jis", "euc_jp", "latin-1"]
    results = {}
    for enc in candidates:
        try:
            raw.decode(enc)
            results[enc] = True
        except Exception:
            results[enc] = False
    # BOM detection
    bom = None
    if raw.startswith(codecs.BOM_UTF8):
        bom = "utf-8-sig"
    elif raw.startswith(codecs.BOM_UTF16_LE):
        bom = "utf-16-le-bom"
    elif raw.startswith(codecs.BOM_UTF16_BE):
        bom = "utf-16-be-bom"
    return results, bom

def is_printable_except_whitespace(s):
    for ch in s:
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t"):
            return False
    return True

def count_unbalanced_quotes(s):
    # Heuristic: count of double quotes should be even in a well-formed CSV field
    return s.count('"') % 2

def find_unmatched_pairs(s):
    stack = []
    for ch in s:
        if ch in UNMATCHED_OPENERS:
            stack.append(UNMATCHED_OPENERS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
    return stack[:]  # closers expected but missing

def normalize_nf(s):
    try:
        return unicodedata.normalize("NFC", s)
    except Exception:
        return s

# -----------------------
# Main diagnostic routine
# -----------------------
def run():
    report = {
        "file": str(CSV_PATH),
        "exists": CSV_PATH.exists(),
        "raw": {},
        "encoding_probe": {},
        "physical_lines": 0,
        "logical_rows": 0,
        "samples": {},
        "stats": {},
        "problems": defaultdict(list),
    }

    if not CSV_PATH.exists():
        print(f"File not found: {CSV_PATH}")
        return

    raw = safe_read_bytes(CSV_PATH)
    if raw is None:
        print(f"Unable to read bytes from {CSV_PATH}")
        return

    report["raw"]["length"] = len(raw)
    report["raw"]["contains_nul_byte"] = any(b in raw for b in FORBIDDEN_BYTES)
    report["raw"]["crlf_count"] = raw.count(b"\r\n")
    report["raw"]["lf_count"] = raw.count(b"\n")
    report["raw"]["cr_count"] = raw.count(b"\r")

    enc_results, bom = detect_encodings(raw)
    report["encoding_probe"] = enc_results
    report["encoding_probe"]["bom"] = bom

    # Choose a read encoding: prefer utf-8-sig, then utf-8, then latin-1
    read_enc = "utf-8-sig" if enc_results.get("utf-8-sig") else ("utf-8" if enc_results.get("utf-8") else "latin-1")
    report["read_encoding"] = read_enc

    # Physical-line checks
    try:
        text = raw.decode(read_enc, errors="replace")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
        report["read_encoding"] = "latin-1 (fallback)"

    phys_lines = text.splitlines(keepends=True)
    report["physical_lines"] = len(phys_lines)

    for idx, pl in enumerate(phys_lines, start=1):
        if "\x00" in pl:
            report["problems"]["physical_nul"].append({"line": idx, "snippet": pl[:200]})
        if pl.rstrip("\r\n").endswith("ui\\00"):
            report["problems"]["ui00_split_physical"].append({"line": idx, "snippet": pl.rstrip("\r\n")})
        if count_unbalanced_quotes(pl):
            report["problems"]["physical_unbalanced_quotes"].append({"line": idx, "snippet": pl[:200]})
        # suspicious trailing backslash or unescaped quotes
        if pl.rstrip("\r\n").endswith("\\") or pl.rstrip("\r\n").endswith('"'):
            report["problems"]["physical_trailing_backslash_or_quote"].append({"line": idx, "snippet": pl[:200]})
        if len(pl) > 2000:
            report["problems"]["very_long_physical_line"].append({"line": idx, "len": len(pl)})

    # Logical CSV parsing
    logical_rows = []
    parse_exception = None
    try:
        with CSV_PATH.open("r", encoding=read_enc, newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader, start=1):
                logical_rows.append((i, row))
                if i >= MAX_ROWS:
                    break
    except Exception as e:
        parse_exception = str(e)
        report["problems"]["csv_reader_exception"].append({"error": parse_exception})
        # fallback: naive split
        naive = text.splitlines()
        logical_rows = [(i+1, [line]) for i, line in enumerate(naive)]

    report["logical_rows"] = len(logical_rows)

    # Per-row analysis
    col_count_counter = Counter()
    key_counter = Counter()
    duplicate_keys = []
    single_col_rows = []
    non_numeric_first = []
    unbalanced_quote_rows = []
    ui00_split_rows = []
    long_field_rows = []
    suspicious_lead_rows = []
    path_fragment_rows = []
    unmatched_pairs_rows = []
    non_printable_rows = []
    ascii_only_rows = []
    high_unicode_rows = []

    for i, row in logical_rows:
        col_count_counter[len(row)] += 1
        joined = "|".join(row) if row else ""
        # first column checks
        first = str(row[0]) if len(row) > 0 else ""
        if first and first != "#Index" and not NUMERIC_RE.match(first):
            non_numeric_first.append({"row": i, "first": first})
        if len(row) == 1:
            single_col_rows.append({"row": i, "value": row[0]})
        # key column
        if len(row) > 1:
            key = row[1]
            if key:
                key_counter[key] += 1
                if key_counter[key] > 1:
                    duplicate_keys.append({"row": i, "key": key})
        # ui\00 split detection: ui\00 present but not ui\00_message combined
        if "ui\\00" in joined and "ui\\00_message" not in joined and "_message" in joined:
            ui00_split_rows.append({"row": i, "snippet": joined[:200]})
        # unbalanced quotes
        if count_unbalanced_quotes(joined):
            unbalanced_quote_rows.append({"row": i, "repr": joined[:300]})
        # long fields
        for j, field in enumerate(row):
            if field and len(field) > 2000:
                long_field_rows.append({"row": i, "col": j, "len": len(field)})
        # suspicious leading characters
        if first and SUSPICIOUS_LEAD.match(first):
            suspicious_lead_rows.append({"row": i, "first": first})
        # path-like fragments
        if any(x in joined for x in ["\\", ".gmd", ".arc", "ui\\00", "ui\\00_message", "quest_info", "pc\\"]):
            path_fragment_rows.append({"row": i, "snippet": joined[:200]})
        # unmatched pairs
        unmatched = find_unmatched_pairs(joined)
        if unmatched:
            unmatched_pairs_rows.append({"row": i, "expected_closers": unmatched, "snippet": joined[:200]})
        # non-printable
        if not is_printable_except_whitespace(joined):
            non_printable_rows.append({"row": i, "snippet": joined[:200]})
        # ascii-only vs high unicode
        if joined and all(ord(ch) < 128 for ch in joined if ch.strip()):
            ascii_only_rows.append({"row": i})
        if any(ord(ch) > 0xFFFF for ch in joined):
            high_unicode_rows.append({"row": i})

    # Aggregate into report
    report["stats"]["col_counts"] = dict(col_count_counter.most_common())
    report["problems"]["duplicate_keys"] = duplicate_keys[:SAMPLE_LIMIT]
    report["problems"]["single_column_rows"] = single_col_rows[:SAMPLE_LIMIT]
    report["problems"]["non_numeric_first"] = non_numeric_first[:SAMPLE_LIMIT]
    report["problems"]["unbalanced_quote_rows"] = unbalanced_quote_rows[:SAMPLE_LIMIT]
    report["problems"]["ui00_split_rows"] = ui00_split_rows[:SAMPLE_LIMIT]
    report["problems"]["long_field_rows"] = long_field_rows[:SAMPLE_LIMIT]
    report["problems"]["suspicious_lead_rows"] = suspicious_lead_rows[:SAMPLE_LIMIT]
    report["problems"]["path_fragment_rows"] = path_fragment_rows[:SAMPLE_LIMIT]
    report["problems"]["unmatched_pairs_rows"] = unmatched_pairs_rows[:SAMPLE_LIMIT]
    report["problems"]["non_printable_rows"] = non_printable_rows[:SAMPLE_LIMIT]
    report["problems"]["ascii_only_rows_sample"] = ascii_only_rows[:50]
    report["problems"]["high_unicode_rows_sample"] = high_unicode_rows[:50]
    if parse_exception:
        report["problems"]["csv_reader_exception_full"] = parse_exception

    # Heuristic: likely fragments (single-col or non-numeric-first that look like text)
    likely_fragments = []
    for item in report["problems"]["single_column_rows"]:
        val = item["value"]
        if re.search(r"[A-Za-z0-9'\".,!?-]{3,}", val) or re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", val):
            likely_fragments.append(item)
    for item in report["problems"]["non_numeric_first"]:
        val = item["first"]
        if re.search(r"[A-Za-z0-9'\".,!?-]{3,}", val) or re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", val):
            likely_fragments.append(item)
    report["problems"]["likely_fragments_sample"] = likely_fragments[:SAMPLE_LIMIT]

    # Write outputs
    try:
        with OUT_JSON.open("w", encoding="utf-8") as fo:
            json.dump(report, fo, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Failed to write JSON:", e)

    try:
        with OUT_LOG.open("w", encoding="utf-8") as fo:
            fo.write(f"Diagnostic log for: {CSV_PATH}\n\n")
            fo.write(f"Read encoding used: {report['read_encoding']}\n")
            fo.write(f"Raw bytes length: {report['raw']['length']}\n")
            fo.write(f"Physical lines: {report['physical_lines']}\n")
            fo.write(f"Logical rows parsed: {report['logical_rows']}\n\n")
            fo.write("Top column counts (sample):\n")
            for cols, cnt in report["stats"]["col_counts"].items():
                fo.write(f"  {cols} columns: {cnt} rows\n")
            fo.write("\nProblems summary (counts and samples):\n")
            for k, v in report["problems"].items():
                fo.write(f"\n=== {k} (count={len(v)}) ===\n")
                for item in v[:SAMPLE_LIMIT]:
                    fo.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as e:
        print("Failed to write log:", e)

    print("Diagnostic complete.")
    print("JSON:", OUT_JSON)
    print("LOG:", OUT_LOG)

if __name__ == "__main__":
    run()