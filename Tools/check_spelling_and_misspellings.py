import pandas as pd
from symspellpy.symspellpy import SymSpell, Verbosity
from rapidfuzz import process, fuzz
from tqdm import tqdm
import os

# === Load custom .dic file ===
def load_dic(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # First line is usually word count; skip it
    words = set(line.strip().split('/')[0].lower() for line in lines[1:])
    return words

dictionary_words = load_dic("en_US.dic")

# === Check files exist ===
if not os.path.exists("English only.csv") or not os.path.exists("gmd.csv"):
    print("Missing one or more required files.")
    input("Press Enter to exit...")
    exit()

# === Load data ===
approved_df = pd.read_csv("English only.csv")
check_df = pd.read_csv("gmd.csv")

# === Prepare lists ===
approved_terms = approved_df.iloc[:, 0].dropna().str.strip().str.lower().tolist()
check_terms = check_df.iloc[:, 0].dropna().str.strip().drop_duplicates().str.lower().tolist()

# === Initialize SymSpell ===
sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
for term in tqdm(approved_terms, desc="Building dictionary with SymSpell"):
    sym_spell.create_dictionary_entry(term, 1)

# === Begin processing ===
misspellings = []

print("Checking terms...")

for term in tqdm(check_terms, desc="Processing terms", unit="term"):
    if not term or term.isnumeric() or len(term) <= 2:
        continue
    if term in approved_terms or term in dictionary_words:
        continue  # Skip exact match in glossary or system dictionary

    # 1. SymSpell check
    suggestions = sym_spell.lookup(term, Verbosity.CLOSEST, max_edit_distance=2)
    if suggestions:
        top = suggestions[0]
        if top.term != term:
            misspellings.append((term, top.term, top.distance, "SymSpell"))
            continue

    # 2. Fuzzy match
    match_data = process.extractOne(term, approved_terms, scorer=fuzz.ratio, score_cutoff=85)
    if match_data:
        match = match_data[0]
        score = match_data[1]
        misspellings.append((term, match, score, "Fuzzy Match"))

# === Save results ===
misspellings_df = pd.DataFrame(
    misspellings,
    columns=["Found Term", "Suggested Correction", "Similarity Score", "Type"]
)
misspellings_df.to_csv("misspellings_custom_dic_symspell_fuzzy.csv", index=False)

print("✅ Done! Saved to misspellings_custom_dic_symspell_fuzzy.csv")
input("Press Enter to exit...")
