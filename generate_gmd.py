import argparse
import re
from pathlib import Path

# Define forbidden symbol replacements
FORBIDDEN_SYMBOLS = {
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "~": "～"
}

def replace_forbidden_symbols(file_path):
    """Replace forbidden symbols in the file's content."""
    content = file_path.read_text(encoding='utf-8')
    for old_symbol, new_symbol in FORBIDDEN_SYMBOLS.items():
        content = content.replace(old_symbol, new_symbol)
    file_path.write_text(content, encoding='utf-8')

def numerical_sort_key(path):
    # Extract numbers from the file name
    name = path.name
    parts = re.split(r'(\d+)', name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]

def clean_files(args):
    """Go through all splits and replace forbidden symbols."""
    for path in args.split_locations:
        directory = Path(path)
        for file in directory.glob("*.csv"):
            replace_forbidden_symbols(file)

def merge_splits(args):
    """Merge split CSV files into gmd.csv after cleaning."""
    splits = []
    for path in args.split_locations:
        directory = Path(path)
        for split in directory.glob("*.csv"):
            splits.append(split)

    if not splits:
        print('No splits to merge. Exiting.')
        return

    splits = sorted(splits, key=numerical_sort_key)

    output_file = Path(args.output_dir) / "gmd.csv"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("#Index,Key,MsgJp,MsgEn,GmdPath,ArcPath,ArcName,ReadIndex\n")
        for split in splits:
            content = split.read_text(encoding='utf-8')
            f.write(content)

    print(f'Generated {output_file}')

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--output_dir', default='.', help='Controls where gmd.csv will be written to')
    parser.add_argument('split_locations', nargs='+', type=str, help='List of directories to find splits')

    args = parser.parse_args()

    output_path = Path(args.output_dir)
    if not output_path.exists() or not output_path.is_dir():
        print(f'Invalid output path: {output_path}. Exiting.')
        return None
    
    for split_dir in args.split_locations:
        split_path = Path(split_dir)
        if not split_path.exists() or not split_path.is_dir():
            print(f'Invalid split path: {split_path}. Exiting.')
            return None

    return args

def main():
    args = parse_args()
    if args is None:
        return
    
    clean_files(args)  # First, clean the files by replacing forbidden symbols
    merge_splits(args)  # Then, merge the files

if __name__ == '__main__':
    main()
