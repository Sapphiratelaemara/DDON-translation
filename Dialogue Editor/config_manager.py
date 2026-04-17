import json
import os
import threading

class ConfigManager:
    def __init__(self, config_file="formatter_config.json", memory_file="memory.json", keys_file="keys.json", cache_file="cache.json"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(base_dir, config_file)
        self.memory_file = os.path.join(base_dir, memory_file)
        self.keys_file = os.path.join(base_dir, keys_file)
        self.cache_file = os.path.join(base_dir, cache_file)
        self.memory = {} 
        self.keys = {}
        self.cache = {}
        self._lock = threading.RLock()
        self.config = self.load_all()
        self.memory = self.load_memory()
        self.keys = self.load_keys()
        self.cache = self.load_cache()
        # Seed archetypes from defaults if not already in config
        self._seed_archetypes()

    def _seed_archetypes(self):
        """Merge new archetypes from DEFAULT_ARCHETYPES into config."""
        try:
            from lore_engine import DEFAULT_ARCHETYPES
            # DEFAULT_ARCHETYPES is nested: {"archetypes": {key: {...}}}
            default_archs = DEFAULT_ARCHETYPES.get("archetypes", {})
            if "archetypes" not in self.config or not self.config["archetypes"]:
                self.config["archetypes"] = {
                    k: dict(v) for k, v in default_archs.items()
                }
            else:
                # Merge new archetypes from defaults without overwriting existing ones
                for key, value in default_archs.items():
                    if key not in self.config["archetypes"]:
                        self.config["archetypes"][key] = dict(value)
        except ImportError:
            if "archetypes" not in self.config:
                self.config["archetypes"] = {}

    def load_keys(self):
        """Load API keys from a separate file. Create with defaults if missing."""
        with self._lock:
            keys = {}
            if not os.path.exists(self.keys_file):
                # Create keys.json with default structure
                default_keys = {
                    "deepl_api_key": "insert your private key here",
                    "openrouter_api_key": "insert your private key here"
                }
                try:
                    with open(self.keys_file, 'w', encoding='utf-8') as f:
                        json.dump(default_keys, f, indent=4)
                    keys = default_keys
                except IOError as e:
                    print(f"Error creating keys file: {e}")
            else:
                try:
                    with open(self.keys_file, 'r', encoding='utf-8') as f:
                        keys = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            return keys

    def save_keys(self):
        """Save API keys to a separate file."""
        with self._lock:
            try:
                with open(self.keys_file, 'w', encoding='utf-8') as f:
                    json.dump(self.keys, f, indent=4)
            except IOError as e:
                print(f"Error saving keys: {e}")

    def get_key(self, service_name):
        return self.keys.get(service_name, "")

    def set_key(self, service_name, key_value):
        self.keys[service_name] = key_value
        self.save_keys()

    def load_cache(self):
        """Load API results from a persistent cache file."""
        with self._lock:
            cache = {}
            if os.path.exists(self.cache_file):
                try:
                    with open(self.cache_file, 'r', encoding='utf-8') as f:
                        cache = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            return cache

    def save_cache(self):
        """Save current cache to file."""
        with self._lock:
            try:
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, indent=4)
            except IOError as e:
                print(f"Error saving cache: {e}")

    def get_cached(self, service, query):
        """Retrieve a cached API result if exists and not expired (7 days)."""
        import time
        if service in self.cache:
            entry = self.cache[service].get(query)
            if entry and isinstance(entry, dict) and "result" in entry and "timestamp" in entry:
                # 7 days = 7 * 24 * 3600 = 604800 seconds
                if time.time() - entry["timestamp"] < 604800:
                    return entry["result"]
                else:
                    # Expired
                    del self.cache[service][query]
                    self.save_cache()
            elif entry and isinstance(entry, str):
                # Legacy cache support: upgrade to dict with current timestamp
                self.set_cached(service, query, entry)
                return entry
        return None

    def set_cached(self, service, query, result):
        """Save an API result to cache with current timestamp."""
        import time
        if service not in self.cache:
            self.cache[service] = {}
        self.cache[service][query] = {
            "result": result,
            "timestamp": time.time()
        }
        self.save_cache()

    def load_memory(self):
        with self._lock:
            mem = {}
            # Migrate from config if present
            if "memory" in self.config:
                mem = self.config.pop("memory")
                self.memory = mem 
                self.save_all() 
            
            if os.path.exists(self.memory_file):
                try:
                    with open(self.memory_file, 'r', encoding='utf-8') as f:
                        mem.update(json.load(f))
                except (json.JSONDecodeError, IOError):
                    pass
            return mem

    def save_memory(self):
        with self._lock:
            try:
                with open(self.memory_file, 'w', encoding='utf-8') as f:
                    json.dump(self.memory, f, indent=4)
            except IOError as e:
                print(f"Error saving memory: {e}")

    def load_all(self):
        with self._lock:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(base_dir)
            terms_dir = os.path.join(project_root, "Terms and references directory")
            default_bible = os.path.normpath(os.path.join(terms_dir, "DDON_BIBLE_V2.txt")).replace("\\", "/")
            default_glossary = os.path.normpath(os.path.join(terms_dir, "glossary.csv")).replace("\\", "/")
            default_assets = os.path.normpath(os.path.join(base_dir, "assets")).replace("\\", "/")

            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                        # Migration of keys to separate file
                        migrated = False
                        for k in ["deepl_api_key", "openrouter_api_key"]:
                            if k in data:
                                self.keys[k] = data.pop(k)
                                migrated = True
                        if migrated:
                            self.save_keys()

                        keys_defaults = {
                            "tag_map": {},
                            "tag_display": {},
                            "presets": {"Standard": 50},
                            "wall_presets": {"Standard": 7},
                            "folders": [],
                            "triggers": [],
                            "speaker_archetypes": {},
                            "speaker_notes": {},
                            "bible_path": default_bible,
                            "glossary_path": default_glossary,
                            "assets_path": default_assets,
                            "archetypes": {},
                            "entry_type_rules": {},
                            "replace_rules": [],
                            "substitution_rules": [],
                            "preview_font": {},
                            "deepl_target_lang": "EN-US",
                            "openrouter_models": ["openrouter/auto", "meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free"],
                            "selected_openrouter_model": "openrouter/auto",
                            "ai_system_prompt": "You are a Dragon's Dogma Online (DDON) localization assistant. You must strictly adhere to the 'Dragon's Dogma' localization style. This style uses Early Modern English & archaic vocabulary (e.g., 'tis, naught, aught, pray, afore, mayhap, forsooth, arise) and a formal medieval fantasy tone. Do not go overboard on the archaic language, it should sound natural in English. NEVER use modern slang, colloquialisms, or too many modern contractions (e.g., avoid 'okay', 'gonna', 'don't', 'can't'). CRITICAL RULES: Do NOT use any Japanese honorifics (e.g. -san, -sama, -dono). Use precise, proper English punctuation. Do NOT insert any blank lines or newlines in your response. Translate Japanese dashes as either an ellipsis (...) or a regular em dash (\u2014), when appropriate for the context. Help the user translate or refine dialogue while respecting these rules and the character archetypes. Do not add unnecessary quotation marks. Stay close to the original meaning, but rephrase it to sound more natural in English. Things within < and > are tags & should be preserved as-is.",
                            "ai_button_prompts": {
                                "translate": "Translate: {text}",
                                "rephrase": "Rephrase this: {text}",
                                "archaize": "Make this more archaic: {text}",
                                "check": "Check this for errors: {text}"
                            },
                            "custom_dark_theme": {},
                            "custom_light_theme": {},
                        }
                        for key, default in keys_defaults.items():
                            if key not in data:
                                data[key] = default
                            elif key in ["bible_path", "glossary_path", "assets_path"]:
                                # Always resolve to absolute, or overwrite with default if invalid
                                val = data[key]
                                if val:
                                    if not os.path.isabs(val):
                                        val = os.path.normpath(os.path.join(base_dir, val)).replace("\\", "/")
                                        data[key] = val
                                    if not os.path.exists(val):
                                        data[key] = default
                                else:
                                    data[key] = default
                        return data
                except (json.JSONDecodeError, IOError):
                    print("Config file corrupted, creating new one.")

            return {
                "tag_map": {},
                "tag_display": {},
                "presets": {"Standard": 50},
                "wall_presets": {"Standard": 7},
                "folders": [],
                "triggers": [],
                "bible_path": default_bible,
                "glossary_path": default_glossary,
                "assets_path": default_assets,
                "speaker_archetypes": {},
                "speaker_notes": {},
                "archetypes": {},
                "entry_type_rules": {},
                "replace_rules": [],
                "ai_system_prompt": "You are a Dragon's Dogma Online (DDON) localization assistant. You must strictly adhere to the 'Dragon's Dogma' localization style. This style uses Early Modern English & archaic vocabulary (e.g., 'tis, naught, aught, pray, afore, mayhap, forsooth, arise) and a formal medieval fantasy tone. Do not go overboard on the archaic language, it should sound natural in English. NEVER use modern slang, colloquialisms, or too many modern contractions (e.g., avoid 'okay', 'gonna', 'don't', 'can't'). CRITICAL RULES: Do NOT use any Japanese honorifics (e.g. -san, -sama, -dono). Use precise, proper English punctuation. Do NOT insert any blank lines or newlines in your response. Translate Japanese dashes as either an ellipsis (...) or a regular em dash (\u2014), when appropriate for the context. Help the user translate or refine dialogue while respecting these rules and the character archetypes. Do not add unnecessary quotation marks. Stay close to the original meaning, but rephrase it to sound more natural in English. Things within < and > are tags & should be preserved as-is.",
                "ai_button_prompts": {
                    "translate": "Translate: {text}",
                    "rephrase": "Rephrase this: {text}",
                    "archaize": "Make this more archaic: {text}",
                    "check": "Check this for errors: {text}"
                },
            }

    def save_all(self):
        with self._lock:
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    # Ensure we don't save keys into the main config
                    to_save = self.config.copy()
                    for k in ["deepl_api_key", "openrouter_api_key"]:
                        to_save.pop(k, None)
                    json.dump(to_save, f, indent=4)
            except IOError as e:
                print(f"Error saving config: {e}")
            self.save_memory()
            self.save_keys()
            self.save_cache()

    # Alias
    def save_config(self):
        self.save_all()

    # Alias
    def save_config(self):
        self.save_all()

    # --- Speaker assignment methods ---

    def set_speaker(self, key, speaker_name):
        """
        Assign a speaker and save immediately.
        key: a string identifier, e.g., 'last_selected_speaker'
        speaker_name: the speaker to assign
        """
        self.memory[key] = speaker_name
        self.save_all()

    def get_speaker(self, key):
        """
        Retrieve a speaker assignment. Returns None if not set.
        """
        return self.memory.get(key)

    def remove_speaker(self, key):
        """
        Remove a speaker assignment if exists.
        """
        if key in self.memory:
            del self.memory[key]
            self.save_all()
