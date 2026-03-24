import json
import os

class ConfigManager:
    def __init__(self, config_file="formatter_config.json"):
        self.config_file = config_file
        self.config = self.load_all()
        # Initialize memory for "Apply & Remember" fixes
        self.memory = self.config.get("memory", {})

    def load_all(self):
        # 1. Check if the file actually exists on the disk
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Ensure essential keys exist so the app doesn't crash
                    if "tag_map" not in data: data["tag_map"] = {}
                    if "presets" not in data: data["presets"] = {"Standard": 50}
                    if "wall_presets" not in data: data["wall_presets"] = {"Standard": 7}
                    if "folders" not in data: data["folders"] = []
                    if "triggers" not in data: data["triggers"] = []
                    if "speaker_archetypes" not in data: data["speaker_archetypes"] = {}
                    if "memory" not in data: data["memory"] = {}
                    return data
            except (json.JSONDecodeError, IOError):
                print("Config file corrupted, creating new one.")
        
        # 2. Default data if no file is found
        return {
            "tag_map": {},
            "presets": {"Standard": 50},
            "wall_presets": {"Standard": 7},
            "folders": [],
            "triggers": [],
            "bible_path": "",
            "glossary_path": "",
            "memory": {},
            "speaker_archetypes": {}
        }

    def save_all(self):
        # Sync memory into the config object before saving
        self.config["memory"] = self.memory
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    # Alias so both main.py and main_dashboard.py can call either name
    def save_config(self):
        self.save_all()