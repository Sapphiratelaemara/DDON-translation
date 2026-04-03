#!/usr/bin/env python3
"""
Combined QTD toolkit with a basic Tkinter UI.

Features
- Fetch .qtd.json files from a GitHub repo subpath into a local folder (only download if missing or changed).
- Parse .qtd.json files into a mapping CSV.
- Integrated third-script processing (apply mapping and speaker names to CSV files).
- Optionally run an external third script.
Run this file to open the UI.
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys
import threading
import urllib.parse
import urllib.request
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import subprocess
import tempfile


API_BASE = 'https://api.github.com/repos'
RAW_BASE = 'https://raw.githubusercontent.com'
META_FILENAME = '.fetch_meta.json'


# ---------------------------
# Networking / file utilities
# ---------------------------
def get_url(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _load_meta(outdir):
    meta_path = os.path.join(outdir, META_FILENAME)
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_meta(outdir, meta):
    meta_path = os.path.join(outdir, META_FILENAME)
    try:
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _git_available():
    try:
        subprocess.run(['git', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

def fetch_dir_git(owner, repo, subpath, outdir, log_fn=print):
    """
    Use git sparse checkout to fetch only the requested subpath.
    This avoids GitHub API listing and reduces rate-limit issues.
    """
    repo_url = f"https://github.com/{owner}/{repo}.git"
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='qtd_git_')
        # shallow clone without blobs, then sparse-checkout the subpath
        # Use --filter=blob:none to avoid downloading file contents for the whole repo
        cmds = [
            ['git', 'clone', '--depth', '1', '--filter=blob:none', '--no-checkout', repo_url, tmpdir],
            ['git', '-C', tmpdir, 'sparse-checkout', 'init', '--cone'],
            ['git', '-C', tmpdir, 'sparse-checkout', 'set', subpath],
            ['git', '-C', tmpdir, 'checkout']
        ]
        for cmd in cmds:
            log_fn('Running: ' + ' '.join(cmd))
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # copy .qtd.json files from tmpdir/subpath into outdir (flat)
        src_root = os.path.join(tmpdir, subpath)
        if not os.path.isdir(src_root):
            log_fn(f"Subpath not found in repo after sparse checkout: {src_root}")
            return 1

        os.makedirs(outdir, exist_ok=True)
        copied = 0
        for root, _, files in os.walk(src_root):
            for fn in files:
                if fn.endswith('.qtd.json'):
                    src_path = os.path.join(root, fn)
                    dst_path = os.path.join(outdir, fn)
                    # copy only if missing or different
                    try:
                        with open(src_path, 'rb') as sf:
                            data = sf.read()
                        if os.path.isfile(dst_path):
                            with open(dst_path, 'rb') as df:
                                if df.read() == data:
                                    log_fn(f"Unchanged: {dst_path}")
                                    continue
                        with open(dst_path, 'wb') as df:
                            df.write(data)
                        log_fn(f"Saved: {dst_path}")
                        copied += 1
                    except Exception as e:
                        log_fn(f"Failed to copy {src_path}: {e}")
        log_fn(f"Git fetch complete. Files copied: {copied}")
        return 0
    except subprocess.CalledProcessError as e:
        log_fn(f"Git command failed: {e}; falling back to API method.")
        return 2
    except Exception as e:
        log_fn(f"Git fetch error: {e}; falling back to API method.")
        return 2
    finally:
        # cleanup tmpdir
        if tmpdir and os.path.isdir(tmpdir):
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

def fetch_dir(owner, repo, subpath, outdir, token=None, log_fn=print):
    """
    Prefer git-based fetch to avoid API rate limits. If git is not available
    or git fetch fails, fall back to the API/raw approach (existing logic).
    """
    # Prefer git if available
    if _git_available():
        rc = fetch_dir_git(owner, repo, subpath, outdir, log_fn=log_fn)
        if rc == 0:
            return 0
        # rc == 2 indicates git failed; fall through to API method

    # --- existing API/raw implementation (unchanged) ---
    headers = {'User-Agent': 'fetch-qtd-script'}
    if token:
        headers['Authorization'] = f'token {token}'

    api_url = f"{API_BASE}/{owner}/{repo}/contents/{urllib.parse.quote(subpath)}"
    try:
        raw = get_url(api_url, headers)
    except Exception as e:
        log_fn(f'Failed to list {api_url}: {e}')
        return 1

    try:
        items = json.loads(raw.decode('utf-8'))
    except Exception as e:
        log_fn(f'Failed to parse listing JSON: {e}')
        return 1

    os.makedirs(outdir, exist_ok=True)
    meta = _load_meta(outdir)

    def save_file_from_path(path, name, sha):
        raw_url = f"{RAW_BASE}/{owner}/{repo}/main/{path}"
        try:
            data = get_url(raw_url, headers)
        except Exception as e:
            log_fn(f'Failed to download {raw_url}: {e}')
            return False
        out_path = os.path.join(outdir, name)
        if os.path.isfile(out_path):
            try:
                with open(out_path, 'rb') as f:
                    existing = f.read()
                if existing == data:
                    meta[path] = sha
                    log_fn(f'Unchanged: {out_path}')
                    return True
            except Exception:
                pass
        try:
            with open(out_path, 'wb') as f:
                f.write(data)
            meta[path] = sha
            log_fn(f'Saved: {out_path}')
            return True
        except Exception as e:
            log_fn(f'Failed to save {out_path}: {e}')
            return False

    def process_items(items_list):
        for it in items_list:
            it_type = it.get('type')
            if it_type == 'file':
                name = it.get('name', '')
                if name.endswith('.qtd.json'):
                    path = it.get('path')
                    sha = it.get('sha')
                    out_path = os.path.join(outdir, name)
                    if sha and meta.get(path) == sha and os.path.isfile(out_path):
                        log_fn(f'Skipping (no change): {out_path}')
                        continue
                    save_file_from_path(path, name, sha)
            elif it_type == 'dir':
                sub = it.get('path')
                try:
                    sub_items_raw = get_url(f"{API_BASE}/{owner}/{repo}/contents/{urllib.parse.quote(sub)}", headers)
                    sub_items = json.loads(sub_items_raw.decode('utf-8'))
                except Exception as e:
                    log_fn(f'Failed to list {sub}: {e}')
                    continue
                for sit in sub_items:
                    if sit.get('type') == 'file' and sit.get('name', '').endswith('.qtd.json'):
                        path = sit.get('path')
                        sha = sit.get('sha')
                        name = sit.get('name')
                        out_path = os.path.join(outdir, name)
                        if sha and meta.get(path) == sha and os.path.isfile(out_path):
                            log_fn(f'Skipping (no change): {out_path}')
                            continue
                        save_file_from_path(path, name, sha)

    process_items(items)
    _save_meta(outdir, meta)
    return 0



# ---------------------------
# Parsing utilities (script 2)
# ---------------------------
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


def parse_folder_to_csv(src_folder, out_csv, log_fn=print):
    if not os.path.isdir(src_folder):
        log_fn(f"Source folder '{src_folder}' does not exist.")
        return 1
    rows = []
    for root, _, files in os.walk(src_folder):
        for fn in files:
            if fn.endswith('.qtd.json'):
                try:
                    rows.extend(parse_file(os.path.join(root, fn)))
                except Exception as e:
                    log_fn(f"Failed to parse {fn}: {e}")
    os.makedirs(os.path.dirname(out_csv) or '.', exist_ok=True)
    fieldnames = ['quest_id', 'gmd_idx', 'type_name', 'en_text', 'source_file', 'entry_index', 'prompt']
    try:
        with open(out_csv, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    except Exception as e:
        log_fn(f"Failed to write CSV {out_csv}: {e}")
        return 1
    log_fn(f"Wrote mapping CSV: {out_csv} ({len(rows)} rows)")
    return 0


# ---------------------------
# Third script functions (integrated)
# ---------------------------
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
            except Exception:
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


def process_csv(path, mapping, speaker_map, csv_dir, out_dir, dry_run, review_writer):
    rows = []
    with open(path, encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)

    changed = False

    for ri, row in enumerate(rows):
        gmd_path = None
        gmd_col = None
        for ci, cell in enumerate(row):
            if isinstance(cell, str) and cell.lower().endswith('.gmd'):
                gmd_path = cell.replace('\\', '/').lower()
                gmd_col = ci
                break
        if not gmd_path:
            continue

        m = re.search(r'q\d{8}', gmd_path)
        if not m:
            continue
        quest = m.group(0)

        is_quest_info = 'ui/00_message/quest_info/' in gmd_path
        is_quest_dialog = (
            'ui/00_message/quest/' in gmd_path
            and not is_quest_info
            and 'examine_message' not in gmd_path
        )

        gmd_index_col = gmd_col + 3
        if gmd_index_col >= len(row):
            continue
        try:
            gmd_index = int(row[gmd_index_col])
        except Exception:
            continue

        type_name = mapping.get(quest, {}).get(gmd_index) if is_quest_info else None
        speaker = speaker_map.get(quest, {}).get(gmd_index) if is_quest_dialog else None

        if not type_name and not speaker:
            continue

        dest_speaker = gmd_index_col + 1
        dest_type = gmd_index_col + 2

        while len(row) <= dest_type:
            row.append('')

        old_speaker = row[dest_speaker] if dest_speaker < len(row) else ''
        old_type = row[dest_type] if dest_type < len(row) else ''

        will_change = False
        write_speaker = False

        if speaker and (old_speaker == '' or old_speaker != speaker):
            write_speaker = True
            will_change = True

        if type_name and old_type != type_name:
            will_change = True

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
                while len(row) <= dest_speaker:
                    row.append('')
                row[dest_speaker] = speaker

            if type_name:
                row[dest_type] = type_name

            changed = True

    if changed and not dry_run:
        if out_dir is not None:
            os.makedirs(out_dir, exist_ok=True)
        script_dir = os.path.abspath(os.path.dirname(__file__))
        backup_dir = os.path.join(script_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))

        if out_dir is None:
            out_path = path
        else:
            relative = os.path.relpath(path, csv_dir)
            out_path = os.path.join(out_dir, relative)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    return changed


def run_third_processing(mapping_path, csv_dir, out_dir, mss_root, dry_run, verbose, log_fn=print):
    if not os.path.isfile(mapping_path):
        log_fn(f"Mapping file not found: {mapping_path}")
        return 1
    if not os.path.isdir(csv_dir):
        log_fn(f"CSV directory not found: {csv_dir}")
        return 1

    mapping = load_mapping(mapping_path)
    speaker_map = load_speakers(mss_root)

    if verbose:
        total_map = sum(len(v) for v in mapping.values())
        log_fn(f'DEBUG: mapping quests={len(mapping)} entries={total_map}')
        sample_q = next(iter(mapping)) if mapping else None
        if sample_q:
            log_fn(f'DEBUG: sample mapping for {sample_q} {list(mapping[sample_q].items())[:5]}')
        log_fn(f'DEBUG: speaker_map quests={len(speaker_map)}')
        sample_s = next(iter(speaker_map)) if speaker_map else None
        if sample_s:
            log_fn(f'DEBUG: sample speakers for {sample_s} {list(speaker_map[sample_s].items())[:5]}')
        log_fn(f'DEBUG: mapping_path={mapping_path}')
        log_fn(f'DEBUG: mss_root={mss_root}')
        csv_count = 0
        for root, _, files in os.walk(csv_dir):
            for fn in files:
                if fn.lower().endswith('.csv'):
                    csv_count += 1
        log_fn(f'DEBUG: csv files found={csv_count}')

    script_dir = os.path.abspath(os.path.dirname(__file__))
    review_path = os.path.join(script_dir, 'review_changes.csv')
    with open(review_path, 'w', encoding='utf-8', newline='') as rf:
        rw = csv.writer(rf)
        rw.writerow(['file', 'row', 'quest', 'gmd_idx', 'old_speaker', 'new_speaker', 'old_type', 'new_type'])

        for root, _, files in os.walk(csv_dir):
            for fn in files:
                if fn.lower().endswith('.csv'):
                    fp = os.path.join(root, fn)
                    run = process_csv(fp, mapping, speaker_map, csv_dir, out_dir, dry_run, rw)
                    if run:
                        log_fn(f'Processed and changed: {fp}')
                    else:
                        log_fn(f'No changes for: {fp}')

    log_fn(f'Done. Review: {review_path}')
    return 0


# ---------------------------
# UI and threading
# ---------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("QTD Fetch, Parse & Process Tool")
        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(sticky='nsew')
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # GitHub inputs
        gh_frame = ttk.LabelFrame(frm, text="GitHub Fetch", padding=8)
        gh_frame.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        for i in range(4):
            gh_frame.columnconfigure(i, weight=1)

        ttk.Label(gh_frame, text="Owner").grid(row=0, column=0, sticky='w')
        self.owner_var = tk.StringVar(value='ddon-research')
        ttk.Entry(gh_frame, textvariable=self.owner_var).grid(row=0, column=1, sticky='ew')

        ttk.Label(gh_frame, text="Repo").grid(row=0, column=2, sticky='w')
        self.repo_var = tk.StringVar(value='ddon-data')
        ttk.Entry(gh_frame, textvariable=self.repo_var).grid(row=0, column=3, sticky='ew')

        ttk.Label(gh_frame, text="Subpath").grid(row=1, column=0, sticky='w')
        self.subpath_var = tk.StringVar(value='client/03040008/quest')
        ttk.Entry(gh_frame, textvariable=self.subpath_var, width=60).grid(row=1, column=1, columnspan=3, sticky='ew')

        ttk.Label(gh_frame, text="Out folder").grid(row=2, column=0, sticky='w')
        self.outdir_var = tk.StringVar(value=os.path.join(os.getcwd(), 'tmp_qtd'))
        ttk.Entry(gh_frame, textvariable=self.outdir_var).grid(row=2, column=1, sticky='ew')
        ttk.Button(gh_frame, text="Browse", command=self.browse_outdir).grid(row=2, column=2, sticky='ew')

        ttk.Label(gh_frame, text="GitHub Token (optional)").grid(row=3, column=0, sticky='w')
        self.token_var = tk.StringVar(value=os.environ.get('GITHUB_TOKEN', ''))
        ttk.Entry(gh_frame, textvariable=self.token_var, show='*').grid(row=3, column=1, sticky='ew')
        ttk.Button(gh_frame, text="Update", command=self.start_fetch).grid(row=3, column=3, sticky='e')

        # Parsing inputs
        parse_frame = ttk.LabelFrame(frm, text="Parse to CSV", padding=8)
        parse_frame.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        parse_frame.columnconfigure(1, weight=1)

        ttk.Label(parse_frame, text="Source folder").grid(row=0, column=0, sticky='w')
        self.parse_src_var = tk.StringVar(value=self.outdir_var.get())
        ttk.Entry(parse_frame, textvariable=self.parse_src_var).grid(row=0, column=1, sticky='ew')
        ttk.Button(parse_frame, text="Browse", command=self.browse_parse_src).grid(row=0, column=2, sticky='ew')

        ttk.Label(parse_frame, text="Output CSV").grid(row=1, column=0, sticky='w')
        self.csv_out_var = tk.StringVar(value=os.path.join(os.getcwd(), 'qtd_mapping.csv'))
        ttk.Entry(parse_frame, textvariable=self.csv_out_var).grid(row=1, column=1, sticky='ew')
        ttk.Button(parse_frame, text="Browse", command=self.browse_csv_out).grid(row=1, column=2, sticky='ew')

        ttk.Button(parse_frame, text="Parse", command=self.start_parse).grid(row=2, column=2, sticky='e')

        # Integrated third-script processing
        third_frame = ttk.LabelFrame(frm, text="Integrated Processing", padding=8)
        third_frame.grid(row=2, column=0, sticky='ew', padx=5, pady=5)
        third_frame.columnconfigure(1, weight=1)

        ttk.Label(third_frame, text="Mapping CSV").grid(row=0, column=0, sticky='w')
        self.mapping_var = tk.StringVar(value=self.csv_out_var.get())
        ttk.Entry(third_frame, textvariable=self.mapping_var).grid(row=0, column=1, sticky='ew')
        ttk.Button(third_frame, text="Browse", command=self.browse_mapping).grid(row=0, column=2, sticky='ew')

        ttk.Label(third_frame, text="CSV Directory").grid(row=1, column=0, sticky='w')
        self.csv_dir_var = tk.StringVar(value=os.getcwd())
        ttk.Entry(third_frame, textvariable=self.csv_dir_var).grid(row=1, column=1, sticky='ew')
        ttk.Button(third_frame, text="Browse", command=self.browse_csv_dir).grid(row=1, column=2, sticky='ew')

        ttk.Label(third_frame, text="Output CSV Dir (optional)").grid(row=2, column=0, sticky='w')
        self.out_csv_dir_var = tk.StringVar(value='')
        ttk.Entry(third_frame, textvariable=self.out_csv_dir_var).grid(row=2, column=1, sticky='ew')
        ttk.Button(third_frame, text="Browse", command=self.browse_out_csv_dir).grid(row=2, column=2, sticky='ew')

        ttk.Label(third_frame, text="MSS Root (optional)").grid(row=3, column=0, sticky='w')
        self.mss_root_var = tk.StringVar(value='')
        ttk.Entry(third_frame, textvariable=self.mss_root_var).grid(row=3, column=1, sticky='ew')
        ttk.Button(third_frame, text="Browse", command=self.browse_mss_root).grid(row=3, column=2, sticky='ew')

        self.dry_run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(third_frame, text="Dry run (do not write changes)", variable=self.dry_run_var).grid(row=4, column=0, sticky='w')
        self.verbose_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(third_frame, text="Verbose debug", variable=self.verbose_var).grid(row=4, column=1, sticky='w')

        ttk.Button(third_frame, text="Run Integrated Processing", command=self.start_integrated_processing).grid(row=5, column=2, sticky='e')

        # Option to run external third script
        ext_frame = ttk.LabelFrame(frm, text="Run External Third Script (optional)", padding=8)
        ext_frame.grid(row=3, column=0, sticky='ew', padx=5, pady=5)
        ext_frame.columnconfigure(1, weight=1)

        ttk.Label(ext_frame, text="Script").grid(row=0, column=0, sticky='w')
        self.third_script_var = tk.StringVar(value='')
        ttk.Entry(ext_frame, textvariable=self.third_script_var).grid(row=0, column=1, sticky='ew')
        ttk.Button(ext_frame, text="Select", command=self.browse_third_script).grid(row=0, column=2, sticky='ew')
        ttk.Button(ext_frame, text="Run", command=self.start_run_third).grid(row=0, column=3, sticky='e')

        # Log area
        log_frame = ttk.LabelFrame(frm, text="Log", padding=8)
        log_frame.grid(row=4, column=0, sticky='nsew', padx=5, pady=5)
        frm.rowconfigure(4, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log = scrolledtext.ScrolledText(log_frame, height=14, state='disabled')
        self.log.grid(row=0, column=0, sticky='nsew')

    # UI helpers
    def browse_outdir(self):
        d = filedialog.askdirectory(initialdir=self.outdir_var.get() or os.getcwd())
        if d:
            self.outdir_var.set(d)
            if not self.parse_src_var.get() or self.parse_src_var.get() == self.outdir_var.get():
                self.parse_src_var.set(d)

    def browse_parse_src(self):
        d = filedialog.askdirectory(initialdir=self.parse_src_var.get() or os.getcwd())
        if d:
            self.parse_src_var.set(d)

    def browse_csv_out(self):
        f = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV files', '*.csv')], initialfile=self.csv_out_var.get())
        if f:
            self.csv_out_var.set(f)
            self.mapping_var.set(f)

    def browse_mapping(self):
        f = filedialog.askopenfilename(filetypes=[('CSV files', '*.csv'), ('All files', '*.*')], initialfile=self.mapping_var.get())
        if f:
            self.mapping_var.set(f)

    def browse_csv_dir(self):
        d = filedialog.askdirectory(initialdir=self.csv_dir_var.get() or os.getcwd())
        if d:
            self.csv_dir_var.set(d)

    def browse_out_csv_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_csv_dir_var.get() or os.getcwd())
        if d:
            self.out_csv_dir_var.set(d)

    def browse_mss_root(self):
        d = filedialog.askdirectory(initialdir=self.mss_root_var.get() or os.getcwd())
        if d:
            self.mss_root_var.set(d)

    def browse_third_script(self):
        f = filedialog.askopenfilename(filetypes=[('Python files', '*.py'), ('All files', '*.*')])
        if f:
            self.third_script_var.set(f)

    def log_fn(self, msg):
        self.log.configure(state='normal')
        self.log.insert('end', msg + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    # Threaded actions
    def start_fetch(self):
        t = threading.Thread(target=self._fetch_thread, daemon=True)
        t.start()

    def _fetch_thread(self):
        owner = self.owner_var.get().strip()
        repo = self.repo_var.get().strip()
        subpath = self.subpath_var.get().strip()
        outdir = self.outdir_var.get().strip()
        token = self.token_var.get().strip() or None
        if not subpath:
            self.log_fn("Subpath is required.")
            return
        self.log_fn(f"Starting update fetch: {owner}/{repo} -> {outdir} (subpath: {subpath})")
        rc = fetch_dir(owner, repo, subpath, outdir, token, log_fn=self.log_fn)
        if rc == 0:
            self.log_fn("Update fetch completed.")
            self.parse_src_var.set(outdir)
        else:
            self.log_fn(f"Fetch finished with code {rc}.")

    def start_parse(self):
        t = threading.Thread(target=self._parse_thread, daemon=True)
        t.start()

    def _parse_thread(self):
        src = self.parse_src_var.get().strip()
        out = self.csv_out_var.get().strip()
        if not src or not out:
            self.log_fn("Source folder and output CSV must be set.")
            return
        self.log_fn(f"Parsing folder {src} -> {out}")
        rc = parse_folder_to_csv(src, out, log_fn=self.log_fn)
        if rc == 0:
            self.log_fn("Parse completed.")
            self.mapping_var.set(out)
        else:
            self.log_fn(f"Parse finished with code {rc}.")

    def start_integrated_processing(self):
        t = threading.Thread(target=self._integrated_processing_thread, daemon=True)
        t.start()

    def _integrated_processing_thread(self):
        mapping = self.mapping_var.get().strip()
        csv_dir = self.csv_dir_var.get().strip()
        out_dir = self.out_csv_dir_var.get().strip() or None
        mss_root = self.mss_root_var.get().strip() or None
        dry_run = bool(self.dry_run_var.get())
        verbose = bool(self.verbose_var.get())
        if not mapping or not csv_dir:
            self.log_fn("Mapping CSV and CSV directory must be set.")
            return
        self.log_fn(f"Running integrated processing: mapping={mapping} csv_dir={csv_dir} out_dir={out_dir} dry_run={dry_run}")
        rc = run_third_processing(mapping, csv_dir, out_dir, mss_root, dry_run, verbose, log_fn=self.log_fn)
        if rc == 0:
            self.log_fn("Integrated processing completed.")
        else:
            self.log_fn(f"Integrated processing finished with code {rc}.")

    def start_run_third(self):
        t = threading.Thread(target=self._run_third_thread, daemon=True)
        t.start()

    def _run_third_thread(self):
        script = self.third_script_var.get().strip()
        if not script or not os.path.isfile(script):
            self.log_fn("No third script selected or file does not exist.")
            return
        env = os.environ.copy()
        env['QTD_SRC'] = self.parse_src_var.get().strip()
        env['QTD_CSV'] = self.csv_out_var.get().strip()
        self.log_fn(f"Running third script: {script}")
        try:
            import subprocess
            proc = subprocess.Popen([sys.executable, script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
            for line in proc.stdout:
                self.log_fn(line.rstrip())
            proc.wait()
            self.log_fn(f"Third script exited with code {proc.returncode}")
        except Exception as e:
            self.log_fn(f"Failed to run third script: {e}")


def main():
    root = tk.Tk()
    app = App(root)
    root.geometry('1000x700')
    root.mainloop()


if __name__ == '__main__':
    main()

