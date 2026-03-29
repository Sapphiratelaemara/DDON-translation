"""Parse .qtd.json files into a mapping CSV.

Usage: python Tools/parse_qtd.py --src Tools/tmp_qtd --out Tools/qtd_mapping.csv
"""
import argparse
import json
import csv
import os
import re


def parse_file(path):
    base = os.path.basename(path)
    m = re.match(r'(q\d{8})', base)
    quest_id = m.group(1) if m else os.path.splitext(base)[0]
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    out = []
    for i, entry in enumerate(data.get('QuestTextDataList', [])):
        g = entry.get('MsgGmdIdx')
        tn = entry.get('TypeName', '')
        msg = entry.get('Message', {}) or {}
        en = msg.get('En', '')
        prompt = entry.get('Prompt') or msg.get('Prompt') or ''
        out.append({
            'quest_id': quest_id,
            'gmd_idx': '' if g is None else str(g),
            'type_name': tn,
            'en_text': en,
            'source_file': base,
            'entry_index': str(i),
            'prompt': prompt,
        })
    return out


def main():
    p = argparse.ArgumentParser()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_src = os.path.join(script_dir, 'ddon-data', 'client', '03040008', 'quest')
    p.add_argument('--src', default=default_src, help=f"source folder with .qtd.json files (default: {default_src})")
    p.add_argument('--out', required=True)
    args = p.parse_args()

    if not os.path.isdir(args.src):
        print(f"Source folder '{args.src}' does not exist. Please provide --src pointing to .qtd.json files.")
        return

    rows = []
    for root, _, files in os.walk(args.src):
        for fn in files:
            if fn.endswith('.qtd.json'):
                rows.extend(parse_file(os.path.join(root, fn)))

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['quest_id', 'gmd_idx', 'type_name', 'en_text', 'source_file', 'entry_index', 'prompt']
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == '__main__':
    main()
