"""
prefetch_manager.py - Background processing queue for editor entries

Processes subsequent entries in the background while user works on current entry.
Caches results for instant display when user switches entries.
"""

import threading
import queue
import time
import json
import os
from typing import Dict, Any, Optional

class PrefetchManager:
    """Manages background prefetching of editor entries."""
    
    def __init__(self, lore_engine_getter=None, cache_file=None, language=None, get_adjacent_context_getter=None, gloss_engine_getter=None, tm_getter=None):
        self._queue = queue.Queue()
        self._cache: Dict[str, Dict[str, Any]] = {}  # Use string keys for JSON serialization
        self._processing = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._current_idx = -1
        self._current_category = None
        self._lock = threading.Lock()
        self._lore_engine_getter = lore_engine_getter
        self._get_adjacent_context_getter = get_adjacent_context_getter
        self._gloss_engine_getter = gloss_engine_getter
        self._tm_getter = tm_getter
        self._language = language  # Store language directly
        # Default cache file path will be set in _get_cache_path()
        self._cache_file = cache_file
        self._load_cache_from_file()
    
    def _get_cache_path(self):
        """Get the cache file path based on current language."""
        if self._cache_file:
            return self._cache_file
        base_dir = None
        try:
            import sys
            if 'main' in sys.modules:
                cm = sys.modules['main'].cm if hasattr(sys.modules['main'], 'cm') else None
                if cm and hasattr(cm, 'base_dir'):
                    base_dir = cm.base_dir
        except Exception:
            pass
        if not base_dir:
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        language = self._language
        if not language:
            try:
                import sys
                if 'main' in sys.modules:
                    cm = sys.modules['main'].cm if hasattr(sys.modules['main'], 'cm') else None
                    if cm and hasattr(cm, 'language'):
                        language = cm.language
            except Exception:
                pass
        if not language:
            return None
        import os
        config_dir = os.path.join(base_dir, "config", language)
        return os.path.join(config_dir, "prefetch_cache.json")
    
    def _cache_key(self, category: str, idx: int) -> str:
        """Convert category and index to a string key for JSON serialization."""
        return f"{category}::{idx}"
    
    def _load_cache_from_file(self):
        """Load cache from file on startup, removing entries older than 7 days."""
        try:
            import os
            import json
            cache_path = self._get_cache_path()
            if cache_path and os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                # Remove entries older than 7 days (604800 seconds)
                current_time = time.time()
                seven_days_ago = current_time - 604800
                self._cache = {
                    k: v for k, v in cached_data.items()
                    if v.get('timestamp', 0) > seven_days_ago
                }
                print(f"[PrefetchManager] Loaded {len(self._cache)} cached items from file (removed {len(cached_data) - len(self._cache)} expired entries)")
        except json.JSONDecodeError as e:
            print(f"[PrefetchManager] Cache file corrupted, clearing cache: {e}")
            self._cache = {}
            # Try to delete the corrupted file
            try:
                import os
                cache_path = self._get_cache_path()
                if cache_path and os.path.exists(cache_path):
                    os.remove(cache_path)
                    print(f"[PrefetchManager] Deleted corrupted cache file")
            except Exception as e:
                print(f"[PrefetchManager] Error deleting corrupted cache file: {e}")
        except Exception as e:
            print(f"[PrefetchManager] Error loading cache from file: {e}")
            self._cache = {}
    
    def _save_cache_to_file(self):
        """Save cache to file."""
        try:
            import os
            import json
            cache_path = self._get_cache_path()
            if not cache_path:
                return  # Skip saving if no config available
            # Ensure directory exists
            cache_dir = os.path.dirname(cache_path)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f)
        except Exception as e:
            print(f"[PrefetchManager] Error saving cache to file: {e}")
        
    def start(self):
        """Start the background worker thread."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
    
    def stop(self):
        """Stop the background worker thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None
    
    def _worker_loop(self):
        """Background worker that processes prefetch requests."""
        print(f"[PrefetchManager] Worker thread started")
        while not self._stop_event.is_set():
            try:
                # Wait for work with timeout to check stop event
                task = self._queue.get(timeout=0.5)
                if task is None:
                    continue

                # Task format: (category, idx, item)
                category, idx, item = task
                print(f"[PrefetchManager] Processing task: category={category}, idx={idx}")
                self._process_item(category, idx, item)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[PrefetchManager] Error processing item: {e}")
        print(f"[PrefetchManager] Worker thread stopped")
    
    def _process_item(self, category: str, idx: int, item: Dict[str, Any]):
        """Process a single item and cache the results.

        Args:
            category: Category name
            idx: Item index
            item: Item data
        """
        try:
            results = {
                'idx': idx,
                'lore_context': None,
                'anachronisms': None,
                'adjacent_context': None,
                'gloss_result': None,
                'timestamp': time.time()
            }

            # Get lore context
            try:
                le = self._lore_engine_getter() if self._lore_engine_getter else None
                if le and item.get('jp'):
                    results['lore_context'] = le.scan_text(item['jp'])
            except Exception as e:
                print(f"[PrefetchManager] Lore context error for idx {idx}: {e}")

            # Get anachronisms
            try:
                if item.get('en'):
                    le = self._lore_engine_getter() if self._lore_engine_getter else None
                    if le:
                        results['anachronisms'] = le.scan_anachronisms(item['en'])
            except Exception as e:
                print(f"[PrefetchManager] Anachronisms error for idx {idx}: {e}")

            # Get adjacent context
            try:
                if item.get('path') and item.get('row') is not None:
                    if self._get_adjacent_context_getter:
                        print(f"[PrefetchManager] Fetching adjacent context for idx {idx}, path={item.get('path')}, row={item.get('row')}")
                        get_adjacent_context = self._get_adjacent_context_getter()
                        if get_adjacent_context:
                            results['adjacent_context'] = get_adjacent_context(item['path'], item['row'])
                            print(f"[PrefetchManager] Got adjacent context for idx {idx}: {results['adjacent_context'] is not None}")
                        else:
                            print(f"[PrefetchManager] get_adjacent_context_getter returned None for idx {idx}")
                    else:
                        print(f"[PrefetchManager] get_adjacent_context_getter not set for idx {idx}")
                else:
                    print(f"[PrefetchManager] Missing path or row for adjacent context, idx {idx}: path={item.get('path')}, row={item.get('row')}")
            except Exception as e:
                print(f"[PrefetchManager] Adjacent context error for idx {idx}: {e}")
            
            # Get gloss result - check ConfigManager cache first, generate if not cached
            try:
                if item.get('jp'):
                    from src.config_manager import ConfigManager
                    cm = ConfigManager()
                    cached = cm.get_cached("gloss", item['jp'])
                    if cached:
                        results['gloss_result'] = cached
                    else:
                        # Generate gloss result in background
                        import re
                        jp_text = item['jp']
                        # Strip tags
                        tag_map = cm.config.get("tag_map", {})
                        for tag_key in tag_map.keys():
                            jp_text = jp_text.replace(f"<{tag_key}>", "")
                        jp_text = re.sub(r'<[^>]+>', '', jp_text)
                        
                        # Import gloss engine
                        if self._gloss_engine_getter:
                            ge = self._gloss_engine_getter()
                            if ge:
                                # Run gloss with timeout
                                import threading
                                result_container = [None]
                                def _run_gloss():
                                    try:
                                        tokens = ge.gloss(jp_text)
                                        result = [
                                            {
                                                "surface": t.surface,
                                                "pos": t.pos,
                                                "candidates": t.candidates[:5] if t.candidates else [],
                                                "is_lore": t.is_lore,
                                            }
                                            for t in tokens
                                        ]
                                        result_container[0] = result
                                    except Exception as e:
                                        print(f"[PrefetchManager] Gloss generation error for idx {idx}: {e}")
                                
                                thread = threading.Thread(target=_run_gloss, daemon=True)
                                thread.start()
                                thread.join(timeout=10.0)  # 10 second timeout for prefetch
                                
                                if result_container[0]:
                                    results['gloss_result'] = result_container[0]
                                    cm.set_cached("gloss", item['jp'], result_container[0])
                        else:
                            print(f"[PrefetchManager] gloss_engine_getter not set for idx {idx}")
            except Exception as e:
                print(f"[PrefetchManager] Gloss processing error for idx {idx}: {e}")
            
            # Get TM matches
            try:
                if item.get('jp') and self._tm_getter:
                    tm_instance, tm_matcher, tm_lock = self._tm_getter()
                    with tm_lock:
                        if tm_matcher:
                            print(f"[PrefetchManager] Fetching TM matches for idx={idx}")
                            matches = tm_matcher.find_matches(item['jp'], tm_instance.entries, 0.7, tm_instance._exact_match_index)
                            # Limit to top 10 matches
                            results['tm_matches'] = matches[:10]
                            print(f"[PrefetchManager] Got {len(matches)} TM matches for idx={idx}")
            except Exception as e:
                print(f"[PrefetchManager] TM error for idx {idx}: {e}")
            
            # Cache the results with category-aware key
            with self._lock:
                cache_key = self._cache_key(category, idx)
                self._cache[cache_key] = results
                self._save_cache_to_file()
                
            print(f"[PrefetchManager] Cached results for category={category}, idx={idx}")
            
        except Exception as e:
            print(f"[PrefetchManager] Error processing category={category}, idx={idx}: {e}")
    
    def enqueue(self, category: str, idx: int, item: Dict[str, Any]):
        """Add an item to the prefetch queue.

        Args:
            category: Category name
            idx: Item index
            item: Item data
        """
        # Skip if already cached and fresh (within 7 days to match disk cache expiration)
        with self._lock:
            cache_key = self._cache_key(category, idx)
            cached = self._cache.get(cache_key)
            if cached and time.time() - cached['timestamp'] < 604800:  # 7 days
                print(f"[PrefetchManager] Skipping {cache_key} - already cached")
                return

        print(f"[PrefetchManager] Enqueuing {cache_key}")
        self._queue.put((category, idx, item))
    
    def get_cached(self, category: str, idx: int) -> Optional[Dict[str, Any]]:
        """Get cached results for a category and index."""
        with self._lock:
            cache_key = self._cache_key(category, idx)
            return self._cache.get(cache_key)
    
    def update_current_idx(self, category: str, idx: int):
        """Update the current index and category, and trigger prefetching of subsequent entries."""
        with self._lock:
            self._current_idx = idx
            self._current_category = category
            # Clear cache for old entries in different categories (keep last 20 per category)
            if len(self._cache) > 20:
                keys_to_remove = [key for key in self._cache.keys() if not key.startswith(f"{category}::")]
                for key in keys_to_remove:
                    del self._cache[key]
    
    def prefetch_next(self, category: str, items: list, current_idx: int, depth: int = 25):
        """Prefetch the next N entries after the current index.

        Args:
            category: Category name
            items: List of items to prefetch
            current_idx: Current index
            depth: Number of entries to prefetch (default 25)
        """
        for offset in range(1, depth + 1):
            next_idx = current_idx + offset
            if next_idx < len(items):
                self.enqueue(category, next_idx, items[next_idx])

    def prefetch_all(self, category: str, items: list):
        """Prefetch all entries in the queue (for local-only operations like gloss/context).

        Args:
            category: Category name
            items: List of items to prefetch
        """
        print(f"[PrefetchManager] Queuing all {len(items)} items for category={category}")
        for idx in range(len(items)):
            self.enqueue(category, idx, items[idx])
    
    def update_cache(self, category: str, idx: int, data: Dict[str, Any]):
        """Directly update the cache for a specific category and index.
        
        Args:
            category: Category name
            idx: Item index
            data: Data to cache (will be merged with existing cache entry)
        """
        with self._lock:
            cache_key = self._cache_key(category, idx)
            existing = self._cache.get(cache_key, {})
            # Merge with existing data, preserving timestamp if not provided
            if 'timestamp' not in data:
                data['timestamp'] = existing.get('timestamp', time.time())
            existing.update(data)
            self._cache[cache_key] = existing
            self._save_cache_to_file()
            print(f"[PrefetchManager] Updated cache for category={category}, idx={idx}")
    
    def clear_cache(self):
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()
            self._save_cache_to_file()
            # Clear the queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
