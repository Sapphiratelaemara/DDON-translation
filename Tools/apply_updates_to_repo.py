#!/usr/bin/env python3
import os, csv, shutil

def main():
    script_dir = os.path.abspath(os.path.dirname(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, '..'))
    updated_dir = os.path.join(script_dir, 'updated_csvs')
    changes_file = os.path.join(script_dir, 'changes_only.csv')
    backup_dir = os.path.join(script_dir, 'backups2')
    os.makedirs(backup_dir, exist_ok=True)

    if not os.path.isdir(updated_dir):
        print('No updated_csvs found at', updated_dir); return
    if not os.path.isfile(changes_file):
        print('No changes_only.csv found at', changes_file); return

    # build mapping basename -> set(original paths)
    mapping = {}
    with open(changes_file, encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            orig = row.get('file')
            if not orig: continue
            base = os.path.basename(orig)
            mapping.setdefault(base, set()).add(orig)

    updated_files = [f for f in os.listdir(updated_dir) if f.lower().endswith('.csv')]
    overwrote = 0
    ambiguous = []
    missing = []
    for uf in updated_files:
        src = os.path.join(updated_dir, uf)
        targets = mapping.get(uf)
        if not targets:
            missing.append(uf)
            continue
        if len(targets) > 1:
            ambiguous.append((uf, targets))
            continue
        target = list(targets)[0]
        # ensure target path exists
        target_path = os.path.abspath(target)
        if not os.path.isfile(target_path):
            # try to resolve relative to repo root
            candidate = os.path.join(repo_root, os.path.relpath(target, repo_root))
            if os.path.isfile(candidate):
                target_path = candidate
            else:
                missing.append(uf)
                continue
        # backup original
        try:
            shutil.copy2(target_path, os.path.join(backup_dir, os.path.basename(target_path)))
        except Exception as e:
            print('Backup failed for', target_path, e)
            continue
        # copy updated over original
        try:
            shutil.copy2(src, target_path)
            overwrote += 1
        except Exception as e:
            print('Failed to copy', src, '->', target_path, e)

    print('Done. Overwrote', overwrote, 'files.')
    if ambiguous:
        print('Ambiguous basenames (skipped):')
        for a,b in ambiguous:
            print(' ', a, '->', len(b), 'targets')
    if missing:
        print('No matching original found for updated files (skipped):', missing[:20])

if __name__ == "__main__":
    main()
