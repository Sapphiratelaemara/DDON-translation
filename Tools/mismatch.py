import pandas as pd
import sys
import os

def process_files(original_file, comparison_file):
    # Read the CSV files into DataFrames
    original_df = pd.read_csv(original_file)
    comparison_df = pd.read_csv(comparison_file)

    # Ensure that required columns exist
    required_columns = ['MsgJp', 'Key', '#Index', 'GmdPath', 'ReadIndex']
    for col in required_columns:
        if col not in original_df.columns or col not in comparison_df.columns:
            raise ValueError(f"Column '{col}' is missing from one of the CSV files.")

    # Merge the original DataFrame with the comparison DataFrame on all key columns
    merged_df = pd.merge(original_df, comparison_df, on=required_columns, how='left', indicator=True)

    # Filter for rows that were not matched in the comparison DataFrame
    missing_entries = merged_df[merged_df['_merge'] == 'left_only']

    # Save the missing entries to a new CSV file
    missing_file = 'missing_entries.csv'
    missing_entries.to_csv(missing_file, index=False)

    # Print a message confirming the results
    total_entries = len(original_df)
    missing_count = len(missing_entries)

    print(f"Total entries processed: {total_entries}")
    if missing_count > 0:
        print(f'Missing entries saved to {missing_file}. Count: {missing_count}')
    else:
        print('No missing entries found.')

if __name__ == "__main__":
    # Check if the right number of arguments is provided
    if len(sys.argv) != 3:
        print("Usage: Drag and drop the original CSV file and the comparison CSV file onto this script.")
        input('Press Enter to exit...')
        sys.exit(1)

    # Get the file paths from the command line arguments
    original_file = sys.argv[1]
    comparison_file = sys.argv[2]

    # Check if files exist
    if not (os.path.isfile(original_file) and os.path.isfile(comparison_file)):
        print("One or both of the provided files do not exist. Please check the file paths.")
        input('Press Enter to exit...')
        sys.exit(1)

    # Process the files
    process_files(original_file, comparison_file)

    # Final confirmation message
    print("The script has finished executing.")
    input('Press Enter to exit...')
