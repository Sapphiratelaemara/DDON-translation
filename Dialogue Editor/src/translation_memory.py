"""
Translation Memory Module - TM with fuzzy matching and auto-substitution
Stores translation units with metadata, context, and quality tracking.
"""

import json
import os
import uuid
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import threading
from difflib import SequenceMatcher

# Test mode flag - check environment variable to avoid circular import
TEST_MODE = os.environ.get('DDON_TEST_MODE', 'false').lower() == 'true'

# Debug logging
DEBUG_ENABLED = True
logger = logging.getLogger('DDON_Editor.TranslationMemory')

def debug_log(message, level='DEBUG'):
    """Log debug message (only when TEST_MODE is enabled)."""
    if not DEBUG_ENABLED or not TEST_MODE:
        return
    log_func = getattr(logger, level.lower(), logger.debug)
    log_func(message)


class TranslationMemory:
    """Manages translation memory with enhanced data structure."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
        self._lock = threading.RLock()
        self.tm_file = os.path.join(
            os.path.dirname(self.cm.user_settings_file),
            "translation_memory.json"
        )
        self.entries = []
        self._exact_match_index = {}  # Hash map for exact lookups: normalized_source -> entry
        self.stats = {
            "total_entries": 0,
            "approved_count": 0,
            "draft_count": 0
        }
        self._load()
    
    def _load(self):
        """Load TM from file."""
        debug_log(f"Loading TM from: {self.tm_file}")
        with self._lock:
            try:
                if os.path.exists(self.tm_file):
                    with open(self.tm_file, 'r', encoding='utf-8-sig') as f:
                        data = json.load(f)
                    if data.get("version") == 2:
                        self.entries = data.get("entries", [])
                        self.stats = data.get("stats", {})
                        debug_log(f"Loaded TM with {len(self.entries)} entries (version 2)")
                    else:
                        # Migrate old format
                        self.entries = data.get("entries", [])
                        self.stats = {"total_entries": len(self.entries), "approved_count": len(self.entries), "draft_count": 0}
                        debug_log(f"Loaded TM with {len(self.entries)} entries (old format migrated)")
                else:
                    self.entries = []
                    self.stats = {"total_entries": 0, "approved_count": 0, "draft_count": 0}
                    debug_log("TM file not found, starting with empty TM")
                
                # Build exact match index
                self._rebuild_index()
            except (json.JSONDecodeError, IOError) as e:
                debug_log(f"Error loading TM: {e}", level='ERROR')
                print(f"[TM] Error loading TM: {e}")
                self.entries = []
                self.stats = {"total_entries": 0, "approved_count": 0, "draft_count": 0}
                self._exact_match_index = {}
    
    def _rebuild_index(self):
        """Rebuild the exact match index from entries."""
        self._exact_match_index = {}
        for entry in self.entries:
            normalized = re.sub(r'\s+', ' ', entry.get("source", "").strip())
            if normalized:
                if normalized not in self._exact_match_index:
                    self._exact_match_index[normalized] = []
                self._exact_match_index[normalized].append(entry)
        debug_log(f"Rebuilt exact match index with {len(self._exact_match_index)} unique sources, {sum(len(v) for v in self._exact_match_index.values())} total entries")
    
    def _save(self):
        """Save TM to file."""
        with self._lock:
            try:
                self._update_stats()
                data = {
                    "version": 2,
                    "entries": self.entries,
                    "stats": self.stats
                }
                # Use no indentation for large files to avoid corruption
                indent = None if len(self.entries) > 1000 else 4
                with open(self.tm_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=indent, ensure_ascii=False)
            except IOError as e:
                print(f"[TM] Error saving TM: {e}")
    
    def _update_stats(self):
        """Update statistics."""
        self.stats["total_entries"] = len(self.entries)
        self.stats["approved_count"] = sum(1 for e in self.entries if e.get("quality") == "approved")
        self.stats["draft_count"] = sum(1 for e in self.entries if e.get("quality") == "draft")
    
    def validate_entry(self, entry: Dict[str, Any]) -> bool:
        """Validate a TM entry has required fields."""
        required = ["id", "source", "translation", "context", "quality", "timestamp"]
        return all(key in entry for key in required)
    
    def add_entry(self, entry_data: Dict[str, Any]) -> str:
        """Add a new entry to TM."""
        from src.translation_manager import generate_entry_id
        debug_log(f"add_entry called with source: {entry_data.get('source', '')[:50]}...")
        with self._lock:
            # Generate entry ID from source text (hash-based)
            entry_id = generate_entry_id(entry_data["source"])
            entry = {
                "id": entry_id,
                "source": entry_data["source"],
                "translation": entry_data["translation"],
                "context": entry_data.get("context", {}),
                "quality": entry_data.get("quality", "draft"),
                "timestamp": entry_data.get("timestamp", datetime.now().isoformat()),
                "match_count": entry_data.get("match_count", 0),
                "last_used": entry_data.get("last_used", None)
            }

            # Check for duplicate source
            for existing in self.entries:
                if existing["source"] == entry["source"] and existing["context"] == entry["context"]:
                    # Update existing instead of duplicate
                    debug_log(f"add_entry: Updating existing entry {existing['id']}")
                    existing.update(entry)
                    self._save()
                    return existing["id"]

            debug_log(f"add_entry: Adding new entry {entry['id']}")
            self.entries.append(entry)
            self._save()
            return entry["id"]
    
    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Get an entry by ID."""
        with self._lock:
            for entry in self.entries:
                if entry["id"] == entry_id:
                    return entry
            return None
    
    def find_by_source(self, source: str) -> List[Dict[str, Any]]:
        """Find all entries with exact source match."""
        with self._lock:
            return [e for e in self.entries if e["source"] == source]
    
    def increment_match_count(self, entry_id: str):
        """Increment match count and update last_used timestamp."""
        with self._lock:
            for entry in self.entries:
                if entry["id"] == entry_id:
                    entry["match_count"] = entry.get("match_count", 0) + 1
                    entry["last_used"] = datetime.now().isoformat()
                    self._save()
                    return True
            return False
    
    def update_entry(self, entry_id: str, updates: Dict[str, Any]) -> bool:
        """Update an entry."""
        with self._lock:
            for entry in self.entries:
                if entry["id"] == entry_id:
                    entry.update(updates)
                    self._save()
                    return True
            return False
    
    def delete_entry(self, entry_id: str) -> bool:
        """Delete an entry."""
        with self._lock:
            original_count = len(self.entries)
            self.entries = [e for e in self.entries if e["id"] != entry_id]
            if len(self.entries) < original_count:
                self._save()
                return True
            return False
    
    def migrate_from_memory(self, old_memory: Dict[str, str]) -> int:
        """Migrate entries from old memory.json format."""
        with self._lock:
            migrated_count = 0
            for source, translation in old_memory.items():
                # Check if already exists
                existing = self.find_by_source(source)
                if not existing:
                    self.add_entry({
                        "source": source,
                        "translation": translation,
                        "context": {},
                        "quality": "approved",  # Migrated entries are approved by default
                        "match_count": 0
                    })
                    migrated_count += 1
            return migrated_count
    
    def export_to_json(self) -> str:
        """Export TM as JSON string."""
        with self._lock:
            return json.dumps({
                "version": 2,
                "entries": self.entries,
                "stats": self.stats
            }, indent=2, ensure_ascii=False)
    
    def import_from_json(self, json_str: str) -> int:
        """Import entries from JSON string."""
        with self._lock:
            data = json.loads(json_str)
            entries = data.get("entries", [])
            imported_count = 0
            for entry in entries:
                # Check for duplicates
                existing = self.find_by_source(entry["source"])
                if not existing:
                    self.entries.append(entry)
                    imported_count += 1
            self._save()
            return imported_count


class FuzzyMatcher:
    """Fuzzy matching algorithm for Translation Memory."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein distance between two strings."""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison (lowercase, remove extra whitespace, particles)."""
        text = re.sub(r'\s+', ' ', text.lower().strip())
        # Remove common Japanese particles for more lenient matching
        text = re.sub(r'\s*[のをにがへとでを]\s*', '', text)
        return text
    
    def _extract_words(self, text: str) -> List[str]:
        """Extract words from text, preserving order."""
        return re.findall(r'\w+', text.lower())
    
    def _extract_ngrams(self, text: str, n: int = 3) -> List[str]:
        """Extract n-grams from text for character-level similarity."""
        text = text.lower()
        return [text[i:i+n] for i in range(len(text) - n + 1)]
    
    def _ngram_similarity(self, s1: str, s2: str, n: int = 3) -> float:
        """Calculate n-gram similarity (Jaccard index)."""
        ngrams1 = set(self._extract_ngrams(s1, n))
        ngrams2 = set(self._extract_ngrams(s2, n))
        
        if not ngrams1 and not ngrams2:
            return 1.0
        if not ngrams1 or not ngrams2:
            return 0.0
        
        intersection = ngrams1 & ngrams2
        union = ngrams1 | ngrams2
        
        return len(intersection) / len(union) if union else 0.0
    
    def _word_order_similarity(self, s1: str, s2: str) -> float:
        """Calculate word order similarity using SequenceMatcher."""
        words1 = self._extract_words(s1)
        words2 = self._extract_words(s2)
        
        if not words1 or not words2:
            return 1.0 if words1 == words2 else 0.0
        
        # Use difflib SequenceMatcher for better sequence matching
        matcher = SequenceMatcher(None, words1, words2)
        return matcher.ratio()
    
    def _extract_tags(self, text: str) -> List[str]:
        """Extract tags like <tag> and {placeholder} for tag-aware matching."""
        tags = []
        # HTML/XML tags
        tags.extend(re.findall(r'<[^>]+>', text))
        # Placeholder tags
        tags.extend(re.findall(r'\{[^}]+\}', text))
        return tags
    
    def _tag_similarity(self, s1: str, s2: str) -> float:
        """Calculate tag similarity - check if tags match."""
        tags1 = self._extract_tags(s1)
        tags2 = self._extract_tags(s2)
        
        if not tags1 and not tags2:
            return 1.0  # No tags in either, perfect match
        if not tags1 or not tags2:
            return 0.95  # One has tags, other doesn't - slight penalty
        
        # Check if tags match in order
        if tags1 == tags2:
            return 1.0
        
        # Check if tags match regardless of order
        if set(tags1) == set(tags2):
            return 0.95  # Same tags, different order - very high match
        
        # Check if tag count matches (same structure)
        if len(tags1) == len(tags2):
            return 0.85  # Same number of tags, different content
        
        # Partial match
        intersection = set(tags1) & set(tags2)
        return len(intersection) / max(len(tags1), len(tags2))
    
    def _strip_tags(self, text: str) -> str:
        """Remove tags for text comparison."""
        # Remove HTML/XML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Remove placeholder tags
        text = re.sub(r'\{[^}]+\}', '', text)
        return text
    
    def _punctuation_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity ignoring punctuation and Japanese particles."""
        # Strip tags first for cleaner comparison
        s1_stripped = self._strip_tags(s1)
        s2_stripped = self._strip_tags(s2)
        
        # Remove common Japanese particles for comparison
        particles = r'\s*[のをにがへとでを]\s*'
        s1_clean = re.sub(particles, '', s1_stripped.lower())
        s2_clean = re.sub(particles, '', s2_stripped.lower())
        
        # Remove punctuation and compare
        s1_clean = re.sub(r'[^\w\s]', '', s1_clean)
        s2_clean = re.sub(r'[^\w\s]', '', s2_clean)
        
        if s1_clean == s2_clean:
            return 1.0
        
        # Calculate similarity on cleaned strings
        if not s1_clean or not s2_clean:
            return 0.0
        
        distance = self._levenshtein_distance(s1_clean, s2_clean)
        max_len = max(len(s1_clean), len(s2_clean))
        
        return 1.0 - (distance / max_len) if max_len > 0 else 1.0
    
    def _length_similarity(self, s1: str, s2: str) -> float:
        """Calculate length similarity (penalize significant length differences)."""
        len1, len2 = len(s1), len(s2)
        
        if len1 == len2:
            return 1.0
        
        # Penalize length differences less severely
        ratio = min(len1, len2) / max(len1, len2)
        
        # More lenient scoring
        if ratio >= 0.8:
            return 0.95  # Very close in length
        elif ratio >= 0.6:
            return 0.85  # Moderately close
        elif ratio >= 0.4:
            return 0.70  # Some difference
        else:
            return ratio  # Significant difference
    
    def calculate_similarity(self, source1: str, source2: str) -> float:
        """Calculate overall similarity score between two source strings."""
        if source1 == source2:
            return 1.0
        
        # Normalize for comparison
        s1_norm = self._normalize_text(source1)
        s2_norm = self._normalize_text(source2)
        
        if s1_norm == s2_norm:
            # Check if the only difference is case/whitespace (not particles)
            if source1.lower().replace(' ', '') == source2.lower().replace(' ', ''):
                return 1.0  # Exact match ignoring case/whitespace
            return 0.98  # Very high match but not exact (particles removed)
        
        # Calculate component scores
        levenshtein_score = 1.0 - (self._levenshtein_distance(s1_norm, s2_norm) / max(len(s1_norm), len(s2_norm))) if max(len(s1_norm), len(s2_norm)) > 0 else 0.0
        word_order_score = self._word_order_similarity(source1, source2)
        punctuation_score = self._punctuation_similarity(source1, source2)
        length_score = self._length_similarity(source1, source2)
        ngram_score = self._ngram_similarity(source1, source2, n=3)
        tag_score = self._tag_similarity(source1, source2)
        
        # Weighted average (adjusted weights for better accuracy)
        overall_score = (
            levenshtein_score * 0.20 +
            word_order_score * 0.30 +
            punctuation_score * 0.20 +
            length_score * 0.10 +
            ngram_score * 0.15 +  # Increased for better typo detection
            tag_score * 0.05
        )
        
        return max(0.0, min(1.0, overall_score))
    
    def _classify_match(self, score: float) -> str:
        """Classify match type based on score."""
        if score >= 1.0:
            return "perfect"
        elif score >= 0.90:
            return "high"
        elif score >= 0.70:
            return "medium"
        elif score >= 0.50:
            return "low"
        else:
            return "none"
    
    def find_matches(self, query: str, tm_entries: List[Dict], threshold: float = 0.5, exact_match_index: Dict = None) -> List[Dict]:
        """Find all TM entries matching query above threshold."""
        debug_log(f"find_matches called with query: {query[:50]}..., threshold: {threshold}")
        # Normalize query to handle line breaks before comparison
        normalized_query = re.sub(r'\s+', ' ', query.strip())
        matches = []
        seen_translations = set()  # Track translations to deduplicate

        # Check exact match index first (O(1) lookup) if provided
        has_exact_match = False
        if exact_match_index and normalized_query in exact_match_index:
            debug_log(f"find_matches: Found exact match in index")
            exact_entries = exact_match_index[normalized_query]
            # Add all entries with this exact match, deduplicating by translation
            for entry in exact_entries:
                translation = entry.get("translation", "")
                if translation not in seen_translations:
                    seen_translations.add(translation)
                    matches.append({
                        "entry": entry,
                        "score": 1.0,
                        "match_type": "perfect"
                    })
            has_exact_match = True

        # Do fuzzy search on all entries if no exact match or need more results
        # Skip fuzzy search if we have 5+ exact matches (sufficient variety)
        if not has_exact_match or len(matches) < 5:
            debug_log(f"find_matches: Performing fuzzy search on {len(tm_entries)} entries")
            for entry in tm_entries:
                # Skip if already matched exactly (by translation)
                translation = entry.get("translation", "")
                if translation in seen_translations:
                    continue

                # Normalize TM source to handle line breaks
                normalized_source = re.sub(r'\s+', ' ', entry["source"].strip())
                score = self.calculate_similarity(normalized_query, normalized_source)
                if score >= threshold:
                    seen_translations.add(translation)
                    matches.append({
                        "entry": entry,
                        "score": score,
                        "match_type": self._classify_match(score)
                    })

        debug_log(f"find_matches: Found {len(matches)} matches")
        # Sort by score descending, then by timestamp (newest first) for same score
        return sorted(matches, key=lambda x: (x["score"], x["entry"].get("timestamp", "")), reverse=True)


class AutoSubstitutor:
    """Auto-substitution for non-translatable elements in TM suggestions."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
    
    # Patterns for non-translatable elements
    PLACEHOLDER_PATTERN = r'\{[^}]+\}'  # {name}, {player}, etc.
    HTML_TAG_PATTERN = r'<[^>]+>'  # <b>, <i>, <br>, etc.
    NUMBER_PATTERN = r'(?<!\{)\b\d+\.?\d*\b(?!\})'  # Numbers like 123, 1.5 (not inside braces)
    ENTITY_PATTERN = r'&[a-z]+;'  # HTML entities like &nbsp;, &amp;
    
    def extract_elements(self, text: str) -> List[str]:
        """Extract all non-translatable elements from text in order."""
        elements = []
        
        # Find all placeholders
        for match in re.finditer(self.PLACEHOLDER_PATTERN, text):
            elements.append(match.group())
        
        # Find all HTML tags
        for match in re.finditer(self.HTML_TAG_PATTERN, text):
            elements.append(match.group())
        
        # Find all numbers (excluding those inside placeholders)
        for match in re.finditer(self.NUMBER_PATTERN, text):
            elements.append(match.group())
        
        # Find all HTML entities
        for match in re.finditer(self.ENTITY_PATTERN, text):
            elements.append(match.group())
        
        return elements
    
    def substitute(self, tm_translation: str, source_elements: List[str], tm_elements: List[str]) -> str:
        """Substitute elements in TM translation with source elements by position."""
        result = tm_translation
        
        # Replace elements by position (not by value)
        for i, tm_elem in enumerate(tm_elements):
            if i < len(source_elements):
                source_elem = source_elements[i]
                # Replace first occurrence of TM element with source element
                result = result.replace(tm_elem, source_elem, 1)
        
        return result
    
    def apply_auto_substitution(self, source: str, tm_entry: Dict) -> str:
        """Apply auto-substitution to a TM entry."""
        source_elements = self.extract_elements(source)
        tm_elements = self.extract_elements(tm_entry["translation"])
        
        # If element counts don't match, return original translation
        if len(source_elements) != len(tm_elements):
            return tm_entry["translation"]
        
        # If no elements, return original
        if not source_elements:
            return tm_entry["translation"]
        
        # Apply substitution
        return self.substitute(tm_entry["translation"], source_elements, tm_elements)


class CrossLanguageTM:
    """Cross-language Translation Memory sharing."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
    
    def get_available_languages(self) -> List[str]:
        """Get list of available language directories."""
        config_dir = os.path.join(self.cm.base_dir, "config")
        if not os.path.exists(config_dir):
            return []
        
        languages = []
        for item in os.listdir(config_dir):
            item_path = os.path.join(config_dir, item)
            if os.path.isdir(item_path):
                languages.append(item)
        
        return languages
    
    def load_tm_for_language(self, language: str) -> Optional[Dict]:
        """Load TM data for a specific language."""
        tm_file = os.path.join(self.cm.base_dir, "config", language, "translation_memory.json")
        if not os.path.exists(tm_file):
            return None
        
        try:
            with open(tm_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading TM for language {language}: {e}")
            return None
    
    def find_cross_language_matches(self, query: str, source_language: str, target_language: str, threshold: float = 0.7) -> List[Dict]:
        """Find matches from another language's TM."""
        # Load target language TM
        tm_data = self.load_tm_for_language(target_language)
        if not tm_data:
            return []
        
        entries = tm_data.get("entries", [])
        if not entries:
            return []
        
        # Use fuzzy matcher to find matches
        matcher = FuzzyMatcher(self.cm)
        matches = matcher.find_matches(query, entries, threshold)
        
        # Add language info to matches
        for match in matches:
            match["source_language"] = source_language
            match["target_language"] = target_language
        
        return matches
    
    def share_translation(self, entry_id: str, target_language: str) -> bool:
        """Share a translation entry to another language's TM."""
        # Load current TM
        current_tm = TranslationMemory(self.cm)
        entry = current_tm.get_entry(entry_id)
        
        if not entry:
            return False
        
        # Load target TM
        target_tm_data = self.load_tm_for_language(target_language)
        if target_tm_data is None:
            # Create new TM file for target language
            target_tm_data = {"entries": []}
        
        # Check for duplicates in target TM
        for existing_entry in target_tm_data.get("entries", []):
            if existing_entry["source"] == entry["source"]:
                return False  # Already exists
        
        # Add entry to target TM
        target_tm_data.setdefault("entries", []).append(entry)
        
        # Save target TM
        target_tm_file = os.path.join(self.cm.base_dir, "config", target_language, "translation_memory.json")
        try:
            with open(target_tm_file, 'w', encoding='utf-8') as f:
                json.dump(target_tm_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving TM for language {target_language}: {e}")
            return False


class TMManager:
    """Translation Memory management tools (view, edit, export, import)."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
        self.tm = TranslationMemory(config_manager)
    
    def get_all_entries(self, filters: Optional[Dict] = None) -> List[Dict]:
        """Get all TM entries with optional filtering."""
        entries = self.tm.entries.copy()
        
        if filters:
            # Filter by quality
            if "quality" in filters:
                entries = [e for e in entries if e.get("quality") == filters["quality"]]
            
            # Filter by minimum match count
            if "min_match_count" in filters:
                entries = [e for e in entries if e.get("match_count", 0) >= filters["min_match_count"]]
            
            # Filter by date range
            if "date_from" in filters:
                entries = [e for e in entries if e.get("timestamp", "") >= filters["date_from"]]
            if "date_to" in filters:
                entries = [e for e in entries if e.get("timestamp", "") <= filters["date_to"]]
        
        return entries
    
    def export_tm(self, filepath: str, format: str = "json") -> bool:
        """Export TM to file."""
        try:
            data = {
                "version": "1.0",
                "exported_at": datetime.now().isoformat(),
                "language": self.cm.language,
                "entries": self.tm.entries
            }
            
            if format == "json":
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            elif format == "csv":
                import csv
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["id", "source", "translation", "quality", "timestamp", "match_count"])
                    for entry in self.tm.entries:
                        writer.writerow([
                            entry.get("id", ""),
                            entry.get("source", ""),
                            entry.get("translation", ""),
                            entry.get("quality", ""),
                            entry.get("timestamp", ""),
                            entry.get("match_count", 0)
                        ])
            else:
                return False
            
            return True
        except Exception as e:
            print(f"Error exporting TM: {e}")
            return False
    
    def import_tm(self, filepath: str, format: str = "json", merge: bool = True) -> Dict:
        """Import TM from file."""
        try:
            if format == "json":
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                entries = data.get("entries", [])
            elif format == "csv":
                import csv
                entries = []
                with open(filepath, 'r', encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        from src.translation_manager import generate_entry_id
                        source = row.get("source", "")
                        entry_id = generate_entry_id(source)
                        entries.append({
                            "id": entry_id,
                            "source": source,
                            "translation": row.get("translation", ""),
                            "quality": row.get("quality", "draft"),
                            "timestamp": row.get("timestamp", datetime.now().isoformat()),
                            "match_count": int(row.get("match_count", 0)),
                            "context": {}
                        })
            else:
                return {"success": False, "imported": 0, "skipped": 0}
            
            imported_count = 0
            skipped_count = 0
            
            for entry in entries:
                if merge:
                    # Check for duplicates
                    existing = self.tm.find_by_source(entry["source"])
                    if existing:
                        skipped_count += 1
                        continue
                
                self.tm.add_entry(entry)
                imported_count += 1
            
            return {
                "success": True,
                "imported": imported_count,
                "skipped": skipped_count
            }
        except Exception as e:
            print(f"Error importing TM: {e}")
            return {"success": False, "imported": 0, "skipped": 0}
    
    def get_statistics(self) -> Dict:
        """Get TM statistics."""
        entries = self.tm.entries
        
        total = len(entries)
        by_quality = {}
        total_matches = 0
        
        for entry in entries:
            quality = entry.get("quality", "unknown")
            by_quality[quality] = by_quality.get(quality, 0) + 1
            total_matches += entry.get("match_count", 0)
        
        return {
            "total_entries": total,
            "by_quality": by_quality,
            "total_matches": total_matches,
            "language": self.cm.language
        }
