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

# Load JSON data from language-specific config directory or fall back to data directory
def _load_json(filename, default=None):
    """Load JSON from language-specific config directory or fall back to data directory."""
    global _config_manager
    if _config_manager:
        try:
            config_dir = _config_manager.config.get('config_dir', '')
            if config_dir:
                json_path = os.path.join(config_dir, filename)
                if os.path.exists(json_path):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
        except Exception as e:
            print(f"[lore_data._load_json] Error loading {filename} from config: {e}")
    
    # Fall back to data directory
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    json_path = os.path.join(data_dir, filename)
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default or {}

# Load vocabularies at module import time
DD1_VOCAB = _load_json('dd1_vocab.json', {})
OTHER_VOCAB = _load_json('other_vocab.json', {})
IN_UNIVERSE_VOCAB = {**DD1_VOCAB, **OTHER_VOCAB}
ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())

def reload_vocab():
    """Reload vocab from ConfigManager after language switch."""
    global DD1_VOCAB, OTHER_VOCAB, IN_UNIVERSE_VOCAB, ANACHRONISM_PATTERNS
    DD1_VOCAB = _load_json('dd1_vocab.json', {})
    OTHER_VOCAB = _load_json('other_vocab.json', {})
    IN_UNIVERSE_VOCAB = {**DD1_VOCAB, **OTHER_VOCAB}
    ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())
    # Invalidate the cached pattern in lore_engine so it rebuilds with new vocab
    from src.lore_engine import LoreEngine
    LoreEngine._ANACH_PATTERN = None
    LoreEngine._ANACH_KEYS = None

# Default archetypes — loaded from JSON, seeded into config on first run, then editable from Options.
# Stored in config["archetypes"] as {key: {name, professions, notes, pawn_map}}.
DEFAULT_ARCHETYPES = _load_json('archetypes.json', {}).get('archetypes', {})
