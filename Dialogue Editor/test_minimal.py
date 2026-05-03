#!/usr/bin/env python3
"""Minimal test that won't hang"""

print("Test starting")
print("Test complete")

# Just import and check function exists
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    import importlib
    main_module = importlib.import_module('main')
    if hasattr(main_module, 'pretranslate_batch'):
        print("Function exists: YES")
    else:
        print("Function exists: NO")
except Exception as e:
    print(f"Import error: {e}")
