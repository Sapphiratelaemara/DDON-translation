"""
Runtime hook to keep console open for debugging
"""
import sys
import os

# Keep console open on exit
def keep_console_open():
    if sys.platform == 'win32':
        input("Press Enter to close...")
    else:
        input("Press Enter to close...")

# Override sys.exit to keep console open
original_exit = sys.exit

def debug_exit(code=0):
    print(f"\nProgram exiting with code: {code}")
    keep_console_open()
    original_exit(code)

sys.exit = debug_exit

# Also handle uncaught exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    import traceback
    print("\n" + "="*50)
    print("UNCAUGHT EXCEPTION:")
    print("="*50)
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    print("="*50)
    keep_console_open()
    original_exit(1)

sys.excepthook = handle_exception
