#!/usr/bin/env python3
import csv, os, re, json
from collections import defaultdict

def load_mapping(path):
    m = defaultdict(dict)
    with open(path, encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            q = row.get('quest_id')
            idx = row.get('gmd_idx')
            if idx is None or idx == '':
                continue
            try:
                ii = int(idx)
            except:
                continue
            m[q][ii] = row.get('type_name','')
    return m

def load_speakers(mss_root):
    m = defaultdict(dict)
    if not os.path.isdir(mss_root):
        return m
    for root, _, files in os.walk(mss_root):
        norm = root.replace('\\','/').lower()
        if '/ui/00_message/quest' not in norm:
            continue
        for fn in files:
            if fn.endswith('.mss.json'):
                path = os.path.join(root, fn)
                q = re.match(r'(q\d{8})', fn)
                quest = q.group(1) if q else os.path.splitext(fn)[0]
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue
                for group in data.get('NativeMsgGroupArray', []):
                    nn = group.get('NpcName') or {}
                    name = nn.get('En') or nn.get('Jp') or None
                    for md in group.get('MsgData', []):
                        g = md.get('GmdIndex')
                        if g is None:
                            continue
                        if name:
                            try:
                                m[quest][int(g)] = name
                            except:
                                pass
    return m

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    mapping_path = os.path.join(repo_root, 'Tools', 'qtd_mapping.csv')
    mss_root = os.path.join(repo_root, 'Tools', 'ddon-data', 'client', '03040008', 'quest')
    csv_dir = os.path.join(repo_root, 'English')

    mapping = load_mapping(mapping_path)
    speakers = load_speakers(mss_root)

    out_path = os.path.join(repo_root, 'Tools', 'changes_only.csv')
    writer = csv.writer(open(out_path, 'w', encoding='utf-8', newline=''))
    writer.writerow(['file','row','quest','gmd_idx','old_speaker','new_speaker','old_type','new_type'])
    total = 0
    for root, _, files in os.walk(csv_dir):
        for fn in files:
            if not fn.lower().endswith('.csv'):
                continue
            fp = os.path.join(root, fn)
            rows = []
            with open(fp, encoding='utf-8', newline='') as f:
                for r in csv.reader(f):
                    rows.append(r)
            for ri, row in enumerate(rows):
                for ci, cell in enumerate(row):
                    if isinstance(cell, str) and re.fullmatch(r'q\d{8}\.arc', cell):
                        quest = cell.split('.')[0]
                        if ci+1 >= len(row):
                            continue
                        try:
                            gmd = int(row[ci+1])
                        except:
                            continue
                        # determine gmd path
                        gmd_path = ''
                        if len(row) > 4:
                            gmd_path = str(row[4])
                        norm = gmd_path.replace('/', '\\').lower()
                        is_quest_info = 'ui\\00_message\\quest_info\\q' in norm
                        is_quest_dialog = 'ui\\00_message\\quest\\q' in norm
                        old_sp = ''
                        if ci+2 < len(row):
                            old_sp = row[ci+2]
                        old_type = ''
                        if ci+3 < len(row):
                            old_type = row[ci+3]

                        new_sp = ''
                        new_type = ''
                        if is_quest_dialog:
                            new_sp = speakers.get(quest, {}).get(gmd,'')
                        if is_quest_info:
                            new_type = mapping.get(quest, {}).get(gmd,'')

                        will_change = False
                        if new_sp and new_sp != old_sp:
                            will_change = True
                        if new_type and new_type != old_type:
                            will_change = True
                        if will_change:
                            writer.writerow([fp, ri+1, quest, gmd, old_sp, new_sp, old_type, new_type])
                            total += 1
    print('Found', total, 'rows that would change. Wrote', out_path)

if __name__ == '__main__':
    main()
