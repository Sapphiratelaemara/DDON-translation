import csv
import sys
import os

def clean_csv(file_path):
    output_path = os.path.splitext(file_path)[0] + '_cleaned.csv'

    with open(file_path, 'r', encoding='utf-8', newline='') as infile, \
         open(output_path, 'w', encoding='utf-8', newline='') as outfile:
        
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

        for row in reader:
            cleaned_row = [field.replace('\n', ' ').replace('\r', ' ') for field in row]
            writer.writerow(cleaned_row)

    print(f"✅ Cleaned: {os.path.basename(file_path)} → {os.path.basename(output_path)}")

# === Entry Point ===
if __name__ == '__main__':
    if len(sys.argv) < 2:
        input("❗ Drag and drop one or more CSV files onto this script.\nPress Enter to exit...")
        sys.exit()

    for file in sys.argv[1:]:
        if file.lower().endswith('.csv') and os.path.isfile(file):
            clean_csv(file)
        else:
            print(f"❌ Skipping non-CSV file: {file}")

    input("\n✅ All done! Press Enter to exit.")
