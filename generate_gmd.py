import argparse
import re
from pathlib import Path

def numerical_sort_key(path):
    # Extract numbers from the file name
    name = path.name
    # Replace numbers with zero-padded versions for consistent sorting
    parts = re.split(r'(\d+)', name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]

def merge_splits(args):
    # Collect all splits
    splits = []
    for path in args.split_locations:
        directory = Path(path)
        for split in directory.glob("gmd_*.csv"):
            splits.append(split)

    if len(splits) == 0:
        print('No splits to merge. Exiting.')
        return

    # Sort splits so they are in numerical order
    splits = sorted(splits, key=numerical_sort_key)

    # Generate gmd.csv with ordered splits
    output_file = Path(f'{args.output_dir}/gmd.csv')
    with open(output_file, 'w', encoding='utf-8') as f:
        # Put the header at the top of the file
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
    if not output_path.exists():
        print(f'The given output path {output_path} does not exist. Exiting.')
        return None
    
    if not output_path.is_dir():
        print(f'The given output path {output_path} is not a directory. Exiting.')
        return None
    
    if len(args.split_locations) == 0:
        print('No split locations given. Exiting.')
        return None

    for split_dir in args.split_locations:
        split_path = Path(split_dir)
        if not split_path.exists() or not split_path.is_dir():
            print(f'The split path "{split_path}" does not exist or is not a directory. Exiting.')
            return
    
    return args

def main():
    args = parse_args()
    if args is None:
        return
    
    merge_splits(args)

if __name__ == '__main__':
    main()
