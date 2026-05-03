#!/usr/bin/env python3
"""Simple test to verify pretranslate function exists and basic imports work"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from config_manager import ConfigManager
    print("[OK] ConfigManager imported")
    
    cm = ConfigManager()
    print("[OK] ConfigManager initialized")
    
    # Check if pretranslate_batch function exists
    import importlib
    main_module = importlib.import_module('main')
    
    if hasattr(main_module, 'pretranslate_batch'):
        print("[OK] pretranslate_batch function exists")
        
        # Test with minimal data
        test_items = [
            {"id": "1", "jp": "test", "file_path": "test.csv", "row_idx": 1, "speaker": "test", "entry_type": "dialogue"}
        ]
        
        print("Testing pretranslate_batch with 1 item...")
        result = main_module.pretranslate_batch(test_items)
        
        if result and "ok" in result:
            print(f"[OK] Function executed successfully: {result.get('ok')}")
            print(f"  Total items: {result.get('total')}")
            print(f"  Results count: {len(result.get('results', []))}")
        else:
            print("[FAIL] Function returned invalid result")
            
    else:
        print("[FAIL] pretranslate_batch function not found")
        
except Exception as e:
    print(f"[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()

print("\nSimple test complete")
