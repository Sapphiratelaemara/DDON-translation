"""
GitHub Sync Module - Optimized version with throttling and per-file storage
Handles syncing translation data with a GitHub repository.
"""

import json
import os
import base64
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
import requests
import re

# Sync timing constants
PUSH_INTERVAL_DEFAULT = 1800  # 30 minutes
PUSH_INTERVAL_COMMENT = 60    # 1 minute after comment
PULL_INTERVAL = 1800          # 30 minutes

class GitHubSync:
    """Manages syncing translation data with a GitHub repository with throttling."""
    
    def __init__(self, config_manager):
        self.cm = config_manager
        self._lock = threading.RLock()
        self._push_timer = None
        self._last_push = 0
        self._last_push_completed = 0
        self._last_pull = 0
        self._pending_push = False
        self._urgent_push = False  # Set True when comment posted
        self._remote_timestamps = {}  # Cache of remote file timestamps
        self._push_in_progress = False
        
    def _get_headers(self) -> Dict[str, str]:
        """Get GitHub API headers with auth token."""
        token = self.cm.user_settings.get('github_token', '')
        return {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
    
    def _get_repo_info(self) -> tuple:
        """Extract owner and repo from config."""
        repo_url = self.cm.user_settings.get('github_repo', '')
        if 'github.com' in repo_url:
            parts = repo_url.replace('.git', '').split('github.com/')[-1].split('/')
            if len(parts) >= 2:
                return parts[0], parts[1]
        return None, None
    
    def _get_file_path(self, file_id: str, entry_id: str = None) -> str:
        """Get the path for a file in the language folder.
        
        file_id: 'status', 'logs', 'comments', or a specific filename
        entry_id: optional entry ID for per-file storage
        """
        language = self.cm.language
        
        # Handle config files directly
        if file_id in ['archetypes.json', 'dd1_vocab.json', 'other_vocab.json', 'anach_definitions.json', 'archaic_examples.json', 
                       'translation_memory.json', 'formatter_config.json', 'tag_map.json', 'presets.json', 'speaker_data.json',
                       'tag_display.json', 'preview_font.json']:
            return f"{language}/{file_id}"
        
        if entry_id:
            # Per-file storage: sanitize filename from entry_id
            safe_name = self._sanitize_filename(entry_id)
            return f"{language}/{safe_name}/{file_id}.json"
        else:
            # No global status file - status is per-file only
            return None
    
    def _sanitize_filename(self, name: str) -> str:
        """Create safe filename from entry_id."""
        # Extract just the filename from full path
        if '/' in name:
            name = name.split('/')[-1]
        elif '\\' in name:
            name = name.split('\\')[-1]
        
        # For CSV files, extract just the base name without path prefixes
        if name.startswith('C__DDON-translation_English_splits_'):
            name = name.replace('C__DDON-translation_English_splits_', '')
        
        # Remove or replace unsafe characters
        safe = re.sub(r'[<>:"/\\|?*]', '_', name)
        # Limit length
        if len(safe) > 100:
            safe = safe[:100]
        return safe or 'unknown'
    
    def _get_api_url(self, path: str) -> Optional[str]:
        """Build GitHub API URL for a file."""
        owner, repo = self._get_repo_info()
        if not owner or not repo:
            return None
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    
    def is_configured(self) -> bool:
        """Check if sync is properly configured."""
        token = self.cm.user_settings.get('github_token', '')
        repo = self.cm.user_settings.get('github_repo', '')
        return bool(token and repo)
    
    def _fetch_remote_file(self, file_path: str) -> Optional[Dict]:
        """Fetch a file from GitHub. Returns dict with content, sha, and last_modified."""
        url = self._get_api_url(file_path)
        if not url:
            return None
        
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=30)
            if resp.status_code == 404:
                return None
            if resp.status_code == 304:
                return {'unchanged': True}
            if resp.status_code != 200:
                print(f"[GitHubSync] Failed to fetch {file_path}: {resp.status_code}")
                return None
            
            data = resp.json()
            # Handle large files with encoding='none' - use download_url
            if data.get('encoding') == 'none':
                download_url = data.get('download_url')
                if download_url:
                    resp = requests.get(download_url, headers=self._get_headers(), timeout=30)
                    if resp.status_code == 200:
                        # For translation_memory.json, this is compressed binary data
                        content = resp.content  # Binary
                        # Try to decompress if it's gzip
                        import gzip
                        try:
                            decompressed = gzip.decompress(content).decode('utf-8')
                            return {
                                'content': json.loads(decompressed),
                                'sha': data['sha'],
                                'last_modified': data.get('commit', {}).get('html_url', ''),
                                'timestamp': datetime.now().isoformat()
                            }
                        except (gzip.BadGzipFile, UnicodeDecodeError, json.JSONDecodeError):
                            # Not compressed or not gzip, return as-is
                            try:
                                return {
                                    'content': json.loads(content.decode('utf-8')),
                                    'sha': data['sha'],
                                    'last_modified': data.get('commit', {}).get('html_url', ''),
                                    'timestamp': datetime.now().isoformat()
                                }
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                return {
                                    'content': content.decode('utf-8', errors='replace'),
                                    'sha': data['sha'],
                                    'last_modified': data.get('commit', {}).get('html_url', ''),
                                    'timestamp': datetime.now().isoformat()
                                }
                return {
                    'content': {},
                    'sha': data['sha'],
                    'last_modified': data.get('last_modified')
                }
            # Handle empty files
            if not data.get('content'):
                return {
                    'content': {},
                    'sha': data['sha'],
                    'last_modified': data.get('last_modified')
                }
            content = base64.b64decode(data['content']).decode('utf-8')
            return {
                'content': json.loads(content),
                'sha': data['sha'],
                'last_modified': data.get('commit', {}).get('html_url', ''),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            print(f"[GitHubSync] Error fetching {file_path}: {e}")
            return None
    
    def _upload_file(self, file_path: str, content: Any, sha: Optional[str] = None) -> dict:
        """Upload/update a file on GitHub. Returns dict with success status and debug info."""
        url = self._get_api_url(file_path)
        if not url:
            return {"success": False, "error": "no URL"}
        
        try:
            message = f"Update {file_path} - {datetime.now().isoformat()}"
            nickname = self.cm.user_settings.get('sync_nickname', 'Anonymous')
            
            # Check if content is already compressed wrapper
            if isinstance(content, dict) and content.get('compressed'):
                # Already compressed and base64 encoded, use as-is
                payload_content = content['data']
                print(f"[GitHubSync] Uploading compressed content ({len(payload_content)} chars)")
            else:
                # Regular JSON content
                payload_content = base64.b64encode(json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')).decode('utf-8')
            
            payload = {
                'message': message,
                'content': payload_content,
                'committer': {
                    'name': nickname,
                    'email': f'{nickname}@ddon-translation.local'
                }
            }
            if sha:
                payload['sha'] = sha
            
            resp = requests.put(url, headers=self._get_headers(), json=payload, timeout=30)
            if resp.status_code in [200, 201]:
                response_data = resp.json()
                print(f"[GitHubSync] Upload response: content size {len(response_data.get('content', {}).get('content', ''))} chars")
                return {"success": True, "status_code": resp.status_code, "response": response_data}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}", "response": resp.text}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    
    def _should_push(self) -> bool:
        """Check if enough time has passed for a push."""
        elapsed = time.time() - self._last_push
        if self._urgent_push:
            return elapsed >= PUSH_INTERVAL_COMMENT
        return elapsed >= PUSH_INTERVAL_DEFAULT
    
    def _should_pull(self) -> bool:
        """Check if enough time has passed for a pull."""
        elapsed = time.time() - self._last_pull
        return elapsed >= PULL_INTERVAL
    
    def request_push(self, urgent: bool = False):
        """Request a push (called by TranslationManager after saves)."""
        with self._lock:
            self._pending_push = True
            if urgent:
                self._urgent_push = True

            # Cancel any existing timer and schedule new one
            if self._push_timer:
                self._push_timer.cancel()

            # Schedule push based on urgency - always use full interval
            delay = PUSH_INTERVAL_COMMENT if urgent else PUSH_INTERVAL_DEFAULT
            self._push_timer = threading.Timer(delay, self._execute_push)
            self._push_timer.start()

    def _execute_push(self):
        """Execute pending push if conditions are met."""
        with self._lock:
            if not self._pending_push:
                return
            if not self._should_push():
                # Not enough time passed, keep pending and reschedule
                delay = PUSH_INTERVAL_COMMENT if self._urgent_push else PUSH_INTERVAL_DEFAULT
                self._push_timer = threading.Timer(delay, self._execute_push)
                self._push_timer.start()
                return
            self._pending_push = False

            # This will be called from translation_manager context
            # Need to get the translation_manager instance
            from src.translation_manager import get_translation_manager
            tm = get_translation_manager(self.cm.language)
            self.sync_push(tm)
    
    def flush_on_exit(self, translation_manager):
        """Force push on client close."""
        print("[GitHubSync] Flushing on exit...")
        self.sync_push(translation_manager)
    
    def _get_entry_files(self, translation_manager) -> Dict[str, List[str]]:
        """Get list of files that need syncing per entry."""
        # Group entries by their source file
        files_data = {}
        for entry_id, entry in translation_manager.entries.items():
            file_path = entry.file_path or 'unknown'
            if file_path not in files_data:
                files_data[file_path] = {
                    'entries': {},
                    'logs': [],
                    'comments': {}
                }
            files_data[file_path]['entries'][entry_id] = entry
        
        # Distribute logs to their respective files
        for log in translation_manager.logs:
            entry_id = log.id
            if entry_id in translation_manager.entries:
                file_path = translation_manager.entries[entry_id].file_path or 'unknown'
                if file_path not in files_data:
                    files_data[file_path] = {'entries': {}, 'logs': []}
                files_data[file_path]['logs'].append(log)
        
        return files_data
    
    def sync_push(self, translation_manager) -> dict:
        """Push local data to remote (per-file structure). Returns dict with success status and debug info."""
        if not self.is_configured():
            return {"success": False, "error": "not configured"}

        with self._lock:
            # Guard against runaway push loops (e.g. repeated triggers during background work).
            # We keep the app responsive and avoid hammering GitHub if a push was just done.
            now = time.time()
            if self._push_in_progress:
                return {"success": True, "skipped": True, "reason": "push already in progress"}
            if (now - self._last_push_completed) < 55:
                return {"success": True, "skipped": True, "reason": "throttled (recent push)"}

            self._push_in_progress = True
            self._urgent_push = False

            try:
                results = []
                debug_info = []
                language = self.cm.language
                
                # Get config directory from ConfigManager base_dir
                base_dir = self.cm.base_dir
                config_dir = os.path.join(base_dir, "config", language)
                
                # Debug: Log the actual paths being used
                print(f"[GitHubSync] Using base_dir: {base_dir}")
                print(f"[GitHubSync] Using config_dir: {config_dir}")
                
                # Only sync config files if translation_manager is None
                if translation_manager is None:
                    # Only push config files, no translation data
                    pass
                else:
                    # Push translation data
                    pass

                # Push language-level files (archetypes, vocab)
                # Push archetypes
                archetypes_path = self._get_file_path('archetypes.json', None)
                remote_archetypes = self._fetch_remote_file(archetypes_path)
                archetypes_file = os.path.join(config_dir, "archetypes.json")
                
                # Skip if this is a temp/test file (not the real archetypes.json)
                if os.path.exists(archetypes_file) and not any(x in archetypes_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(archetypes_file, 'r', encoding='utf-8-sig') as f:
                        archetypes_content = json.load(f)
                    archetypes_result = self._upload_file(
                        archetypes_path,
                        archetypes_content,
                        remote_archetypes['sha'] if remote_archetypes else None
                    )
                    results.append(archetypes_result.get("success", False))
                    debug_info.append({"file": "archetypes.json", "type": "archetypes", "result": archetypes_result})

                # Push dd1_vocab
                dd1_vocab_path = self._get_file_path('dd1_vocab.json', None)
                remote_dd1_vocab = self._fetch_remote_file(dd1_vocab_path)
                dd1_vocab_file = os.path.join(config_dir, "dd1_vocab.json")
                
                # Skip if this is a temp/test file (not the real dd1_vocab.json)
                if os.path.exists(dd1_vocab_file) and not any(x in dd1_vocab_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(dd1_vocab_file, 'r', encoding='utf-8-sig') as f:
                        dd1_vocab_content = json.load(f)
                    dd1_vocab_result = self._upload_file(
                        dd1_vocab_path,
                        dd1_vocab_content,
                        remote_dd1_vocab['sha'] if remote_dd1_vocab else None
                    )
                    results.append(dd1_vocab_result.get("success", False))
                    debug_info.append({"file": "dd1_vocab.json", "type": "vocab", "result": dd1_vocab_result})

                # Push other_vocab
                other_vocab_path = self._get_file_path('other_vocab.json', None)
                remote_other_vocab = self._fetch_remote_file(other_vocab_path)
                other_vocab_file = os.path.join(config_dir, "other_vocab.json")
                
                # Skip if this is a temp/test file (not the real other_vocab.json)
                if os.path.exists(other_vocab_file) and not any(x in other_vocab_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(other_vocab_file, 'r', encoding='utf-8-sig') as f:
                        other_vocab_content = json.load(f)
                    other_vocab_result = self._upload_file(
                        other_vocab_path,
                        other_vocab_content,
                        remote_other_vocab['sha'] if remote_other_vocab else None
                    )
                    results.append(other_vocab_result.get("success", False))
                    debug_info.append({"file": "other_vocab.json", "type": "vocab", "result": other_vocab_result})

                # Push anach_definitions
                anach_definitions_path = self._get_file_path('anach_definitions.json', None)
                remote_anach_definitions = self._fetch_remote_file(anach_definitions_path)
                anach_file = os.path.join(config_dir, "anach_definitions.json")
                
                # Skip if this is a temp/test file (not the real anach_definitions.json)
                if os.path.exists(anach_file) and not any(x in anach_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(anach_file, 'r', encoding='utf-8-sig') as f:
                        anach_definitions_content = json.load(f)
                    anach_definitions_result = self._upload_file(
                        anach_definitions_path,
                        anach_definitions_content,
                        remote_anach_definitions['sha'] if remote_anach_definitions else None
                    )
                    results.append(anach_definitions_result.get("success", False))
                    debug_info.append({"file": "anach_definitions.json", "type": "definitions", "result": anach_definitions_result})

                # Push archaic_examples
                archaic_examples_path = self._get_file_path('archaic_examples.json', None)
                remote_archaic_examples = self._fetch_remote_file(archaic_examples_path)
                archaic_file = os.path.join(config_dir, "archaic_examples.json")
                
                # Skip if this is a temp/test file (not the real archaic_examples.json)
                if os.path.exists(archaic_file) and not any(x in archaic_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(archaic_file, 'r', encoding='utf-8-sig') as f:
                        archaic_examples_content = json.load(f)
                    archaic_examples_result = self._upload_file(
                        archaic_examples_path,
                        archaic_examples_content,
                        remote_archaic_examples['sha'] if remote_archaic_examples else None
                    )
                    results.append(archaic_examples_result.get("success", False))
                    debug_info.append({"file": "archaic_examples.json", "type": "examples", "result": archaic_examples_result})

                # Push formatter_config (only non-split keys)
                formatter_config_path = self._get_file_path('formatter_config.json', None)
                remote_formatter_config = self._fetch_remote_file(formatter_config_path)
                formatter_config_file = os.path.join(config_dir, "formatter_config.json")
                
                # Skip if this is a temp/test file (not the real formatter_config.json)
                if os.path.exists(formatter_config_file) and not any(x in formatter_config_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(formatter_config_file, 'r', encoding='utf-8-sig') as f:
                        full_config = json.load(f)
                    
                    # Only include shared fields that should be synced (read from separate files, not full_config)
                    formatter_config_content = {
                        "triggers": full_config.get("triggers", []),
                        "styles": {},  # styles.json doesn't exist, keep empty
                        "wall_preset": full_config.get("wall_preset", "Tutorial Box"),
                        "tag_map": self.cm.config.get("tag_map", {}),
                        "substitution_rules": self.cm.config.get("substitution_rules", [])
                    }
                    
                    formatter_config_result = self._upload_file(
                        formatter_config_path,
                        formatter_config_content,
                        remote_formatter_config['sha'] if remote_formatter_config else None
                    )
                    results.append(formatter_config_result.get("success", False))
                    debug_info.append({"file": "formatter_config.json", "type": "formatter", "result": formatter_config_result})

                # Push translation_memory
                translation_memory_path = self._get_file_path('translation_memory.json', None)
                remote_translation_memory = self._fetch_remote_file(translation_memory_path)
                translation_memory_file = os.path.join(config_dir, "translation_memory.json")
                
                # Skip if this is a temp/test file (not the real translation_memory.json)
                if os.path.exists(translation_memory_file) and not any(x in translation_memory_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                    with open(translation_memory_file, 'r', encoding='utf-8-sig') as f:
                        translation_memory_content = json.load(f)
                    print(f"[GitHubSync] Pushing translation_memory.json ({len(translation_memory_content.get('entries', []))} entries)")
                    
                    # Compress with gzip to reduce size for GitHub API
                    import gzip
                    json_str = json.dumps(translation_memory_content, ensure_ascii=False, indent=2)
                    compressed = gzip.compress(json_str.encode('utf-8'))
                    # Wrap with compression marker
                    upload_content = {
                        'compressed': True,
                        'encoding': 'gzip',
                        'data': base64.b64encode(compressed).decode('utf-8')
                    }
                    print(f"[GitHubSync] Compressed TM: {len(json_str)/1024/1024:.2f} MB -> {len(compressed)/1024/1024:.2f} MB ({len(json_str)/len(compressed):.1f}x)")
                    
                    # Handle translation_memory upload with proper SHA handling
                    sha = remote_translation_memory.get('sha') if remote_translation_memory else None
                    if not sha and remote_translation_memory:
                        print(f"[GitHubSync] Warning: remote_translation_memory exists but no SHA: {remote_translation_memory}")
                    translation_memory_result = self._upload_file(
                        translation_memory_path,
                        upload_content,
                        sha
                    )
                    print(f"[GitHubSync] Translation memory upload result: {translation_memory_result.get('success', False)}")
                    if not translation_memory_result.get('success'):
                        print(f"[GitHubSync] Upload error: {translation_memory_result.get('error', 'Unknown')}")
                    results.append(translation_memory_result.get("success", False))
                    debug_info.append({"file": "translation_memory.json", "type": "memory", "result": translation_memory_result})

                # Push split config files
                split_config_files = [
                    ('tag_map.json', 'tag_map'),
                    ('presets.json', 'presets'),
                    ('speaker_data.json', 'speaker_data'),
                    ('tag_display.json', 'tag_display'),
                    ('preview_font.json', 'preview_font')
                ]
                
                for filename, config_key in split_config_files:
                    file_path = self._get_file_path(filename, None)
                    local_file = os.path.join(config_dir, filename)
                    
                    if os.path.exists(local_file):
                        try:
                            with open(local_file, 'r', encoding='utf-8-sig') as f:
                                content = json.load(f)
                            
                            remote_file = self._fetch_remote_file(file_path)
                            result = self._upload_file(
                                file_path,
                                content,
                                remote_file['sha'] if remote_file else None
                            )
                            results.append(result.get("success", False))
                            debug_info.append({"file": filename, "type": config_key, "result": result})
                        except Exception as e:
                            print(f"[GitHubSync] Error pushing {filename}: {e}")
                            results.append(False)

                # Push entry data (status, logs, comments) - only if translation_manager is provided
                if translation_manager is not None:
                    files_data = self._get_entry_files(translation_manager)

                    for file_path, data in files_data.items():
                        # Sanitize the file path for directory name
                        dir_name = self._sanitize_filename(file_path)
                        
                        # Push status file for this entry file
                        status_content = {k: v.to_dict() for k, v in data['entries'].items()}
                        status_path = self._get_file_path('status', dir_name)
                        remote_status = self._fetch_remote_file(status_path)
                        status_result = self._upload_file(
                            status_path,
                            status_content,
                            remote_status['sha'] if remote_status else None
                        )
                        results.append(status_result.get("success", False))
                        debug_info.append({"file": file_path, "type": "status", "result": status_result})
                        
                        # Push logs for this entry file
                        if data['logs']:
                            logs_content = [log.to_dict() for log in data['logs']]
                            remote_logs = self._fetch_remote_file(self._get_file_path('logs', dir_name))
                            
                            # Merge with remote logs
                            if remote_logs and 'content' in remote_logs:
                                seen = {log.get('id', '') + log.get('timestamp', '') for log in remote_logs['content']}
                                for log in logs_content:
                                    key = log.get('id', '') + log.get('timestamp', '')
                                    if key not in seen:
                                        remote_logs['content'].append(log)
                                logs_content = remote_logs['content']
                            
                            logs_result = self._upload_file(
                                self._get_file_path('logs', dir_name),
                                logs_content,
                                remote_logs['sha'] if remote_logs else None
                            )
                            results.append(logs_result.get("success", False))
                            debug_info.append({"file": file_path, "type": "logs", "result": logs_result})
                        
                        # Comments are now embedded in logs, no separate sync needed
                
                success = all(results) if results else True
                return {"success": success, "debug": debug_info, "total": len(results), "successful": sum(results)}
                
            except Exception as e:
                import traceback
                return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            finally:
                # Mark completion for throttling / scheduling decisions.
                self._push_in_progress = False
                self._last_push = time.time()
                self._last_push_completed = self._last_push
    
    def _check_remote_timestamp(self, file_path: str) -> Optional[str]:
        """Check if remote file has been modified since we last synced."""
        url = self._get_api_url(file_path)
        if not url:
            return None
        
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('sha')
            return None
        except:
            return None
    
    def sync_pull(self, translation_manager) -> bool:
        """Pull remote data and merge with local (only if changed). Returns True if successful."""
        if not self.is_configured():
            return False
        
        if not self._should_pull():
            print("[GitHubSync] Pull skipped - too soon")
            return True
        
        with self._lock:
            self._last_pull = time.time()
            
            try:
                language = self.cm.language
                owner, repo = self._get_repo_info()
                if not owner or not repo:
                    return False
                
                # Get config directory from ConfigManager base_dir
                base_dir = self.cm.base_dir
                config_dir = os.path.join(base_dir, "config", language)
                
                # Debug: Log the actual paths being used
                print(f"[GitHubSync] Using base_dir: {base_dir}")
                print(f"[GitHubSync] Using config_dir: {config_dir}")
                os.makedirs(config_dir, exist_ok=True)
                
                # Pull language-level files (archetypes, vocab)
                # Helper to validate remote content is usable
                def _is_valid_content(content):
                    """Check if content is a non-empty dict."""
                    return isinstance(content, dict) and len(content) > 0
                
                # Pull archetypes
                archetypes_path = self._get_file_path('archetypes.json', None)
                remote_archetypes = self._fetch_remote_file(archetypes_path)
                if remote_archetypes and 'content' in remote_archetypes:
                    if _is_valid_content(remote_archetypes['content']):
                        self.cm.archetypes = remote_archetypes['content']
                        self.cm.save_archetypes()
                        print(f"[GitHubSync] Pulled archetypes ({len(remote_archetypes['content'])} entries)")
                    else:
                        print(f"[GitHubSync] Skipped archetypes - remote content empty or invalid")
                
                # Pull dd1_vocab
                dd1_vocab_path = self._get_file_path('dd1_vocab.json', None)
                remote_dd1_vocab = self._fetch_remote_file(dd1_vocab_path)
                if remote_dd1_vocab and 'content' in remote_dd1_vocab:
                    if _is_valid_content(remote_dd1_vocab['content']):
                        self.cm.dd1_vocab = remote_dd1_vocab['content']
                        dd1_vocab_file = os.path.join(config_dir, "dd1_vocab.json")
                        self.cm.save_vocab(dd1_vocab_file, remote_dd1_vocab['content'])
                        print(f"[GitHubSync] Pulled dd1_vocab ({len(remote_dd1_vocab['content'])} entries)")
                    else:
                        print(f"[GitHubSync] Skipped dd1_vocab - remote content empty or invalid")
                
                # Pull other_vocab
                other_vocab_path = self._get_file_path('other_vocab.json', None)
                remote_other_vocab = self._fetch_remote_file(other_vocab_path)
                if remote_other_vocab and 'content' in remote_other_vocab:
                    if _is_valid_content(remote_other_vocab['content']):
                        self.cm.other_vocab = remote_other_vocab['content']
                        other_vocab_file = os.path.join(config_dir, "other_vocab.json")
                        self.cm.save_vocab(other_vocab_file, remote_other_vocab['content'])
                        print(f"[GitHubSync] Pulled other_vocab ({len(remote_other_vocab['content'])} entries)")
                    else:
                        print(f"[GitHubSync] Skipped other_vocab - remote content empty or invalid")
                
                # Pull anach_definitions
                anach_definitions_path = self._get_file_path('anach_definitions.json', None)
                remote_anach_definitions = self._fetch_remote_file(anach_definitions_path)
                if remote_anach_definitions and 'content' in remote_anach_definitions:
                    if _is_valid_content(remote_anach_definitions['content']):
                        anach_file = os.path.join(config_dir, "anach_definitions.json")
                        os.makedirs(config_dir, exist_ok=True)
                        with open(anach_file, 'w', encoding='utf-8-sig') as f:
                            json.dump(remote_anach_definitions['content'], f, indent=2, ensure_ascii=False)
                        print(f"[GitHubSync] Pulled anach_definitions ({len(remote_anach_definitions['content'])} entries)")
                    else:
                        print(f"[GitHubSync] Skipped anach_definitions - remote content empty or invalid")
                
                # Pull archaic_examples
                archaic_examples_path = self._get_file_path('archaic_examples.json', None)
                remote_archaic_examples = self._fetch_remote_file(archaic_examples_path)
                if remote_archaic_examples and 'content' in remote_archaic_examples:
                    if _is_valid_content(remote_archaic_examples['content']):
                        archaic_file = os.path.join(config_dir, "archaic_examples.json")
                        os.makedirs(config_dir, exist_ok=True)
                        with open(archaic_file, 'w', encoding='utf-8-sig') as f:
                            json.dump(remote_archaic_examples['content'], f, indent=2, ensure_ascii=False)
                        print(f"[GitHubSync] Pulled archaic_examples ({len(remote_archaic_examples['content'])} entries)")
                    else:
                        print(f"[GitHubSync] Skipped archaic_examples - remote content empty or invalid")
                
                # Pull formatter_config (merge with local)
                formatter_path = self._get_file_path('formatter_config.json', None)
                remote_formatter_config = self._fetch_remote_file(formatter_path)
                if remote_formatter_config and 'content' in remote_formatter_config:
                    remote_content = remote_formatter_config['content']
                    # Validate remote content is a dict
                    if isinstance(remote_content, dict):
                        formatter_file = os.path.join(config_dir, "formatter_config.json")
                        
                        # Load local formatter config
                        local_config = {}
                        if os.path.exists(formatter_file):
                            with open(formatter_file, 'r', encoding='utf-8-sig') as f:
                                local_config = json.load(f)
                        
                        # Validate local config is also a dict
                        if not isinstance(local_config, dict):
                            print(f"[GitHubSync] Warning: local formatter_config is not a dict, resetting to empty")
                            local_config = {}
                        
                        # Merge: shared fields from remote, user-specific fields from local
                        shared_fields = ['triggers', 'tag_map', 'styles', 'tag_display', 'wall_preset']
                        merged_config = {}
                        
                        # Copy shared fields from remote (preserve local if remote is empty)
                        for field in shared_fields:
                            if field in remote_content and remote_content[field] is not None:
                                # Only use remote if it has actual data (not empty dict/list)
                                remote_value = remote_content[field]
                                if isinstance(remote_value, dict) and not remote_value:
                                    # Remote has empty dict, keep local if it has data
                                    if field in local_config and local_config[field]:
                                        merged_config[field] = local_config[field]
                                    else:
                                        merged_config[field] = {}
                                elif isinstance(remote_value, list) and not remote_value:
                                    # Remote has empty list, keep local if it has data
                                    if field in local_config and local_config[field]:
                                        merged_config[field] = local_config[field]
                                    else:
                                        merged_config[field] = []
                                else:
                                    merged_config[field] = remote_value
                            elif field in local_config:
                                # Remote doesn't have field, keep local
                                merged_config[field] = local_config[field]
                        
                        # Keep user-specific fields from local
                        user_fields = ['dark_mode', 'sync_language', 'pretranslate_settings', 'config_dir', 'deepl_target_lang', 'archetypes']
                        for field in user_fields:
                            if field in local_config:
                                merged_config[field] = local_config[field]
                        
                        # Keep any other fields from local that aren't in shared fields
                        for field, value in local_config.items():
                            if field not in shared_fields and field not in merged_config:
                                merged_config[field] = value
                        
                        # Save merged config
                        with open(formatter_file, 'w', encoding='utf-8-sig') as f:
                            json.dump(merged_config, f, indent=2, ensure_ascii=False)
                        print(f"[GitHubSync] Pulled formatter_config (merged {len(merged_config)} fields)")
                    else:
                        print(f"[GitHubSync] Skipped formatter_config - remote content is not a dict (type: {type(remote_content).__name__})")
                
                # Pull translation_memory (merge with local)
                translation_memory_path = self._get_file_path('translation_memory.json', None)
                remote_translation_memory = self._fetch_remote_file(translation_memory_path)
                if remote_translation_memory and 'content' in remote_translation_memory:
                    remote_tm_content = remote_translation_memory['content']
                    
                    # Handle compressed translation memory
                    if isinstance(remote_tm_content, dict) and remote_tm_content.get('compressed'):
                        import gzip
                        try:
                            compressed_data = base64.b64decode(remote_tm_content['data'])
                            decompressed = gzip.decompress(compressed_data).decode('utf-8')
                            remote_tm_content = json.loads(decompressed)
                            print(f"[GitHubSync] Decompressed translation_memory ({len(compressed_data)/1024/1024:.2f} MB -> {len(decompressed)/1024/1024:.2f} MB)")
                        except Exception as e:
                            print(f"[GitHubSync] Error decompressing translation_memory: {e}")
                            remote_tm_content = None
                    
                    # Validate remote content is a dict with entries array
                    if isinstance(remote_tm_content, dict) and "entries" in remote_tm_content:
                        translation_memory_file = os.path.join(config_dir, "translation_memory.json")
                        
                        # Load local translation memory
                        local_memory = {"version": 2, "entries": [], "stats": {"total_entries": 0, "approved_count": 0, "draft_count": 0}}
                        if os.path.exists(translation_memory_file) and not any(x in translation_memory_file for x in ['pytest', 'tmp', '__pycache__', '.coverage']):
                            with open(translation_memory_file, 'r', encoding='utf-8-sig') as f:
                                try:
                                    loaded = json.load(f)
                                    if isinstance(loaded, dict) and "entries" in loaded:
                                        local_memory = loaded
                                except:
                                    pass
                        
                        # Merge entries: combine both lists, remote takes precedence for same ID
                        local_entries = local_memory.get("entries", [])
                        remote_entries = remote_tm_content.get("entries", [])
                        
                        # Build merged entries dict by ID (remote overwrites local on conflict)
                        merged_entries_by_id = {}
                        for entry in local_entries:
                            entry_id = entry.get("id") or entry.get("source", "")
                            if entry_id:
                                merged_entries_by_id[entry_id] = entry
                        
                        for entry in remote_entries:
                            entry_id = entry.get("id") or entry.get("source", "")
                            if entry_id:
                                merged_entries_by_id[entry_id] = entry
                        
                        merged_entries = list(merged_entries_by_id.values())
                        
                        # Build merged stats
                        merged_stats = {
                            "total_entries": len(merged_entries),
                            "approved_count": sum(1 for e in merged_entries if e.get("quality") == "approved"),
                            "draft_count": sum(1 for e in merged_entries if e.get("quality") != "approved")
                        }
                        
                        merged_memory = {
                            "version": 2,
                            "entries": merged_entries,
                            "stats": merged_stats
                        }
                        
                        # Save merged memory
                        with open(translation_memory_file, 'w', encoding='utf-8-sig') as f:
                            json.dump(merged_memory, f, indent=2, ensure_ascii=False)
                        print(f"[GitHubSync] Pulled translation_memory ({len(remote_entries)} remote + {len(local_entries)} local = {len(merged_entries)} merged)")
                    else:
                        print(f"[GitHubSync] Skipped translation_memory - remote content missing 'entries' array (keys: {list(remote_tm_content.keys()) if isinstance(remote_tm_content, dict) else 'N/A'})")
                
                # Pull split config files
                split_config_files = [
                    ('tag_map.json', 'tag_map'),
                    ('presets.json', 'presets'),
                    ('speaker_data.json', 'speaker_data'),
                    ('tag_display.json', 'tag_display'),
                    ('preview_font.json', 'preview_font')
                ]
                
                for filename, config_key in split_config_files:
                    file_path = self._get_file_path(filename, None)
                    remote_file = self._fetch_remote_file(file_path)
                    
                    if remote_file and 'content' in remote_file:
                        remote_content = remote_file['content']
                        if isinstance(remote_content, dict) and remote_content:
                            local_file = os.path.join(config_dir, filename)
                            os.makedirs(config_dir, exist_ok=True)
                            with open(local_file, 'w', encoding='utf-8-sig') as f:
                                json.dump(remote_content, f, indent=2, ensure_ascii=False)
                            print(f"[GitHubSync] Pulled {filename} ({len(remote_content)} keys)")
                            
                            # Update in-memory config
                            if config_key == 'tag_map':
                                self.cm.config['tag_map'] = remote_content
                            elif config_key == 'presets':
                                if 'presets' in remote_content:
                                    self.cm.config['presets'] = remote_content['presets']
                                if 'wall_presets' in remote_content:
                                    self.cm.config['wall_presets'] = remote_content['wall_presets']
                            elif config_key == 'speaker_data':
                                if 'speaker_archetypes' in remote_content:
                                    self.cm.config['speaker_archetypes'] = remote_content['speaker_archetypes']
                                if 'speaker_notes' in remote_content:
                                    self.cm.config['speaker_notes'] = remote_content['speaker_notes']
                        else:
                            print(f"[GitHubSync] Skipped {filename} - remote content empty or invalid")
                
                # Initialize counters
                total_entries = 0
                total_logs = 0
                
                # Pull entry data (status, logs, comments)
                if translation_manager is not None:
                    # List contents of language directory
                    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{language}"
                    resp = requests.get(url, headers=self._get_headers(), timeout=30)
                    
                    if resp.status_code == 404:
                        # No data yet on remote
                        return True
                    if resp.status_code != 200:
                        print(f"[GitHubSync] Failed to list remote files: {resp.status_code}")
                        return False
                    
                    contents = resp.json()
                    
                    # Process each directory (corresponds to a source file)
                    for item in contents:
                        if item['type'] != 'dir':
                            continue
                        
                        dir_name = item['name']
                        
                        # Skip directories that are actually our config files
                        if dir_name.endswith('.json'):
                            continue
                        
                        # Check status file
                        status_path = f"{language}/{dir_name}/status.json"
                        current_sha = self._remote_timestamps.get(status_path)
                        new_sha = self._check_remote_timestamp(status_path)
                        
                        if new_sha == current_sha:
                            continue  # No changes
                        
                        self._remote_timestamps[status_path] = new_sha
                        
                        # Fetch status
                        remote_status = self._fetch_remote_file(status_path)
                        if remote_status and 'content' in remote_status:
                            for entry_id, entry_data in remote_status['content'].items():
                                total_entries += 1
                                if entry_id not in translation_manager.entries:
                                    translation_manager.entries[entry_id] = translation_manager._entry_from_dict(entry_data)
                                else:
                                    local_time = translation_manager.entries[entry_id].updated_at
                                    remote_time = entry_data.get('updated_at', '')
                                    if remote_time > local_time:
                                        translation_manager.entries[entry_id] = translation_manager._entry_from_dict(entry_data)
                        
                        # Fetch logs (comments are now embedded in logs)
                        logs_path = self._get_file_path('logs', dir_name)
                        remote_logs = self._fetch_remote_file(logs_path)
                        if remote_logs and 'content' in remote_logs:
                            seen = {log.id + log.timestamp for log in translation_manager.logs}
                            for log_data in remote_logs['content']:
                                key = log_data.get('id', '') + log_data.get('timestamp', '')
                                if key not in seen:
                                    translation_manager.logs.append(translation_manager._log_from_dict(log_data))
                                    total_logs += 1
                        
                        # Comments are now embedded in logs, no separate sync needed
                        
                        # Mark this file as dirty so it gets saved locally
                        translation_manager._mark_dirty(dir_name)
                
                # Save all merged data to local per-file storage (only if translation_manager provided)
                if translation_manager is not None:
                    translation_manager.flush_saves()
                
                print(f"[GitHubSync] Pull completed: {total_entries} entries, {total_logs} logs")
                return True
                
            except Exception as e:
                print(f"[GitHubSync] Pull failed: {e}")
                return False
    
    def start_auto_sync(self, translation_manager):
        """Start background auto-sync thread (30 min intervals)."""
        def sync_loop():
            while True:
                time.sleep(60)  # Check every minute
                try:
                    if not self.is_configured():
                        continue
                    if not self.cm.config.get('sync_auto', False):
                        continue
                    
                    # Pull if needed
                    if self._should_pull():
                        self.sync_pull(translation_manager)
                    
                    # Push if pending and enough time passed
                    if self._pending_push and self._should_push():
                        self.sync_push(translation_manager)
                        
                except Exception as e:
                    print(f"[GitHubSync] Auto-sync error: {e}")
        
        thread = threading.Thread(target=sync_loop, daemon=True)
        thread.start()
        print("[GitHubSync] Auto-sync thread started (30min intervals)")
