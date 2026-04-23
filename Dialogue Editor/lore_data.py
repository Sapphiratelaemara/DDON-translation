# lore_data.py — static data for lore_engine.py
# Edit vocab and archetypes here; the engine imports them automatically.

import os
import csv
import re
import json
import urllib.request
import urllib.error
import threading

# Global config manager reference (set by main.py)
_config_manager = None

def set_config_manager(cm):
    """Set the ConfigManager instance for loading language-specific data."""
    global _config_manager
    _config_manager = cm

def reload_vocab():
    """Reload vocab from ConfigManager after language switch."""
    global DD1_VOCAB, OTHER_VOCAB, IN_UNIVERSE_VOCAB, ANACHRONISM_PATTERNS
    DD1_VOCAB = _load_json('dd1_vocab.json', {})
    OTHER_VOCAB = _load_json('other_vocab.json', {})
    IN_UNIVERSE_VOCAB = {**DD1_VOCAB, **OTHER_VOCAB}
    ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())

# Load JSON data from language-specific config directory
def _load_json(filename, default=None):
    """Load JSON from language-specific config directory or fall back to data directory."""
    global _config_manager
    if _config_manager:
        # Try loading from language-specific config directory
        lang_vocab = _config_manager.dd1_vocab if filename == 'dd1_vocab.json' else _config_manager.other_vocab
        if lang_vocab:
            return lang_vocab
    
    # Fallback to config/en/ for backward compatibility (templates)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, 'config', 'en', filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    
    return default if default is not None else {}

# Default archetypes — loaded from JSON, seeded into config on first run, then editable from Options.
# Stored in config["archetypes"] as {key: {name, professions, notes, pawn_map}}.
DEFAULT_ARCHETYPES = _load_json('archetypes.json', {}).get('archetypes', {})

# DD-sourced words (loaded from JSON, with inline defaults)
DD1_VOCAB = _load_json('dd1_vocab.json', {})

# Non-DD sourced archaic words (loaded from JSON, with inline defaults)
OTHER_VOCAB = _load_json('other_vocab.json', {})
# Merge both vocabularies for the full replacement list
IN_UNIVERSE_VOCAB = {**DD1_VOCAB, **OTHER_VOCAB}

ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())
