import json
import os

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
        self.config = self.load_all()
        self.memory = self.load_memory()
        self.keys = self.load_keys()
        self.cache = self.load_cache()
        # Seed archetypes from defaults if not already in config
        self._seed_archetypes()

    def _seed_archetypes(self):
        """Populate config['archetypes'] from DEFAULT_ARCHETYPES if absent."""
        if "archetypes" not in self.config or not self.config["archetypes"]:
            try:
                from lore_engine import DEFAULT_ARCHETYPES
                self.config["archetypes"] = {
                    k: dict(v) for k, v in DEFAULT_ARCHETYPES.items()
                }
            except ImportError:
                self.config["archetypes"] = {}

    def load_keys(self):
        """Load API keys from a separate file."""
        keys = {}
        if os.path.exists(self.keys_file):
            try:
                with open(self.keys_file, 'r', encoding='utf-8') as f:
                    keys = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return keys

    def save_keys(self):
        """Save API keys to a separate file."""
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
        try:
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(self.memory, f, indent=4)
        except IOError as e:
            print(f"Error saving memory: {e}")

    def load_all(self):
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
                        "bible_path": "",
                        "glossary_path": "",
                        "archetypes": {},
                        "entry_type_rules": {},
                        "replace_rules": [],
                        "substitution_rules": [],
                        "preview_font": {},
                        "deepl_target_lang": "EN-US",
                        "openrouter_models": ["openrouter/auto", "meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free"],
                        "selected_openrouter_model": "openrouter/auto",
                    }
                    for key, default in keys_defaults.items():
                        if key not in data:
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
            "bible_path": "",
            "glossary_path": "",
            "speaker_archetypes": {},
            "speaker_notes": {},
            "archetypes": {},
            "entry_type_rules": {},
            "replace_rules": [],
        }

    def save_all(self):
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