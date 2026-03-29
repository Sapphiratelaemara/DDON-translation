#!/usr/bin/env python3
import argparse
import csv
import os
import re
import shutil
from collections import defaultdict
import json

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
            m[q][ii] = row.get('type_name', '')
    return m

def load_speakers(mss_root=None):
    m = defaultdict(dict)
    script_dir = os.path.abspath(os.path.dirname(__file__))
    if mss_root is None:
        mss_root = os.path.join(script_dir, 'ddon-data', 'client', '03040008', 'quest')
    if not os.path.isdir(mss_root):
        return m

    for root, _, files in os.walk(mss_root):
        norm = root.replace('\\', '/').lower()
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
                            except Exception:
                                pass
    return m

def process_csv(path, mapping, speaker_map, out_dir, dry_run, review_writer):
    rows = []
    with open(path, encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)

    changed = False

    for ri, row in enumerate(rows):
        # 1. Find GMD path column
        gmd_path = None
        gmd_col = None
        for ci, cell in enumerate(row):
            if isinstance(cell, str) and cell.lower().endswith('.gmd'):
                gmd_path = cell.replace('\\', '/').lower()
                gmd_col = ci
                break
        if not gmd_path:
            continue

        # 2. Extract quest ID
        m = re.search(r'q\d{8}', gmd_path)
        if not m:
            continue
        quest = m.group(0)

        # 3. Determine quest type
        is_quest_info = 'ui/00_message/quest_info/' in gmd_path
        is_quest_dialog = (
            'ui/00_message/quest/' in gmd_path
            and not is_quest_info
            and 'examine_message' not in gmd_path
        )

        # 4. Extract GMD index (always gmd_col + 3)
        gmd_index_col = gmd_col + 3
        if gmd_index_col >= len(row):
            continue
        try:
            gmd_index = int(row[gmd_index_col])
        except:
            continue

        # 5. Look up mapping values
        type_name = mapping.get(quest, {}).get(gmd_index) if is_quest_info else None
        speaker = speaker_map.get(quest, {}).get(gmd_index) if is_quest_dialog else None

        if not type_name and not speaker:
            continue

        # 6. Ensure speaker and type columns exist
        dest_speaker = gmd_index_col + 1
        dest_type = gmd_index_col + 2

        while len(row) <= dest_type:
            row.append('')

        old_speaker = row[dest_speaker]
        old_type = row[dest_type]

        # 7. Determine if changes are needed
        will_change = False
        write_speaker = False

        if speaker and (old_speaker == '' or old_speaker != speaker):
            write_speaker = True
            will_change = True

        if type_name and old_type != type_name:
            will_change = True

        # 8. Apply changes
        if will_change:
            review_writer.writerow([
                path,
                ri + 1,
                quest,
                gmd_index,
                old_speaker,
                speaker if write_speaker else '',
                old_type,
                type_name or ''
            ])

            if write_speaker:
                row[dest_speaker] = speaker

            if type_name:
                row[dest_type] = type_name

            changed = True

    if changed and not dry_run:
        os.makedirs(out_dir, exist_ok=True)
        script_dir = os.path.abspath(os.path.dirname(__file__))
        backup_dir = os.path.join(script_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))

        out_path = path if out_dir is None else os.path.join(out_dir, os.path.basename(path))
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    return changed

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mapping', required=True)
    p.add_argument('--csv-dir', required=True)
    p.add_argument('--out', default=None)
    p.add_argument('--mss-root', default=None)
    p.add_argument('--verbose', action='store_true')
    p.add_argument('--dry_run', action='store_true')
    args = p.parse_args()

    script_dir = os.path.abspath(os.path.dirname(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, '..'))

    def clean(pth):
        if pth is None:
            return None
        return pth.strip().strip('"').strip("'")

    def resolve(pth):
        if not pth:
            return None
        if os.path.isabs(pth):
            return pth
        return os.path.abspath(os.path.join(repo_root, pth))


    mapping_path = resolve(clean(args.mapping))
    csv_dir = resolve(clean(args.csv_dir))
    out_dir = resolve(clean(args.out))
    mss_root = resolve(clean(args.mss_root)) if args.mss_root else None

    mapping = load_mapping(mapping_path)
    speaker_map = load_speakers(mss_root)

    if args.verbose:
        total_map = sum(len(v) for v in mapping.values())
        print('DEBUG: mapping quests=', len(mapping), 'entries=', total_map)
        sample_q = next(iter(mapping)) if mapping else None
        if sample_q:
            print('DEBUG: sample mapping for', sample_q, list(mapping[sample_q].items())[:5])
        print('DEBUG: speaker_map quests=', len(speaker_map))
        sample_s = next(iter(speaker_map)) if speaker_map else None
        if sample_s:
            print('DEBUG: sample speakers for', sample_s, list(speaker_map[sample_s].items())[:5])
        print('DEBUG: mapping_path=', mapping_path)
        print('DEBUG: mss_root=', mss_root)
        print('DEBUG: csv_dir=', csv_dir)

        csv_count = 0
        for root, _, files in os.walk(csv_dir):
            for fn in files:
                if fn.lower().endswith('.csv'):
                    csv_count += 1
        print('DEBUG: csv files found=', csv_count)

    review_path = os.path.join(script_dir, 'review_changes.csv')
    with open(review_path, 'w', encoding='utf-8', newline='') as rf:
        rw = csv.writer(rf)
        rw.writerow(['file', 'row', 'quest', 'gmd_idx', 'old_speaker', 'new_speaker', 'old_type', 'new_type'])

        for root, _, files in os.walk(csv_dir):
            for fn in files:
                if fn.lower().endswith('.csv'):
                    fp = os.path.join(root, fn)
                    process_csv(fp, mapping, speaker_map, out_dir, args.dry_run, rw)

    print('Done. Review:', review_path)

if __name__ == '__main__':
    main()

