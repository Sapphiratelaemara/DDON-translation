import os, sys
sys.path.insert(0, '.')
import main

folders = ['C:/DDON-translation/English/Fully Translated', 'C:/DDON-translation/English/splits']
triggers = ['フッフッフ、まぁ聞きたまえ！']
found = 0
for folder in folders:
    for root, _d, files in os.walk(folder):
        for name in files:
            if not name.endswith('.csv'):
                continue
            fp = os.path.join(root, name)
            try:
                _raw, _dial, rows = main._read_csv_cached(fp)
            except Exception as e:
                print('ERR', fp, e)
                continue
            for ri, row in enumerate(rows):
                if len(row) <= 3:
                    continue
                if not main.row_matches_triggers(row, triggers):
                    continue
                jp = row[main.CSV_COL_JP] if len(row) > main.CSV_COL_JP else ''
                en = row[main.CSV_COL_EN] if len(row) > main.CSV_COL_EN else ''
                if not jp:
                    continue
                if en and en.strip():
                    continue
                found += 1
                print('FOUND', fp, ri)
print('total found:', found)
