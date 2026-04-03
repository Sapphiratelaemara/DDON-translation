import json
import os

class ConfigManager:
    def __init__(self, config_file="formatter_config.json"):
        self.config_file = config_file
        self.config = self.load_all()
        self.memory = self.config.get("memory", {})
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

    def load_all(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    keys_defaults = {
                        "tag_map": {},
                        "tag_display": {},
                        "presets": {"Standard": 50},
                        "wall_presets": {"Standard": 7},
                        "folders": [],
                        "triggers": [],
                        "speaker_archetypes": {},
                        "speaker_notes": {},
                        "memory": {},
                        "bible_path": "",
                        "glossary_path": "",
                        "archetypes": {},
                        "entry_type_rules": {},
                        "replace_rules": [],
                        "substitution_rules": [],
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
            "memory": {},
            "speaker_archetypes": {},
            "speaker_notes": {},
            "archetypes": {},
            "entry_type_rules": {},
            "replace_rules": [],
        }

    def save_all(self):
        # Sync memory into config before saving
        self.config["memory"] = self.memory
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Error saving config: {e}")

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