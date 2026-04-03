import os
import csv
import re
import json
import urllib.request
import urllib.error
import threading

from lore_data import DEFAULT_ARCHETYPES, IN_UNIVERSE_VOCAB, ANACHRONISM_PATTERNS

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
            "集視": "Attention",
            "無恐": "Fearless",
            "集中": "Concentration",
            "蘇生": "Resurrection"
        }

    def load_data(self, bible_path, glossary_path):
        for path in [bible_path, glossary_path]:
            if not path or not os.path.exists(path):
                continue
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
                        if len(row) >= 2 and row[0].strip():
                            self.lore_map[row[0].strip()] = row[1].strip()
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
        return {k: v for k, v in IN_UNIVERSE_VOCAB.items() if v is not None}

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
                parts.append(re.escape(k))
            else:
                parts.append(r'\b' + re.escape(k) + r'\b')
        cls._ANACH_PATTERN = re.compile('|'.join(parts), re.IGNORECASE)
        cls._ANACH_KEYS    = sorted_keys

    def scan_anachronisms(self, en_text):
        if not en_text: return []
        self._build_anach_pattern()
        seen = set()
        unique = []
        for m in self._ANACH_PATTERN.finditer(en_text):
            word = m.group(0)
            key  = word.lower()
            if key not in seen:
                seen.add(key)
                unique.append((word, IN_UNIVERSE_VOCAB.get(key)))
        return unique

    # ---------------- Definition Cache ----------------
    # Always resolve relative to this source file so it works regardless of working directory
    DEFINITIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anach_definitions.json")

    @classmethod
    def _load_def_cache(cls):
        if os.path.exists(cls.DEFINITIONS_FILE):
            try:
                with open(cls.DEFINITIONS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @classmethod
    def _save_def_cache(cls, cache):
        try:
            with open(cls.DEFINITIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Definition cache save error: {e}")

    @classmethod
    def get_definition(cls, word, callback=None):
        """Return cached short definition for word, or fetch it asynchronously.
        If callback is given, calls callback(word, definition) when fetch completes.
        Returns cached value immediately if available, else None."""
        cache = cls._load_def_cache()
        word_lower = word.lower()
        if word_lower in cache:
            return cache[word_lower]
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

    @classmethod
    def _fetch_definition(cls, word):
        """Fetch short definition from Free Dictionary API. Returns string or empty str."""
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.request.quote(word)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'DDON-tool/1.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                # Walk to first short definition
                for entry in data:
                    for meaning in entry.get('meanings', []):
                        for defn in meaning.get('definitions', []):
                            d = defn.get('definition', '').strip()
                            if d:
                                # Truncate to ~80 chars
                                return d if len(d) <= 80 else d[:77] + '...'
        except Exception:
            pass
        return ""

    @classmethod
    def prefetch_definitions(cls, words):
        """Background-fetch definitions for a list of words, populating the cache."""
        def _run():
            cache = cls._load_def_cache()
            changed = False
            for w in words:
                wl = w.lower()
                if wl not in cache:
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
            re.escape(k) if " " in k else r'\b' + re.escape(k) + r'\b'
            for k in sorted_keys
        )
        new_text = re.sub(pattern, replace_match, en_text, flags=re.IGNORECASE)
        return new_text, flags