#!/usr/bin/env python3
"""Fetch .qtd.json files from a GitHub repo subpath into a local folder.

Usage:
  python Tools/fetch_qtd.py --owner ddon-research --repo ddon-data --subpath client/03040008/quest --out Tools/tmp_qtd

Notes: unauthenticated requests are rate-limited by GitHub. To use a token set env GITHUB_TOKEN.
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.parse

API_BASE = 'https://api.github.com/repos'
RAW_BASE = 'https://raw.githubusercontent.com'


def get_url(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.read()


def fetch_dir(owner, repo, subpath, outdir, token=None):
    headers = {'User-Agent': 'fetch-qtd-script'}
    if token:
        headers['Authorization'] = f'token {token}'

    api_url = f"{API_BASE}/{owner}/{repo}/contents/{urllib.parse.quote(subpath)}"
    try:
        raw = get_url(api_url, headers)
    except Exception as e:
        print('Failed to list', api_url, e)
        return 1

    items = json.loads(raw.decode('utf-8'))
    os.makedirs(outdir, exist_ok=True)

    for it in items:
        if it.get('type') == 'file':
            name = it.get('name','')
            if name.endswith('.qtd.json'):
                raw_url = f"{RAW_BASE}/{owner}/{repo}/main/{it['path']}"
                try:
                    data = get_url(raw_url, headers)
                except Exception as e:
                    print('Failed to download', raw_url, e)
                    continue
                out_path = os.path.join(outdir, name)
                with open(out_path, 'wb') as f:
                    f.write(data)
                print('Saved', out_path)
        elif it.get('type') == 'dir':
            # recurse into subdirectory
            sub = it.get('path')
            # strip leading path from outdir to keep flat structure per-file
            try:
                sub_items = json.loads(get_url(f"{API_BASE}/{owner}/{repo}/contents/{urllib.parse.quote(sub)}", headers).decode('utf-8'))
            except Exception as e:
                print('Failed to list', sub, e)
                continue
            for sit in sub_items:
                if sit.get('type') == 'file' and sit.get('name','').endswith('.qtd.json'):
                    raw_url = f"{RAW_BASE}/{owner}/{repo}/main/{sit['path']}"
                    try:
                        data = get_url(raw_url, headers)
                    except Exception as e:
                        print('Failed to download', raw_url, e)
                        continue
                    out_path = os.path.join(outdir, sit['name'])
                    with open(out_path, 'wb') as f:
                        f.write(data)
                    print('Saved', out_path)

    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--owner', default='ddon-research')
    p.add_argument('--repo', default='ddon-data')
    p.add_argument('--subpath', required=True)
    p.add_argument('--out', default='Tools/tmp_qtd')
    args = p.parse_args()
    token = os.environ.get('GITHUB_TOKEN')
    rc = fetch_dir(args.owner, args.repo, args.subpath, args.out, token)
    sys.exit(rc)


if __name__ == '__main__':
    main()
