"""
Integrity Checker Module - File corruption detection and recovery
Provides backup rotation, file validation, and corruption logging.
"""

import json
import os
import shutil
import csv
import io
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
import logging

logger = logging.getLogger('DDON_Editor.IntegrityChecker')


class IntegrityChecker:
    """Manages file integrity checks, backups, and recovery."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
        self.base_dir = self.cm.base_dir
        self.config_dir = os.path.join(self.base_dir, "config", self.cm.language)
        self.data_dir = os.path.join(self.base_dir, "data")
        
        # Backup directories
        self.config_backup_dir = os.path.join(self.config_dir, "backups")
        self.data_backup_dir = os.path.join(self.data_dir, "backups")
        
        # Create backup directories
        os.makedirs(self.config_backup_dir, exist_ok=True)
        os.makedirs(self.data_backup_dir, exist_ok=True)
        
        # Corruption log file
        self.corruption_log_file = os.path.join(self.config_dir, "corruption_log.json")
        self.corruption_log = self._load_corruption_log()
        
        # Track recovery events for user notification
        self.recovery_events = []
    
    def _load_corruption_log(self) -> List[Dict[str, Any]]:
        """Load corruption log from file."""
        if os.path.exists(self.corruption_log_file):
            try:
                with open(self.corruption_log_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []
    
    def _save_corruption_log(self):
        """Save corruption log to file."""
        try:
            with open(self.corruption_log_file, 'w', encoding='utf-8') as f:
                json.dump(self.corruption_log, f, indent=4)
        except IOError as e:
            logger.error(f"Failed to save corruption log: {e}")
    
    def _log_corruption(self, filepath: str, error: str, action: str, success: bool):
        """Log a corruption event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "filepath": filepath,
            "error": error,
            "action": action,
            "success": success
        }
        self.corruption_log.append(event)
        self._save_corruption_log()
        
        # Track for user notification
        if success:
            self.recovery_events.append({
                "filepath": os.path.basename(filepath),
                "action": action
            })
    
    def _get_backup_dir(self, filepath: str) -> str:
        """Determine which backup directory to use based on file location."""
        if filepath.startswith(self.config_dir):
            return self.config_backup_dir
        elif filepath.startswith(self.data_dir):
            return self.data_backup_dir
        else:
            # Default to config backup dir
            return self.config_backup_dir
    
    def _get_backup_count(self, filepath: str) -> int:
        """Determine number of backups to keep based on file size/type."""
        filename = os.path.basename(filepath)
        
        # Translation memory is large - keep 3 backups
        if filename == "translation_memory.json":
            return 3
        
        # Cache files are regeneratable - keep 1 backup
        if filename in ["cache.json", "prefetch_cache.json", "review_items_cache.json", "review_queues_cache.json"]:
            return 1
        
        # Small config files - keep 5 backups
        return 5
    
    def backup_file(self, filepath: str) -> bool:
        """Create a backup of the file before writing."""
        if not os.path.exists(filepath):
            return True  # Nothing to backup
        
        try:
            backup_dir = self._get_backup_dir(filepath)
            filename = os.path.basename(filepath)
            max_backups = self._get_backup_count(filepath)
            
            # Create timestamped backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{filename}.{timestamp}.bak"
            backup_path = os.path.join(backup_dir, backup_name)
            
            shutil.copy2(filepath, backup_path)
            logger.debug(f"Created backup: {backup_path}")
            
            # Rotate old backups
            self._rotate_backups(backup_dir, filename, max_backups)
            
            return True
        except (IOError, shutil.Error) as e:
            logger.error(f"Failed to create backup for {filepath}: {e}")
            return False
    
    def _rotate_backups(self, backup_dir: str, filename: str, max_backups: int):
        """Remove old backups beyond max_backups, keeping most recent."""
        # Get all backup files for this file
        backup_files = []
        for f in os.listdir(backup_dir):
            if f.startswith(filename) and f.endswith(".bak"):
                full_path = os.path.join(backup_dir, f)
                backup_files.append((full_path, os.path.getmtime(full_path)))
        
        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        # Remove old backups beyond max_backups
        for backup_path, _ in backup_files[max_backups:]:
            try:
                os.remove(backup_path)
                logger.debug(f"Removed old backup: {backup_path}")
            except IOError as e:
                logger.error(f"Failed to remove old backup {backup_path}: {e}")
    
    def restore_from_backup(self, filepath: str) -> Tuple[bool, Optional[str]]:
        """Restore file from most recent backup. Returns (success, error_message)."""
        backup_dir = self._get_backup_dir(filepath)
        filename = os.path.basename(filepath)
        
        # Find most recent backup
        backup_files = []
        for f in os.listdir(backup_dir):
            if f.startswith(filename) and f.endswith(".bak"):
                full_path = os.path.join(backup_dir, f)
                backup_files.append((full_path, os.path.getmtime(full_path)))
        
        if not backup_files:
            return False, "No backups found"
        
        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        most_recent_backup = backup_files[0][0]
        
        try:
            shutil.copy2(most_recent_backup, filepath)
            logger.info(f"Restored {filepath} from backup: {most_recent_backup}")
            return True, None
        except (IOError, shutil.Error) as e:
            error_msg = f"Failed to restore from backup: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def validate_json_file(self, filepath: str, expected_structure: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], Optional[Any]]:
        """
        Validate JSON file.
        Returns (is_valid, error_message, data_if_valid).
        """
        if not os.path.exists(filepath):
            return False, "File does not exist", None
        
        if os.path.getsize(filepath) == 0:
            return False, "File is empty (0 bytes)", None
        
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin-1']
        data = None
        last_error = None
        
        for encoding in encodings:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    data = json.load(f)
                break
            except UnicodeDecodeError as e:
                last_error = f"Encoding error ({encoding}): {e}"
                continue
            except json.JSONDecodeError as e:
                last_error = f"JSON decode error: {e}"
                # Don't try other encodings for JSON errors
                break
        
        if data is None:
            return False, last_error or "Failed to parse JSON", None
        
        # Validate structure if provided
        if expected_structure:
            for key, expected_type in expected_structure.items():
                if key not in data:
                    return False, f"Missing required key: {key}", None
                if not isinstance(data[key], expected_type):
                    return False, f"Key '{key}' has wrong type (expected {expected_type.__name__}, got {type(data[key]).__name__})", None
        
        return True, None, data
    
    def validate_csv_file(self, filepath: str) -> Tuple[bool, Optional[str]]:
        """
        Validate CSV file.
        Returns (is_valid, error_message).
        """
        if not os.path.exists(filepath):
            return False, "File does not exist"
        
        if os.path.getsize(filepath) == 0:
            return False, "File is empty (0 bytes)"
        
        # Try different encodings
        encodings = ['utf-8-sig', 'utf-8', 'latin-1']
        
        for encoding in encodings:
            try:
                with open(filepath, 'r', encoding=encoding, newline='') as f:
                    raw = f.read()
                
                # Try to sniff dialect
                try:
                    dialect = csv.Sniffer().sniff(raw[:4096])
                    dialect.doublequote = True
                except csv.Error:
                    dialect = csv.excel
                
                # Try to parse
                reader = csv.reader(io.StringIO(raw), dialect)
                rows = list(reader)
                
                if len(rows) == 0:
                    return False, "CSV has no rows"
                
                return True, None
                
            except UnicodeDecodeError:
                continue
            except Exception as e:
                return False, f"CSV parsing error: {e}"
        
        return False, "Failed to decode CSV with any encoding"
    
    def check_and_recover_json(self, filepath: str, expected_structure: Optional[Dict[str, Any]] = None, default_data: Optional[Any] = None) -> Tuple[bool, Any]:
        """
        Check JSON file and attempt recovery if corrupted.
        Returns (success, data).
        """
        is_valid, error, data = self.validate_json_file(filepath, expected_structure)
        
        if is_valid:
            return True, data
        
        # File is corrupted - log it
        logger.warning(f"Corrupted JSON file detected: {filepath} - {error}")
        
        # Try to restore from backup
        restored, restore_error = self.restore_from_backup(filepath)
        
        if restored:
            # Validate restored file
            is_valid, error, data = self.validate_json_file(filepath, expected_structure)
            if is_valid:
                self._log_corruption(filepath, error, "Restored from backup", True)
                return True, data
            else:
                self._log_corruption(filepath, error, "Backup also corrupted", False)
        
        # Backup failed or backup is corrupted - use default
        if default_data is not None:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(default_data, f, indent=4)
                self._log_corruption(filepath, error, "Created with defaults", True)
                return True, default_data
            except IOError as e:
                self._log_corruption(filepath, error, f"Failed to create defaults: {e}", False)
                return False, default_data
        
        # No default available - return failure
        self._log_corruption(filepath, error, "No recovery possible", False)
        return False, {}
    
    def check_all_files(self) -> Dict[str, List[str]]:
        """
        Run integrity checks on all critical files.
        Returns dict with "recovered" and "failed" lists of filenames.
        """
        results = {"recovered": [], "failed": []}
        
        # Define critical files and their expected structures
        critical_files = {
            self.cm.config_file: {
                "structure": {"tag_map": dict, "presets": dict},
                "default": self.cm.load_all()  # This will return defaults if file is missing
            },
            self.cm.user_settings_file: {
                "structure": {"folders": list, "theme_mode": str},
                "default": self.cm.load_user_settings()
            },
            self.cm.memory_file: {
                "structure": None,  # No structure validation for memory
                "default": {}
            },
            self.cm.keys_file: {
                "structure": None,
                "default": {"deepl_api_key": "insert your private key here", "openrouter_api_key": "insert your private key here"}
            },
            self.cm.cache_file: {
                "structure": None,
                "default": {}
            },
            self.cm.archetypes_file: {
                "structure": None,
                "default": {}
            },
            self.cm.dd1_vocab_file: {
                "structure": None,
                "default": {}
            },
            self.cm.other_vocab_file: {
                "structure": None,
                "default": {}
            }
        }
        
        # Add translation memory file if it exists
        tm_file = os.path.join(os.path.dirname(self.cm.user_settings_file), "translation_memory.json")
        if os.path.exists(tm_file):
            critical_files[tm_file] = {
                "structure": {"version": int, "entries": list, "stats": dict},
                "default": {"version": 2, "entries": [], "stats": {"total_entries": 0, "approved_count": 0, "draft_count": 0}}
            }
        
        # Check each file
        for filepath, config in critical_files.items():
            success, data = self.check_and_recover_json(
                filepath,
                config["structure"],
                config["default"]
            )
            
            if success:
                if os.path.basename(filepath) in [e["filepath"] for e in self.recovery_events]:
                    results["recovered"].append(os.path.basename(filepath))
            else:
                results["failed"].append(os.path.basename(filepath))
        
        return results
    
    def get_recovery_events(self) -> List[Dict[str, str]]:
        """Get list of recovery events for user notification."""
        return self.recovery_events
