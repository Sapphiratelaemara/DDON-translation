#!/usr/bin/env python3
"""Test pretranslate_batch with timeout using threading pattern"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_pretranslate_with_timeout():
    """Test pretranslate_batch with 30 second timeout"""
    print("[TEST] Starting pretranslate test with 30s timeout")
    
    result_container = [None]
    error_container = [None]
    
    def _run_test():
        try:
            import importlib
            main_module = importlib.import_module('main')
            
            test_items = [
                {"id": "1", "jp": "test", "file_path": "test.csv", "row_idx": 1, "speaker": "test", "entry_type": "dialogue"}
            ]
            
            result = main_module.pretranslate_batch(test_items)
            result_container[0] = result
        except Exception as e:
            error_container[0] = e
    
    thread = threading.Thread(target=_run_test, daemon=True)
    thread.start()
    thread.join(timeout=30.0)  # 30 second timeout
    
    if thread.is_alive():
        print("[TEST] TIMEOUT after 30s - test failed")
        return False
    
    if error_container[0]:
        print(f"[TEST] ERROR: {error_container[0]}")
        return False
    
    if result_container[0]:
        print(f"[TEST] SUCCESS: {result_container[0]}")
        return True
    
    print("[TEST] NO RESULT")
    return False

if __name__ == "__main__":
    success = test_pretranslate_with_timeout()
    sys.exit(0 if success else 1)
