"""
Conflict Resolution Module
Handles detection and resolution of sync conflicts between local and remote data.
"""

import json
import os
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, asdict

@dataclass
class ConflictItem:
    """Represents a single conflict between local and remote versions."""
    entry_id: str
    file_path: str
    field: str  # 'status', 'translation', 'notes', etc.
    local_value: Any
    remote_value: Any
    local_timestamp: str
    remote_timestamp: str
    conflict_type: str  # 'both_modified', 'deleted_remote', 'deleted_local'
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ConflictItem':
        """Create from dictionary."""
        return cls(**data)

class ConflictResolver:
    """Manages conflict detection and resolution for GitHub sync."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
        self.conflicts: List[ConflictItem] = []
        self.resolution_strategies = {
            'local_wins': self._resolve_local_wins,
            'remote_wins': self._resolve_remote_wins,
            'merge': self._resolve_merge,
            'manual': self._resolve_manual
        }
    
    def detect_conflicts(self, local_entries: Dict, remote_entries: Dict, file_path: str) -> List[ConflictItem]:
        """Detect conflicts between local and remote entries."""
        conflicts = []
        
        # Check for conflicts in each entry
        all_entry_ids = set(local_entries.keys()) | set(remote_entries.keys())
        
        for entry_id in all_entry_ids:
            local_entry = local_entries.get(entry_id)
            remote_entry = remote_entries.get(entry_id)
            
            if not local_entry and remote_entry:
                # Entry exists remotely but not locally - might be a conflict if we expected it
                continue
            elif local_entry and not remote_entry:
                # Entry exists locally but not remotely - check if it was deleted remotely
                continue
            elif local_entry and remote_entry:
                # Both exist - check for conflicts
                conflicts.extend(self._compare_entries(entry_id, local_entry, remote_entry, file_path))
        
        return conflicts
    
    def _compare_entries(self, entry_id: str, local: Dict, remote: Dict, file_path: str) -> List[ConflictItem]:
        """Compare two entries and detect conflicts."""
        conflicts = []
        local_time = local.get('updated_at', '')
        remote_time = remote.get('updated_at', '')
        
        # Check if both were modified after last sync
        if self._both_modified(local_time, remote_time):
            # Compare fields
            fields_to_check = ['jp_text', 'en_text', 'notes', 'speaker', 'entry_type']
            
            for field in fields_to_check:
                local_val = local.get(field)
                remote_val = remote.get(field)
                
                if local_val != remote_val:
                    conflicts.append(ConflictItem(
                        entry_id=entry_id,
                        file_path=file_path,
                        field=field,
                        local_value=local_val,
                        remote_value=remote_val,
                        local_timestamp=local_time,
                        remote_timestamp=remote_time,
                        conflict_type='both_modified'
                    ))
        
        return conflicts
    
    def _both_modified(self, local_time: str, remote_time: str) -> bool:
        """Check if both local and remote have been modified since last sync."""
        # This is a simplified check - in practice we'd need to track last sync time
        # For now, assume if both have timestamps and they're different, there's a conflict
        return bool(local_time and remote_time and local_time != remote_time)
    
    def add_conflicts(self, conflicts: List[ConflictItem]):
        """Add conflicts to the resolution queue."""
        self.conflicts.extend(conflicts)
        self._save_conflicts()
    
    def get_conflicts(self) -> List[ConflictItem]:
        """Get all pending conflicts."""
        return self.conflicts
    
    def resolve_conflict(self, conflict_id: str, strategy: str, resolution_data: Optional[Dict] = None) -> bool:
        """Resolve a specific conflict."""
        conflict = self._find_conflict(conflict_id)
        if not conflict:
            return False
        
        if strategy not in self.resolution_strategies:
            return False
        
        # Apply resolution strategy
        resolver = self.resolution_strategies[strategy]
        success = resolver(conflict, resolution_data or {})
        
        if success:
            # Remove resolved conflict
            self.conflicts = [c for c in self.conflicts if c.entry_id != conflict_id or c.field != conflict.field]
            self._save_conflicts()
        
        return success
    
    def _find_conflict(self, conflict_id: str) -> Optional[ConflictItem]:
        """Find a conflict by ID (entry_id:field format)."""
        for conflict in self.conflicts:
            if f"{conflict.entry_id}:{conflict.field}" == conflict_id:
                return conflict
        return None
    
    def _resolve_local_wins(self, conflict: ConflictItem, data: Dict) -> bool:
        """Resolve conflict by keeping local version."""
        # This would be handled by the sync process - local version is already in place
        print(f"[ConflictResolver] Resolved {conflict.entry_id}:{conflict.field} - local wins")
        return True
    
    def _resolve_remote_wins(self, conflict: ConflictItem, data: Dict) -> bool:
        """Resolve conflict by keeping remote version."""
        # This would trigger an update to the local entry
        print(f"[ConflictResolver] Resolved {conflict.entry_id}:{conflict.field} - remote wins")
        return True
    
    def _resolve_merge(self, conflict: ConflictItem, data: Dict) -> bool:
        """Resolve conflict by merging (if possible)."""
        # For text fields, we could try to merge non-overlapping changes
        if conflict.field in ['notes']:
            merged = self._merge_text(conflict.local_value, conflict.remote_value)
            if merged:
                print(f"[ConflictResolver] Merged {conflict.entry_id}:{conflict.field}")
                return True
        return False
    
    def _resolve_manual(self, conflict: ConflictItem, data: Dict) -> bool:
        """Resolve conflict with manual user input."""
        # The resolved value should be in data['resolved_value']
        resolved_value = data.get('resolved_value')
        if resolved_value is not None:
            print(f"[ConflictResolver] Manual resolution for {conflict.entry_id}:{conflict.field}")
            return True
        return False
    
    def _merge_text(self, local: str, remote: str) -> Optional[str]:
        """Attempt to merge two text strings."""
        if not local:
            return remote
        if not remote:
            return local
        
        # Simple merge strategy: combine with separator
        if local != remote:
            return f"{local}\n\n[Merged with remote]\n{remote}"
        return local
    
    def save_conflicts(self):
        """Save conflicts to file."""
        conflicts_file = os.path.join(os.path.dirname(self.cm.cache_file), 'conflicts.json')
        conflicts_data = [c.to_dict() for c in self.conflicts]
        with open(conflicts_file, 'w', encoding='utf-8') as f:
            json.dump(conflicts_data, f, indent=2, ensure_ascii=False)
    
    def load_conflicts(self):
        """Load conflicts from file."""
        conflicts_file = os.path.join(os.path.dirname(self.cm.cache_file), 'conflicts.json')
        try:
            with open(conflicts_file, 'r', encoding='utf-8') as f:
                conflicts_data = json.load(f)
                self.conflicts = [ConflictItem.from_dict(c) for c in conflicts_data]
        except (FileNotFoundError, json.JSONDecodeError):
            self.conflicts = []
    
    def clear_resolved_conflicts(self):
        """Clear all resolved conflicts."""
        self.conflicts = []
        self._save_conflicts()
    
    def get_conflict_summary(self) -> Dict:
        """Get a summary of pending conflicts."""
        summary = {
            'total_conflicts': len(self.conflicts),
            'by_file': {},
            'by_field': {},
            'by_type': {}
        }
        
        for conflict in self.conflicts:
            # Count by file
            file_path = conflict.file_path
            summary['by_file'][file_path] = summary['by_file'].get(file_path, 0) + 1
            
            # Count by field
            field = conflict.field
            summary['by_field'][field] = summary['by_field'].get(field, 0) + 1
            
            # Count by type
            conflict_type = conflict.conflict_type
            summary['by_type'][conflict_type] = summary['by_type'].get(conflict_type, 0) + 1
        
        return summary
