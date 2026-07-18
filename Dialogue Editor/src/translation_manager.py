"""
Translation Management Module - Per-file storage with MessagePack and security
Handles translation features with efficient binary storage and input validation.
"""

import json
import os
import re
import html
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict

# Test mode flag - check environment variable to avoid circular import
TEST_MODE = os.environ.get('DDON_TEST_MODE', 'false').lower() == 'true'

def debug_log(component, message, level='DEBUG'):
    """Log debug message with component name (only when TEST_MODE is enabled)."""
    if not TEST_MODE:
        return
    logger = logging.getLogger('DDON_Editor.TranslationManager')
    log_func = getattr(logger, level.lower(), logger.debug)
    log_msg = f"[{component}] {message}"
    log_func(log_msg)

try:
    import msgpack
    MSGPACK_AVAILABLE = True
except ImportError:
    MSGPACK_AVAILABLE = False
    print("[TranslationManager] msgpack not available, falling back to JSON")

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB max file size
MAX_COMMENT_LENGTH = 5000  # Max characters in a comment
MAX_LOG_ENTRIES = 100000  # Max history entries per file
MAX_COMMENTS_PER_ENTRY = 1000  # Max comments per translation entry

# Validation schemas
VALID_STATUSES = {"untranslated", "translated", "pre-translated", "approved", "rejected"}
VALID_ACTIONS = {"translate", "approve", "reject", "comment", "vote"}


def sanitize_text(text: str, max_length: int = 10000) -> str:
    """Sanitize text input to prevent injection attacks."""
    if not isinstance(text, str):
        return ""
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]
    # Escape HTML to prevent XSS
    text = html.escape(text)
    # Remove null bytes and control characters except newlines/tabs
    text = ''.join(c for c in text if c == '\n' or c == '\t' or ord(c) >= 32)
    return text


def validate_entry_id(entry_id: str) -> bool:
    """Validate entry ID format - alphanumeric with underscores/hyphens only."""
    if not isinstance(entry_id, str):
        return False
    if len(entry_id) > 200:
        return False
    # Allow: alphanumeric, underscore, hyphen, dot, colon
    return bool(re.match(r'^[a-zA-Z0-9_\-\.:]+$', entry_id))


def generate_entry_id(source_text: str) -> str:
    """Generate entry ID from source text using SHA256 hash."""
    import hashlib
    # Normalize the source text for consistent hashing
    normalized = source_text.strip().replace('\n', ' ').replace('\r', ' ')
    # Generate SHA256 hash and take first 16 characters
    hash_obj = hashlib.sha256(normalized.encode('utf-8'))
    return hash_obj.hexdigest()[:16]


def validate_username(username: str) -> bool:
    """Validate username - alphanumeric with common characters."""
    if not isinstance(username, str):
        return False
    if len(username) > 50:
        return False
    # Allow: alphanumeric, spaces, common punctuation
    return bool(re.match(r'^[\w\s\-_.@]+$', username))


@dataclass
class TranslationEntry:
    """Represents a translation entry with status and metadata."""
    id: str
    source_text: str
    translated_text: Optional[str] = None
    status: str = "untranslated"  # untranslated, translated, approved, rejected
    translator: Optional[str] = None
    approver: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    approved_at: Optional[str] = None
    file_path: Optional[str] = None
    row_index: Optional[int] = None
    speaker: Optional[str] = None
    entry_type: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TranslationEntry":
        # Validate and sanitize
        data['source_text'] = sanitize_text(data.get('source_text', ''))
        data['translated_text'] = sanitize_text(data.get('translated_text', '')) if data.get('translated_text') else None
        data['status'] = data.get('status', 'untranslated')
        if data['status'] not in VALID_STATUSES:
            data['status'] = 'untranslated'
        return cls(**data)


@dataclass
class TranslationLogEntry:
    """Represents a single action in translation history."""
    id: str
    action: str  # translate, approve, reject, comment, vote
    user: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    comment: Optional[str] = None
    source: Optional[str] = None  # Translation source: 'tm', 'openrouter', 'deepl', etc.
    comments: List['Comment'] = field(default_factory=list)  # Comments attached to this history entry
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Comment:
    """Represents a comment on a translation entry."""
    id: str
    entry_id: str
    user: str
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_id: Optional[str] = None  # For threaded comments
    history_entry_id: Optional[str] = None  # Explicit attachment to specific history entry
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Vote:
    """Represents a vote on a translation."""
    entry_id: str
    user: str
    vote: int  # +1 for upvote, -1 for downvote
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return asdict(self)


class TranslationManager:
    """Manages translation entries, history, comments, and voting - with security."""
    
    def __init__(self, language: str = "en"):
        self.language = language
        self.entries: Dict[str, TranslationEntry] = {}
        self.logs: List[TranslationLogEntry] = []
        self.votes: Dict[str, List[Vote]] = defaultdict(list)
        self._sync_callback = None
        self._dirty_files: set = set()
        
        # Ensure data directory exists
        self._ensure_data_dir()
        self._load_data()
    
    def set_config_manager(self, cm):
        """Set the ConfigManager used for Translation Memory access."""
        self.cm = cm

    def _ensure_data_dir(self):
        """Create data directory if it doesn't exist."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "config", self.language, "translation_data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
    
    def _sanitize_filename(self, name: str) -> str:
        """Create safe directory name from file path (uses only filename)."""
        # Extract just the filename from the full path
        filename = os.path.basename(name)
        safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
        if len(safe) > 100:
            safe = safe[:100]
        return safe or 'unknown'
    
    def _get_file_dir(self, file_path: str) -> str:
        """Get the data directory path for a source file."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "config", self.language, "translation_data")
        safe_name = self._sanitize_filename(file_path)
        return os.path.join(data_dir, safe_name)
    
    def _ensure_file_dir(self, file_path: str):
        """Create directory for a file's data if it doesn't exist."""
        dir_path = self._get_file_dir(file_path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
    
    def _compute_checksum(self, data: bytes) -> str:
        """Compute checksum for data integrity."""
        return hashlib.sha256(data).hexdigest()[:16]
    
    def _load_msgpack_file(self, filepath: str) -> Optional[Any]:
        """Load data from MessagePack file with validation."""
        try:
            # Check file size
            if os.path.getsize(filepath) > MAX_FILE_SIZE:
                print(f"[TranslationManager] File too large: {filepath}")
                return None
            
            with open(filepath, 'rb') as f:
                data = f.read()
            
            if MSGPACK_AVAILABLE:
                return msgpack.unpackb(data, raw=False, strict_map_key=False)
            else:
                # Fallback to JSON
                return json.loads(data.decode('utf-8'))
        except Exception as e:
            print(f"[TranslationManager] Error loading {filepath}: {e}")
            return None
    
    def _save_msgpack_file(self, filepath: str, data: Any) -> bool:
        """Save data to MessagePack file with backup."""
        try:
            # Create backup if file exists
            if os.path.exists(filepath):
                backup_path = filepath + '.backup'
                try:
                    os.replace(filepath, backup_path)
                except Exception:
                    pass
            
            if MSGPACK_AVAILABLE:
                packed = msgpack.packb(data, use_bin_type=True)
            else:
                # Fallback to JSON
                packed = json.dumps(data, ensure_ascii=False).encode('utf-8')
            
            with open(filepath, 'wb') as f:
                f.write(packed)
            
            return True
        except Exception as e:
            print(f"[TranslationManager] Error saving {filepath}: {e}")
            # Try to restore backup
            backup_path = filepath + '.backup'
            if os.path.exists(backup_path):
                try:
                    os.replace(backup_path, filepath)
                except Exception:
                    pass
            return False
    
    def set_sync_callback(self, callback):
        """Set callback function to trigger after save operations."""
        self._sync_callback = callback
    
    def _trigger_sync(self, urgent: bool = False):
        """Trigger sync callback if set."""
        if self._sync_callback:
            try:
                self._sync_callback(urgent=urgent)
            except Exception as e:
                print(f"[TranslationManager] Sync callback error: {e}")
    
    def _mark_dirty(self, file_path: str):
        """Mark a file as needing to be saved."""
        self._dirty_files.add(file_path or 'unknown')
    
    def _load_data(self):
        """Load all persisted data from per-file storage."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "config", self.language, "translation_data")
        
        if not os.path.exists(data_dir):
            print(f"[TranslationManager] Data directory {data_dir} does not exist, starting fresh")
            return

        print(f"[TranslationManager] Loading data from {data_dir}")
        loaded_dirs = 0

        for dir_name in os.listdir(data_dir):
            dir_path = os.path.join(data_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue

            try:
                # Load status file
                status_path = os.path.join(dir_path, 'status.mp' if MSGPACK_AVAILABLE else 'status.json')
                fallback_status = os.path.join(dir_path, 'status.json')

                for path in [status_path, fallback_status]:
                    if os.path.exists(path):
                        data = self._load_msgpack_file(path)
                        if data and isinstance(data, dict):
                            for entry_id, entry_data in data.items():
                                if validate_entry_id(entry_id):
                                    try:
                                        self.entries[entry_id] = TranslationEntry.from_dict(entry_data)
                                    except Exception as e:
                                        print(f"[TranslationManager] Invalid entry {entry_id}: {e}")
                            break

                # Load logs file
                logs_path = os.path.join(dir_path, 'logs.mp' if MSGPACK_AVAILABLE else 'logs.json')
                fallback_logs = os.path.join(dir_path, 'logs.json')

                for path in [logs_path, fallback_logs]:
                    if os.path.exists(path):
                        data = self._load_msgpack_file(path)
                        if data and isinstance(data, list):
                            for log_data in data[:MAX_LOG_ENTRIES]:  # Limit entries
                                try:
                                    if log_data.get('action') in VALID_ACTIONS:
                                        # Convert comments from dicts to Comment objects
                                        if 'comments' in log_data and isinstance(log_data['comments'], list):
                                            log_data['comments'] = [Comment(**c) if isinstance(c, dict) else c for c in log_data['comments']]
                                        self.logs.append(TranslationLogEntry(**log_data))
                                except Exception as e:
                                    print(f"[TranslationManager] Invalid log entry: {e}")
                            break

                loaded_dirs += 1
            except Exception as e:
                print(f"[TranslationManager] Error loading data from {dir_name}: {e}")

        print(f"[TranslationManager] Loaded data from {loaded_dirs} directories: {len(self.entries)} entries, {len(self.logs)} logs, {sum(len(log.comments) for log in self.logs)} comments")
    
    def _get_entries_by_file(self, file_path: str) -> Dict[str, TranslationEntry]:
        """Get all entries belonging to a specific file."""
        return {k: v for k, v in self.entries.items() if v.file_path == file_path}
    
    def _get_logs_by_file(self, file_path: str) -> List[TranslationLogEntry]:
        """Get all logs for entries belonging to a specific file.

        Log ids are ``{entry_id}_{timestamp}``, so a log belongs to a file if its
        id starts with one of that file's entry ids.
        """
        file_entries = self._get_entries_by_file(file_path)
        file_entry_ids = set(file_entries.keys())
        return [log for log in self.logs if any(log.id.startswith(eid) for eid in file_entry_ids)]
    
    def _save_file_data(self, file_path: str):
        """Save all data for a specific file using MessagePack."""
        file_path = file_path or 'unknown'
        self._ensure_file_dir(file_path)
        dir_path = self._get_file_dir(file_path)

        try:
            # Save status
            entries = self._get_entries_by_file(file_path)
            ext = '.mp' if MSGPACK_AVAILABLE else '.json'
            status_path = os.path.join(dir_path, f'status{ext}')
            status_data = {k: v.to_dict() for k, v in entries.items()}
            # Only save if there's data
            if status_data:
                self._save_msgpack_file(status_path, status_data)

            # Save logs (limit to most recent) - comments are now embedded in logs
            logs = self._get_logs_by_file(file_path)
            logs_path = os.path.join(dir_path, f'logs{ext}')
            logs_data = [log.to_dict() for log in logs[-MAX_LOG_ENTRIES:]]
            # Only save if there's data
            if logs_data:
                self._save_msgpack_file(logs_path, logs_data)

            print(f"[TranslationManager] Saved data for {file_path}")

        except Exception as e:
            print(f"[TranslationManager] Error saving data for {file_path}: {e}")
    
    def _save_all_dirty(self):
        """Save all dirty files."""
        for file_path in self._dirty_files:
            self._save_file_data(file_path)
        self._dirty_files.clear()
        self._trigger_sync()
    
    def flush_saves(self):
        """Force save all dirty files immediately."""
        self._save_all_dirty()
    
    def get_or_create_entry(self, entry_id: str, source_text: str, 
                           file_path: Optional[str] = None,
                           row_index: Optional[int] = None,
                           speaker: Optional[str] = None,
                           entry_type: Optional[str] = None) -> TranslationEntry:
        """Get existing entry or create new one."""
        if not validate_entry_id(entry_id):
            raise ValueError(f"Invalid entry ID: {entry_id}")
        
        if entry_id not in self.entries:
            self.entries[entry_id] = TranslationEntry(
                id=entry_id,
                source_text=sanitize_text(source_text),
                file_path=file_path,
                row_index=row_index,
                speaker=sanitize_text(speaker) if speaker else None,
                entry_type=sanitize_text(entry_type) if entry_type else None
            )
            self._mark_dirty(file_path)
            self._save_file_data(file_path)
        return self.entries[entry_id]
    
    def submit_translation(self, entry_id: str, source_text: str, translated_text: str,
                          translator: str, file_path: str,
                          row_index: Optional[int] = None,
                          speaker: Optional[str] = None,
                          entry_type: Optional[str] = None,
                          status: str = "translated",
                          source: Optional[str] = None) -> TranslationEntry:
        """Submit a new translation."""
        debug_log("submit_translation", f"Called with entry_id={entry_id}, status={status}")
        if not validate_entry_id(entry_id):
            debug_log("submit_translation", f"Invalid entry ID: {entry_id}", level="ERROR")
            raise ValueError(f"Invalid entry ID: {entry_id}")
        if not validate_username(translator):
            debug_log("submit_translation", f"Invalid translator name: {translator}", level="ERROR")
            raise ValueError(f"Invalid translator name: {translator}")
        if status not in VALID_STATUSES:
            debug_log("submit_translation", f"Invalid status: {status}", level="ERROR")
            raise ValueError(f"Invalid status: {status}")

        entry = self.get_or_create_entry(entry_id, source_text, file_path, row_index, speaker, entry_type)
        debug_log("submit_translation", f"Got or created entry: {entry_id}")

        old_value = entry.translated_text
        entry.translated_text = sanitize_text(translated_text)
        entry.translator = sanitize_text(translator)
        entry.status = status
        entry.updated_at = datetime.now().isoformat()

        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        debug_log("submit_translation", f"Saved entry data for {file_path}")

        self.logs.append(TranslationLogEntry(
            id=f"{entry_id}_{datetime.now().timestamp()}",
            action="translate",
            user=sanitize_text(translator),
            old_value=old_value,
            new_value=sanitize_text(translated_text),
            source=source
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        debug_log("submit_translation", f"Logged translation action for {entry_id}")

        # Add to Translation Memory if approved
        if status == "approved" and self.cm:
            try:
                from src.translation_memory import TranslationMemory
                tm = TranslationMemory(self.cm)
                tm_entry = {
                    "source": source_text,
                    "translation": translated_text,
                    "context": {
                        "file": file_path,
                        "row": row_index,
                        "speaker": speaker,
                        "entry_type": entry_type
                    },
                    "quality": "approved"
                }
                tm.add_entry(tm_entry)
                debug_log("submit_translation", f"Added approved translation to TM: {entry_id}")
                print(f"[TranslationManager] Added approved translation to TM: {entry_id}")
            except Exception as e:
                debug_log("submit_translation", f"Failed to add to TM: {e}", level="ERROR")
                print(f"[TranslationManager] Failed to add to TM: {e}")

        debug_log("submit_translation", f"Completed successfully for {entry_id}")
        return entry
    
    def approve_translation(self, entry_id: str, approver: str) -> Optional[TranslationEntry]:
        """Approve a translation."""
        debug_log("approve_translation", f"Called with entry_id={entry_id}, approver={approver}")
        if not validate_entry_id(entry_id):
            debug_log("approve_translation", f"Invalid entry ID: {entry_id}", level="ERROR")
            return None
        if not validate_username(approver):
            debug_log("approve_translation", f"Invalid approver name: {approver}", level="ERROR")
            return None

        if entry_id not in self.entries:
            debug_log("approve_translation", f"Entry not found: {entry_id}", level="ERROR")
            return None

        entry = self.entries[entry_id]
        entry.status = "approved"
        entry.approver = sanitize_text(approver)
        entry.approved_at = datetime.now().isoformat()
        entry.updated_at = datetime.now().isoformat()
        debug_log("approve_translation", f"Updated entry status to approved: {entry_id}")

        file_path = entry.file_path
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        debug_log("approve_translation", f"Saved entry data for {file_path}")

        # Log the approve action
        self.logs.append(TranslationLogEntry(
            id=f"{entry_id}_{datetime.now().timestamp()}",
            action="approve",
            user=sanitize_text(approver),
            new_value=entry.translated_text
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        debug_log("approve_translation", f"Logged approve action for {entry_id}")

        # Add to Translation Memory
        if self.cm:
            try:
                from src.translation_memory import TranslationMemory
                tm = TranslationMemory(self.cm)
                tm_entry = {
                    "source": entry.source_text,
                    "translation": entry.translated_text,
                    "context": {
                        "file": entry.file_path,
                        "row": entry.row_index,
                        "speaker": entry.speaker,
                        "entry_type": entry.entry_type
                    },
                    "quality": "approved"
                }
                tm.add_entry(tm_entry)
                debug_log("approve_translation", f"Added approved translation to TM: {entry_id}")
                print(f"[TranslationManager] Added approved translation to TM: {entry_id}")
            except Exception as e:
                debug_log("approve_translation", f"Failed to add to TM: {e}", level="ERROR")
                print(f"[TranslationManager] Failed to add to TM: {e}")

        debug_log("approve_translation", f"Completed successfully for {entry_id}")
        return entry

    def reject_translation(self, entry_id: str, reviewer: str, reason: Optional[str] = None) -> Optional[TranslationEntry]:
        """Reject a translation."""
        debug_log("reject_translation", f"Called with entry_id={entry_id}, reviewer={reviewer}")
        if not validate_entry_id(entry_id):
            debug_log("reject_translation", f"Invalid entry ID: {entry_id}", level="ERROR")
            return None
        if not validate_username(reviewer):
            debug_log("reject_translation", f"Invalid reviewer name: {reviewer}", level="ERROR")
            return None

        if entry_id not in self.entries:
            debug_log("reject_translation", f"Entry not found: {entry_id}", level="ERROR")
            return None

        entry = self.entries[entry_id]
        entry.status = "rejected"
        entry.updated_at = datetime.now().isoformat()
        debug_log("reject_translation", f"Updated entry status to rejected: {entry_id}")

        file_path = entry.file_path
        self._mark_dirty(file_path)
        self._save_file_data(file_path)

        # Log the reject action
        self.logs.append(TranslationLogEntry(
            id=f"{entry_id}_{datetime.now().timestamp()}",
            action="reject",
            user=sanitize_text(reviewer),
            new_value=entry.translated_text,
            comment=reason
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)

        return entry
    
    def add_comment(self, entry_id: str, user: str, text: str, parent_id: Optional[str] = None, history_entry_id: Optional[str] = None) -> Comment:
        """Add a comment to a translation entry.
        
        Args:
            entry_id: The translation entry ID
            user: Username adding the comment
            text: Comment text
            parent_id: For threaded comments (replies)
            history_entry_id: If specified, attach to this specific history entry. 
                            If None, attach to the most recent history entry for this entry_id.
        """
        if not validate_entry_id(entry_id):
            raise ValueError(f"Invalid entry ID: {entry_id}")
        if not validate_username(user):
            raise ValueError(f"Invalid username: {user}")
        
        sanitized_text = sanitize_text(text, MAX_COMMENT_LENGTH)
        if not sanitized_text:
            raise ValueError("Comment text cannot be empty")
        
        # Find the target history entry
        target_history_entry = None
        if history_entry_id:
            # Find specific history entry by exact ID match
            for log in reversed(self.logs):
                if log.id == history_entry_id:
                    target_history_entry = log
                    break
            if not target_history_entry:
                raise ValueError(f"History entry {history_entry_id} not found")
        else:
            # Find most recent history entry for this entry_id
            for log in reversed(self.logs):
                if log.id.startswith(entry_id):
                    target_history_entry = log
                    break
        
        if not target_history_entry:
            raise ValueError(f"No history entry found for {entry_id}. Cannot attach comment.")
        
        # Check comment limit on the target history entry
        if len(target_history_entry.comments) >= MAX_COMMENTS_PER_ENTRY:
            raise ValueError(f"Maximum comments ({MAX_COMMENTS_PER_ENTRY}) reached for this history entry")
        
        comment = Comment(
            id=f"{entry_id}_{len(target_history_entry.comments)}_{datetime.now().timestamp()}",
            entry_id=entry_id,
            user=sanitize_text(user),
            text=sanitized_text,
            parent_id=sanitize_text(parent_id) if parent_id else None,
            history_entry_id=target_history_entry.id
        )
        
        # Attach comment to history entry
        target_history_entry.comments.append(comment)
        
        file_path = self.entries.get(entry_id, {}).file_path if entry_id in self.entries else None
        self._mark_dirty(file_path)
        self._trigger_sync(urgent=True)
        self._save_file_data(file_path)
        
        return comment
    
    def get_comments(self, entry_id: str) -> List[Comment]:
        """Get all comments for an entry (collected from history entries)."""
        comments = []
        for log in self.logs:
            if log.id.startswith(entry_id):
                comments.extend(log.comments)
        return comments
    
    def get_sanitized_comments_for_display(self, entry_id: str) -> List[Dict]:
        """Get comments sanitized for HTML display."""
        comments = self.get_comments(entry_id)
        return [{
            'id': c.id,
            'user': html.escape(c.user),
            'text': html.escape(c.text),  # Already escaped but double-escape for safety
            'timestamp': c.timestamp,
            'parent_id': c.parent_id
        } for c in comments]
    
    def vote_translation(self, entry_id: str, user: str, vote: int) -> Vote:
        """Vote on a translation (+1 for upvote, -1 for downvote)."""
        if not validate_entry_id(entry_id):
            raise ValueError(f"Invalid entry ID: {entry_id}")
        if not validate_username(user):
            raise ValueError(f"Invalid username: {user}")
        if vote not in (-1, 1):
            raise ValueError("Vote must be +1 or -1")
        
        # Remove existing vote from this user
        self.votes[entry_id] = [v for v in self.votes[entry_id] if v.user != user]
        
        new_vote = Vote(entry_id=entry_id, user=sanitize_text(user), vote=vote)
        self.votes[entry_id].append(new_vote)
        
        # Log vote
        self.logs.append(TranslationLogEntry(
            id=f"{entry_id}_{datetime.now().timestamp()}",
            action="vote",
            user=sanitize_text(user),
            new_value=str(vote)
        ))
        
        file_path = self.entries.get(entry_id, {}).file_path if entry_id in self.entries else None
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        
        return new_vote
    
    def get_vote_score(self, entry_id: str) -> int:
        """Get total vote score for an entry."""
        return sum(v.vote for v in self.votes.get(entry_id, []))
    
    def get_entry_status(self, entry_id: str) -> Optional[str]:
        """Get status of an entry."""
        if entry_id in self.entries:
            return self.entries[entry_id].status
        return None
    
    def get_translation_history(self, entry_id: str) -> List[TranslationLogEntry]:
        """Get all logged actions for an entry."""
        return [log for log in self.logs if log.id.startswith(entry_id)]
    
    def get_recent_activity(self, limit: int = 50) -> List[TranslationLogEntry]:
        """Get recent translation activity across all entries."""
        return sorted(self.logs, key=lambda x: x.timestamp, reverse=True)[:min(limit, 1000)]
    
    def get_translation_logs(self) -> List[TranslationLogEntry]:
        """Get all translation logs."""
        return self.logs
    
    def get_comment_log(self) -> List[TranslationLogEntry]:
        """Get all comment logs."""
        return [log for log in self.logs if log.action == 'comment']
    
    def get_stats(self) -> Dict[str, int]:
        """Get translation statistics."""
        stats = {
            "total": len(self.entries),
            "untranslated": 0,
            "translated": 0,
            "approved": 0,
            "rejected": 0
        }
        
        for entry in self.entries.values():
            if entry.status in stats:
                stats[entry.status] += 1
        
        return stats
    
    def get_entries_by_status(self, status: str) -> List[TranslationEntry]:
        """Get all entries with a specific status."""
        return [e for e in self.entries.values() if e.status == status]

    def get_approved_entries(self) -> List[TranslationEntry]:
        """Get all approved entries."""
        return self.get_entries_by_status("approved")

    def get_unapproved_entries_with_comments(self) -> List[Dict]:
        """Get all unapproved entries with comment count."""
        result = []
        # Only get entries from translation_manager (these have history/comments)
        for entry in self.entries.values():
            if entry.status != 'approved':
                comment_count = len(self.get_comments(entry.id))
                result.append({
                    'entry': entry.to_dict(),
                    'comment_count': comment_count
                })

        return result

    def get_pretranslated_unapproved_entries(self) -> List[Dict]:
        """Get all pre-translated unapproved entries with comment count."""
        result = []
        print(f"[get_pretranslated_unapproved_entries] Checking {len(self.entries)} entries for pre-translated status")
        for entry in self.entries.values():
            if entry.status == 'pre-translated':
                comment_count = len(self.get_comments(entry.id))
                result.append({
                    'entry': entry.to_dict(),
                    'comment_count': comment_count
                })
                print(f"[get_pretranslated_unapproved_entries] Found pre-translated entry: {entry.id}, comments: {comment_count}")
        print(f"[get_pretranslated_unapproved_entries] Returning {len(result)} pre-translated entries")
        return result

    def cleanup_old_approval_logs(self):
        """Remove old approve/reject log entries that are no longer needed."""
        # Keep approve/reject logs in history for badge determination per history entry
        # Only remove duplicate approve/reject actions, keeping the most recent one
        pass

    def update_all_log_usernames(self, new_username: str):
        """Update all log entries to use the new username."""
        for log in self.logs:
            if log.user in ('translator', 'reviewer'):
                log.user = sanitize_text(new_username)
        self._save_all_dirty()
    
    # Static helper methods for dict conversion (used by GitHubSync)
    @staticmethod
    def _entry_from_dict(data: Dict) -> 'TranslationEntry':
        """Convert dict to TranslationEntry."""
        return TranslationEntry.from_dict(data)
    
    @staticmethod
    def _log_from_dict(data: Dict) -> 'TranslationLogEntry':
        """Convert dict to TranslationLogEntry."""
        # Convert comments from dicts to Comment objects
        if 'comments' in data and isinstance(data['comments'], list):
            data['comments'] = [Comment(**c) if isinstance(c, dict) else c for c in data['comments']]
        return TranslationLogEntry(**data)
    
    @staticmethod
    def _comment_from_dict(data: Dict) -> 'Comment':
        """Convert dict to Comment."""
        return Comment(**data)


# Global instance - will be initialized with language from config
translation_manager = None

def get_translation_manager(language: str = "en") -> TranslationManager:
    """Get or create a TranslationManager instance for the specified language."""
    global translation_manager
    if translation_manager is None or translation_manager.language != language:
        translation_manager = TranslationManager(language)
    return translation_manager
