#!/usr/bin/env python3
"""
Test script for pretranslate batch functionality
Tests rate limiting, error handling, and fallback behavior
"""

import sys
import os
import time
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_manager import ConfigManager
from translation_memory import TranslationMemory, FuzzyMatcher, AutoSubstitutor

def test_pretranslate_batch():
    """Test pretranslate batch with various scenarios"""
    print("[TEST] Starting pretranslate batch tests")
    
    # Initialize components
    cm = ConfigManager()
    cm.language = "en"
    
    # Test items
    test_items = [
        {"id": "1", "jp": "こんにちは", "file_path": "test.csv", "row_idx": 1, "speaker": "test", "entry_type": "dialogue"},
        {"id": "2", "jp": "こんにちは", "file_path": "test.csv", "row_idx": 2, "speaker": "test", "entry_type": "dialogue"},  # Duplicate - should use batch cache
        {"id": "3", "jp": "さようなら", "file_path": "test.csv", "row_idx": 3, "speaker": "test", "entry_type": "dialogue"},
        {"id": "4", "jp": "", "file_path": "test.csv", "row_idx": 4, "speaker": "test", "entry_type": "dialogue"},  # Empty - should be skipped
        {"id": "5", "jp": "ありがとう", "file_path": "test.csv", "row_idx": 5, "speaker": "test", "entry_type": "dialogue"},
    ]
    
    # Import the function from main
    import importlib
    main_module = importlib.import_module('main')
    
    print(f"[TEST] Testing {len(test_items)} items")
    start_time = time.time()
    
    try:
        # Test with no API keys (should only use TM)
        print("[TEST] Testing without API keys (TM only)")
        result = main_module.pretranslate_batch(test_items, tm_threshold=0.9, tm_min_quality="approved")
        
        print(f"[TEST] Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
        print(f"[TEST] Total time: {time.time() - start_time:.2f}s")
        
        # Verify results
        assert result["ok"] == True
        assert result["total"] == 5
        assert "results" in result
        
        # Check specific items
        for item_result in result["results"]:
            item_id = item_result["item_id"]
            if item_id == "4":  # Empty text
                assert item_result["success"] == False
                assert item_result["reason"] == "No JP text"
            else:
                # Non-empty items should have some result (even if no translation available)
                print(f"[TEST] Item {item_id}: success={item_result.get('success')}, source={item_result.get('source')}")
        
        print("[TEST] ✓ All tests passed")
        
    except Exception as e:
        print(f"[TEST] ✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def test_rate_limiting():
    """Test rate limiting behavior"""
    print("[TEST] Testing rate limiting")
    
    cm = ConfigManager()
    cm.language = "en"
    
    # Mock API keys to test rate limiting
    cm.user_settings["openrouter_api_key"] = "test_key"
    cm.user_settings["deepl_api_key"] = "test_key"
    
    # Test items that will require API calls
    test_items = [
        {"id": "1", "jp": "テストテストテスト", "file_path": "test.csv", "row_idx": 1, "speaker": "test", "entry_type": "dialogue"},
        {"id": "2", "jp": "テストテストテスト", "file_path": "test.csv", "row_idx": 2, "speaker": "test", "entry_type": "dialogue"},  # Duplicate
        {"id": "3", "jp": "ユニークテキスト", "file_path": "test.csv", "row_idx": 3, "speaker": "test", "entry_type": "dialogue"},
    ]
    
    import importlib
    main_module = importlib.import_module('main')
    
    start_time = time.time()
    
    try:
        # This should trigger rate limiting delays
        print("[TEST] Testing with mock API keys (should fail and test rate limiting)")
        result = main_module.pretranslate_batch(test_items, tm_threshold=0.9, tm_min_quality="approved")
        
        elapsed = time.time() - start_time
        print(f"[TEST] Completed in {elapsed:.2f}s")
        print(f"[TEST] Expected minimum time with rate limiting: ~5s for 2 API calls")
        
        # Should take at least 5 seconds due to rate limiting
        if elapsed < 4.5:
            print("[TEST] ⚠ Rate limiting may not be working (too fast)")
        else:
            print("[TEST] ✓ Rate limiting appears to be working")
        
    except Exception as e:
        print(f"[TEST] Rate limiting test error: {e}")
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("PRETRANSLATE BATCH TEST SUITE")
    print("=" * 60)
    
    # Run tests
    test_pretranslate_batch()
    print()
    test_rate_limiting()
    
    print()
    print("=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)
