import sys
import re
import os

# Regex to capture: "KEY": "VALUE"
pattern = re.compile(r'^\s*"([^"]+)"\s*:\s*"([^"]+)"')

def main():
    if len(sys.argv) < 2:
        print("Drag a text file onto this script.")
        return

    infile = sys.argv[1]
    outfile = os.path.splitext(infile)[0] + "_lengths.txt"

    with open(infile, "r", encoding="utf-8") as f, \
         open(outfile, "w", encoding="utf-8") as out:

        for line in f:
            m = pattern.match(line)
            if not m:
                continue

            key = m.group(1)
            value = m.group(2)

            length = len(value)

            out.write(f"\"{key}\": {length},\n")

    print(f"Done. Output written to: {outfile}")

if __name__ == "__main__":
    main()