#!/usr/bin/env python3

import sys
sys.path.append('.')
from src.config_manager import ConfigManager
from src.translator_engine import TranslationEngine

# Test the current tokenization with quoted tags
cm = ConfigManager(language='en')
engine = TranslationEngine(cm.config.get('tag_map', {}))

test_text = '"<NAME QUEST>"'
print('Input text:', repr(test_text))
print('Tokens:', engine._tokenise(test_text))

# Test wrapping
wrapped = engine.master_tag_wrap(test_text, 50)
print('Wrapped result:', repr(wrapped))
print('Wrapped lines:', wrapped.split('\n'))
