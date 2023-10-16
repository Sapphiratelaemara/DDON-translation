# silly little tool for converting toml files to csv, by Feld (https://github.com/Feldherren)
# if you have issues with it (this is far from perfect), just drop me a line. Or rewrite the thing yourself; I don't mind

import toml # non-default; install with pip install toml
import csv
import glob
import argparse
import os
from pathlib import Path

parser = argparse.ArgumentParser(prog='toml2yaml', description='Converts .toml files in specified location to .csv files')
parser.add_argument('src', help='Source folder of .toml files')
parser.add_argument('dst', help='Destination folder for .csv files')

args = parser.parse_args()

toml_files = glob.glob('**/*.toml', root_dir=args.src, recursive=True)

for toml_file in toml_files:
    # print(toml_file)
    # UTF-8-BOM is a blight that should not exist, but I don't want to have to change the encoding on 6000~ files so UTF-8-sig it is
    f = open(os.path.join(args.src, toml_file), "r", encoding='UTF-8-sig')
    try:
        f_dict = toml.load(f)
    except toml.decoder.TomlDecodeError:
        print(f'Error decoding {toml_file}; please handle it manually')
    # print(f_dict)

    # using pathlib.Path here lets us avoid needing to check if this folder exists first, or else get annoying errors
    Path(os.path.join(args.dst, os.path.dirname(toml_file))).mkdir(parents=True, exist_ok=True)

    with open(os.path.join(args.dst, os.path.splitext(toml_file)[0] + '.csv'), 'w', newline='', encoding='UTF-8') as csvfile:
        fieldnames = []
        for header in f_dict:
            for d in f_dict[header]:
                print(d)
                print(toml_file)
                # note: this is allergic to 'default_format = {...}' as a first line, and will throw an exception, 
                # but it'll also stop right after it reports the file so finding the thing and fixing it should be easy
                # copes perfectly fine with format fields for items proper, though
                for k in d.keys():
                    if k not in fieldnames:
                        fieldnames.append(k)

        # fieldnames = ['key', 'old', 'new']

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for header in f_dict:
            for d in f_dict[header]:
                writer.writerow(d)