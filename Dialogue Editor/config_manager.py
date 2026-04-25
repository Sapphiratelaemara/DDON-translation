import json
import os
import threading
import logging

# Debug logging
DEBUG_ENABLED = True
logger = logging.getLogger('DDON_Editor.ConfigManager')

def debug_log(message, level='DEBUG'):
    """Log debug message."""
    if not DEBUG_ENABLED:
        return
    log_func = getattr(logger, level.lower(), logger.debug)
    log_func(message)

class ConfigManager:
    def __init__(self, config_file="formatter_config.json", memory_file="memory.json", keys_file="keys.json", cache_file="cache.json", user_settings_file="user_settings.json", language="en"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = base_dir
        self.language = language
        config_dir = os.path.join(base_dir, "config", language)
        data_dir = os.path.join(base_dir, "data")
        
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        
        self.config_file = os.path.join(config_dir, config_file)
        self.memory_file = os.path.join(config_dir, memory_file)
        self.user_settings_file = os.path.join(config_dir, user_settings_file)
        self.keys_file = os.path.join(base_dir, keys_file)
        self.cache_file = os.path.join(config_dir, cache_file)
        
        # Language-specific data files
        self.archetypes_file = os.path.join(config_dir, "archetypes.json")
        self.dd1_vocab_file = os.path.join(config_dir, "dd1_vocab.json")
        self.other_vocab_file = os.path.join(config_dir, "other_vocab.json")
        
        self.memory = {}
        self.keys = {}
        self.cache = {}
        self.user_settings = {}
        self.archetypes = {}
        self.dd1_vocab = {}
        self.other_vocab = {}
        self._lock = threading.RLock()
        self.config = self.load_all()
        self.memory = self.load_memory()
        self.keys = self.load_keys()
        self.cache = self.load_cache()
        self.user_settings = self.load_user_settings()
        self.archetypes = self.load_archetypes()
        self.dd1_vocab = self.load_vocab(self.dd1_vocab_file, {})
        self.other_vocab = self.load_vocab(self.other_vocab_file, {})
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

    def load_user_settings(self):
        """Load user-specific settings from a separate file."""
        debug_log(f"Loading user_settings from: {self.user_settings_file}")
        with self._lock:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(base_dir)
            terms_dir = os.path.join(project_root, "Terms and references directory")
            default_bible = os.path.normpath(os.path.join(terms_dir, "DDON_BIBLE_V2.txt")).replace("\\", "/")
            default_glossary = os.path.normpath(os.path.join(terms_dir, "glossary.csv")).replace("\\", "/")
            default_assets = os.path.normpath(os.path.join(base_dir, "assets")).replace("\\", "/")

            user_settings = {}
            if os.path.exists(self.user_settings_file):
                try:
                    with open(self.user_settings_file, 'r', encoding='utf-8') as f:
                        user_settings = json.load(f)
                    debug_log(f"Loaded user_settings with {len(user_settings)} keys")
                except (json.JSONDecodeError, IOError) as e:
                    debug_log(f"Failed to load user_settings: {e}", level='ERROR')
                    pass
            
            # Ensure speaker_archetypes and speaker_notes exist
            if "speaker_archetypes" not in user_settings:
                user_settings["speaker_archetypes"] = {}
                debug_log("Initialized speaker_archetypes in user_settings")
            if "speaker_notes" not in user_settings:
                user_settings["speaker_notes"] = {}
                debug_log("Initialized speaker_notes in user_settings")
            
            # Migrate github_token from keys.json if not in user_settings
            if "github_token" not in user_settings or user_settings["github_token"] is None:
                github_token = self.get_key("github_token")
                if github_token and github_token != "insert your private key here":
                    user_settings["github_token"] = github_token
                    # Remove from keys.json after migration
                    if "github_token" in self.keys:
                        del self.keys["github_token"]
                        self.save_keys()
                    # Save user_settings with migrated token
                    self.save_user_settings()
            
            # Migrate github_repo and sync_nickname from config.json if not in user_settings
            # These may have been stored in the main config before being moved to user_settings
            if "github_repo" not in user_settings or user_settings["github_repo"] is None:
                if "github_repo" in self.config and self.config["github_repo"]:
                    user_settings["github_repo"] = self.config["github_repo"]
                    del self.config["github_repo"]
                    self.save_all()
                    self.save_user_settings()
            
            if "sync_nickname" not in user_settings or user_settings["sync_nickname"] is None:
                if "sync_nickname" in self.config and self.config["sync_nickname"]:
                    user_settings["sync_nickname"] = self.config["sync_nickname"]
                    del self.config["sync_nickname"]
                    self.save_all()
                    self.save_user_settings()

            # Set defaults for user-specific settings
            defaults = {
                "folders": [],
                "bible_path": default_bible,
                "glossary_path": default_glossary,
                "assets_path": default_assets,
                "theme_mode": "dark",
                "dark_mode": True,
                "in_universe": True,
                "openrouter_models": ["openrouter/auto", "meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free"],
                "selected_openrouter_model": "openrouter/auto",
                "preview_mode": True,
                "show_paid_models": False,
                "selected_preset": "Dialogue Box",
                "custom_dark_theme": {},
                "custom_light_theme": {},
                "last_stats": {"total": 0, "translated": 0, "percent": 0},
                "github_repo": None,
                "github_token": None,
                "sync_nickname": None,
                "sync_auto": False
            }

            for key, default in defaults.items():
                if key not in user_settings:
                    user_settings[key] = default
                elif key in ["bible_path", "glossary_path", "assets_path"]:
                    # Only resolve to absolute if not empty; don't override empty strings with defaults
                    val = user_settings[key]
                    if val:  # Only process if not empty string
                        if not os.path.isabs(val):
                            val = os.path.normpath(os.path.join(base_dir, val)).replace("\\", "/")
                            user_settings[key] = val
                        # Don't override with default if path doesn't exist - user may have intentionally set it
                    # If val is empty string, keep it empty (don't apply default)

            return user_settings

    def save_user_settings(self):
        """Save user-specific settings to a separate file."""
        with self._lock:
            try:
                with open(self.user_settings_file, 'w', encoding='utf-8') as f:
                    json.dump(self.user_settings, f, indent=4)
                print(f"[DEBUG] Saved user_settings to {self.user_settings_file}")
            except IOError as e:
                print(f"Error saving user settings: {e}")

    def load_archetypes(self):
        """Load archetypes from language-specific file."""
        with self._lock:
            archetypes = {}
            if os.path.exists(self.archetypes_file):
                try:
                    with open(self.archetypes_file, 'r', encoding='utf-8') as f:
                        archetypes = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            return archetypes

    def save_archetypes(self):
        """Save archetypes to language-specific file."""
        with self._lock:
            try:
                with open(self.archetypes_file, 'w', encoding='utf-8') as f:
                    json.dump(self.archetypes, f, indent=4)
            except IOError as e:
                print(f"Error saving archetypes: {e}")

    def load_vocab(self, vocab_file, default):
        """Load vocab from language-specific file."""
        with self._lock:
            vocab = {}
            if os.path.exists(vocab_file):
                try:
                    with open(vocab_file, 'r', encoding='utf-8') as f:
                        vocab = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
            return vocab if vocab else default

    def save_vocab(self, vocab_file, vocab_data):
        """Save vocab to language-specific file."""
        with self._lock:
            try:
                with open(vocab_file, 'w', encoding='utf-8') as f:
                    json.dump(vocab_data, f, indent=4)
            except IOError as e:
                print(f"Error saving vocab: {e}")

    def switch_language(self, new_language):
        """Switch to a different language and reload config."""
        with self._lock:
            self.language = new_language
            config_dir = os.path.join(self.base_dir, "config", new_language)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            
            self.config_file = os.path.join(config_dir, "formatter_config.json")
            self.memory_file = os.path.join(config_dir, "memory.json")
            self.user_settings_file = os.path.join(config_dir, "user_settings.json")
            self.archetypes_file = os.path.join(config_dir, "archetypes.json")
            self.dd1_vocab_file = os.path.join(config_dir, "dd1_vocab.json")
            self.other_vocab_file = os.path.join(config_dir, "other_vocab.json")
            
            self.config = self.load_all()
            self.memory = self.load_memory()
            self.user_settings = self.load_user_settings()
            self.archetypes = self.load_archetypes()
            self.dd1_vocab = self.load_vocab(self.dd1_vocab_file, {})
            self.other_vocab = self.load_vocab(self.other_vocab_file, {})
            # Seed archetypes from defaults if not already in config
            self._seed_archetypes()
            return True

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

                        # Migration of user-specific settings to user_settings.json
                        user_specific_keys = [
                            "folders", "bible_path", "glossary_path", "assets_path",
                            "theme_mode", "dark_mode", "in_universe", "openrouter_models",
                            "selected_openrouter_model", "preview_mode",
                            "show_paid_models", "selected_preset",
                            "custom_dark_theme", "custom_light_theme", "last_stats",
                            "github_repo", "github_token", "sync_nickname", "sync_auto"
                        ]
                        user_migrated = False
                        for k in user_specific_keys:
                            if k in data:
                                if not os.path.exists(self.user_settings_file):
                                    self.user_settings[k] = data.pop(k)
                                    user_migrated = True
                        if user_migrated:
                            self.save_user_settings()

                        keys_defaults = {
                            "tag_map": {},
                            "tag_display": {},
                            "presets": {"Standard": 50},
                            "wall_presets": {"Standard": 7},
                            "triggers": [],
                            "speaker_archetypes": {},
                            "speaker_notes": {},
                            "archetypes": {},
                            "entry_type_rules": {},
                            "replace_rules": [],
                            "substitution_rules": [],
                            "preview_font": {},
                            "deepl_target_lang": "EN-US",
                            "ai_system_prompt": "You are a Dragon's Dogma Online (DDON) localization assistant. You must strictly adhere to the 'Dragon's Dogma' localization style. This style uses Early Modern English & archaic vocabulary (e.g., 'tis, naught, aught, pray, afore, mayhap, forsooth, arise) and a formal medieval fantasy tone. Do not go overboard on the archaic language, it should sound natural in English. NEVER use modern slang, colloquialisms, or too many modern contractions (e.g., avoid 'okay', 'gonna', 'don't', 'can't'). CRITICAL RULES: Do NOT use any Japanese honorifics (e.g. -san, -sama, -dono). Use precise, proper English punctuation. Do NOT insert any blank lines or newlines in your response. Translate Japanese dashes as either an ellipsis (...) or a regular em dash (\u2014), when appropriate for the context. Help the user translate or refine dialogue while respecting these rules and the character archetypes. Do not add unnecessary quotation marks. Stay close to the original meaning, but rephrase it to sound more natural in English. Things within < and > are tags & should be preserved as-is.",
                            "ai_button_prompts": {
                                "translate": "Translate: {text}",
                                "rephrase": "Rephrase this: {text}",
                                "archaize": "Make this more archaic: {text}",
                                "check": "Check this for errors: {text}"
                            },
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
                "triggers": [],
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
            self.save_user_settings()

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
