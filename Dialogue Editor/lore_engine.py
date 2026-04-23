import os
import csv
import re
import json
import urllib.request
import urllib.error
import threading
import time

from lore_data import DEFAULT_ARCHETYPES, IN_UNIVERSE_VOCAB, ANACHRONISM_PATTERNS, DD1_VOCAB

# Track files written by app for cache invalidation
_recently_written_files = {}

def mark_file_written(file_path):
    """Mark a file as recently written by the app (to avoid cache invalidation)."""
    _recently_written_files[file_path] = time.time()

def should_invalidate_cache(file_path, cache_timestamp):
    """Check if cache should be invalidated based on file modification time."""
    if not os.path.exists(file_path):
        return True
    file_mtime = os.path.getmtime(file_path)
    last_write = _recently_written_files.get(file_path, 0)
    # Invalidate if file was modified externally (after cache and not by us)
    return file_mtime > cache_timestamp and file_mtime > last_write

class LoreEngine:
    def __init__(self, config_archetypes=None):
        # Use config archetypes if provided, else seed from defaults
        if config_archetypes:
            self.archetypes = config_archetypes
        else:
            self.archetypes = dict(DEFAULT_ARCHETYPES)
        # Invalidate the compiled pattern so any vocab changes take effect this session
        LoreEngine._ANACH_PATTERN = None
        LoreEngine._ANACH_KEYS    = None
        self.lore_map = {
            "剛化": "Harden",
            "重化": "Heavy",
            "癒活": "Restoration",
            "守護": "Protection",
            "柔化": "Weaken",
            "集視": "Attraction",
            "無恐": "Fearless",
            "集中": "Concentration",
            "蘇生": "Resurrection"
        }
        # Track cache timestamps for glossary/lore files
        self._cache_timestamps = {}

    def load_data(self, bible_path, glossary_path):
        for path in [bible_path, glossary_path]:
            if not path or not os.path.exists(path):
                continue
            # Check if file was modified externally since last load
            if path in self._cache_timestamps:
                if not should_invalidate_cache(path, self._cache_timestamps[path]):
                    continue  # Skip reload if file not modified externally
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    content = f.read(1024)
                    f.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(content) if ',' in content or '\t' in content else 'excel'
                    except csv.Error:
                        dialect = 'excel'

                    reader = csv.reader(f, dialect=dialect)
                    for row in reader:
                        if len(row) >= 1 and row[0].strip():
                            jp = row[0].strip()
                            en = row[1].strip() if len(row) >= 2 else ""
                            # Column 5 (Description [ja]) often contains additional suggestions
                            desc = row[5].strip() if len(row) >= 6 else ""
                            
                            parts = []
                            if en: parts.append(en)
                            if desc and desc != en: parts.append(desc)
                            
                            if parts:
                                # Join with a distinct separator for internal use
                                self.lore_map[jp] = " | ".join(parts)
                # Update cache timestamp after successful load
                self._cache_timestamps[path] = time.time()
                # Import and clear gloss cache since lore_map changed
                try:
                    import main
                    with main._gloss_cache_lock:
                        main._gloss_cache.clear()
                except Exception:
                    pass  # Main module may not be available in all contexts
            except Exception as e:
                print(f"Lore Engine Error on {path}: {e}")

    def scan_text(self, jp_text):
        if not jp_text: return []
        matches = []
        for jp_term, en_term in self.lore_map.items():
            if jp_term in jp_text:
                matches.append((jp_term, en_term))
        return matches

    # ---------------- Archetype Handling ----------------
    def get_archetype_options(self):
        """Return (key, name) pairs for dropdown without professions."""
        return [(key, data["name"]) for key, data in self.archetypes.items()]

    def get_archetype_label(self, key):
        if key not in self.archetypes:
            return "(none)"
        return self.archetypes[key]["name"]

    def get_archetype_hint_for_speaker(self, speaker_name):
        """Return notes for a speaker based on assigned archetype."""
        archetype_key = self.memory.get(speaker_name)
        if not archetype_key or archetype_key not in self.archetypes:
            return "(none)"
        return self.archetypes[archetype_key].get("notes", "")

    # ---------------- In-Universe Replacements ----------------
    def get_in_universe_replacements(self):
        # Handle both string and list values
        replacements = {}
        for k, v in IN_UNIVERSE_VOCAB.items():
            if v is not None:
                # If value is a list, use the first element (or could use random/last)
                if isinstance(v, list):
                    replacements[k] = v[0]
                else:
                    replacements[k] = v
        return replacements

    # Pre-compiled anachronism regex — built once per session, reset when vocab changes
    _ANACH_PATTERN = None
    _ANACH_KEYS    = None

    @classmethod
    def _build_anach_pattern(cls):
        if cls._ANACH_PATTERN is not None:
            return
        # Longest keys first so multi-word phrases match before single words
        sorted_keys = sorted(IN_UNIVERSE_VOCAB.keys(), key=lambda x: -len(x))
        parts = []
        for k in sorted_keys:
            if " " in k:
                # Add word boundaries for multi-word phrases too
                parts.append(r'\b' + re.escape(k) + r'\b')
            else:
                parts.append(r'\b' + re.escape(k) + r'\b')
        cls._ANACH_PATTERN = re.compile('|'.join(parts), re.IGNORECASE)
        cls._ANACH_KEYS    = sorted_keys

    def scan_anachronisms(self, en_text):
        if not en_text: return []
        # Force pattern rebuild to ensure new logic takes effect
        LoreEngine._ANACH_PATTERN = None
        self._build_anach_pattern()
        # Get all matches with their positions
        matches = []
        for m in self._ANACH_PATTERN.finditer(en_text):
            word = m.group(0)
            key = word.lower()
            matches.append((m.start(), m.end(), word, key))
        
        # Sort by position, then by length (longer first)
        matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        
        # Filter out matches that are contained within longer matches at the same position
        filtered = []
        for start, end, word, key in matches:
            # Check if this match is contained within any longer match at the same position
            is_contained = False
            for s, e, w, k in filtered:
                if start >= s and end <= e and (end - start) < (e - s):
                    is_contained = True
                    break
            if not is_contained:
                filtered.append((start, end, word, key))
        
        # Remove duplicates and return
        seen = set()
        unique = []
        for start, end, word, key in filtered:
            if key not in seen:
                seen.add(key)
                archaic_word = IN_UNIVERSE_VOCAB.get(key)
                # Handle list values - use first element
                if isinstance(archaic_word, list):
                    archaic_word = archaic_word[0]
                # Check if the archaic_word actually came from DD1_VOCAB (not just if key exists)
                # Compare the actual value to determine source
                dd1_value = DD1_VOCAB.get(key)
                if isinstance(dd1_value, list):
                    dd1_value = dd1_value[0]
                is_dd1 = (archaic_word == dd1_value)
                unique.append((word, archaic_word, is_dd1))
        return unique

    # ---------------- Definition Cache ----------------
    # Always resolve relative to this source file so it works regardless of working directory
    DEFINITIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anach_definitions.json")
    EXAMPLES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archaic_examples.json")

    @classmethod
    def _load_def_cache(cls):
        if os.path.exists(cls.DEFINITIONS_FILE):
            try:
                with open(cls.DEFINITIONS_FILE, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                    # Handle new nested structure with dd1_definitions and other_definitions
                    if isinstance(data, dict) and "dd1_definitions" in data:
                        definitions = {}
                        # Add dd1_definitions first (higher priority)
                        definitions.update(data.get("dd1_definitions", {}))
                        # Add other_definitions only if word not already in dd1_definitions
                        for word, definition in data.get("other_definitions", {}).items():
                            if word not in definitions:
                                definitions[word] = definition
                        return definitions
                    return data
            except Exception:
                pass
        return {}

    @classmethod
    def _save_def_cache(cls, cache):
        """Save definitions as strings only - no examples in this file."""
        try:
            # Load existing file to preserve structure
            if os.path.exists(cls.DEFINITIONS_FILE):
                with open(cls.DEFINITIONS_FILE, 'r', encoding='utf-8-sig') as f:
                    existing_data = json.load(f)
            else:
                existing_data = {}
            
            # Merge new cache entries into the appropriate sections
            dd1_defs = existing_data.get("dd1_definitions", {})
            other_defs = existing_data.get("other_definitions", {})
            
            for word, definition in cache.items():
                # Extract just the definition string if it's a tuple/list
                if isinstance(definition, (list, tuple)) and len(definition) > 0:
                    defn_str = definition[0] if definition[0] else ""
                elif isinstance(definition, str):
                    defn_str = definition
                else:
                    defn_str = str(definition)
                
                # Only save if we have a non-empty definition
                if defn_str:
                    if word in dd1_defs:
                        dd1_defs[word] = defn_str
                    else:
                        other_defs[word] = defn_str
            
            # Preserve structure with comments
            new_data = {
                "_comment": "Definitions sourced from Dragon's Dogma 1 dialogue (combined_output.csv)",
                "dd1_definitions": dd1_defs,
                "_comment2": "Definitions sourced from non-DD1 sources (API, manual curation, etc.)",
                "other_definitions": other_defs
            }
            
            with open(cls.DEFINITIONS_FILE, 'w', encoding='utf-8-sig') as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Definition cache save error: {e}")

    @classmethod
    def _load_examples(cls):
        """Load local examples database."""
        if os.path.exists(cls.EXAMPLES_FILE):
            try:
                with open(cls.EXAMPLES_FILE, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                    # Handle new nested structure with dd1_examples and other_examples
                    if isinstance(data, dict) and "dd1_examples" in data:
                        examples = {}
                        # Add dd1_examples first (higher priority)
                        examples.update(data.get("dd1_examples", {}))
                        # Add other_examples only if word not already in dd1_examples
                        for word, example in data.get("other_examples", {}).items():
                            if word not in examples:
                                examples[word] = example
                        return examples
                    return data
            except Exception:
                pass
        return {}

    @classmethod
    def get_definition(cls, word, callback=None):
        """Return cached (definition, example) tuple for word, or fetch it asynchronously.
        If callback is given, calls callback(word, (definition, example)) when fetch completes.
        Returns cached value immediately if available, else None."""
        cache = cls._load_def_cache()
        word_lower = word.lower()
        cached = cache.get(word_lower)
        if cached is not None:
            # Handle legacy string format (old cache) vs new tuple format
            if isinstance(cached, str):
                # Check if local database has an example for this word
                examples = cls._load_examples()
                if word_lower in examples and examples[word_lower]:
                    # Re-fetch to get the example from local database
                    if callback:
                        def _fetch():
                            defn = cls._fetch_definition(word_lower)
                            cache2 = cls._load_def_cache()
                            cache2[word_lower] = defn
                            cls._save_def_cache(cache2)
                            if callback:
                                callback(word, defn)
                        threading.Thread(target=_fetch, daemon=True).start()
                return None
            # Check if cached entry has no example but local database has one
            if isinstance(cached, list) and len(cached) == 2 and not cached[1]:
                examples = cls._load_examples()
                if word_lower in examples and examples[word_lower]:
                    # Re-fetch to get the example from local database
                    if callback:
                        def _fetch():
                            defn = cls._fetch_definition(word_lower)
                            cache2 = cls._load_def_cache()
                            cache2[word_lower] = defn
                            cls._save_def_cache(cache2)
                            if callback:
                                callback(word, defn)
                        threading.Thread(target=_fetch, daemon=True).start()
            return cached
        if callback:
            def _fetch():
                defn = cls._fetch_definition(word_lower)
                cache2 = cls._load_def_cache()
                cache2[word_lower] = defn
                cls._save_def_cache(cache2)
                if callback:
                    callback(word, defn)
            threading.Thread(target=_fetch, daemon=True).start()

    @classmethod
    def _fetch_definition(cls, word):
        """Fetch definition from local examples only. No external API calls."""
        # Check local examples only (DDON dialogue takes priority)
        examples = cls._load_examples()
        local_example = examples.get(word, "")
        if local_example:
            return ("", local_example)
        return ("", "")

    @classmethod
    def prefetch_definitions(cls, words):
        """Background-fetch definitions for a list of words, populating the cache."""
        def _run():
            cache = cls._load_def_cache()
            changed = False
            for w in words:
                wl = w.lower()
                # Only fetch for archaic words (values from IN_UNIVERSE_VOCAB), not modern triggers
                # Skip common modern words that are just triggers
                if wl in cache:
                    continue
                # Skip if it's a common modern word/contraction (heuristic check)
                if "'" in wl or wl in ["going", "to", "from", "for", "with", "without", "within"]:
                    continue
                defn = cls._fetch_definition(wl)
                cache[wl] = defn
                changed = True
            if changed:
                cls._save_def_cache(cache)
        threading.Thread(target=_run, daemon=True).start()

    def apply_in_universe(self, en_text):
        """Replace text where possible, flag-only terms returned separately."""
        replacements = self.get_in_universe_replacements()
        flags = []
        sorted_keys = sorted(IN_UNIVERSE_VOCAB.keys(), key=lambda x: -len(x))

        def replace_match(match):
            word = match.group(0)
            lower = word.lower()
            if lower in replacements:
                return replacements[lower]
            elif lower in IN_UNIVERSE_VOCAB and IN_UNIVERSE_VOCAB[lower] is None:
                flags.append(word)
            return word

        pattern = r'|'.join(
            r'\b' + re.escape(k) + r'\b' if " " in k else r'\b' + re.escape(k) + r'\b'
            for k in sorted_keys
        )
        new_text = re.sub(pattern, replace_match, en_text, flags=re.IGNORECASE)
        return new_text, flags