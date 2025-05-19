import csv
import os
import sys

# CONFIGURATION
min_length = 5       # Set to None to disable min check
max_length = 40      # Set to None to disable max check
output_filename = 'length_violations.txt'

def main(input_filepath):
    if not os.path.isfile(input_filepath):
        print("❌ Error: File not found.")
        input("Press Enter to exit...")
        return

    output_path = os.path.join(os.path.dirname(input_filepath), output_filename)

    try:
        with open(input_filepath, 'r', encoding='utf-8-sig') as infile, \
             open(output_path, 'w', encoding='utf-8') as outfile:

            reader = csv.reader(infile)
            violations_found = False

            for line_num, row in enumerate(reader, start=1):
                if len(row) < 4:
                    continue  # Skip malformed rows

                field = row[3]
                length = len(field)

                if ((min_length is not None and length < min_length) or
                    (max_length is not None and length > max_length)):
                    violations_found = True
                    outfile.write(
                        f"Line {line_num} violates limit "
                        f"({length} chars):\n{','.join(row)}\n\n"
                    )

            if not violations_found:
                outfile.write("No violations found.\n")

        print(f"\n✅ Done. Results saved to:\n{output_path}")
    except Exception as e:
        print(f"❌ Error during processing: {e}")

    input("\nPress Enter to close...")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("📂 Drag and drop a text file onto this script.")
        input("Press Enter to exit...")
    else:
        main(sys.argv[1])
