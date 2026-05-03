#!/usr/bin/env python3

import sys
sys.path.append('.')
from src.config_manager import ConfigManager
from src.translator_engine import TranslationEngine

# Test wrapping with quoted tags at different limits
cm = ConfigManager(language='en')
engine = TranslationEngine(cm.config.get('tag_map', {}))

test_cases = [
    ('"<NAME QUEST>"', 50),
    ('This is some text before "<NAME QUEST>" and after', 30),
    ('"<NAME QUEST>" "<PAWN_NAME>" "<STG 1>"', 40),
]

for test_text, limit in test_cases:
    print(f'Test: {repr(test_text)} at limit {limit}')
    print('Tokens:', engine._tokenise(test_text))
    
    wrapped = engine.master_tag_wrap(test_text, limit)
    print('Wrapped:', repr(wrapped))
    print('Lines:', wrapped.split('\n'))
    
    # Check each line's simulated length
    for i, line in enumerate(wrapped.split('\n')):
        line_len = engine.get_simulated_len(line)
        print(f'  Line {i+1}: {repr(line)} (len: {line_len})')
    print()
