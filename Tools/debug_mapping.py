import csv, os
from collections import defaultdict
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
changes_path = os.path.join(os.path.dirname(__file__), 'changes_only.csv')
updated_dir = os.path.join(os.path.dirname(__file__), 'updated_csvs')
print('changes_path', changes_path)
if not os.path.isfile(changes_path):
    print('no changes_only.csv')
    raise SystemExit(1)
mapb = defaultdict(set)
with open(changes_path, encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        b = os.path.basename(row['file'])
        mapb[b].add(row['file'])

updated = [f for f in os.listdir(updated_dir) if f.lower().endswith('.csv')]
print('updated files count', len(updated))
missing = []
amb = []
for uf in updated:
    targets = mapb.get(uf)
    if not targets:
        missing.append(uf)
    elif len(targets) > 1:
        amb.append((uf, len(targets)))

print('missing count', len(missing))
print('ambiguous count', len(amb))
print('\nambiguous examples:')
for a in amb[:10]:
    print(a)
print('\nmissing examples:')
for m in missing[:20]:
    print(m)
print('\nTotal mapping entries', len(mapb))
