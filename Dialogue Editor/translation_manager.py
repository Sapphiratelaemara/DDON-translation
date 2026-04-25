"""
Translation Management Module - Per-file storage with MessagePack and security
Handles Crowdin-style features with efficient binary storage and input validation.
"""

import json
import os
import re
import html
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict

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
VALID_STATUSES = {"untranslated", "translated", "approved", "rejected"}
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
        self.comments: Dict[str, List[Comment]] = defaultdict(list)
        self.votes: Dict[str, List[Vote]] = defaultdict(list)
        self._sync_callback = None
        self._dirty_files: set = set()
        
        # Ensure data directory exists
        self._ensure_data_dir()
        self._load_data()
    
    def _ensure_data_dir(self):
        """Create data directory if it doesn't exist."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
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
        base_dir = os.path.dirname(os.path.abspath(__file__))
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
        base_dir = os.path.dirname(os.path.abspath(__file__))
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
                                        self.logs.append(TranslationLogEntry(**log_data))
                                except Exception as e:
                                    print(f"[TranslationManager] Invalid log entry: {e}")
                            break

                # Load comments file
                comments_path = os.path.join(dir_path, 'comments.mp' if MSGPACK_AVAILABLE else 'comments.json')
                fallback_comments = os.path.join(dir_path, 'comments.json')

                for path in [comments_path, fallback_comments]:
                    if os.path.exists(path):
                        data = self._load_msgpack_file(path)
                        if data and isinstance(data, dict):
                            for entry_id, comments_list in data.items():
                                if validate_entry_id(entry_id) and isinstance(comments_list, list):
                                    valid_comments = []
                                    for c in comments_list[:MAX_COMMENTS_PER_ENTRY]:
                                        try:
                                            if isinstance(c, dict) and 'text' in c:
                                                c['text'] = sanitize_text(c['text'], MAX_COMMENT_LENGTH)
                                                valid_comments.append(Comment(**c))
                                        except Exception as e:
                                            print(f"[TranslationManager] Invalid comment: {e}")
                                    self.comments[entry_id] = valid_comments
                            break

                loaded_dirs += 1
            except Exception as e:
                print(f"[TranslationManager] Error loading data from {dir_name}: {e}")

        print(f"[TranslationManager] Loaded data from {loaded_dirs} directories: {len(self.entries)} entries, {len(self.logs)} logs, {sum(len(v) for v in self.comments.values())} comments")
    
    def _get_entries_by_file(self, file_path: str) -> Dict[str, TranslationEntry]:
        """Get all entries belonging to a specific file."""
        return {k: v for k, v in self.entries.items() if v.file_path == file_path}
    
    def _get_logs_by_file(self, file_path: str) -> List[TranslationLogEntry]:
        """Get all logs for entries belonging to a specific file."""
        file_entries = self._get_entries_by_file(file_path)
        file_entry_ids = set(file_entries.keys())
        return [log for log in self.logs if log.id in file_entry_ids]
    
    def _get_comments_by_file(self, file_path: str) -> Dict[str, List[Comment]]:
        """Get all comments for entries belonging to a specific file."""
        file_entries = self._get_entries_by_file(file_path)
        file_entry_ids = set(file_entries.keys())
        return {k: v for k, v in self.comments.items() if k in file_entry_ids}
    
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

            # Save logs (limit to most recent)
            logs = self._get_logs_by_file(file_path)
            logs_path = os.path.join(dir_path, f'logs{ext}')
            logs_data = [log.to_dict() for log in logs[-MAX_LOG_ENTRIES:]]
            # Only save if there's data
            if logs_data:
                self._save_msgpack_file(logs_path, logs_data)

            # Save comments
            comments = self._get_comments_by_file(file_path)
            comments_path = os.path.join(dir_path, f'comments{ext}')
            comments_data = {k: [c.to_dict() for c in v] for k, v in comments.items()}
            # Only save if there's data
            if comments_data:
                self._save_msgpack_file(comments_path, comments_data)

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
                          translator: str, file_path: Optional[str] = None,
                          row_index: Optional[int] = None,
                          speaker: Optional[str] = None,
                          entry_type: Optional[str] = None) -> TranslationEntry:
        """Submit a new translation."""
        if not validate_entry_id(entry_id):
            raise ValueError(f"Invalid entry ID: {entry_id}")
        if not validate_username(translator):
            raise ValueError(f"Invalid translator name: {translator}")
        
        entry = self.get_or_create_entry(entry_id, source_text, file_path, row_index, speaker, entry_type)
        
        old_value = entry.translated_text
        entry.translated_text = sanitize_text(translated_text)
        entry.translator = sanitize_text(translator)
        entry.status = "translated"
        entry.updated_at = datetime.now().isoformat()
        
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        
        self.logs.append(TranslationLogEntry(
            id=entry_id,
            action="translate",
            user=sanitize_text(translator),
            old_value=old_value,
            new_value=sanitize_text(translated_text)
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        
        return entry
    
    def approve_translation(self, entry_id: str, approver: str) -> Optional[TranslationEntry]:
        """Approve a translation."""
        if not validate_entry_id(entry_id):
            return None
        if not validate_username(approver):
            return None

        if entry_id not in self.entries:
            return None

        entry = self.entries[entry_id]
        entry.status = "approved"
        entry.approver = sanitize_text(approver)
        entry.approved_at = datetime.now().isoformat()
        entry.updated_at = datetime.now().isoformat()

        file_path = entry.file_path
        self._mark_dirty(file_path)
        self._save_file_data(file_path)

        # Log the approve action
        self.logs.append(TranslationLogEntry(
            id=entry_id,
            action="approve",
            user=sanitize_text(approver),
            new_value=entry.translated_text
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)

        return entry

    def reject_translation(self, entry_id: str, reviewer: str, reason: Optional[str] = None) -> Optional[TranslationEntry]:
        """Reject a translation."""
        if not validate_entry_id(entry_id):
            return None
        if not validate_username(reviewer):
            return None

        if entry_id not in self.entries:
            return None

        entry = self.entries[entry_id]
        entry.status = "rejected"
        entry.updated_at = datetime.now().isoformat()

        file_path = entry.file_path
        self._mark_dirty(file_path)
        self._save_file_data(file_path)

        # Log the reject action
        self.logs.append(TranslationLogEntry(
            id=entry_id,
            action="reject",
            user=sanitize_text(reviewer),
            new_value=entry.translated_text,
            comment=reason
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)

        return entry
    
    def add_comment(self, entry_id: str, user: str, text: str, parent_id: Optional[str] = None) -> Comment:
        """Add a comment to a translation entry."""
        if not validate_entry_id(entry_id):
            raise ValueError(f"Invalid entry ID: {entry_id}")
        if not validate_username(user):
            raise ValueError(f"Invalid username: {user}")
        
        sanitized_text = sanitize_text(text, MAX_COMMENT_LENGTH)
        if not sanitized_text:
            raise ValueError("Comment text cannot be empty")
        
        # Check comment limit
        existing = self.comments.get(entry_id, [])
        if len(existing) >= MAX_COMMENTS_PER_ENTRY:
            raise ValueError(f"Maximum comments ({MAX_COMMENTS_PER_ENTRY}) reached for this entry")
        
        comment = Comment(
            id=f"{entry_id}_{len(existing)}_{datetime.now().timestamp()}",
            entry_id=entry_id,
            user=sanitize_text(user),
            text=sanitized_text,
            parent_id=sanitize_text(parent_id) if parent_id else None
        )
        
        self.comments[entry_id].append(comment)
        
        file_path = self.entries.get(entry_id, {}).file_path if entry_id in self.entries else None
        self._mark_dirty(file_path)
        self._trigger_sync(urgent=True)
        self._save_file_data(file_path)
        
        # Log comment
        self.logs.append(TranslationLogEntry(
            id=entry_id,
            action="comment",
            user=sanitize_text(user),
            comment=sanitized_text
        ))
        self._mark_dirty(file_path)
        self._save_file_data(file_path)
        
        return comment
    
    def get_comments(self, entry_id: str) -> List[Comment]:
        """Get all comments for an entry."""
        return self.comments.get(entry_id, [])
    
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
            id=entry_id,
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
        return [log for log in self.logs if log.id == entry_id]
    
    def get_recent_activity(self, limit: int = 50) -> List[TranslationLogEntry]:
        """Get recent translation activity across all entries."""
        return sorted(self.logs, key=lambda x: x.timestamp, reverse=True)[:min(limit, 1000)]
    
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

    def get_unapproved_entries_with_comments(self) -> List[Dict]:
        """Get all unapproved entries with comment count."""
        result = []
        # Only get entries from translation_manager (these have history/comments)
        for entry in self.entries.values():
            if entry.status != 'approved':
                comment_count = len(self.comments.get(entry.id, []))
                result.append({
                    'entry': entry.to_dict(),
                    'comment_count': comment_count
                })

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
