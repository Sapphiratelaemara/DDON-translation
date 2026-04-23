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
        self._last_pull = 0
        self._pending_push = False
        self._urgent_push = False  # Set True when comment posted
        self._remote_timestamps = {}  # Cache of remote file timestamps
        
    def _get_headers(self) -> Dict[str, str]:
        """Get GitHub API headers with auth token."""
        token = self.cm.get_key('github_token')
        return {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
    
    def _get_repo_info(self) -> tuple:
        """Extract owner and repo from config."""
        repo_url = self.cm.config.get('github_repo', '')
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
        language = self.cm.config.get('sync_language', 'English')
        
        if entry_id:
            # Per-file storage: sanitize filename from entry_id
            safe_name = self._sanitize_filename(entry_id)
            return f"{language}/{safe_name}/{file_id}.json"
        else:
            # Global status file only
            return f"{language}/status.json"
    
    def _sanitize_filename(self, name: str) -> str:
        """Create safe filename from entry_id."""
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
        token = self.cm.config.get('github_token', '')
        repo = self.cm.config.get('github_repo', '')
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
    
    def _upload_file(self, file_path: str, content: Any, sha: Optional[str] = None) -> bool:
        """Upload/update a file on GitHub."""
        url = self._get_api_url(file_path)
        if not url:
            return False
        
        try:
            message = f"Update {file_path} - {datetime.now().isoformat()}"
            nickname = self.cm.config.get('sync_nickname', 'Anonymous')
            
            payload = {
                'message': message,
                'content': base64.b64encode(json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')).decode('utf-8'),
                'committer': {
                    'name': nickname,
                    'email': f'{nickname}@ddon-translation.local'
                }
            }
            if sha:
                payload['sha'] = sha
            
            resp = requests.put(url, headers=self._get_headers(), json=payload, timeout=30)
            if resp.status_code in [200, 201]:
                print(f"[GitHubSync] Uploaded {file_path}")
                return True
            else:
                print(f"[GitHubSync] Failed to upload {file_path}: {resp.status_code}")
                return False
        except Exception as e:
            print(f"[GitHubSync] Error uploading {file_path}: {e}")
            return False
    
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
            from translation_manager import translation_manager as tm
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
                    files_data[file_path] = {'entries': {}, 'logs': [], 'comments': {}}
                files_data[file_path]['logs'].append(log)
        
        # Distribute comments to their respective files
        for entry_id, comments in translation_manager.comments.items():
            if entry_id in translation_manager.entries:
                file_path = translation_manager.entries[entry_id].file_path or 'unknown'
                if file_path not in files_data:
                    files_data[file_path] = {'entries': {}, 'logs': [], 'comments': {}}
                files_data[file_path]['comments'][entry_id] = comments
        
        return files_data
    
    def sync_push(self, translation_manager) -> bool:
        """Push local data to remote (per-file structure). Returns True if successful."""
        if not self.is_configured():
            print("[GitHubSync] Push aborted: not configured")
            return False

        # Validate data before pushing
        if len(translation_manager.entries) == 0:
            print("[GitHubSync] Push aborted: no entries to push")
            return False

        with self._lock:
            self._last_push = time.time()
            self._urgent_push = False

            try:
                print(f"[GitHubSync] Starting push...")
                print(f"[GitHubSync] TM entries: {len(translation_manager.entries)}")
                print(f"[GitHubSync] TM logs: {len(translation_manager.logs)}")
                print(f"[GitHubSync] TM comments: {len(translation_manager.comments)}")

                files_data = self._get_entry_files(translation_manager)
                print(f"[GitHubSync] Files to sync: {list(files_data.keys())}")

                # Validate files_data before pushing
                if not files_data:
                    print("[GitHubSync] Push aborted: no file data to push")
                    return False

                results = []

                for file_path, data in files_data.items():
                    print(f"[GitHubSync] Processing file: {file_path}")
                    print(f"[GitHubSync]   Entries: {len(data['entries'])}, Logs: {len(data['logs'])}, Comments: {len(data['comments'])}")
                    
                    # Sanitize the file path for directory name
                    dir_name = self._sanitize_filename(file_path)
                    print(f"[GitHubSync]   Dir name: {dir_name}")
                    
                    # Push status file for this entry file
                    status_content = {k: v.to_dict() for k, v in data['entries'].items()}
                    status_path = self._get_file_path('status', dir_name)
                    print(f"[GitHubSync]   Pushing status to: {status_path}")
                    remote_status = self._fetch_remote_file(status_path)
                    status_result = self._upload_file(
                        status_path,
                        status_content,
                        remote_status['sha'] if remote_status else None
                    )
                    print(f"[GitHubSync]   Status upload: {'OK' if status_result else 'FAILED'}")
                    results.append(status_result)
                    
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
                        
                        results.append(self._upload_file(
                            self._get_file_path('logs', dir_name),
                            logs_content,
                            remote_logs['sha'] if remote_logs else None
                        ))
                    
                    # Push comments for this entry file
                    if data['comments']:
                        comments_content = {k: [c.to_dict() for c in v] for k, v in data['comments'].items()}
                        remote_comments = self._fetch_remote_file(self._get_file_path('comments', dir_name))
                        
                        # Merge with remote comments
                        if remote_comments and 'content' in remote_comments:
                            for entry_id, local_comments in comments_content.items():
                                remote_list = remote_comments['content'].get(entry_id, [])
                                seen = {c.get('id', '') + c.get('timestamp', '') for c in remote_list}
                                for c in local_comments:
                                    key = c.get('id', '') + c.get('timestamp', '')
                                    if key not in seen:
                                        remote_list.append(c)
                                remote_comments['content'][entry_id] = remote_list
                            comments_content = remote_comments['content']
                        
                        results.append(self._upload_file(
                            self._get_file_path('comments', dir_name),
                            comments_content,
                            remote_comments['sha'] if remote_comments else None
                        ))
                
                success = all(results) if results else True
                print(f"[GitHubSync] Push completed: {sum(results)}/{len(results)} files uploaded")
                return success
                
            except Exception as e:
                print(f"[GitHubSync] Push failed: {e}")
                return False
    
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
                # First, get list of directories (files) in the language folder
                language = self.cm.config.get('sync_language', 'English')
                owner, repo = self._get_repo_info()
                if not owner or not repo:
                    return False
                
                # List contents of language directory
                url = f"https://api.github.com/repos/{owner}/{repo}/contents/{language}"
                resp = requests.get(url, headers=self._get_headers(), timeout=30)
                
                if resp.status_code == 404:
                    # No data yet on remote
                    return True
                if resp.status_code != 200:
                    print(f"[GitHubSync] Failed to list remote files: {resp.status_code}")
                    return False
                
                directories = resp.json()
                if not isinstance(directories, list):
                    directories = [directories]
                
                # Filter to only directories (each represents a source file)
                file_dirs = [d for d in directories if d.get('type') == 'dir']
                
                total_entries = 0
                total_logs = 0
                total_comments = 0
                
                for dir_info in file_dirs:
                    dir_name = dir_info['name']
                    
                    # Check if we need to update this file's data
                    status_path = self._get_file_path('status', dir_name)
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
                    
                    # Fetch logs
                    logs_path = self._get_file_path('logs', dir_name)
                    remote_logs = self._fetch_remote_file(logs_path)
                    if remote_logs and 'content' in remote_logs:
                        seen = {log.id + log.timestamp for log in translation_manager.logs}
                        for log_data in remote_logs['content']:
                            key = log_data.get('id', '') + log_data.get('timestamp', '')
                            if key not in seen:
                                translation_manager.logs.append(translation_manager._log_from_dict(log_data))
                                total_logs += 1
                    
                    # Fetch comments
                    comments_path = self._get_file_path('comments', dir_name)
                    remote_comments = self._fetch_remote_file(comments_path)
                    if remote_comments and 'content' in remote_comments:
                        for entry_id, comments_list in remote_comments['content'].items():
                            if entry_id not in translation_manager.comments:
                                translation_manager.comments[entry_id] = []
                            seen = {c.id + c.timestamp for c in translation_manager.comments[entry_id]}
                            for c in comments_list:
                                key = c.get('id', '') + c.get('timestamp', '')
                                if key not in seen:
                                    translation_manager.comments[entry_id].append(translation_manager._comment_from_dict(c))
                                    total_comments += 1
                    
                    # Mark this file as dirty so it gets saved locally
                    translation_manager._mark_dirty(dir_name)
                
                # Save all merged data to local per-file storage
                translation_manager.flush_saves()
                
                print(f"[GitHubSync] Pull completed: {total_entries} entries, {total_logs} logs, {total_comments} comments")
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
