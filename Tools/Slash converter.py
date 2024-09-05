import sys
import os

def replace_backslashes_in_csv(file_path):
    # Check if the file is a CSV file
    if not file_path.lower().endswith('.csv'):
        print(f"Error: {file_path} is not a CSV file.")
        return
    
    try:
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()

        # Replace all backslashes with forward slashes
        content = content.replace('\\', '/')

        # Write the updated content back to the file
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)

        print(f"Successfully replaced backslashes in {file_path}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Process each file dragged onto the script
        for file_path in sys.argv[1:]:
            replace_backslashes_in_csv(file_path)
    else:
        print("Please drag and drop a CSV file onto the script.")
