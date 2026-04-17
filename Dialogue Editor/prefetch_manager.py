"""
prefetch_manager.py - Background processing queue for editor entries

Processes subsequent entries in the background while user works on current entry.
Caches results for instant display when user switches entries.
"""

import threading
import queue
import time
from typing import Dict, Any, Optional

class PrefetchManager:
    """Manages background prefetching of editor entries."""
    
    def __init__(self, lore_engine_getter=None, cache_file="prefetch_cache.json"):
        self._queue = queue.Queue()
        self._cache: Dict[str, Dict[str, Any]] = {}  # Use string keys for JSON serialization
        self._processing = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._current_idx = -1
        self._current_category = None
        self._lock = threading.Lock()
        self._lore_engine_getter = lore_engine_getter
        self._cache_file = cache_file
        self._load_cache_from_file()
    
    def _cache_key(self, category: str, idx: int) -> str:
        """Convert category and index to a string key for JSON serialization."""
        return f"{category}::{idx}"
    
    def _load_cache_from_file(self):
        """Load cache from file on startup, removing entries older than 7 days."""
        try:
            import os
            import json
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cache_path = os.path.join(base_dir, self._cache_file)
            if os.path.exists(cache_path):
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
                base_dir = os.path.dirname(os.path.abspath(__file__))
                cache_path = os.path.join(base_dir, self._cache_file)
                if os.path.exists(cache_path):
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
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cache_path = os.path.join(base_dir, self._cache_file)
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
        while not self._stop_event.is_set():
            try:
                # Wait for work with timeout to check stop event
                task = self._queue.get(timeout=0.5)
                if task is None:
                    continue
                    
                category, idx, item = task
                self._process_item(category, idx, item)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[PrefetchManager] Error processing item: {e}")
    
    def _process_item(self, category: str, idx: int, item: Dict[str, Any]):
        """Process a single item and cache the results."""
        try:
            results = {
                'idx': idx,
                'lore_context': None,
                'anachronisms': None,
                'adjacent_context': None,
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
            
            # Cache the results with category-aware key
            with self._lock:
                cache_key = self._cache_key(category, idx)
                self._cache[cache_key] = results
                self._save_cache_to_file()
                
            print(f"[PrefetchManager] Cached results for category={category}, idx={idx}")
            
        except Exception as e:
            print(f"[PrefetchManager] Error processing category={category}, idx={idx}: {e}")
    
    def enqueue(self, category: str, idx: int, item: Dict[str, Any]):
        """Add an item to the prefetch queue."""
        # Skip if already cached and fresh (within 5 minutes)
        with self._lock:
            cache_key = self._cache_key(category, idx)
            cached = self._cache.get(cache_key)
            if cached and time.time() - cached['timestamp'] < 300:
                return
        
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
    
    def prefetch_next(self, category: str, items: list, current_idx: int, depth: int = 3):
        """Prefetch the next N entries after the current index."""
        for offset in range(1, depth + 1):
            next_idx = current_idx + offset
            if next_idx < len(items):
                self.enqueue(category, next_idx, items[next_idx])
    
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
