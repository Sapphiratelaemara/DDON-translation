# lore_data.py — static data for lore_engine.py
# Edit vocab and archetypes here; the engine imports them automatically.

import os
import csv
import re
import json
import urllib.request
import urllib.error
import threading

# Load JSON data from data directory
def _load_json(filename, default=None):
    """Load JSON data from the data directory."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, 'data', filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
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
