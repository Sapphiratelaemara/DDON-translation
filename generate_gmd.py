import re
from pathlib import Path
from datetime import datetime

# Define the pattern for a date in format dd/mm/yy
DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b")

def replace_dates_in_csv():
    """Find and replace dates in Fully Translated/104.csv with the current date."""
    file_path = Path("Fully Translated/104.csv")
    if not file_path.exists():
        print(f"File {file_path} not found. Skipping modification.")
        return

    # Get the current date in dd/mm/yy format
    current_date = datetime.now().strftime("%d/%m/%y")

    # Read the file content
    lines = file_path.read_text(encoding='utf-8').splitlines()
    modified = False

    # Replace dates wherever they occur
    for i, line in enumerate(lines):
        if DATE_PATTERN.search(line):
            lines[i] = DATE_PATTERN.sub(current_date, line)
            modified = True

    # Write back changes if any modifications were made
    if modified:
        file_path.write_text("\n".join(lines), encoding='utf-8')
        print(f"Updated dates in {file_path} to {current_date}")
    else:
        print(f"No matching dates found in {file_path}. No changes made.")

def main():
    replace_dates_in_csv()

if __name__ == "__main__":
    main()
