import os
import sys
import subprocess
import logging
from datetime import datetime

# Set console to UTF-8 for Windows to handle Japanese characters
if sys.platform == 'win32':
    import codecs
    # Set console code page to UTF-8 instead of wrapping stdout (avoids threading issues)
    import subprocess
    subprocess.run(['chcp', '65001'], shell=True, capture_output=True)

# Configure debug logging
DEBUG_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
DEBUG_ENABLED = True
TEST_MODE = False  # Set to True during testing to disable side effects (file writes, API calls)

def setup_debug_logging():
    """Setup logging.

    Important: keep DEBUG detail in `debug.log`, but avoid flooding the terminal.
    """
    if not DEBUG_ENABLED:
        return

    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Configure root logger explicitly (avoid basicConfig surprises if anything
    # else configured logging earlier).
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # allow all levels; handlers will filter
    for h in list(root.handlers):
        root.removeHandler(h)

    file_handler = logging.FileHandler(DEBUG_LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))

    stream_handler = logging.StreamHandler(sys.stdout)
    # Console should be quiet by default; DEBUG stays in the file.
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter(log_format))

    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Third-party libraries can be extremely noisy at DEBUG (e.g. jamdict/jamdict-data DB queries
    # via puchikarui). Keep our app logs at DEBUG, but suppress those unless explicitly needed.
    noisy_defaults = {
        "puchikarui": logging.WARNING,
        "puchikarui.puchikarui": logging.WARNING,
        "urllib3": logging.INFO,
        "urllib3.connectionpool": logging.INFO,
    }
    for name, level in noisy_defaults.items():
        try:
            logging.getLogger(name).setLevel(level)
            # Avoid duplicates if a library adds its own handlers.
            logging.getLogger(name).propagate = True
        except Exception:
            pass

    return logging.getLogger('DDON_Editor')

logger = setup_debug_logging()

def debug_log(component, message, level='DEBUG'):
    """Log debug message with component name."""
    if not DEBUG_ENABLED:
        return
    log_func = getattr(logger, level.lower(), logger.debug)
    log_msg = f"[{component}] {message}"
    log_func(log_msg)

# Dependency check and auto-install
def check_dependencies():
    """Check if required packages are installed, offer to install if missing."""
    required = {
        'eel': 'eel>=0.16.0',
        'requests': 'requests>=2.31.0',
        'msgpack': 'msgpack>=1.0.0',
        'PIL': 'Pillow>=10.0.0',
    }
    
    missing = []
    for package in required.keys():
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        response = input("Install missing dependencies? (y/n): ").strip().lower()
        if response == 'y':
            for package in missing:
                spec = required[package]
                print(f"Installing {spec}...")
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", spec])
                    print(f"Successfully installed {package}")
                except subprocess.CalledProcessError as e:
                    print(f"Failed to install {package}: {e}")
                    sys.exit(1)
        else:
            print("Cannot run without required dependencies.")
            sys.exit(1)

check_dependencies()

import eel
import json
import re
import threading
import time
from collections import defaultdict
from datetime import datetime

from src.config_manager import ConfigManager
from src.api_handler import DeepLClient, OpenRouterClient
from src.translator_engine import TranslationEngine
from src.file_utils import _get_csv_files, _read_csv
from src.batch_runner import run_batch, BatchSettings
from src.translation_manager import get_translation_manager
from src.github_sync import GitHubSync
from src.source_validator import SourceValidator

# Initialize core logic
# Load language from global user_settings if available, default to "en"
import os
import json
initial_language = "en"
global_user_settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_settings.json")
if os.path.exists(global_user_settings_path):
    try:
        with open(global_user_settings_path, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
            initial_language = user_settings.get("language", "en")
    except:
        pass

from src.lore_data import set_config_manager, reload_vocab

cm     = ConfigManager(language=initial_language)
set_config_manager(cm)  # Set ConfigManager for lore_data to load language-specific vocab
reload_vocab()  # Reload vocab from ConfigManager to ensure it's loaded from the correct source
engine = TranslationEngine(cm.config.get("tag_map", {}))
github_sync = GitHubSync(cm)
translation_manager = get_translation_manager(initial_language)
source_validator = SourceValidator()
source_validator.load_tag_map(cm.config.get("tag_map", {}))

# Set up sync callback - request push to GitHub after local saves
# Comments trigger urgent push (1 min), other changes wait (30 min)
def sync_push_request(urgent: bool = False):
    """Request a sync push - urgent for comments, normal for other changes."""
    github_sync.request_push(urgent=urgent)

translation_manager.set_sync_callback(sync_push_request)

# Lazy-initialized lore engine
_lore_engine      = None
_lore_engine_lock = threading.Lock()

# Lazy-initialized gloss engine
_gloss_engine      = None
_gloss_engine_lock = threading.Lock()
_gloss_engine_last_lore_map = None
_gloss_cache = {}  # Clear cache on restart to use new smaller format

# Preview image cache
_preview_cache = {}
_preview_cache_lock = threading.Lock()

# Clear preview cache on startup to get fresh timing data
print("[main] Preview cache cleared for timing analysis")

# Lazy-initialized TM components
_tm_instance      = None
_tm_lock          = threading.Lock()
_tm_matcher       = None
_tm_substitutor    = None

# TM result cache: jp_text -> (matches, timestamp)
_tm_result_cache = {}
_tm_cache_lock = threading.Lock()
_tm_cache_ttl = 300  # 5 minutes

# Start GitHub auto-sync if enabled (30 min intervals)
if github_sync.is_configured() and cm.config.get('sync_auto', False):
    github_sync.start_auto_sync(translation_manager)
    print("[main] GitHub auto-sync started (30min intervals)")

def _get_tm_components():
    """Return cached TM instance, matcher, and substitutor."""
    global _tm_instance, _tm_matcher, _tm_substitutor
    with _tm_lock:
        if _tm_instance is None:
            from src.translation_memory import TranslationMemory, FuzzyMatcher, AutoSubstitutor
            _tm_instance = TranslationMemory(cm)
            _tm_matcher = FuzzyMatcher(cm)
            _tm_substitutor = AutoSubstitutor(cm)
            print(f"[TM] Initialized TM with {len(_tm_instance.entries)} entries")
        return _tm_instance, _tm_matcher, _tm_substitutor

def _get_gloss_engine():
    """Return a cached GlossEngine, rebuilding if needed."""
    global _gloss_engine, _gloss_engine_last_lore_map
    # Get lore_map from LoreEngine (which loads from glossary files)
    le = _get_lore_engine()
    lore_map = le.lore_map if le else {}
    try:
        if _gloss_engine is None:
            with _gloss_engine_lock:
                if _gloss_engine is None:
                    from src.gloss_engine import GlossEngine
                    _gloss_engine = GlossEngine(lore_map=lore_map)
                    _gloss_engine_last_lore_map = lore_map
        # Only update and clear cache if lore_map actually changed
        if lore_map != _gloss_engine_last_lore_map:
            _gloss_engine.update_lore_map(lore_map)
            # Clear gloss cache when lore_map is updated
            global _gloss_cache
            with _gloss_cache_lock:
                _gloss_cache.clear()
            _gloss_engine_last_lore_map = lore_map
    except Exception as e:
        print(f"[WARN] GlossEngine unavailable: {e}")
    return _gloss_engine

def _get_lore_engine():
    """Return a cached LoreEngine, rebuilding if invalidated."""
    global _lore_engine
    if _lore_engine is None:
        with _lore_engine_lock:
            if _lore_engine is None:
                try:
                    from src.lore_engine import LoreEngine
                    le = LoreEngine(cm.config.get("archetypes"))
                    le.load_data(
                        cm.user_settings.get("bible_path",    "") if hasattr(cm, 'user_settings') else "",
                        cm.user_settings.get("glossary_path", "") if hasattr(cm, 'user_settings') else "")
                    _lore_engine = le
                except Exception as e:
                    print(f"[WARN] LoreEngine unavailable: {e}")
    return _lore_engine

# Pre-initialize Jamdict to avoid first-call timeout (optional dependency)
print("[MAIN] Pre-initializing Jamdict (optional)...")
try:
    ge = _get_gloss_engine()
    if ge:
        print("[MAIN] Jamdict pre-initialization successful")
    else:
        print("[MAIN] Jamdict unavailable - gloss feature disabled")
except Exception as e:
    print(f"[MAIN] Jamdict pre-initialization error: {e}")
    print("[MAIN] Continuing without gloss feature")

# --- QUEUES ---
review_queues = {
    "tag":   defaultdict(list),
    "wall":  defaultdict(list),
    "dash":  defaultdict(list),
    "anach": defaultdict(list),
}
review_items       = []
current_review_idx = 0
batch_scan_complete = False

# --- QUEUE PERSISTENCE ---
def _get_queue_cache_file(filename):
    """Get the path to a queue cache file for the current language."""
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(base_dir, "config", cm.language)
    return os.path.join(config_dir, filename)

def _save_review_queues():
    """Save review queues to disk for persistence across restarts."""
    try:
        serializable = {}
        for key, queue_data in review_queues.items():
            serializable[key] = dict(queue_data)
        queue_file = _get_queue_cache_file("review_queues_cache.json")
        with open(queue_file, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[_save_review_queues] Error: {e}")

def _load_review_queues():
    """Load review queues from disk if they exist."""
    global review_queues
    try:
        queue_file = _get_queue_cache_file("review_queues_cache.json")
        if os.path.exists(queue_file):
            with open(queue_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for key, queue_data in data.items():
                review_queues[key] = defaultdict(list, queue_data)
            print(f"[_load_review_queues] Loaded queues with {sum(len(q) for q in review_queues.values())} items")
    except Exception as e:
        print(f"[_load_review_queues] Error: {e}")

def _save_review_items():
    """Save review_items (manual translation queue) to disk for persistence."""
    global review_items
    try:
        queue_file = _get_queue_cache_file("review_items_cache.json")
        with open(queue_file, 'w', encoding='utf-8') as f:
            json.dump(review_items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[_save_review_items] Error: {e}")

def _load_review_items():
    """Load review_items from disk if they exist."""
    global review_items
    try:
        queue_file = _get_queue_cache_file("review_items_cache.json")
        if os.path.exists(queue_file):
            with open(queue_file, 'r', encoding='utf-8') as f:
                review_items = json.load(f)
            print(f"[_load_review_items] Loaded {len(review_items)} items")
    except Exception as e:
        print(f"[_load_review_items] Error: {e}")

# Load queues at startup
_load_review_queues()
_load_review_items()


# --- CSV WRITE MANAGEMENT ---
pending_csv_writes = {}

# --- CSV READ CACHE ---
_csv_cache = {}
_csv_cache_lock = threading.Lock()
_recently_written_files = {}  # Track files written by app for cache invalidation

# --- GLOSS CACHE (must be defined early for _get_gloss_engine) ---
_gloss_cache = {}
_gloss_cache_lock = threading.Lock()

def mark_file_written(file_path):
    """Mark a file as recently written by the app (to avoid cache invalidation)."""
    _recently_written_files[file_path] = time.time()

def should_invalidate_cache(file_path, cache_timestamp):
    """Check if cache should be invalidated based on file modification time."""
    if not os.path.exists(file_path):
        return True
    file_mtime = os.path.getmtime(file_path)
    last_write = _recently_written_files.get(file_path, 0)
    # Invalidate if file was modified externally (after cache and not by us)
    return file_mtime > cache_timestamp and file_mtime > last_write

def _read_csv_cached(path):
    """Read CSV with caching to avoid repeated file reads."""
    global _csv_cache
    # Check cache with modification time validation
    with _csv_cache_lock:
        if path in _csv_cache:
            cached_data = _csv_cache[path]
            # If cached data includes timestamp, check if file was modified
            if isinstance(cached_data, dict) and 'timestamp' in cached_data:
                if not should_invalidate_cache(path, cached_data['timestamp']):
                    return cached_data['data']
            else:
                # Legacy cache format without timestamp
                return cached_data
    
    # Read from file
    raw, dialect, rows = _read_csv(path)
    
    # Cache result with timestamp
    with _csv_cache_lock:
        _csv_cache[path] = {
            'data': (raw, dialect, rows),
            'timestamp': time.time()
        }
    
    return raw, dialect, rows

def clear_csv_cache():
    """Clear the CSV cache (call when files are modified)."""
    global _csv_cache
    with _csv_cache_lock:
        _csv_cache.clear()

# --- ACTIVE EDITOR TRACKING ---
active_editors = []

# --- ROUTING ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR  = os.path.join(BASE_DIR, 'web')

# Initialize Eel early so decorators work
eel.init(WEB_DIR)

@eel.btl.route('/assets/<path:path>')
def serve_assets(path):
    assets_abs = os.path.join(PARENT_DIR, 'assets')
    return eel.btl.static_file(path, root=assets_abs)

# =============================================================================
# DASHBOARD
# =============================================================================

@eel.expose
def get_dashboard_data():
    folders   = cm.user_settings.get("folders", []) if hasattr(cm, 'user_settings') else []
    csv_files = _get_csv_files(folders)
    return {
        "folders":      folders,
        "triggers":     cm.user_settings.get("triggers",   []) if hasattr(cm, 'user_settings') else [],
        "file_count":   len(csv_files),
        "last_scan":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "in_universe":  cm.user_settings.get("in_universe",  True) if hasattr(cm, 'user_settings') else True,
        "preview_mode": cm.user_settings.get("preview_mode", False) if hasattr(cm, 'user_settings') else False,
        "last_stats":   cm.user_settings.get("last_stats",   {}) if hasattr(cm, 'user_settings') else {},
        "presets":      list(cm.config.get("presets", {"Standard": 50}).keys()),
        "wall_presets": list(cm.config.get("wall_presets", {"Standard": 7}).keys()),
        "selected_preset": cm.user_settings.get("selected_preset", "Standard") if hasattr(cm, 'user_settings') else "Standard",
        "wall_preset":  cm.user_settings.get("wall_preset", "Standard") if hasattr(cm, 'user_settings') else "Standard",
        "dark_mode":    cm.user_settings.get("dark_mode", False) if hasattr(cm, 'user_settings') else False,
        "theme_colors": get_theme_colors(),
    }

@eel.expose
def calculate_project_stats():
    """Project-wide stats: total lines vs translated lines."""
    folders   = cm.user_settings.get("folders", []) if hasattr(cm, 'user_settings') else []
    csv_files = _get_csv_files(folders)
    total_lines = 0
    translated  = 0
    for f_path in csv_files:
        try:
            _, _, rows = _read_csv(f_path)
            for i, row in enumerate(rows):
                if i == 0 or len(row) < 6:
                    continue
                en_text = row[3].strip() if len(row) > 3 else ""
                jp_text = row[2].strip() if len(row) > 2 else ""
                if not jp_text: 
                    continue
                total_lines += 1
                if en_text and en_text != jp_text:
                    translated += 1
        except:
            continue
    res = {
        "total":      total_lines,
        "translated": translated,
        "percent":    round((translated / total_lines * 100), 1) if total_lines > 0 else 0,
    }
    cm.user_settings.setdefault("last_stats", res)
    cm.user_settings["last_stats"] = res
    cm.save_user_settings()
    return res

@eel.expose
def clear_log():
    """Clear the execution log."""
    return True

@eel.expose
def add_log_message(message):
    """Add a message to the execution log."""
    return message

# =============================================================================
# THEME & DARK MODE
# =============================================================================

@eel.expose
def get_theme_colors():
    """Return current theme colors based on dark mode setting."""
    dark_mode = cm.user_settings.get("dark_mode", False) if hasattr(cm, 'user_settings') else False
    
    # Default colors
    default_dark = {
        "bg":       "#11131c",
        "fg":       "#C3F5FF",
        "list_bg":  "#1d1f29",
        "btn_bg":   "#1d1f29",
        "log_bg":   "#0c0e17",
        "log_fg":   "#C3F5FF",
        "label":    "#C3F5FF",
        "button_text": "#C3F5FF",
        "accent":   "#00C853",
        "accent_fill": "#00C853",
        "accent_text": "#000000",
        "run_bg":   "#00C853",
        "border":   "rgba(195, 245, 255, 0.1)",
        "header_bg": "#0c0e17",
        "panel_bg": "rgba(29, 31, 41, 0.6)",
        "tab_inactive": "rgba(195, 245, 255, 0.4)",
        "glow":     "rgba(0, 200, 83, 0.5)",
        "lore":     "#6fb3ff",
        "lore_hover": "#a8d4ff",
        "anach":    "#ffd700",
        "tooltip":  "#fcf34b",
        "mask_015": "rgba(0, 0, 0, 0.15)",
        "mask_025": "rgba(0, 0, 0, 0.25)",
        "mask_03":  "rgba(0, 0, 0, 0.3)",
        "mask_05":  "rgba(0, 0, 0, 0.5)",
        "mask_08":  "rgba(0, 0, 0, 0.8)",
        # Theme color channels
        "theme_backgrounds_color": "245, 247, 248",
        "theme_primaries_color": "67, 160, 71",
        "theme_blacks": "0, 0, 0",
        "theme_whites": "255, 255, 255",
        "theme_grays": "38, 50, 56",
        "theme_typeface_color": "38, 50, 56",
        "theme_cards_color": "38, 50, 56",
        # Theme colors
        "theme_level_1_bg": "#f5f7f8",
        "theme_level_2_bg": "#ffffff",
        "theme_level_3_bg": "#ffffff",
        "theme_primary": "#43a047",
        "theme_link_hover": "#5bbb60",
        "theme_border_color": "rgba(38, 50, 56, 0.1)",
        "theme_dark_border_color": "rgba(0, 0, 0, 0.12)",
        "theme_shimmer": "#eceff1",
        "theme_icons_color": "rgba(38, 50, 56, 1)",
        "theme_primary_green_50": "#e8f5e9",
        "theme_primary_green_100": "#c8e6c9",
        "theme_primary_blue_600": "#1e88e5",
        "theme_primary_blue_gray": "#eceff1",
        "theme_dark": "rgba(38, 50, 56, 1)",
        "theme_gray_005": "rgba(38, 50, 56, 0.05)",
        "theme_gray_01": "rgba(38, 50, 56, 0.1)",
        "theme_gray_02": "rgba(38, 50, 56, 0.2)",
        "theme_gray_03": "rgba(38, 50, 56, 0.3)",
        "theme_white_005": "rgba(255, 255, 255, 0.05)",
        "theme_white_012": "rgba(255, 255, 255, 0.12)",
        "theme_white": "rgba(255, 255, 255, 1)",
        "theme_black": "rgba(0, 0, 0, 1)",
        "theme_danger": "#dc5242",
        "theme_danger_hover_color": "#e4796d",
        "theme_danger_bg": "rgba(220, 82, 66, 0.5)",
        "theme_danger_bg_level_1": "rgba(220, 82, 66, 0.1)",
        "theme_danger_bg_level_2": "rgba(220, 82, 66, 0.2)",
        "theme_info": "#1e88e5",
        "theme_info_bg": "rgba(30, 136, 229, 0.1)",
        "theme_info_link": "#166dba",
        "theme_warning": "#c79d1c",
        "theme_warning_bg": "rgba(199, 157, 28, 0.2)",
        "theme_warning_link": "#9a7a16",
        "theme_success": "#6dae02",
        "theme_success_bg": "rgba(109, 174, 2, 0.1)",
        "theme_success_link": "#4d7c01",
        "theme_btn_hover_bg": "rgba(38, 50, 56, 0.05)",
        "theme_btn_active_bg": "rgba(38, 50, 56, 0.1)",
        "theme_btn_disabled_bg": "rgba(38, 50, 56, 0.05)",
        "theme_primary_btn_hover_bg": "#4caf50",
        "theme_primary_btn_active_bg": "#388e3c",
        "theme_danger_btn_bg": "#c63625",
        "theme_danger_btn_hover_bg": "#dc5242",
        "theme_danger_btn_border": "#9b2a1d",
        "theme_warning_btn_bg": "#c79d1c",
        "theme_warning_btn_hover_bg": "#e1b42b",
        "theme_warning_btn_border": "#c79d1c",
        "theme_warning_btn_hover_border": "#e1b42b",
        "theme_tab_active_bg": "rgba(67, 160, 71, 0.2)",
        "theme_tab_active_color": "#347c37",
        "theme_tag_color": "#787459",
        "theme_tag_color_hover": "#4C482E",
        "theme_tag_bg": "#FAF6D8",
        "theme_tag_bg_hover": "#F8F0C0",
        "theme_special_light_color": "#770000",
        "theme_special_light_bg": "#F0F0FF",
        "theme_find_replace_highlight_bg": "#F5D87D",
    }
    default_light = {
        "bg":       "#ffffff",
        "fg":       "#000000",
        "list_bg":  "#eaf0f7",
        "btn_bg":   "#ebe6ff",
        "log_bg":   "#dbffd9",
        "log_fg":   "#2d2d2d",
        "label":    "#475569",
        "button_text": "#1e293b",
        "accent":   "#9ab8f5",
        "accent_fill": "#9ab8f5",
        "accent_text": "#000000",
        "run_bg":   "#0cf000",
        "border":   "#000000",
        "header_bg": "#ffffff",
        "panel_bg": "#eaf0f7",
        "tab_inactive": "#657b9a",
        "glow":     "#3b82f6",
        "lore":     "#3b82f6",
        "lore_hover": "#79b4fb",
        "anach":    "#fb634d",
        "tooltip":  "#fcf34b",
        "mask_015": "rgba(0, 0, 0, 0.08)",
        "mask_025": "rgba(0, 0, 0, 0.12)",
        "mask_03":  "rgba(0, 0, 0, 0.15)",
        "mask_05":  "rgba(0, 0, 0, 0.2)",
        "mask_08":  "rgba(0, 0, 0, 0.3)",
        # Theme color channels
        "theme_backgrounds_color": "245, 247, 248",
        "theme_primaries_color": "67, 160, 71",
        "theme_blacks": "0, 0, 0",
        "theme_whites": "255, 255, 255",
        "theme_grays": "38, 50, 56",
        "theme_typeface_color": "38, 50, 56",
        "theme_cards_color": "38, 50, 56",
        # Theme colors
        "theme_level_1_bg": "#f5f7f8",
        "theme_level_2_bg": "#ffffff",
        "theme_level_3_bg": "#ffffff",
        "theme_primary": "#43a047",
        "theme_link_hover": "#5bbb60",
        "theme_border_color": "rgba(38, 50, 56, 0.1)",
        "theme_dark_border_color": "rgba(0, 0, 0, 0.12)",
        "theme_shimmer": "#eceff1",
        "theme_icons_color": "rgba(38, 50, 56, 1)",
        "theme_primary_green_50": "#e8f5e9",
        "theme_primary_green_100": "#c8e6c9",
        "theme_primary_blue_600": "#1e88e5",
        "theme_primary_blue_gray": "#eceff1",
        "theme_dark": "rgba(38, 50, 56, 1)",
        "theme_gray_005": "rgba(38, 50, 56, 0.05)",
        "theme_gray_01": "rgba(38, 50, 56, 0.1)",
        "theme_gray_02": "rgba(38, 50, 56, 0.2)",
        "theme_gray_03": "rgba(38, 50, 56, 0.3)",
        "theme_white_005": "rgba(255, 255, 255, 0.05)",
        "theme_white_012": "rgba(255, 255, 255, 0.12)",
        "theme_white": "rgba(255, 255, 255, 1)",
        "theme_black": "rgba(0, 0, 0, 1)",
        "theme_danger": "#dc5242",
        "theme_danger_hover_color": "#e4796d",
        "theme_danger_bg": "rgba(220, 82, 66, 0.5)",
        "theme_danger_bg_level_1": "rgba(220, 82, 66, 0.1)",
        "theme_danger_bg_level_2": "rgba(220, 82, 66, 0.2)",
        "theme_info": "#1e88e5",
        "theme_info_bg": "rgba(30, 136, 229, 0.1)",
        "theme_info_link": "#166dba",
        "theme_warning": "#c79d1c",
        "theme_warning_bg": "rgba(199, 157, 28, 0.2)",
        "theme_warning_link": "#9a7a16",
        "theme_success": "#6dae02",
        "theme_success_bg": "rgba(109, 174, 2, 0.1)",
        "theme_success_link": "#4d7c01",
        "theme_btn_hover_bg": "rgba(38, 50, 56, 0.05)",
        "theme_btn_active_bg": "rgba(38, 50, 56, 0.1)",
        "theme_btn_disabled_bg": "rgba(38, 50, 56, 0.05)",
        "theme_primary_btn_hover_bg": "#4caf50",
        "theme_primary_btn_active_bg": "#388e3c",
        "theme_danger_btn_bg": "#c63625",
        "theme_danger_btn_hover_bg": "#dc5242",
        "theme_danger_btn_border": "#9b2a1d",
        "theme_warning_btn_bg": "#c79d1c",
        "theme_warning_btn_hover_bg": "#e1b42b",
        "theme_warning_btn_border": "#c79d1c",
        "theme_warning_btn_hover_border": "#e1b42b",
        "theme_tab_active_bg": "rgba(67, 160, 71, 0.2)",
        "theme_tab_active_color": "#347c37",
        "theme_tag_color": "#787459",
        "theme_tag_color_hover": "#4C482E",
        "theme_tag_bg": "#FAF6D8",
        "theme_tag_bg_hover": "#F8F0C0",
        "theme_special_light_color": "#770000",
        "theme_special_light_bg": "#F0F0FF",
        "theme_find_replace_highlight_bg": "#F5D87D",
    }
    
    if dark_mode:
        # Use custom dark theme if configured
        custom = cm.user_settings.get("custom_dark_theme", {}) if hasattr(cm, 'user_settings') else {}
        if custom:
            return {**default_dark, **custom}
        return default_dark
    else:
        # Use custom light theme if configured
        custom = cm.user_settings.get("custom_light_theme", {}) if hasattr(cm, 'user_settings') else {}
        if custom:
            return {**default_light, **custom}
        return default_light

@eel.expose
def toggle_dark_mode():
    """Toggle dark mode and return new theme colors."""
    current_mode = cm.user_settings.get("dark_mode", False) if hasattr(cm, 'user_settings') else False
    new_mode = not current_mode
    cm.user_settings.setdefault("dark_mode", False)
    cm.user_settings["dark_mode"] = new_mode
    cm.save_user_settings()
    return get_theme_colors()

# =============================================================================
# SETTINGS & CONFIG
# =============================================================================
# --- CONFIG LIST MANAGEMENT (Folders, Triggers) ---
@eel.expose
def update_config_dict(dict_key, action, key, value=None):
    """Handles Dictionary-based settings (tags, presets)"""
    user_specific_keys = ["speaker_archetypes", "speaker_notes"]
    is_user_specific = dict_key in user_specific_keys
    
    if is_user_specific:
        cm.user_settings.setdefault(dict_key, {})
        target_dict = cm.user_settings
    else:
        cm.config.setdefault(dict_key, {})
        target_dict = cm.config
        
    if action == "add":
        target_dict[dict_key][key] = value
    elif action == "remove":
        if key in target_dict[dict_key]:
            del target_dict[dict_key][key]
            
    if is_user_specific:
        cm.save_user_settings()
    else:
        cm.save_all()
    return target_dict[dict_key]
    
@eel.expose
def update_config_list(list_key, action, item=None, index=None):
    """Generic handler for folders and triggers lists"""
    user_specific_keys = ["folders", "triggers"]
    is_user_specific = list_key in user_specific_keys
    
    if is_user_specific:
        cm.user_settings.setdefault(list_key, [])
        target_dict = cm.user_settings
    else:
        cm.config.setdefault(list_key, [])
        target_dict = cm.config
        
    if action == "add" and item:
        target_dict[list_key].append(item)
    elif action == "remove":
        if index is not None:
            target_dict[list_key].pop(index)
        elif item in target_dict[list_key]:
            target_dict[list_key].remove(item)
            
    if is_user_specific:
        cm.save_user_settings()
    else:
        cm.save_all()
    return target_dict[list_key]

@eel.expose
def switch_language(new_language):
    """Switch to a different language and reload config."""
    global cm, engine, _lore_engine
    success = cm.switch_language(new_language)
    if success:
        # Save language to global user_settings
        global_user_settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_settings.json")
        try:
            user_settings = {}
            if os.path.exists(global_user_settings_path):
                with open(global_user_settings_path, 'r', encoding='utf-8') as f:
                    user_settings = json.load(f)
            user_settings["language"] = new_language
            with open(global_user_settings_path, 'w', encoding='utf-8') as f:
                json.dump(user_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving global user_settings: {e}")
        # Reload vocab for the new language
        reload_vocab()
        # Reinitialize engine with new config
        engine = TranslationEngine(cm.config.get("tag_map", {}))
        # Invalidate lore cache
        _lore_engine = None
    return success

@eel.expose
def create_language(language_code):
    """Create a new language directory with default config"""
    import os
    import shutil
    import json
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(base_dir, "config", language_code)
    
    if not language_code or not language_code.isalpha() or len(language_code) != 2:
        return False, "Invalid language code (must be 2 letters)"
    
    if os.path.exists(config_dir):
        return False, "Language already exists"
    
    try:
        os.makedirs(config_dir, exist_ok=True)
        # Copy formatter_config.json from en as a template
        en_config = os.path.join(base_dir, "config", "en", "formatter_config.json")
        if os.path.exists(en_config):
            shutil.copy2(en_config, os.path.join(config_dir, "formatter_config.json"))
        # Copy archetypes.json from config/en/ as a template
        en_archetypes = os.path.join(base_dir, "config", "en", "archetypes.json")
        if os.path.exists(en_archetypes):
            shutil.copy2(en_archetypes, os.path.join(config_dir, "archetypes.json"))
        # Copy vocab files from config/en/ as templates
        en_dd1_vocab = os.path.join(base_dir, "config", "en", "dd1_vocab.json")
        if os.path.exists(en_dd1_vocab):
            shutil.copy2(en_dd1_vocab, os.path.join(config_dir, "dd1_vocab.json"))
        en_other_vocab = os.path.join(base_dir, "config", "en", "other_vocab.json")
        if os.path.exists(en_other_vocab):
            shutil.copy2(en_other_vocab, os.path.join(config_dir, "other_vocab.json"))
        
        # Copy anach_definitions.json and archaic_examples.json from config/en/ as templates
        en_anach_definitions = os.path.join(base_dir, "config", "en", "anach_definitions.json")
        if os.path.exists(en_anach_definitions):
            shutil.copy2(en_anach_definitions, os.path.join(config_dir, "anach_definitions.json"))
        en_archaic_examples = os.path.join(base_dir, "config", "en", "archaic_examples.json")
        if os.path.exists(en_archaic_examples):
            shutil.copy2(en_archaic_examples, os.path.join(config_dir, "archaic_examples.json"))
        
        # Create minimal user_settings.json with only language-specific defaults
        # Do NOT include sync settings (github_repo, github_token, sync_nickname, sync_auto)
        # Do NOT include bible_path/glossary_path - these should be configured per-language by the user
        user_settings = {
            "folders": [],
            "bible_path": "",
            "glossary_path": "",
            "assets_path": "assets",
            "theme_mode": "dark",
            "dark_mode": True,
            "in_universe": True,
            "openrouter_models": [
                "openrouter/auto",
                "meta-llama/llama-3.3-70b-instruct:free",
                "google/gemma-3-27b-it:free"
            ],
            "selected_openrouter_model": "openrouter/auto",
            "preview_mode": True,
            "show_paid_models": False,
            "selected_preset": "Dialogue Box",
            "custom_dark_theme": {},
            "custom_light_theme": {},
            "last_stats": {
                "total": 0,
                "translated": 0,
                "percent": 0
            },
            # Sync settings intentionally omitted - must be configured per-language
        }
        with open(os.path.join(config_dir, "user_settings.json"), 'w', encoding='utf-8') as f:
            json.dump(user_settings, f, indent=4)
        
        return True, f"Created language: {language_code}"
    except Exception as e:
        return False, str(e)

@eel.expose
def get_available_languages():
    """Get list of available languages (directories in config/)"""
    import os
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
    if not os.path.exists(config_dir):
        return ["en"]
    languages = [d for d in os.listdir(config_dir) if os.path.isdir(os.path.join(config_dir, d))]
    return sorted(languages) if languages else ["en"]

@eel.expose
def get_full_config():
    data = cm.config.copy()
    data['deepl_api_key']      = cm.get_key("deepl_api_key")
    data['openrouter_api_key'] = cm.get_key("openrouter_api_key")
    # Merge user-specific settings (includes github_token now)
    data.update(cm.user_settings)
    data['language'] = cm.language
    for key in ["folders", "triggers", "replace_rules"]:
        if key not in data:
            data[key] = []
    return data

@eel.expose
def save_config_field(key, value):
    global _lore_engine
    print(f"[DEBUG] save_config_field: key={key}, value={value[:50] if isinstance(value, str) else value}")
    user_specific_keys = [
        "folders", "bible_path", "glossary_path", "assets_path",
        "theme_mode", "dark_mode", "in_universe", "openrouter_models",
        "selected_openrouter_model", "preview_mode",
        "show_paid_models", "selected_preset",
        "custom_dark_theme", "custom_light_theme", "last_stats",
        "github_repo", "github_token", "sync_nickname", "sync_auto"
    ]
    if key in ["deepl_api_key", "openrouter_api_key"]:
        cm.set_key(key, value)
    elif key in user_specific_keys:
        cm.user_settings.setdefault(key, value)
        cm.user_settings[key] = value
        print(f"[DEBUG] Calling save_user_settings() for key={key}")
        cm.save_user_settings()  # Save to user_settings.json
        if key in ("bible_path", "glossary_path"):
            _lore_engine = None   # invalidate lore cache
    else:
        cm.config[key] = value
        cm.save_all()
        if key == "tag_map":
            engine.__init__(cm.config.get("tag_map", {}))
    return True

@eel.expose
def update_map_setting(section, key, value):
    if section == "tag_map" and isinstance(value, str):
        display_text = value
        # Strip ★ character (lore marker) before calculating length
        text_without_stars = display_text.replace('★', '')
        length       = engine.get_simulated_len(text_without_stars)
        cm.config.setdefault("tag_display", {})[key] = display_text
        cm.config.setdefault("tag_map",     {})[key] = length
    else:
        if section not in cm.config:
            cm.config[section] = {}
        cm.config[section][key] = value
    cm.save_all()
    if section == "tag_map":
        engine.__init__(cm.config.get("tag_map", {}))
    return True

@eel.expose
def delete_map_setting(section, key):
    if section in cm.config and key in cm.config[section]:
        del cm.config[section][key]
        if section == "tag_map":
            cm.config.get("tag_display", {}).pop(key, None)
            engine.__init__(cm.config.get("tag_map", {}))
        cm.save_all()
        return True
    return False

@eel.expose
def add_list_item(section, item):
    user_specific_keys = ["folders", "triggers"]
    is_user_specific = section in user_specific_keys
    
    if is_user_specific:
        cm.user_settings.setdefault(section, [])
        items = cm.user_settings.get(section, [])
        if item not in items:
            items.append(item)
            cm.user_settings[section] = items
            cm.save_user_settings()
    else:
        cm.config.setdefault(section, [])
        items = cm.config.get(section, [])
        if item not in items:
            items.append(item)
            cm.config[section] = items
            cm.save_all()
    return items

@eel.expose
def remove_list_item(section, item):
    user_specific_keys = ["folders", "triggers"]
    is_user_specific = section in user_specific_keys
    
    if is_user_specific:
        cm.user_settings.setdefault(section, [])
        items = cm.user_settings.get(section, [])
        if item in items:
            items.remove(item)
            cm.user_settings[section] = items
            cm.save_user_settings()
    else:
        cm.config.setdefault(section, [])
        items = cm.config.get(section, [])
        if item in items:
            items.remove(item)
            cm.config[section] = items
            cm.save_all()
    return items

@eel.expose
def update_list_item(section, index, item):
    user_specific_keys = ["folders", "triggers"]
    is_user_specific = section in user_specific_keys
    
    if is_user_specific:
        cm.user_settings.setdefault(section, [])
        items = cm.user_settings.get(section, [])
        if 0 <= index < len(items):
            items[index] = item
            cm.user_settings[section] = items
            cm.save_user_settings()
    else:
        cm.config.setdefault(section, [])
        items = cm.config.get(section, [])
        if 0 <= index < len(items):
            items[index] = item
            cm.config[section] = items
            cm.save_all()
    return items

# --- REPLACEMENT RULES ---
@eel.expose
def save_replace_rule(rule_data, index=None):
    """Saves or updates a regex replacement rule"""
    rules = cm.config.get("replace_rules", [])
    if index is not None and 0 <= index < len(rules):
        rules[index] = rule_data
    else:
        rules.append(rule_data)
    
    cm.config["replace_rules"] = rules
    cm.save_all()
    return rules

@eel.expose
def save_replace_rules(rules):
    """Saves the entire array of regex replacement rules"""
    cm.config["replace_rules"] = rules
    cm.save_all()
    return rules

@eel.expose
def save_archetype(key, name, notes):
    cm.config.setdefault("archetypes", {})[key] = {"name": name, "notes": notes}
    cm.save_all()
    return True

# --- ARCHETYPES ---
@eel.expose
def save_archetype_data(key, data):
    """Hooks into the archetype system used by the LoreEngine"""
    if "archetypes" not in cm.config:
        cm.config["archetypes"] = {}
    
    cm.config["archetypes"][key] = data
    cm.save_all()
    # If LoreEngine is active, we'd trigger a reload here
    global _lore_engine
    _lore_engine = None 
    return True

# --- FILE PICKER (Parity with old filedialog) ---
@eel.expose
def pick_directory():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askdirectory()
    root.destroy()
    return path

@eel.expose
def pick_file(title="Select File", filetypes=[("All Files", "*.*")]):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return path

@eel.expose
def add_folder(folder_path):
    """Add a folder to the watched folders list."""
    cm.user_settings.setdefault("folders", [])
    if folder_path and folder_path not in cm.user_settings["folders"]:
        cm.user_settings["folders"].append(folder_path)
        cm.save_user_settings()
        return cm.user_settings["folders"]
    return cm.user_settings.get("folders", []) if hasattr(cm, 'user_settings') else []

@eel.expose
def remove_folder(index):
    """Remove a folder from the watched folders list by index."""
    folders = cm.user_settings.get("folders", [])
    if 0 <= index < len(folders):
        folders.pop(index)
        cm.user_settings.setdefault("folders", [])
        cm.user_settings["folders"] = folders
        cm.save_user_settings()
    return folders

@eel.expose
def add_trigger(trigger_text):
    """Add a trigger to the scan triggers list."""
    cm.user_settings.setdefault("triggers", [])
    if trigger_text and trigger_text not in cm.user_settings["triggers"]:
        cm.user_settings["triggers"].append(trigger_text)
        cm.save_user_settings()
        return cm.user_settings["triggers"]
    return cm.user_settings.get("triggers", []) if hasattr(cm, 'user_settings') else []

@eel.expose
def remove_trigger(index):
    """Remove a trigger from the scan triggers list by index."""
    triggers = cm.user_settings.get("triggers", [])
    if 0 <= index < len(triggers):
        triggers.pop(index)
        cm.user_settings.setdefault("triggers", [])
        cm.user_settings["triggers"] = triggers
        cm.save_user_settings()
    return triggers

@eel.expose
def refresh_ui():
    """Refresh UI components and notify active editors."""
    global active_editors
    
    # In web context, this mainly updates the dashboard data
    # The frontend will handle the actual UI refresh
    return {
        "folders": cm.user_settings.get("folders", []),
        "triggers": cm.user_settings.get("triggers", []),
        "presets": list(cm.config.get("presets", {"Standard": 50}).keys()),
        "wall_presets": list(cm.config.get("wall_presets", {"Standard": 7}).keys()),
        "selected_preset": cm.user_settings.get("selected_preset", "Standard"),
        "wall_preset": cm.user_settings.get("wall_preset", "Standard"),
        "in_universe": cm.user_settings.get("in_universe", True),
        "preview_mode": cm.user_settings.get("preview_mode", False),
    }

@eel.expose
def notify_active_editors():
    """Notify all active editors to reload their glossary maps."""
    global active_editors
    # In web context, this would notify connected browser sessions
    # For now, return the count of active editors
    return {"active_editors": len(active_editors)}

@eel.expose
def register_editor():
    """Register a new active editor session."""
    global active_editors
    editor_id = len(active_editors)
    active_editors.append({"id": editor_id, "created": datetime.now().isoformat()})
    return {"editor_id": editor_id, "total_active": len(active_editors)}

@eel.expose
def unregister_editor(editor_id):
    """Unregister an editor session."""
    global active_editors
    active_editors = [e for e in active_editors if e.get("id") != editor_id]
    return {"active_editors": len(active_editors)}

@eel.expose
def delete_archetype(key):
    archetypes = cm.config.get("archetypes", {})
    if key in archetypes:
        del archetypes[key]
        cm.save_all()
        return True
    return False

@eel.expose
def reset_archetypes_to_defaults():
    try:
        from src.lore_engine import DEFAULT_ARCHETYPES
        # DEFAULT_ARCHETYPES is nested: {"archetypes": {key: {...}}}
        default_archs = DEFAULT_ARCHETYPES.get("archetypes", {})
        cm.config["archetypes"] = {k: dict(v) for k, v in default_archs.items()}
        cm.save_all()
        # Invalidate cached LoreEngine to pick up new archetypes
        global _lore_engine
        _lore_engine = None
        return cm.config["archetypes"]
    except Exception as e:
        return {"error": str(e)}

@eel.expose
def reload_archetypes_from_file():
    """Merge new archetypes from DEFAULT_ARCHETYPES into existing config."""
    try:
        from src.lore_engine import DEFAULT_ARCHETYPES
        # DEFAULT_ARCHETYPES is nested: {"archetypes": {key: {...}}}
        default_archs = DEFAULT_ARCHETYPES.get("archetypes", {})
        if "archetypes" not in cm.config:
            cm.config["archetypes"] = {}
        # Merge new archetypes without overwriting existing ones
        for key, value in default_archs.items():
            if key not in cm.config["archetypes"]:
                cm.config["archetypes"][key] = dict(value)
        cm.save_all()
        # Invalidate cached LoreEngine to pick up new archetypes
        global _lore_engine
        _lore_engine = None
        return cm.config["archetypes"]
    except Exception as e:
        return {"error": str(e)}

@eel.expose
def save_speaker_archetype(speaker, archetype_key, note=""):
    cm.user_settings.setdefault("speaker_archetypes", {})[speaker] = archetype_key if archetype_key else None
    if not archetype_key:
        cm.user_settings["speaker_archetypes"].pop(speaker, None)
    if note:
        cm.user_settings.setdefault("speaker_notes", {})[speaker] = note
    else:
        cm.user_settings.setdefault("speaker_notes", {}).pop(speaker, None)
    cm.save_user_settings()
    return True

@eel.expose
def get_archetypes_list():
    """Return list of available archetypes for dropdown."""
    archetypes = cm.archetypes.get("archetypes", {})
    result = [{"key": k, "name": v.get("name", k)} for k, v in archetypes.items()]
    result.insert(0, {"key": "", "name": "(none)"})
    return result

@eel.expose
def get_speaker_archetype(speaker):
    """Return saved archetype for a speaker."""
    debug_log("Main", f"get_speaker_archetype called for speaker: {speaker}")
    result = cm.user_settings.get("speaker_archetypes", {}).get(speaker, "")
    debug_log("Main", f"get_speaker_archetype result: {result}")
    return result

@eel.expose
def get_speaker_note(speaker):
    """Return saved note for a speaker."""
    debug_log("Main", f"get_speaker_note called for speaker: {speaker}")
    result = cm.user_settings.get("speaker_notes", {}).get(speaker, "")
    debug_log("Main", f"get_speaker_note result: {result}")
    return result

@eel.expose
def get_speakers_list():
    """Return list of unique speakers from current review queue."""
    speakers = set()
    for item in review_items:
        speaker = item.get("speaker", "")
        if speaker and speaker != "Unknown":
            speakers.add(speaker)
    return sorted(list(speakers))

@eel.expose
def get_entry_types_list():
    """Return list of available entry types from config."""
    rules = cm.config.get("entry_type_rules", {})
    return [{"key": k, "name": k} for k in sorted(rules.keys())]

# =============================================================================
# API HELPERS
# =============================================================================

@eel.expose
def test_deepl(key):
    return DeepLClient(key).translate("テスト")

@eel.expose
def test_openrouter(key):
    return OpenRouterClient(key).chat([{"role": "user", "content": "Respond with 'Connected'"}])

@eel.expose
def fetch_models(key, free_only=True):
    models = OpenRouterClient(key).fetch_models(free_only=free_only)
    if models:
        cm.user_settings.setdefault("openrouter_models", [])
        cm.user_settings["openrouter_models"] = models
        cm.save_user_settings()
    return models

# =============================================================================
# ENGINE HELPERS
# =============================================================================

@eel.expose
def test_regex(pattern, repl, text):
    try:
        if not pattern:
            return {"text": text}
        return {"text": re.sub(pattern, repl, text)}
    except Exception as e:
        return {"error": str(e)}

@eel.expose
def get_simulated_len(text):
    if not text:
        return 0
    # Strip ★ character (lore marker) before calculating length
    text_without_stars = text.replace('★', '')
    return engine.get_simulated_len(text_without_stars)

@eel.expose
def rewrap_text(text, limit=None):
    if not text:
        return text
    if limit is None:
        limit = list(cm.config.get("presets", {"Standard": 50}).values())[0]
    try:
        return engine.master_tag_wrap(text, int(limit))
    except Exception as e:
        print(f"[rewrap_text] Error: {e}")
        return text

@eel.expose
def get_tag_aware_character_count(text):
    """Get tag-aware character count for line counters."""
    if not text:
        return 0
    try:
        return engine.get_simulated_len(text)
    except Exception as e:
        print(f"[get_tag_aware_character_count] Error: {e}")
        return len(text)  # Fallback to raw length



@eel.expose
def get_standard_limit():
    selected = cm.user_settings.get("selected_preset", "Standard")
    presets  = cm.config.get("presets", {"Standard": 50})
    return presets.get(selected, list(presets.values())[0] if presets else 50)

@eel.expose
def get_wall_limit():
    selected = cm.user_settings.get("wall_preset", "Standard")
    presets  = cm.config.get("wall_presets", {"Standard": 3})
    return presets.get(selected, list(presets.values())[0] if presets else 3)

@eel.expose
def get_all_presets():
    """Return all preset values for character and line limits."""
    char_presets = cm.config.get("presets", {"Standard": 50})
    line_presets = cm.config.get("wall_presets", {"Standard": 3})
    return {
        "char_presets": char_presets,
        "line_presets": line_presets,
        "selected_char": cm.user_settings.get("selected_preset", "Standard"),
        "selected_line": cm.user_settings.get("wall_preset", "Standard"),
    }

@eel.expose
def get_preview_profiles():
    """Return complete preview metadata including hardcoded defaults."""
    pf = cm.config.get("preview_font", {})
    
    # Hardcoded defaults from formatter_config.json
    _hardcoded = {
        "dialogue": {
            "crop": [3, 5, 478, 173], "pad": 20, "fg": "#2f2b2b",
            "font_sz": 18, "line_spacing": 1, "text_x": 38, "text_y": 21,
        },
        "questlog": {
            "crop": [0, 0, 400, 107], "pad": 10, "fg": "#ffffff",
            "font_sz": 13, "line_spacing": 1, "text_x": 93, "text_y": 82,
        },
        "questlog_scroll": {
            "crop": [0, 0, 480, 335], "pad": 10, "fg": "#ffffff",
            "font_sz": 18, "line_spacing": 1, "text_x": 25, "text_y": 10,
        },
        "tutorial_body": {
            "crop": [0, 0, 480, 335], "pad": 10, "fg": "#ffffff",
            "font_sz": 18, "line_spacing": 1, "text_x": 20, "text_y": 89,
        },
        "boardquest_list": {
            "crop": [25, 129, 424, 200], "pad": 10, "fg": "#ffffff",
            "font_sz": 15, "line_spacing": 1, "text_x": 57, "text_y": 42,
        },
        "exm_list": {
            "crop": [0, 122, 435, 168], "pad": 10, "fg": "#ffffff",
            "font_sz": 18, "line_spacing": 1, "text_x": 41, "text_y": 15,
        },
        "tutorial_list": {
            "crop": [0, 0, 264, 110], "pad": 10, "fg": "#ffffff",
            "font_sz": 15, "line_spacing": 1, "text_x": 25, "text_y": 79,
        },
        "item_window": {
            "crop": [0, 124, 325, 241], "pad": 10, "fg": "#ffffff",
            "font_sz": 10, "line_spacing": 1, "text_x": 25, "text_y": 10,
        },
        "appraisal_left": {
            "crop": [0, 100, 480, 155], "pad": 10, "fg": "#ffffff",
            "font_sz": 9, "line_spacing": 1, "text_x": 45, "text_y": 36,
        },
        "appraisal_right": {
            "crop": [0, 27, 292, 70], "pad": 10, "fg": "#ffffff",
            "font_sz": 18, "line_spacing": 1, "text_x": 33, "text_y": 18,
        },
        "chat": {
            "crop": [22, 0, 366, 115], "pad": 10, "fg": "#ffffff",
            "font_sz": 18, "line_spacing": 1, "text_x": 7, "text_y": 6,
        },
        "choice": {
            "crop": [0, 0, 261, 187], "pad": 10, "fg": "#ffffff",
            "font_sz": 12, "line_spacing": 1, "text_x": 28, "text_y": 31,
        },
        "item_name": {
            "crop": [0, 0, 333, 69], "pad": 10, "fg": "#ffffff",
            "font_sz": 18, "line_spacing": 1, "text_x": 73, "text_y": 20,
        },
        "substory": {
            "crop": [2, 256, 416, 451], "pad": 10, "fg": "#2f2b2b",
            "font_sz": 18, "line_spacing": 1, "text_x": 26, "text_y": 30,
        },
    }
    
    meta = {}
    all_keys = list(_hardcoded.keys()) + [k for k in pf if k not in _hardcoded]
    for key in all_keys:
        base = dict(_hardcoded.get(key, {
            "crop": [0, 0, 200, 60], "pad": 10,
            "fg": "#000000", "font_sz": 14, "line_spacing": 1,
            "text_x": 10, "text_y": 10,
        }))
        saved = pf.get(key, {})
        if "crop"         in saved: base["crop"]         = list(saved["crop"])
        if "font_sz"      in saved: base["font_sz"]      = saved["font_sz"]
        if "line_spacing" in saved: base["line_spacing"]  = saved["line_spacing"]
        if "text_x"       in saved: base["text_x"]       = saved["text_x"]
        if "text_y"       in saved: base["text_y"]       = saved["text_y"]
        if "fg"           in saved: base["fg"]           = saved["fg"]
        meta[key] = base
    
    return meta

@eel.expose
def save_preview_profile(profile_name, profile_data):
    """Save a preview profile configuration."""
    if "preview_font" not in cm.config:
        cm.config["preview_font"] = {}
    cm.config["preview_font"][profile_name] = profile_data
    cm.save_all()
    return True

@eel.expose
def add_preview_type(profile_name):
    """Add a new preview type with default settings."""
    if "preview_font" not in cm.config:
        cm.config["preview_font"] = {}
    
    default_profile = {
        "crop": [0, 0, 200, 60],
        "pad": 10,
        "fg": "#ffffff",
        "font_sz": 14,
        "line_spacing": 1,
        "text_x": 0,
        "text_y": 0
    }
    
    cm.config["preview_font"][profile_name] = default_profile
    cm.save_all()
    return True

@eel.expose
def remove_preview_type(profile_name):
    """Remove a preview type (except built-in ones)."""
    if profile_name in ["dialogue", "choice", "questlog", "tutorial"]:
        return False  # Cannot remove built-in types
    
    if "preview_font" in cm.config and profile_name in cm.config["preview_font"]:
        del cm.config["preview_font"][profile_name]
        cm.save_all()
        return True
    return False

@eel.expose
def generate_preview_image(profile_name, text):
    """Generate a preview image with text overlay for the given profile."""
    import time
    start_time = time.time()
    try:
        import os
        import io
        import base64
        import hashlib
        from PIL import Image, ImageDraw, ImageFont
        
        # Create cache key from profile_name and text
        cache_key = f"{profile_name}:{hashlib.md5(text.encode('utf-8')).hexdigest()}"
        
        # Check cache
        with _preview_cache_lock:
            if cache_key in _preview_cache:
                print(f"[generate_preview_image] Cache hit for {profile_name}")
                return _preview_cache[cache_key]
        
        print(f"[generate_preview_image] Cache miss for {profile_name}, text={text[:50]}...")
        cache_check_time = time.time()
        
        # Get profile data
        profiles = get_preview_profiles()
        profile = profiles.get(profile_name)
        if not profile:
            print(f"[generate_preview_image] Profile '{profile_name}' not found. Available: {list(profiles.keys())}")
            return {"error": f"Profile '{profile_name}' not found"}
        
        print(f"[generate_preview_image] Profile found: {profile}")
        print(f"[generate_preview_image] Text parameters - font_sz: {profile.get('font_sz', 14)}, line_spacing: {profile.get('line_spacing', 1)}, text_x: {profile.get('text_x', 10)}, text_y: {profile.get('text_y', 10)}")
        print(f"[generate_preview_image] Received text has {text.count(chr(10))} newlines, {len(text)} chars")
        print(f"[generate_preview_image] First 200 chars: {text[:200]}")
        profile_time = time.time()
        image_load_time = profile_time  # Default if no image loaded
        
        # Load actual PNG image from assets
        # assets_path is in user_settings, not the main config
        assets_path = cm.user_settings.get("assets_path") if hasattr(cm, 'user_settings') else None
        if not assets_path:
            return {
                "error": "Assets path not configured",
                "debug": {
                    "has_user_settings": hasattr(cm, 'user_settings'),
                    "assets_path": assets_path
                }
            }
        
        # Don't crop in Python - return full image and use CSS to position based on crop values
        # This prevents zooming when crop dimensions change
        # Try to load actual PNG files
        src_candidates = [
            os.path.join(assets_path, f"{profile_name}_box.png"),
            os.path.join(assets_path, "dialogue_box.png"),
            os.path.join(assets_path, "choice_box.png"),
            os.path.join(assets_path, "questlog_box.png"),
            os.path.join(assets_path, "tutorial_box.png"),
        ]
        
        final_base = None
        for png_path in src_candidates:
            print(f"[generate_preview_image] Trying to load: {png_path}, exists: {os.path.exists(png_path)}")
            if not os.path.exists(png_path):
                continue
            try:
                with Image.open(png_path) as img:
                    final_base = img.convert("RGBA")
                print(f"[generate_preview_image] Successfully loaded: {png_path}")
                image_load_time = time.time()
                break
            except Exception as e:
                print(f"[generate_preview_image] Failed to load {png_path}: {e}")
                continue
        
        # Fallback to procedural if no image found - create with transparency
        if final_base is None:
            print(f"[generate_preview_image] No PNG found, using procedural fallback")
            _box_styles = {
                "dialogue": {"bg": (242, 238, 220, 255), "border": (180, 160, 100, 255)},
                "choice":   {"bg": (30, 25, 45, 255),    "border": (120, 100, 200, 255)},
                "questlog": {"bg": (45, 45, 55, 255),    "border": (100, 100, 120, 255)},
                "tutorial": {"bg": (35, 55, 35, 255),    "border": (100, 150, 100, 255)},
            }
            style = _box_styles.get(profile_name, {"bg": (40, 40, 40, 255), "border": (100, 100, 100, 255)})
            # Use fixed size for fallback - don't use crop dimensions
            final_base = Image.new('RGBA', (800, 300), style["bg"])
            draw = ImageDraw.Draw(final_base)
            border_color = style["border"]
            draw.rectangle([0, 0, 799, 299], outline=border_color, width=2)
        
        # Try to load font
        font_path = os.path.join(assets_path, "DDONfont.otf")
        print(f"[generate_preview_image] Font path: {font_path}, exists: {os.path.exists(font_path)}")
        if not os.path.exists(font_path):
            font_path = None
        
        font_load_time = time.time()
        if not font_path:
            # Fallback to system font
            print(f"[generate_preview_image] Font not found, using system font")
            try:
                font = ImageFont.truetype("arial.ttf", profile.get("font_sz", 14))
            except Exception as e:
                print(f"[generate_preview_image] System font failed: {e}, using default")
                font = ImageFont.load_default()
        else:
            try:
                font = ImageFont.truetype(font_path, profile.get("font_sz", 14))
                print(f"[generate_preview_image] Successfully loaded custom font")
            except Exception as e:
                print(f"[generate_preview_image] Custom font failed: {e}, using default")
                font = ImageFont.load_default()
        
        # Add text overlay on RGBA image
        draw = ImageDraw.Draw(final_base)
        text_x = profile.get("text_x", 10)
        text_y = profile.get("text_y", 10)
        
        # Get crop values to pass to JavaScript for positioning
        crop = profile.get("crop", [0, 0, 0, 0])
        text_color = profile.get("fg", "#ffffff")
        
        # Convert hex color to RGBA (with full opacity)
        if text_color.startswith("#"):
            text_color = tuple(int(text_color[i:i+2], 16) for i in (1, 3, 5)) + (255,)
        elif isinstance(text_color, str):
            text_color = (255, 255, 255, 255)  # Default white with full opacity
        
        # Draw text with boundary checking only (no automatic wrapping)
        line_spacing = profile.get("line_spacing", 1)
        if line_spacing <= 1:
            line_spacing = 1.2
        
        # Get image dimensions for boundary checking
        img_width, img_height = final_base.size
        margin = 10  # Safety margin from edges
        
        # Calculate maximum text height based on crop settings or image bounds
        crop = profile.get("crop", [0, 0, img_width, img_height])
        max_text_height = crop[3] - text_y - margin if crop[3] > 0 else img_height - text_y - margin
        
        # Split text by manual newlines only (no automatic wrapping)
        lines = text.split('\n')
        y_offset = text_y
        font_size = profile.get("font_sz", 14)
        
        for line in lines:
            if y_offset + font_size > max_text_height:
                # Stop if we've reached the bottom boundary
                print(f"[generate_preview_image] Text truncated - reached bottom boundary at y={y_offset}")
                break
                
            if line.strip():
                draw.text((text_x, y_offset), line, fill=text_color, font=font)
            
            y_offset += int(font_size * line_spacing)
        
        text_draw_time = time.time()
        
        # Convert to base64 (preserve RGBA/transparency)
        buffer = io.BytesIO()
        final_base.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        print(f"[generate_preview_image] Successfully generated preview: {final_base.width}x{final_base.height}")
        print(f"[generate_preview_image] Base64 size: {len(img_base64)} bytes")
        print(f"[generate_preview_image] Timing - Cache check: {(cache_check_time - start_time)*1000:.2f}ms, Profile: {(profile_time - cache_check_time)*1000:.2f}ms, Image load: {(image_load_time - profile_time)*1000:.2f}ms, Font load: {(font_load_time - image_load_time)*1000:.2f}ms, Text draw: {(text_draw_time - font_load_time)*1000:.2f}ms, Base64: {(time.time() - text_draw_time)*1000:.2f}ms, Total: {(time.time() - start_time)*1000:.2f}ms")
        
        result = {
            "image": f"data:image/png;base64,{img_base64}",
            "width": final_base.width,
            "height": final_base.height,
            "crop": crop
        }
        
        # Store in cache
        with _preview_cache_lock:
            _preview_cache[cache_key] = result
            # Limit cache size to 100 entries
            if len(_preview_cache) > 100:
                # Remove oldest entry (first key)
                _preview_cache.pop(next(iter(_preview_cache)))
        
        return result
        
    except Exception as e:
        import traceback
        print(f"[generate_preview_image] Exception: {e}")
        traceback.print_exc()
        return {"error": f"Failed to generate preview: {str(e)}"}

# --- GLOSSING / WORD LOOKUP ---

# --- LORE CONTEXT CACHE ---
_lore_context_cache = {}
_lore_context_cache_lock = threading.Lock()

@eel.expose
def get_gloss(jp_text):
    """Returns morpheme gloss for the given JP text via GlossEngine."""
    print(f"[get_gloss] Called with: {jp_text[:50] if jp_text else 'None'}...")
    if not jp_text:
        return []
    
    # Check prefetch cache first (in-memory, fastest)
    global _prefetch_mgr
    if _prefetch_mgr:
        # Try to find cached gloss by matching jp_text in cached items
        with _prefetch_mgr._lock:
            for cache_key, cached_data in _prefetch_mgr._cache.items():
                # Check if this cached entry has gloss data
                if cached_data.get('gloss_result'):
                    # We can't easily match by jp_text since prefetch caches by category::idx
                    # Skip for now - would need to pass category/idx to use this cache
                    pass
    
    # Check ConfigManager cache (file-based, per-language)
    cached = cm.get_cached("gloss", jp_text)
    if cached:
        print(f"[get_gloss] Cache hit for: {jp_text[:30]}...")
        return cached
    
    ge = _get_gloss_engine()
    print(f"[get_gloss] GlossEngine: {ge}")
    if not ge:
        return []
    # Debug: show lore_map keys from LoreEngine (not cm.config)
    le = _get_lore_engine()
    lore_map = le.lore_map if le else {}
    print(f"[get_gloss] LoreEngine lore_map has {len(lore_map)} keys")
    if "メガド" in lore_map:
        print(f"[get_gloss] Found メガド in lore_map: {lore_map['メガド']}")
    
    # Run gloss with timeout wrapper
    import time
    import re
    start = time.time()
    print(f"[get_gloss] Starting gloss() call with 10s timeout")
    
    # Strip tags from text before sending to gloss engine
    tag_map = cm.config.get("tag_map", {})
    original_text = jp_text
    for tag_key in tag_map.keys():
        tag_pattern = f"<{tag_key}>"
        jp_text = jp_text.replace(tag_pattern, "")
    # Also strip common control tags
    jp_text = re.sub(r'<[^>]+>', '', jp_text)
    
    print(f"[get_gloss] Text length: {len(original_text)} -> {len(jp_text)} chars after stripping tags")
    print(f"[get_gloss] First 100 chars: {jp_text[:100]}")
    
    # Batch process gloss for text longer than 200 chars
    if len(jp_text) > 200:
        print(f"[get_gloss] Text longer than 200 chars, processing in batches")
        # Split text into chunks of ~150 chars
        chunk_size = 150
        chunks = []
        for i in range(0, len(jp_text), chunk_size):
            chunk = jp_text[i:i+chunk_size]
            chunks.append(chunk)
        
        print(f"[get_gloss] Split into {len(chunks)} chunks")
        all_results = []
        
        for i, chunk in enumerate(chunks):
            print(f"[get_gloss] Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
            try:
                tokens = ge.gloss(chunk)
                # Convert tokens to serializable dicts (minimize payload for Eel speed)
                result = [
                    {
                        "surface": t.surface,
                        "pos": t.pos,
                        "candidates": t.candidates[:5] if t.candidates else [],  # Limit to top 5 candidates
                        "is_lore": t.is_lore,
                    }
                    for t in tokens
                ]
                all_results.extend(result)
                print(f"[get_gloss] Chunk {i+1} completed, got {len(result)} tokens")
            except Exception as e:
                print(f"[get_gloss] Error processing chunk {i+1}: {e}")
        
        print(f"[get_gloss] Batch processing completed, total {len(all_results)} tokens")
        # Cache result using ConfigManager (file-based, per-language)
        cm.set_cached("gloss", jp_text, all_results)
        print(f"[get_gloss] Returning {len(all_results)} dicts, total time: {(time.time() - start)*1000:.0f}ms")
        return all_results
    
    def _gloss_with_timeout():
        try:
            tokens = ge.gloss(jp_text)
            print(f"[get_gloss] gloss() returned, got {len(tokens) if tokens else 'None'} tokens")
            # Convert tokens to serializable dicts (minimize payload for Eel speed)
            result = [
                {
                    "surface": t.surface,
                    "pos": t.pos,
                    "candidates": t.candidates[:5] if t.candidates else [],  # Limit to top 5 candidates
                    "is_lore": t.is_lore,
                }
                for t in tokens
            ]
            print(f"[get_gloss] Converted {len(result)} tokens to dicts")
            # Cache result using ConfigManager (file-based, per-language)
            cm.set_cached("gloss", jp_text, result)
            return result
        except Exception as e:
            print(f"[get_gloss] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # Run gloss in thread with timeout
    result_container = [None]
    def _run():
        result_container[0] = _gloss_with_timeout()
    
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=5.0)  # 5 second timeout for gloss() - fail fast for UI responsiveness
    
    if thread.is_alive():
        print(f"[get_gloss] Timeout after 5s, returning empty result")
        return []
    
    if result_container[0]:
        print(f"[get_gloss] Returning {len(result_container[0])} dicts, total time: {(time.time() - start)*1000:.0f}ms")
        return result_container[0]
    
    print(f"[get_gloss] No result, returning empty")
    return []

@eel.expose
def get_lore_context(jp_text):
    """Returns lore glossary + tag display matches for the given JP text."""
    if not jp_text:
        return []
    
    # Check cache
    with _lore_context_cache_lock:
        if jp_text in _lore_context_cache:
            return _lore_context_cache[jp_text]
    
    # Run lore context in a thread to avoid blocking Eel event loop
    result_container = [None]
    error_container = [None]
    
    def _run_lore_context():
        try:
            import time
            start = time.time()
            print(f"[get_lore_context] Starting lore context lookup")
            le = _get_lore_engine()
            if not le:
                error_container[0] = "LoreEngine not available"
                return
            result = []
            # Lore glossary matches
            lore_start = time.time()
            for jp, en in le.scan_text(jp_text):
                result.append({"jp": jp, "en": en, "is_lore": True})
            lore_time = time.time() - lore_start
            print(f"[get_lore_context] lore scan completed in {lore_time*1000:.0f}ms, found {len(result)} matches")
            # Tag display matches
            tag_start = time.time()
            tag_map = cm.config.get("tag_map", {})
            tag_display = cm.config.get("tag_display", {})
            for tag_key in tag_map.keys():
                tag_pattern = f"<{tag_key}>"
                if tag_pattern in jp_text:
                    display_text = tag_display.get(tag_key, tag_key)
                    result.append({"jp": f"<{tag_key}>", "en": display_text, "is_lore": False})
            tag_time = time.time() - tag_start
            print(f"[get_lore_context] tag scan completed in {tag_time*1000:.0f}ms")
            # Cache result
            with _lore_context_cache_lock:
                _lore_context_cache[jp_text] = result
            result_container[0] = result
            print(f"[get_lore_context] Total time: {(time.time() - start)*1000:.0f}ms")
        except Exception as e:
            print(f"[get_lore_context] Error: {e}")
            error_container[0] = str(e)
    
    thread = threading.Thread(target=_run_lore_context)
    thread.start()
    thread.join(timeout=30.0)  # Wait up to 30 seconds for the thread to complete
    
    if error_container[0]:
        print(f"[get_lore_context] Error: {error_container[0]}")
        return []
    if result_container[0] is not None:
        return result_container[0]
    
    # If thread didn't complete in time, return empty result but log it
    print(f"[get_lore_context] Timeout after 30s - returning empty result")
    return []

@eel.expose
def scan_anachronisms(en_text):
    """Scan English text for modern words that should use archaic alternatives."""
    if not en_text:
        return []
    
    # Check ConfigManager cache (file-based, per-language)
    cached = cm.get_cached("anachronisms", en_text)
    if cached:
        print(f"[scan_anachronisms] Cache hit")
        return cached
    
    try:
        le = _get_lore_engine()
        if not le:
            return []
        result = le.scan_anachronisms(en_text)
        # Cache result using ConfigManager (file-based, per-language)
        cm.set_cached("anachronisms", en_text, result)
        return result
    except Exception as e:
        print(f"[scan_anachronisms] Error: {e}")
        return []

@eel.expose
def get_definition(word):
    """Return cached definition for word, or fetch it from Free Dictionary API."""
    if not word:
        return ""
    try:
        le = _get_lore_engine()
        if not le:
            return ""
        # Synchronous fetch - wait for result
        result_container = [None]
        def _callback(w, defn):
            result_container[0] = defn
        le.get_definition(word, _callback)
        # Wait a bit for async fetch to complete if not cached
        import time
        for _ in range(10):  # Wait up to 1 second
            if result_container[0] is not None:
                return result_container[0]
            time.sleep(0.1)
        # If still None, try getting from cache directly
        return le.get_definition(word) or ""
    except Exception as e:
        print(f"[get_definition] Error: {e}")
        return ""

@eel.expose
def prefetch_definitions(words):
    """Background-fetch definitions for a list of words, populating the cache."""
    if not words:
        return {"status": "ok", "message": "No words to prefetch"}
    try:
        le = _get_lore_engine()
        if not le:
            return {"status": "error", "message": "LoreEngine not available"}
        le.prefetch_definitions(words)
        return {"status": "ok", "message": f"Prefetching {len(words)} words"}
    except Exception as e:
        print(f"[prefetch_definitions] Error: {e}")
        return {"status": "error", "message": str(e)}

@eel.expose
def get_adjacent_context(path, row_idx):
    """Returns prev/next rows (0-based row_idx into the CSV rows list)."""
    print(f"[get_adjacent_context] Called with path={path}, row_idx={row_idx}")
    if not path or row_idx is None:
        print(f"[get_adjacent_context] Returning empty: path={path}, row_idx={row_idx}")
        return {}
    try:
        _, _, rows = _read_csv(path)
        print(f"[get_adjacent_context] Read {len(rows)} rows from CSV")
        
        # Row index is used directly (no header row in source CSVs)
        data_row_idx = row_idx
        
        result = {}
        if data_row_idx > 0:
            prev = rows[data_row_idx - 1]
            result["prev"] = {
                "jp": (prev[2] if len(prev) > 2 else "").replace("\r", ""),
                "en": (prev[3] if len(prev) > 3 else "").replace("\r", ""),
            }
            print(f"[get_adjacent_context] Found prev row at index {data_row_idx - 1}")
        if data_row_idx < len(rows) - 1:
            nxt = rows[data_row_idx + 1]
            result["next"] = {
                "jp": (nxt[2] if len(nxt) > 2 else "").replace("\r", ""),
                "en": (nxt[3] if len(nxt) > 3 else "").replace("\r", ""),
            }
            print(f"[get_adjacent_context] Found next row at index {data_row_idx + 1}")
        # print(f"[get_adjacent_context] Returning result: {result}")  # Disabled due to encoding issues
        return result
    except Exception as e:
        print(f"[get_adjacent_context] Error: {e}")
        import traceback
        traceback.print_exc()
        return {}

@eel.expose
def get_archetype_options():
    archetypes = cm.config.get("archetypes", {})
    return [
        {"key": k, "name": v.get("name", k), "notes": v.get("notes", "")}
        for k, v in archetypes.items()
    ]

@eel.expose
def get_archetype_notes(archetype_key):
    """Return notes for a specific archetype."""
    if not archetype_key:
        return ""
    archetypes = cm.config.get("archetypes", {})
    return archetypes.get(archetype_key, {}).get("notes", "")

# =============================================================================
# BATCH RUNNER
# =============================================================================

@eel.expose
def start_batch_scan(preset_name="Standard", wall_preset_name="Standard"):
    global review_items, current_review_idx, batch_scan_complete
    for q in review_queues.values():
        q.clear()
    # Don't clear review_items to preserve manual translation items
    current_review_idx = 0
    batch_scan_complete = False

    # Save selected limits and UI state
    cm.user_settings.setdefault("selected_preset", preset_name)
    cm.user_settings["selected_preset"] = preset_name
    cm.user_settings.setdefault("wall_preset", wall_preset_name)
    cm.user_settings["wall_preset"]     = wall_preset_name
    cm.user_settings.setdefault("in_universe", True)
    cm.user_settings["in_universe"]     = cm.user_settings.get("in_universe",  True)
    cm.save_user_settings()

    limit      = cm.config.get("presets",      {}).get(preset_name, 50)
    wall_limit = cm.config.get("wall_presets", {}).get(wall_preset_name, 7)

    settings = BatchSettings(
        limit            = limit,
        wall_limit       = wall_limit,
        triggers         = cm.user_settings.get("triggers",     []) if hasattr(cm, 'user_settings') else [],
        do_in_universe   = cm.user_settings.get("in_universe",  True) if hasattr(cm, 'user_settings') else True,
        folders          = cm.user_settings.get("folders",      []) if hasattr(cm, 'user_settings') else [],
        tag_map          = cm.config.get("tag_map",      {}),
        entry_type_rules = cm.config.get("entry_type_rules", {}),
        replace_rules    = cm.config.get("replace_rules",    []),
        preview_mode     = cm.user_settings.get("preview_mode",     False) if hasattr(cm, 'user_settings') else False,
        checkpoint_file  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch_checkpoint.json"),
    )

    def log_cb(msg):   eel.log_to_js(msg)
    def prog_cb(pct):  eel.update_progress(pct)

    def done_cb(limit, wall_limit):
        global review_items, batch_scan_complete
        # Set completion flag for polling
        batch_scan_complete = True
        # Save queues to disk for persistence
        _save_review_queues()
        print(f"[done_cb] Scan complete, saved {sum(len(q) for q in review_queues.values())} items")

    threading.Thread(
        target=run_batch,
        args=(settings, cm, engine, review_queues, log_cb, prog_cb, done_cb),
        daemon=True,
    ).start()
    return True

# =============================================================================
# REVIEWER
# =============================================================================

@eel.expose
def is_batch_scan_complete():
    """Check if the batch scan has completed."""
    global batch_scan_complete
    return batch_scan_complete

@eel.expose
def get_queue_structure():
    """Return the queue structure with categories (matching old EditorWindow)."""
    categories = {
        "Tag Issues (Complex Tags)": "tag",
        "Line Limit": "wall",
        "Double Dashes": "dash",
        "Possible Anachronisms": "anach",
    }
    result = {
        "Manual Translation": {
            "queue_key": "manual",
            "texts": [],
            "count": len(review_items),
        }
    }
    for display_name, queue_key in categories.items():
        queue_data = review_queues.get(queue_key, {})
        result[display_name] = {
            "queue_key": queue_key,
            "texts": list(queue_data.keys()),
            "count": len(queue_data),
        }
    return result

@eel.expose
def get_items_for_category(category_display_name):
    """Return items for a specific category (for string list)."""
    categories = {
        "Tag Issues (Complex Tags)": "tag",
        "Line Limit": "wall",
        "Double Dashes": "dash",
        "Possible Anachronisms": "anach",
    }
    queue_key = categories.get(category_display_name)
    if not queue_key:
        return []
    
    queue_data = review_queues.get(queue_key, {})
    items = []
    for orig_text, instances in queue_data.items():
        inst = instances[0]
        # Read CSV to get Japanese source at row[2]
        jp_source = orig_text  # Default to orig_text if CSV read fails
        try:
            _, _, rows = _read_csv(inst["path"])
            if inst["row_idx"] < len(rows):
                row = rows[inst["row_idx"]]
                if len(row) > 2:
                    jp_source = row[2]
        except Exception as e:
            print(f"[get_items_for_category] Error reading CSV: {e}")
        
        items.append({
            "id": len(items) + 1,
            "speaker": inst.get("speaker", "Unknown"),
            "jp": jp_source,
            "en": orig_text,
            "category": queue_key.upper(),  # Add category for entry type display
            "path": inst["path"],
            "row": inst["row_idx"],
            "entry_type": inst.get("entry_type", ""),
        })
    return items

@eel.expose
def get_all_items_in_queue():
    """Return the full flat review queue for the Reviewer tab."""
    return review_items


@eel.expose
def get_row_text(path, row_idx):
    """Return (jp,en,speaker,entry_type) from a CSV row.

    This is used by the frontend to refresh stale cached queue items. If the user
    loaded a queue from localStorage (or an older cache file) when CSV parsing
    was incorrect, fields may appear truncated. Re-reading from disk ensures the
    editor reflects the current CSV contents.
    """
    try:
        if not path or row_idx is None:
            return None
        row_idx = int(row_idx)
        if row_idx < 0:
            return None
        _, _, rows = _read_csv(path)
        if row_idx >= len(rows):
            return None
        row = rows[row_idx]
        jp = row[2] if len(row) > 2 else ""
        en = row[3] if len(row) > 3 else ""
        speaker = row[8].strip() if len(row) > 8 and row[8] else ""
        entry_type = row[9].strip() if len(row) > 9 and row[9] else ""
        return {"jp": jp, "en": en, "speaker": speaker, "entry_type": entry_type}
    except Exception as e:
        return {"error": str(e)}

@eel.expose
def get_next_review_item():
    global current_review_idx
    if current_review_idx < len(review_items):
        item = review_items[current_review_idx]
        current_review_idx += 1
        return item
    return None

@eel.expose
def get_deepl_suggestion(text):
    key = cm.get_key("deepl_api_key")
    if not key:
        return "No DeepL key configured."
    cached = cm.get_cached("deepl", text)
    if cached:
        return cached
    target_lang = cm.config.get("deepl_target_lang", "EN-US")
    res = DeepLClient(key).translate(text, target_lang=target_lang)
    if "text" in res:
        cm.set_cached("deepl", text, res["text"])
        return res["text"]
    return f"Error: {res.get('error')}"

@eel.expose
def send_ai_chat(message, history, current_jp="", speaker="", archetype_key=""):
    key = cm.get_key("openrouter_api_key")
    if not key:
        return "Error: No OpenRouter key found."

    model = cm.user_settings.get("selected_openrouter_model", "openrouter/auto")
    cache_key = f"{model}::{message}"
    cached = cm.get_cached("openrouter", cache_key)
    if cached:
        return cached

    sys_prompt = cm.config.get("ai_system_prompt",
        "You are a Dragon's Dogma Online (DDON) localization assistant. "
        "Your output will be inserted directly into the game — follow every rule precisely.\n\n"

        "OUTPUT FORMAT:\n"
        "Return only the translated or refined text. No preamble, no explanation, no quotation marks. "
        "If you are genuinely uncertain about a reading, append a single bracketed note: [alt: ...]. "
        "Do not insert blank lines or extra newlines.\n\n"

        "HARD RULES:\n"
        "- Preserve anything inside < > angle brackets exactly as-is — these are engine tags. "
        "Text between paired tags (e.g. <COL>text</COL>) should be translated; the tags themselves must not change.\n"
        "- Do NOT use Japanese honorifics (e.g. -san, -sama, -dono).\n"
        "- Render Japanese dashes as an ellipsis (...) or em dash (—) depending on context.\n"
        "- For unknown proper nouns (names, places, skills), keep the established romanisation.\n"
        "- Address the player as 'Master' or 'Arisen' as context warrants. Use 'ser' not 'sir'.\n\n"

        "STYLE — THE DRAGON'S DOGMA HOUSE STYLE:\n"
        "The style is natural English grammar with archaic vocabulary woven in. "
        "Standard contractions (don't, can't, won't, it's, let's, we're) are used freely — "
        "what is avoided is modern slang: never use 'gonna', 'gotta', 'kinda', 'sorta', 'nah', 'dude', 'okay', 'awesome'.\n\n"

        "Draw on these archaic vocabulary choices where they fit naturally:\n"
        "  'tis / 'twas / 'twould  — for 'it is / it was / it would'\n"
        "  naught / aught          — for 'nothing / anything'\n"
        "  afore                   — for 'before'\n"
        "  ere                     — for 'before' (in time: 'ere more arrive')\n"
        "  nigh                    — for 'near' or 'almost'\n"
        "  mayhap                  — for 'perhaps'\n"
        "  o'er / whate'er / e'er  — contracted forms\n"
        "  nary                    — for 'not a single'\n"
        "  summat                  — for 'something' (informal)\n"
        "  what                    — as a relative pronoun ('fiends what haunt these halls')\n\n"

        "'Tis is especially characteristic — use it freely for observations and reactions "
        "('Hobgoblin! 'Tis a formidable foe.', ''Tis more bloodthirsty than a wolf!'). "
        "Short, punchy combat calls are the norm for battle lines — keep them terse.\n\n"

        "EXAMPLES (from the actual game):\n"
        "JP: 仲間を呼ばれる前に仕留めましょう！\n"
        "EN: Silence that howl, ere more arrive!\n\n"
        "JP: あいつも尻尾が弱点かもしれませんね\n"
        "EN: Mayhap their tails are weak as well.\n\n"
        "JP: こう素早いと…当てにくいです！\n"
        "EN: 'Tis a trial to hit such swift targets!\n\n"
        "JP: 陸に上がる前に仕留めましょう！\n"
        "EN: Let's end this afore they reach land!\n\n"
        "JP: ゴールデンナイトの攻撃力は脅威です！\n"
        "EN: The knight of gold is fearsome strong!\n\n"

        "TRANSLATION GUIDANCE:\n"
        "Stay faithful to the original meaning and its length — do not add, omit, or embellish. "
        "Rephrase for natural English flow within the style above. "
        "Characters often speak with heightened gravity — preserve that register rather than flattening it. "
        "Respect the character's voice and any archetype notes provided. "
        "Stay consistent with any translation choices made earlier in this conversation.\n"
    )
    
    # Add archetype notes if available
    if archetype_key:
        archetypes = cm.config.get("archetypes", {})
        if archetype_key in archetypes:
            arch_data = archetypes[archetype_key]
            sys_prompt += f"\n\nCHARACTER ARCHETYPE FOR {speaker or 'SPEAKER'}:\n{arch_data.get('notes', '')}"
    
    # Add lore glossary terms from current JP text
    if current_jp:
        le = _get_lore_engine()
        if le:
            # Inject archaic suggestions for any modern words detected in the drafted English
            anach_hits = le.scan_anachronisms(current_jp)
            if anach_hits:
                sys_prompt += "\n\nSUGGESTED ARCHAIC ALTERNATIVES (use these instead of modern words if appropriate):\n"
                for word, suggestion, is_ddon in anach_hits:
                    if suggestion:
                        sys_prompt += f"- Instead of '{word}', consider '{suggestion}'\n"
            
            # Get relevant lore terms from Japanese text
            relevant_terms = le.scan_text(current_jp)
            if relevant_terms:
                sys_prompt += "\n\nMANDATORY GLOSSARY TERMS FOR THIS LINE:\n"
                for jp, en in relevant_terms:
                    sys_prompt += f"- {jp} MUST be translated as '{en}'\n"
    
    try:
        res = OpenRouterClient(key).chat(
            [{"role": "system", "content": sys_prompt}] + history,
            model=model,
        )
        
        if "text" in res:
            response_text = res["text"]
            cm.set_cached("openrouter", cache_key, response_text)
            return response_text
        else:
            error_msg = res.get('error', 'Unknown OpenRouter error')
            return error_msg
    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        return error_msg

# =============================================================================
# APPLY FIX
# =============================================================================

@eel.expose
def flush_csv_writes():
    """Flush pending CSV writes to disk."""
    global pending_csv_writes
    cm.save_memory()
    if not pending_csv_writes:
        return {"ok": True, "written": 0}

    written_files = 0
    for path, writes in pending_csv_writes.items():
        try:
            raw, dialect, rows = _read_csv(path)
            for r_idx, new_text in writes:
                if r_idx < len(rows):
                    rows[r_idx][3] = new_text
            import csv as _csv
            # Override dialect quoting to use QUOTE_MINIMAL
            dialect.quoting = _csv.QUOTE_MINIMAL
            dialect.quotechar = '"'
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = _csv.writer(f, dialect=dialect)
                writer.writerows(rows)
            mark_file_written(path)  # Mark as written by app
            written_files += 1
        except Exception as e:
            print(f"Error flushing CSV {path}: {e}")
            return {"ok": False, "error": str(e)}

    pending_csv_writes.clear()
    return {"ok": True, "written": written_files}

@eel.expose
def apply_fix(item_id, new_text, force=False, user="translator"):
    """Write corrected text to CSV. Returns {"ok": bool, "error": str|None}."""
    global review_items, pending_csv_writes, review_queues

    item = None
    if isinstance(item_id, str) and (item_id.startswith("SEARCH_") or item_id.startswith("MANUAL_")):
        for i in review_items:
            if i["id"] == item_id:
                item = i
                break
    else:
        # First try to find in review_items (manual mode)
        idx = int(item_id) - 1
        if 0 <= idx < len(review_items):
            item = review_items[idx]
        
        # If not found in review_items, try to find in review_queues (batch scan mode)
        if not item:
            # Search all queues for the item by ID
            for queue_key, queue_data in review_queues.items():
                # Items from get_items_for_category have sequential IDs
                # We need to find the item by iterating through the queue
                current_id = 1
                for orig_text, instances in queue_data.items():
                    inst = instances[0]
                    if current_id == int(item_id):
                        # Construct item with the same structure as get_items_for_category
                        try:
                            _, _, rows = _read_csv(inst["path"])
                            if inst["row_idx"] < len(rows):
                                row = rows[inst["row_idx"]]
                                jp_source = row[2] if len(row) > 2 else orig_text
                            else:
                                jp_source = orig_text
                        except Exception:
                            jp_source = orig_text
                        
                        item = {
                            "id": item_id,
                            "speaker": inst.get("speaker", "Unknown"),
                            "jp": jp_source,
                            "en": orig_text,
                            "category": queue_key.upper(),
                            "path": inst["path"],
                            "row": inst["row_idx"],
                            "entry_type": inst.get("entry_type", ""),
                        }
                        break
                    current_id += 1
                if item:
                    break

    if not item:
        return {"ok": False, "error": f"Item {item_id} not found."}

    # Update the item in review_items to reflect the saved translation
    item["en"] = new_text

    # Always update the in-memory fix dictionary
    cm.memory[item["jp"]] = new_text

    # Track translation in translation manager
    from src.translation_manager import generate_entry_id
    # Generate entry ID from source text (hash-based)
    entry_id = generate_entry_id(item["jp"])
    print(f"[apply_fix] Generated entry_id={entry_id} from source text")
    print(f"[apply_fix] Tracking translation for item {item_id}")
    print(f"[apply_fix]   path: {item.get('path')}, row: {item.get('row')}")
    print(f"[apply_fix]   TM entries before: {len(translation_manager.entries)}")
    translation_manager.submit_translation(
        entry_id=entry_id,
        source_text=item["jp"],
        translated_text=new_text,
        translator=user,
        file_path=item.get("path"),
        row_index=item.get("row"),
        speaker=item.get("speaker"),
        entry_type=item.get("entry_type")
    )
    print(f"[apply_fix]   TM entries after: {len(translation_manager.entries)}")
    print(f"[apply_fix]   TM logs: {len(translation_manager.logs)}")

    # Respect Preview Mode - don't write to disk if user is just reviewing
    if cm.user_settings.get("preview_mode", False) if hasattr(cm, 'user_settings') else False:
        cm.save_all()
        return {"ok": True}

    # Length validation (skipped when forced)
    if not force:
        limit    = list(cm.config.get("presets", {"Standard": 50}).values())[0]
        overlong = [
            i + 1 for i, line in enumerate(new_text.splitlines())
            if engine.get_simulated_len(line.replace('★', '')) > limit
        ]
        if overlong:
            ln  = ", ".join(str(n) for n in overlong)
            return {"ok": False, "error": f"Line(s) {ln} exceed the {limit}-char limit. Use FORCE_SAVE to override."}

    # Strip ★ character (lore marker) before saving to CSV
    text_to_save = new_text.replace('★', '')
    # Add to pending writes for batch processing
    pending_csv_writes.setdefault(item["path"], []).append((item["row"], text_to_save))
    
    # Auto-flush for single items (can be optimized later)
    return flush_csv_writes()

# --- endpoint for Translate CSV parity ---
@eel.expose
def load_csv_for_translation(filepath=None):
    import tkinter as tk
    from tkinter import filedialog
    
    if not filepath:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True) # Force focus over Eel window
        filepath = filedialog.askopenfilename(
            title="Select CSV to Translate",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        root.destroy()
        
    if not filepath:
        return None
        
    try:
        _, _, rows = _read_csv(filepath)
        global review_items, current_review_idx
        review_items = []
        current_review_idx = 0
        
        for i, row in enumerate(rows):
            if len(row) < 3: 
                continue
            jp_text = row[2]
            if not jp_text.strip(): 
                continue
            
            en_text  = row[3] if len(row) > 3 else ""
            speaker  = row[8].strip() if len(row) > 8 and row[8].strip() else "Unknown"
            category = row[9].strip() if len(row) > 9 and row[9].strip() else "MANUAL"
            
            # Load all rows with Japanese text, regardless of translation status
            # This allows users to review and edit completed translations
            review_items.append({
                "id": f"MANUAL_{i}",
                "speaker": speaker,
                "jp": jp_text,
                "en": en_text,
                "category": category,
                "entry_type": category,  # Use category as entry_type
                "path": filepath,
                "row": i  # i is the actual row index in the CSV file
            })
        _save_review_items()
        return len(review_items)
    except Exception as e:
        return {"error": str(e)}

# =============================================================================
# INITIALIZATION
# =============================================================================

# Clean up old approve/reject log entries and update usernames on startup
try:
    translation_manager.cleanup_old_approval_logs()
    print("[INIT] Cleaned up old approve/reject log entries")
except Exception as e:
    print(f"[INIT] Error cleaning up old logs: {e}")

try:
    if hasattr(cm, 'user_settings') and 'sync_nickname' in cm.user_settings:
        translation_manager.update_all_log_usernames(cm.user_settings['sync_nickname'])
        print(f"[INIT] Updated log usernames to {cm.user_settings['sync_nickname']}")
except Exception as e:
    print(f"[INIT] Error updating log usernames: {e}")

# =============================================================================
# PREFETCH MANAGER
# =============================================================================
from src.prefetch_manager import PrefetchManager

# Initialize TM components before PrefetchManager so they're available
_get_tm_components()

_prefetch_mgr = PrefetchManager(lore_engine_getter=_get_lore_engine, language=initial_language, get_adjacent_context_getter=lambda: get_adjacent_context, gloss_engine_getter=_get_gloss_engine, tm_getter=lambda: (_tm_instance, _tm_matcher, _tm_lock))
_prefetch_mgr.start()

@eel.expose
def start_prefetch(category, items, current_idx, depth=3):
    """Start prefetching the next N entries after current index.

    Args:
        category: Category name
        items: List of items to prefetch
        current_idx: Current index
        depth: Number of entries to prefetch
    """
    try:
        _prefetch_mgr.update_current_idx(category, current_idx)
        _prefetch_mgr.prefetch_next(category, items, current_idx, depth)
        return True
    except Exception as e:
        print(f"[start_prefetch] Error: {e}")
        return False

@eel.expose
def fetch_deepl_batch(category, items, start_idx, count=20):
    """Fetch DeepL translations for a batch of entries starting from start_idx.

    Args:
        category: Category name
        items: List of items
        start_idx: Starting index
        count: Number of entries to fetch (default 20)
    """
    print(f"[fetch_deepl_batch] CALLED with category={category}, start_idx={start_idx}, count={count}")
    try:
        from src.api_handler import DeepLClient
        key = cm.get_key("deepl_api_key")
        if not key:
            print(f"[fetch_deepl_batch] No DeepL key configured")
            return False

        target_lang = cm.config.get("deepl_target_lang", "EN-US")
        end_idx = min(start_idx + count, len(items))
        print(f"[fetch_deepl_batch] Fetching DeepL for indices {start_idx}-{end_idx-1}")

        for i in range(start_idx, end_idx):
            item = items[i]
            if item.get('jp'):
                try:
                    # Check cache first
                    cached_deepl = cm.get_cached("deepl", item['jp'])
                    if cached_deepl:
                        translation = cached_deepl
                        print(f"[fetch_deepl_batch] idx={i}: using cached translation")
                    else:
                        res = DeepLClient(key).translate(item['jp'], target_lang=target_lang)
                        if "text" in res:
                            translation = res["text"]
                            cm.set_cached("deepl", item['jp'], translation)
                        else:
                            translation = None
                            print(f"[fetch_deepl_batch] idx={i}: DeepL error: {res.get('error')}")
                    print(f"[fetch_deepl_batch] idx={i}: {translation[:50] if translation else 'None'}...")
                    # Update prefetch cache with the result
                    cache_key = _prefetch_mgr._cache_key(category, i)
                    cached = _prefetch_mgr._cache.get(cache_key, {})
                    cached['deepl_suggestion'] = translation
                    cached['timestamp'] = time.time()
                    _prefetch_mgr._cache[cache_key] = cached
                except Exception as e:
                    print(f"[fetch_deepl_batch] Error fetching idx={i}: {e}")

        _prefetch_mgr._save_cache_to_file()
        return True
    except Exception as e:
        print(f"[fetch_deepl_batch] Error: {e}")
        return False

@eel.expose
def start_prefetch_all(category, items):
    """Start prefetching all entries in the queue (for local-only operations).

    Args:
        category: Category name
        items: List of items to prefetch
    """
    try:
        print(f"[start_prefetch_all] Called with category={category}, items={len(items) if items else 0}")
        _prefetch_mgr.prefetch_all(category, items)
        return True
    except Exception as e:
        print(f"[start_prefetch_all] Error: {e}")
        return False

@eel.expose
def get_prefetch_cache(category, idx):
    """Get cached prefetch results for a category and index."""
    try:
        print(f"[get_prefetch_cache] Called with category={category}, idx={idx}")
        result = _prefetch_mgr.get_cached(category, idx)
        print(f"[get_prefetch_cache] Result: {result is not None}, keys={list(result.keys()) if result else 'None'}")
        return result
    except Exception as e:
        print(f"[get_prefetch_cache] Error: {e}")
        return None

@eel.expose
def update_prefetch_cache(category, idx, data):
    """Update the prefetch cache for a specific category and index."""
    try:
        _prefetch_mgr.update_cache(category, idx, data)
        return True
    except Exception as e:
        print(f"[update_prefetch_cache] Error: {e}")
        return False

@eel.expose
def clear_prefetch_cache():
    """Clear the prefetch cache."""
    try:
        _prefetch_mgr.clear_cache()
        return True
    except Exception as e:
        print(f"[clear_prefetch_cache] Error: {e}")
        return False

@eel.expose
def clear_gloss_cache():
    """Clear the gloss cache."""
    global _gloss_cache
    try:
        with _gloss_cache_lock:
            _gloss_cache.clear()
        print("[clear_gloss_cache] Gloss cache cleared")
        return True
    except Exception as e:
        print(f"[clear_gloss_cache] Error: {e}")
        return False

# =============================================================================
# TRANSLATION MANAGEMENT
# =============================================================================

@eel.expose
def approve_translation(entry_id, approver="reviewer"):
    """Approve a translation. Returns the updated entry."""
    try:
        entry = translation_manager.approve_translation(entry_id, approver)
        if entry:
            return {"ok": True, "entry": entry.to_dict()}
        return {"ok": False, "error": "Entry not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def reject_translation(entry_id, reviewer="reviewer", reason=None):
    """Reject a translation. Returns the updated entry."""
    try:
        entry = translation_manager.reject_translation(entry_id, reviewer, reason)
        if entry:
            return {"ok": True, "entry": entry.to_dict()}
        return {"ok": False, "error": "Entry not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_translation_status(entry_id):
    """Get status of a translation entry."""
    try:
        status = translation_manager.get_entry_status(entry_id)
        entry = translation_manager.entries.get(entry_id)
        if entry:
            return {"ok": True, "status": status, "entry": entry.to_dict()}
        return {"ok": False, "error": "Entry not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def add_translation_comment(entry_id, user, text, parent_id=None, history_entry_id=None):
    """Add a comment to a translation entry.
    
    Args:
        entry_id: The translation entry ID
        user: Username adding the comment
        text: Comment text
        parent_id: For threaded comments (replies)
        history_entry_id: If specified, attach to this specific history entry.
                        If None, attach to the most recent history entry.
    """
    try:
        comment = translation_manager.add_comment(entry_id, user, text, parent_id, history_entry_id)
        return {"ok": True, "comment": comment.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_translation_comments(entry_id):
    """Get all comments for a translation entry."""
    try:
        comments = translation_manager.get_comments(entry_id)
        return {"ok": True, "comments": [c.to_dict() for c in comments]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def vote_translation(entry_id, user, vote):
    """Vote on a translation (+1 for upvote, -1 for downvote)."""
    try:
        vote_obj = translation_manager.vote_translation(entry_id, user, vote)
        score = translation_manager.get_vote_score(entry_id)
        return {"ok": True, "vote": vote_obj.to_dict(), "score": score}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def save_translation_history(entry_id, jp_text, en_text, speaker=None, entry_type=None, translator=None, file_path=None, row_index=None):
    """Save translation history without writing to CSV (for Save button)."""
    try:
        from src.translation_manager import generate_entry_id
        # Generate entry ID from source text (hash-based)
        entry_id = generate_entry_id(jp_text)
        print(f"[save_translation_history] Generated entry_id={entry_id} from source text, translator={translator}, file_path={file_path}")
        # Track in translation manager (saves history)
        print(f"[save_translation_history] Calling submit_translation with translator={translator or user}")
        translation_manager.submit_translation(
            entry_id=entry_id,
            source_text=jp_text,
            translated_text=en_text,
            translator=translator or user,
            file_path=file_path,
            row_index=row_index,
            speaker=speaker,
            entry_type=entry_type
        )
        print(f"[save_translation_history] submit_translation completed, logs count={len(translation_manager.logs)}")
        return {"ok": True, "entry_id": entry_id}
    except Exception as e:
        print(f"[save_translation_history] Error: {e}")
        return {"ok": False, "error": str(e)}

@eel.expose
def get_translation_history(entry_id):
    """Get translation history for an entry."""
    try:
        history = translation_manager.get_translation_history(entry_id)
        status = translation_manager.get_entry_status(entry_id)
        return {"ok": True, "history": [h.to_dict() for h in history], "status": status}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def cleanup_old_approval_logs():
    """Remove old approve/reject log entries from the database."""
    try:
        translation_manager.cleanup_old_approval_logs()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def update_all_log_usernames(new_username):
    """Update all log entries to use the new username."""
    try:
        translation_manager.update_all_log_usernames(new_username)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_recent_translation_activity(limit=50):
    """Get recent translation activity across all entries."""
    try:
        activity = translation_manager.get_recent_activity(limit)
        return {"ok": True, "activity": [a.to_dict() for a in activity]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_translation_stats():
    """Get overall translation statistics."""
    try:
        stats = translation_manager.get_stats()
        return {"ok": True, "stats": stats}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_entries_by_status(status):
    """Get all entries with a specific status."""
    try:
        entries = translation_manager.get_entries_by_status(status)
        return {"ok": True, "entries": [e.to_dict() for e in entries], "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_unapproved_entries_with_comments():
    """Get all unapproved entries with comment count."""
    try:
        entries = translation_manager.get_unapproved_entries_with_comments()
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def get_pretranslated_unapproved_entries():
    """Get all pre-translated unapproved entries with comment count."""
    try:
        entries = translation_manager.get_pretranslated_unapproved_entries()
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =============================================================================
# GITHUB SYNC
# =============================================================================

@eel.expose
def sync_push():
    """Manually push local translation data to GitHub."""
    try:
        # Check if configured
        if not github_sync.is_configured():
            return {"ok": False, "error": "GitHub sync not configured. Please set up GitHub token and repository in Options."}
        
        # Get counts for status message
        entry_count = len(translation_manager.get_approved_entries())
        log_count = len(translation_manager.get_translation_logs())
        comment_count = len(translation_manager.get_comment_log())
        
        if entry_count == 0:
            return {"ok": False, "error": f"No entries to sync. Have you approved/rejected any translations?\nTM Status: {entry_count} entries, {log_count} logs, {comment_count} comments"}
        
        result = github_sync.sync_push(translation_manager)
        return {
            "ok": result.get("success", False), 
            "message": f"Push {'successful' if result.get('success') else 'failed'}. Synced {entry_count} entries, {log_count} logs, {comment_count} comments.",
            "debug": result.get("debug", []),
            "sync_error": result.get("error")
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}

@eel.expose
def sync_pull():
    """Manually pull translation data from GitHub and merge with local."""
    try:
        success = github_sync.sync_pull(translation_manager)
        return {"ok": success, "message": "Pull successful" if success else "Pull failed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@eel.expose
def sync_config_files():
    """Manually push config files (vocab, archetypes) to GitHub."""
    try:
        # Check if configured
        if not github_sync.is_configured():
            return {"ok": False, "error": "GitHub sync not configured. Please set up GitHub token and repository in Options."}
        
        # Create a dummy translation manager for config sync
        result = github_sync.sync_push(None)  # Pass None to only sync config files
        return {
            "ok": result.get("success", False), 
            "message": f"Config files push {'successful' if result.get('success') else 'failed'}.",
            "debug": result.get("debug", [])
        }
    except Exception as e:
        print(f"[sync_config_files] Error: {e}")
        return {"ok": False, "error": str(e)}

@eel.expose
def get_sync_status():
    """Get current sync configuration status."""
    try:
        return {
            "ok": True,
            "configured": github_sync.is_configured(),
            "repo": cm.user_settings.get('github_repo', ''),
            "nickname": cm.user_settings.get('sync_nickname', ''),
            "language": cm.language,
            "auto_sync": cm.user_settings.get('sync_auto', False) if hasattr(cm, 'user_settings') else False,
            "interval": cm.config.get('sync_interval', 30)
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =============================================================================
# SEARCH
# =============================================================================

@eel.expose
def clear_queue():
    """Clear the current review queue."""
    global review_items
    review_items = []
    _save_review_items()
    return True

@eel.expose
def bulk_inject(items):
    global review_items
    from src.translation_manager import generate_entry_id
    for item in reversed(items):
        # Generate entry ID from source text (hash-based)
        item["id"] = generate_entry_id(item.get('jp', ''))
        review_items.insert(current_review_idx, item)
    _save_review_items()
    return True

@eel.expose
def perform_search(query, field_col=None):
    if not query:
        return []
    query_lc  = query.lower()
    csv_files = _get_csv_files(cm.user_settings.get("folders", []) if hasattr(cm, 'user_settings') else [])
    results   = []
    for f_path in csv_files:
        try:
            _, _, rows = _read_csv(f_path)
            for i, row in enumerate(rows):
                if i == 0: continue
                if field_col is None:
                    hits = [(ci, row[ci]) for ci in range(len(row)) if query_lc in row[ci].lower()]
                else:
                    col  = int(field_col)
                    hits = [(col, row[col])] if col < len(row) and query_lc in row[col].lower() else []
                if hits:
                    mc, mv = hits[0]
                    speaker = row[8].strip() if len(row) > 8 and row[8].strip() else "Unknown"
                    category = row[9].strip() if len(row) > 9 and row[9].strip() else ""
                    results.append({
                        "file":  os.path.basename(f_path),
                        "path":  f_path,
                        "row":   i,  # i is already the actual row index in the CSV file
                        "col":   mc,
                        "match": mv[:200],
                        "en":    (row[3] if len(row) > 3 else "")[:200],
                        "jp":    (row[2] if len(row) > 2 else "")[:200],
                        "speaker": speaker,
                        "category": category,
                        "entry_type": category,  # Use category as entry_type for search results
                    })
        except:
            continue
    return results

# =============================================================================
# DIAGNOSTICS — Feature Status
# =============================================================================

@eel.expose
def validate_translation(source: str, translation: str) -> dict:
    """Validate that translation preserves source elements (tags, placeholders)."""
    try:
        # Reload tag_map in case it was updated
        source_validator.load_tag_map(cm.config.get("tag_map", {}))
        errors = source_validator.validate_translation(source, translation)
        print(f"[validate_translation] Source: {source[:50]}...")
        print(f"[validate_translation] Translation: {translation[:50]}...")
        print(f"[validate_translation] Errors: {errors}")
        return {"ok": True, "errors": errors}
    except Exception as e:
        print(f"[validate_translation] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

@eel.expose
def get_feature_status():
    """Return status of optional features (gloss, DeepL, lore context, etc)."""
    status = {
        "gloss": False,
        "gloss_error": None,
        "deepl": False,
        "deepl_error": None,
        "deepl_key_configured": False,
        "lore_context": False,
        "lore_context_error": None,
        "glossary_path": cm.user_settings.get("glossary_path", "") if hasattr(cm, 'user_settings') else "",
        "bible_path": cm.user_settings.get("bible_path", "") if hasattr(cm, 'user_settings') else "",
    }
    
    # Check GlossEngine (Jamdict)
    try:
        ge = _get_gloss_engine()
        status["gloss"] = ge is not None
        if not ge:
            status["gloss_error"] = "GlossEngine not initialized (Jamdict may not be installed)"
    except Exception as e:
        status["gloss"] = False
        status["gloss_error"] = str(e)
    
    # Check DeepL
    try:
        deepl_key = cm.get_key("deepl_api_key")
        if deepl_key:
            status["deepl_key_configured"] = True
            try:
                # Test with a simple request
                result = DeepLClient(deepl_key).translate("テスト", target_lang="EN-US")
                status["deepl"] = "text" in result or "error" not in result
                if "error" in result:
                    status["deepl_error"] = result.get("error")
            except Exception as e:
                status["deepl_error"] = f"DeepL API error: {str(e)}"
        else:
            status["deepl_error"] = "No DeepL API key configured"
    except Exception as e:
        status["deepl_error"] = f"Error checking DeepL: {str(e)}"
    
    # Check LoreEngine (for lore_context)
    try:
        le = _get_lore_engine()
        status["lore_context"] = le is not None
        if not le:
            status["lore_context_error"] = "LoreEngine not initialized"
        elif not le.lore_map:
            status["lore_context_error"] = "LoreEngine has no lore_map data"
    except Exception as e:
        status["lore_context"] = False
        status["lore_context_error"] = str(e)
    
    return status

# =============================================================================
# SHUTDOWN / CLEANUP
# =============================================================================

def is_port_available(port):
    """Check if a port is available for binding."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result != 0  # Return True if port is NOT in use
    except:
        return True

def find_available_port(start_port=8000, max_attempts=10):
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if is_port_available(port):
            print(f"[STARTUP] Found available port: {port}")
            return port
    print(f"[ERROR] No available ports found in range {start_port}-{start_port + max_attempts}")
    return None

@eel.expose
def shutdown_app():
    """Gracefully shutdown the application."""
    print("[SHUTDOWN] App shutdown requested by frontend")
    try:
        # Flush any pending sync data
        if github_sync.is_configured():
            github_sync.flush_on_exit(translation_manager)
    except Exception as e:
        print(f"[SHUTDOWN] Sync flush failed: {e}")
    
    try:
        # Trigger frontend to close
        eel.close()
    except:
        pass
    # Force exit after a short delay
    def do_exit():
        time.sleep(0.5)
        os._exit(0)
    t = threading.Thread(target=do_exit, daemon=True)
    t.start()
    return {"ok": True}

# =============================================================================
# START APP
# =============================================================================

def main():
    print(f"[STARTUP] Starting Dialogue Editor Suite from {WEB_DIR}...")
    print(f"[STARTUP] Web directory: {WEB_DIR}")
    
    # Verify web directory exists
    if not os.path.isdir(WEB_DIR):
        print(f"[ERROR] Web directory not found: {WEB_DIR}")
        return False
    
    # Check for index.html
    index_path = os.path.join(WEB_DIR, 'index.html')
    if not os.path.isfile(index_path):
        print(f"[ERROR] index.html not found: {index_path}")
        return False
    
    print("[STARTUP] Web files verified")
    
    # Initialize Eel
    try:
        print("[STARTUP] Initializing Eel...")
        eel.init(WEB_DIR)
        print("[STARTUP] Eel initialized successfully")
    except Exception as e:
        print(f"[ERROR] Failed to initialize Eel: {e}")
        return False
    
    # Print feature status for debugging
    print("[STARTUP] Checking optional features...")
    status = get_feature_status()
    print(f"[STARTUP] Gloss (Jamdict): {status['gloss']}" + (f" - {status['gloss_error']}" if status['gloss_error'] else ""))
    print(f"[STARTUP] DeepL: {status['deepl']}" + (f" - {status['deepl_error']}" if status['deepl_error'] else ""))
    print(f"[STARTUP] Lore Context: {status['lore_context']}" + (f" - {status['lore_context_error']}" if status['lore_context_error'] else ""))
    print(f"[STARTUP] Glossary path: {status['glossary_path']}")
    print(f"[STARTUP] Bible path: {status['bible_path']}")
    
    # Find available port
    port = find_available_port(8000, 10)
    if port is None:
        print("[ERROR] Could not find available port")
        return False
    
    # Eel startup with multiple mode attempts
    startup_successful = False
    modes = ['chrome', 'chrome-app', 'edge', 'default']
    
    for mode in modes:
        try:
            print(f"[STARTUP] Attempting to start with mode: {mode} on port {port}")
            eel.start('index.html', size=(1300, 900), mode=mode, port=port)
            startup_successful = True
            print(f"[STARTUP] Mode '{mode}' started successfully")
            break
        except Exception as e:
            print(f"[STARTUP] Mode '{mode}' failed: {type(e).__name__}: {e}")
            # On Windows, chrome modes might fail but that's OK, we have fallbacks
            if mode in ['chrome', 'chrome-app']:
                continue
            # Try next mode
            continue
    
    if not startup_successful:
        print("[ERROR] Failed to start Eel with any mode")
        return False
    
    return True

# =============================================================================
# TRANSLATION MEMORY DIAGNOSTICS
# =============================================================================

@eel.expose
def tm_test_data_structure():
    """Test TM data structure creation and validation."""
    tm, _, _ = _get_tm_components()
    
    # Create test entry
    test_entry = {
        "source": "テストテキスト",
        "translation": "Test text",
        "context": {"speaker": "Test", "entry_type": "dialogue"},
        "quality": "approved"
    }
    
    entry_id = tm.add_entry(test_entry)
    retrieved = tm.get_entry(entry_id)
    validation = tm.validate_entry(retrieved) if retrieved else False
    
    # Cleanup
    tm.delete_entry(entry_id)
    
    return {
        "ok": True,
        "entry_id": entry_id,
        "retrieved": retrieved,
        "validation": validation,
        "pass": validation is True
    }

@eel.expose
def tm_test_migration():
    """Test migration from old memory.json to new format."""
    tm, _, _ = _get_tm_components()
    
    # Get current memory count
    old_memory = cm.memory.copy()
    old_count = len(old_memory)
    
    # Run migration
    migrated_count = tm.migrate_from_memory(old_memory)
    
    # Check results
    tm_entries_count = len(tm.entries)
    
    return {
        "ok": True,
        "old_count": old_count,
        "migrated_count": migrated_count,
        "tm_entries": tm_entries_count,
        "pass": migrated_count == old_count or old_count == 0
    }

@eel.expose
def tm_test_fuzzy_matching():
    """Test fuzzy matching with various test cases."""
    from src.translation_memory import FuzzyMatcher
    
    matcher = FuzzyMatcher(cm)
    
    test_cases = [
        ("exact match", "テスト", "テスト", 1.0),
        ("minor typo", "テスト", "テストト", 0.9),
        ("word order", "A B C", "B A C", 0.7),
        ("punctuation", "Hello.", "Hello!", 0.95),
        ("tags", "Hello {name}", "Hello {player}", 0.85),
        ("no match", "完全に違う", "totally different", 0.0)
    ]
    
    results = []
    for name, source1, source2, expected in test_cases:
        score = matcher.calculate_similarity(source1, source2)
        results.append({
            "test": name,
            "score": score,
            "expected": expected,
            "pass": abs(score - expected) < 0.15  # Allow 15% tolerance
        })
    
    return {"ok": True, "results": results}

@eel.expose
def tm_test_match_performance():
    """Test fuzzy matching performance with large dataset."""
    from src.translation_memory import FuzzyMatcher
    import time
    
    tm, matcher, _ = _get_tm_components()
    
    # Generate test data
    for i in range(1000):
        tm.add_entry({
            "source": f"Test text {i}",
            "translation": f"Translation {i}",
            "context": {},
            "quality": "approved"
        })
    
    query = "Test text 500"
    start = time.time()
    matches = matcher.find_matches(query, tm.entries, threshold=0.5)
    elapsed = time.time() - start
    
    # Cleanup
    for i in range(1000):
        # Find and delete the test entries
        matches_to_delete = tm.find_by_source(f"Test text {i}")
        for match in matches_to_delete:
            tm.delete_entry(match["id"])
    
    return {
        "ok": True,
        "entry_count": 1000,
        "match_count": len(matches),
        "top_score": matches[0]["score"] if matches else 0,
        "elapsed_ms": elapsed * 1000,
        "pass": elapsed < 1.0  # Should complete in under 1 second
    }

@eel.expose
def tm_test_auto_substitution():
    """Test auto-substitution with various patterns."""
    from src.translation_memory import AutoSubstitutor
    
    sub = AutoSubstitutor(cm)
    
    test_cases = [
        ("placeholders", "Hello {player}", "Bonjour {name}", "Bonjour {player}"),
        ("multiple placeholders", "A {x} B {y}", "X {1} Y {2}", "X {x} Y {y}"),
        ("html tags", "<b>Bold</b>", "<b>Gras</b>", "<b>Gras</b>"),
        ("numbers", "Level 5", "Niveau 3", "Niveau 5"),
        ("mixed", "Hello {player} <br> Level {level}", "Bonjour {name} <br> Niveau {lvl}", "Bonjour {player} <br> Niveau {level}")
    ]
    
    results = []
    for name, source, tm, expected in test_cases:
        result = sub.apply_auto_substitution(source, {"translation": tm})
        results.append({
            "test": name,
            "result": result,
            "expected": expected,
            "pass": result == expected
        })
    
    return {"ok": True, "results": results}

@eel.expose
def tm_find_matches(jp_text: str, threshold: float = 0.5, max_results: int = 10):
    """Find TM matches for given JP text."""
    import time
    start_time = time.time()
    
    # Normalize jp_text for cache key
    normalized_text = re.sub(r'\s+', ' ', jp_text.strip())
    cache_key = f"{normalized_text}:{threshold}:{max_results}"
    
    # Check cache first
    with _tm_cache_lock:
        if cache_key in _tm_result_cache:
            cached_matches, cache_time = _tm_result_cache[cache_key]
            # Check if cache is still valid
            if time.time() - cache_time < _tm_cache_ttl:
                elapsed = (time.time() - start_time) * 1000
                print(f"[TM] Cache hit for '{jp_text[:30]}...', elapsed={elapsed:.2f}ms")
                return {
                    "ok": True,
                    "matches": cached_matches[:max_results],
                    "total_found": len(cached_matches),
                    "cached": True
                }
    
    tm, matcher, substitutor = _get_tm_components()
    
    if not tm.entries:
        elapsed = (time.time() - start_time) * 1000
        print(f"[TM] No entries available, elapsed={elapsed:.2f}ms")
        return {"ok": True, "matches": [], "message": "No TM entries available"}
    
    matches = matcher.find_matches(jp_text, tm.entries, threshold)
    
    # Apply auto-substitution to matches
    for match in matches[:max_results]:
        substituted = substitutor.apply_auto_substitution(jp_text, match["entry"])
        match["substituted_translation"] = substituted
        debug_log("TM", f"Match: query='{jp_text}' vs tm_source='{match['entry'].get('source', 'N/A')}', score={match['score']:.2f}")
    
    elapsed = (time.time() - start_time) * 1000
    print(f"[TM] Found {len(matches)} matches, elapsed={elapsed:.2f}ms")
    
    # Cache the result
    with _tm_cache_lock:
        _tm_result_cache[cache_key] = (matches[:max_results], time.time())
    
    return {
        "ok": True,
        "matches": matches[:max_results],
        "total_found": len(matches),
        "cached": False
    }

@eel.expose
def tm_track_usage(entry_id: str):
    """Track TM entry usage."""
    tm, _, _ = _get_tm_components()
    success = tm.increment_match_count(entry_id)
    
    return {"ok": True, "success": success}

@eel.expose
def tm_test_ui_integration():
    """Test TM UI integration functions."""
    from translation_memory import TranslationMemory, FuzzyMatcher, AutoSubstitutor
    
    tm = TranslationMemory(cm)
    matcher = FuzzyMatcher(cm)
    substitutor = AutoSubstitutor(cm)
    
    # Add test entry
    test_entry = {
        "source": "テストメッセージ",
        "translation": "Test message",
        "context": {"file": "test.csv", "row": 1},
        "quality": "approved"
    }
    entry_id = tm.add_entry(test_entry)
    
    # Test find_matches
    matches = matcher.find_matches("テストメッセージ", tm.entries, threshold=0.5)
    
    # Test auto-substitution
    substituted = substitutor.apply_auto_substitution("テストメッセージ", test_entry)
    
    # Test track usage
    success = tm.increment_match_count(entry_id)
    
    # Cleanup
    tm.delete_entry(entry_id)
    
    return {
        "ok": True,
        "find_matches_count": len(matches),
        "find_matches_score": matches[0]["score"] if matches else 0,
        "substituted": substituted,
        "track_usage_success": success,
        "pass": len(matches) > 0 and matches[0]["score"] >= 0.9 and success
    }

@eel.expose
def tm_pretranslate_batch(items: list, threshold: float = 0.9, min_quality: str = "approved"):
    """Pre-translate batch of items using high-confidence TM matches."""
    tm, matcher, substitutor = _get_tm_components()
    
    results = []
    applied_count = 0
    
    for item in items:
        jp_text = item.get("jp", "")
        if not jp_text:
            results.append({
                "item_id": item.get("id"),
                "success": False,
                "reason": "No JP text"
            })
            continue
        
        # Find matches
        matches = matcher.find_matches(jp_text, tm.entries, threshold)
        
        # Filter by quality and find best match
        best_match = None
        for match in matches:
            if match["entry"].get("quality") == min_quality or min_quality == "any":
                if best_match is None or match["score"] > best_match["score"]:
                    best_match = match
        
        if best_match and best_match["score"] >= threshold:
            # Apply auto-substitution
            translation = substitutor.apply_auto_substitution(jp_text, best_match["entry"])
            
            results.append({
                "item_id": item.get("id"),
                "success": True,
                "translation": translation,
                "score": best_match["score"],
                "match_type": best_match["match_type"]
            })
            applied_count += 1
            
            # Track usage
            tm.increment_match_count(best_match["entry"]["id"])
        else:
            results.append({
                "item_id": item.get("id"),
                "success": False,
                "reason": "No high-confidence match"
            })
    
    return {
        "ok": True,
        "total": len(items),
        "applied": applied_count,
        "results": results
    }

@eel.expose
def pretranslate_batch(items: list, tm_threshold: float = None, tm_min_quality: str = None):
    """
    Pre-translate batch using TM, OpenRouter, and DeepL fallback.
    
    Order of operations:
    1. Translation Memory (high-confidence matches)
    2. OpenRouter AI (if key configured and enabled)
    3. DeepL (fallback if no OpenRouter key or disabled)
    
    All pre-translated entries are marked as 'pre-translated' (not 'approved').
    
    Args:
        items: List of dicts with keys: id, jp, file_path, row_idx, speaker, entry_type
        tm_threshold: TM match threshold (uses config if not provided)
        tm_min_quality: Minimum TM quality to use (uses config if not provided)
    """
    from translation_memory import TranslationMemory, FuzzyMatcher, AutoSubstitutor
    
    # Get settings from config or use defaults
    pretranslate_settings = cm.config.get("pretranslate_settings", {})
    tm_threshold = tm_threshold if tm_threshold is not None else pretranslate_settings.get("tm_threshold", 0.9)
    tm_min_quality = tm_min_quality if tm_min_quality is not None else pretranslate_settings.get("tm_quality", "approved")
    enable_openrouter = pretranslate_settings.get("enable_openrouter", True)
    enable_deepl = pretranslate_settings.get("enable_deepl", True)
    
    print(f"[pretranslate_batch] Settings: tm_threshold={tm_threshold}, tm_min_quality={tm_min_quality}, enable_openrouter={enable_openrouter}, enable_deepl={enable_deepl}")

    tm = TranslationMemory(cm)
    matcher = FuzzyMatcher(cm.config.get("tm_settings", {}))
    substitutor = AutoSubstitutor(cm.config.get("tm_settings", {}))
    
    openrouter_key = cm.get_key("openrouter_api_key") if enable_openrouter else None
    deepl_key = cm.get_key("deepl_api_key") if enable_deepl else None
    openrouter_model = cm.user_settings.get("selected_openrouter_model", "openrouter/auto")
    deepl_target_lang = cm.config.get("deepl_target_lang", "EN-US")
    
    print(f"[pretranslate_batch] API keys: openrouter={'configured' if openrouter_key else 'none'}, deepl={'configured' if deepl_key else 'none'}")
    
    # Rate limiting for API calls
    import time
    last_openrouter_call = 0
    last_deepl_call = 0
    OPENROUTER_RATE_LIMIT = 5.0  # seconds between calls (more reasonable)
    DEEPL_RATE_LIMIT = 2.0        # seconds between calls (Free tier: 5/min, allows buffer)
    
    # Local cache for translations within this batch (avoids duplicate API calls for identical JP text)
    batch_translation_cache = {}
    
    results = []
    tm_applied = 0
    ai_applied = 0
    deepl_applied = 0
    
    for item in items:
        item_id = item.get("id")
        jp_text = item.get("jp", "")
        file_path = item.get("file_path", "")
        row_idx = item.get("row_idx", 0)
        speaker = item.get("speaker", "")
        entry_type = item.get("entry_type", "")
        
        print(f"[pretranslate_batch] Processing item {item_id}: jp_text='{jp_text[:50]}...'")
        
        if not jp_text:
            results.append({
                "item_id": item_id,
                "success": False,
                "reason": "No JP text"
            })
            print(f"[pretranslate_batch] Item {item_id}: skipped (no JP text)")
            continue
        
        translation = None
        source = None
        
        # Step 1: Try Translation Memory (100% matches or element-only differences)
        matches = matcher.find_matches(jp_text, tm.entries, tm_threshold)
        print(f"[pretranslate_batch] Item {item_id}: TM found {len(matches)} matches")
        
        best_match = None
        for match in matches:
            if match["entry"].get("quality") == tm_min_quality or tm_min_quality == "any":
                # Check if this is a 100% match OR differs only in non-translatable elements
                is_100_match = match["score"] >= 1.0
                
                # For auto-substitution: check if Japanese sources differ only in elements
                # Strip all non-translatable elements and compare the remaining text
                source_elements = substitutor.extract_elements(jp_text)
                tm_source_elements = substitutor.extract_elements(match["entry"]["source"])
                
                # Remove elements from both texts and compare
                import re
                # Remove placeholders, tags, numbers, entities
                element_pattern = r'\{[^}]+\}|<[^>]+>|\d+\.?\d*|&[a-z]+;'
                source_stripped = re.sub(element_pattern, '', jp_text)
                tm_source_stripped = re.sub(element_pattern, '', match["entry"]["source"])
                
                # Normalize whitespace (line breaks, tabs, multiple spaces -> single space)
                source_stripped = re.sub(r'\s+', ' ', source_stripped).strip()
                tm_source_stripped = re.sub(r'\s+', ' ', tm_source_stripped).strip()
                
                # If stripped text matches AND element counts match, difference is only in elements → safe for auto-substitution
                is_element_only_diff = (source_stripped == tm_source_stripped and 
                                       len(source_elements) == len(tm_source_elements) and 
                                       len(source_elements) > 0)
                
                print(f"[pretranslate_batch] Item {item_id}: Match score={match['score']:.3f}, is_100={is_100_match}, is_element_only={is_element_only_diff}, source_elements={len(source_elements)}, tm_elements={len(tm_source_elements)}")
                
                if is_100_match or is_element_only_diff:
                    if best_match is None or match["score"] > best_match["score"]:
                        best_match = match
        
        if best_match and best_match["score"] >= tm_threshold:
            translation = substitutor.apply_auto_substitution(jp_text, best_match["entry"])
            source = "tm"
            tm.increment_match_count(best_match["entry"]["id"])
            tm_applied += 1
            print(f"[pretranslate_batch] Item {item_id}: Using TM translation")
        
        # Step 2: Try OpenRouter AI (if no TM match and key configured)
        if translation is None and openrouter_key:
            # Check local batch cache first
            if jp_text in batch_translation_cache:
                cached_trans, cached_source = batch_translation_cache[jp_text]
                translation = cached_trans
                source = f"{cached_source}_batch_cached"
                print(f"[pretranslate_batch] Item {item_id}: Using batch-cached translation from {cached_source}")
            else:
                print(f"[pretranslate_batch] Item {item_id}: Trying OpenRouter AI")
                try:
                    sys_prompt = cm.config.get("ai_system_prompt",
                        "You are a Dragon's Dogma Online (DDON) localization assistant. "
                        "Your output will be inserted directly into the game — follow every rule precisely.\n\n"

                        "OUTPUT FORMAT:\n"
                        "Return only the translated or refined text. No preamble, no explanation, no quotation marks. "
                        "If genuinely uncertain about a reading, append a single bracketed note: [alt: ...]. "
                        "Do not insert blank lines or extra newlines.\n\n"

                        "HARD RULES:\n"
                        "- Preserve anything inside < > angle brackets exactly as-is — these are engine tags. "
                        "Text between paired tags (e.g. <COL>text</COL>) should be translated; the tags themselves must not change.\n"
                        "- Do NOT use Japanese honorifics (e.g. -san, -sama, -dono).\n"
                        "- Render Japanese dashes as an ellipsis (...) or em dash (—) depending on context.\n"
                        "- For unknown proper nouns, keep the established romanisation.\n\n"

                        "STYLE — THE DRAGON'S DOGMA HOUSE STYLE:\n"
                        "Natural English grammar with archaic vocabulary woven in. "
                        "Standard contractions (don't, can't, won't, it's, let's, we're) are used freely. "
                        "What is avoided is modern slang: never use 'gonna', 'gotta', 'kinda', 'sorta', 'okay', 'awesome', 'yeah'.\n"
                        "Favour archaic vocabulary where it fits naturally: "
                        "'tis / 'twas, naught / aught, afore, ere, nigh, mayhap, o'er, e'er, nary, anon, forsooth, hath, dost. "
                        "'Tis is especially characteristic — use it freely for observations ('Tis a formidable foe.').\n"
                        "Characters often speak with heightened gravity — preserve that register rather than flattening it.\n\n"

                        "EXAMPLES (from the actual game):\n"
                        "❌ \"Watch out, the monster is almost here!\"\n"
                        "✓  \"Have a care! The beast draws nigh!\"\n"
                        "❌ \"Let's finish this before more show up.\"\n"
                        "✓  \"Let's end this afore more arrive!\"\n"
                        "❌ \"It's a fast enemy, hard to hit.\"\n"
                        "✓  \"'Tis a trial to hit such swift targets!\"\n\n"

                        "TRANSLATION GUIDANCE:\n"
                        "Stay faithful to the original meaning and length — do not add, omit, or embellish. "
                        "Rephrase for natural English flow within the style above. "
                        "Stay consistent with any translation choices made earlier in this conversation.\n"
                    )
                    
                    # Add archetype notes if available
                    if speaker:
                        # Get the archetype key assigned to this speaker
                        archetype_key = cm.user_settings.get("speaker_archetypes", {}).get(speaker, "")
                        if archetype_key:
                            archetypes = cm.config.get("archetypes", {})
                            if archetype_key in archetypes:
                                arch_data = archetypes[archetype_key]
                                sys_prompt += f"\n\nCHARACTER ARCHETYPE FOR {speaker}:\n{arch_data.get('notes', '')}"
                                print(f"[pretranslate_batch] Item {item_id}: Added archetype notes for speaker {speaker} (archetype: {archetype_key})")
                    
                    # Add lore glossary terms from current JP text
                    le = _get_lore_engine()
                    if le:
                        # Get relevant lore terms from Japanese text
                        relevant_terms = le.scan_text(jp_text)
                        if relevant_terms:
                            sys_prompt += "\n\nGLOSSARY — use these renderings unless the surrounding context makes a different reading clearly more accurate:\n"
                            for jp, en in relevant_terms:
                                sys_prompt += f"- {jp} → {en}\n"
                            print(f"[pretranslate_batch] Item {item_id}: Added {len(relevant_terms)} glossary terms")
                    
                    cache_key = f"{openrouter_model}::{jp_text}"
                    cached = cm.get_cached("openrouter", cache_key)
                    if cached:
                        translation = cached
                        source = "openrouter_cached"
                        # Store in batch cache for reuse
                        batch_translation_cache[jp_text] = (translation, source)
                        print(f"[pretranslate_batch] Item {item_id}: Using persistent cached OpenRouter translation")
                    else:
                        # Reset translation for this attempt
                        translation = None
                        source = None
                        
                        # Rate limiting: wait if needed
                        current_time = time.time()
                        time_since_openrouter = current_time - last_openrouter_call
                        if time_since_openrouter < OPENROUTER_RATE_LIMIT:
                            sleep_time = OPENROUTER_RATE_LIMIT - time_since_openrouter
                            print(f"[pretranslate_batch] Rate limiting OpenRouter: waiting {sleep_time:.1f}s")
                            time.sleep(sleep_time)
                        
                        print(f"[pretranslate_batch] Item {item_id}: Calling OpenRouter API with model {openrouter_model}")
                        last_openrouter_call = time.time()
                        res = OpenRouterClient(openrouter_key).chat(
                            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"Translate this to English: {jp_text}"}],
                            model=openrouter_model
                        )
                        if "text" in res:
                            translation = res["text"]
                            cm.set_cached("openrouter", cache_key, translation)
                            source = "openrouter"
                            # Store in batch cache for reuse
                            batch_translation_cache[jp_text] = (translation, source)
                            print(f"[pretranslate_batch] Item {item_id}: OpenRouter translation successful")
                        else:
                            error = res.get('error', 'Unknown error')
                            if 'rate limit' in error.lower() or '429' in error:
                                print(f"[pretranslate_batch] OpenRouter rate limit hit for {item_id}: {error}")
                                # Increase delay for next call
                                last_openrouter_call = time.time() + 30  # Add 30s penalty
                            else:
                                print(f"[pretranslate_batch] OpenRouter error for {item_id}: {error}")
                except Exception as e:
                    print(f"[pretranslate_batch] OpenRouter exception for {item_id}: {e}")
        
        # Step 3: Fallback to DeepL (if no translation yet and key configured)
        if translation is None and deepl_key:
            # Check local batch cache first
            if jp_text in batch_translation_cache:
                cached_trans, cached_source = batch_translation_cache[jp_text]
                translation = cached_trans
                source = f"{cached_source}_batch_cached"
                print(f"[pretranslate_batch] Item {item_id}: Using batch-cached translation from {cached_source}")
            else:
                # Rate limiting: wait if needed
                current_time = time.time()
                time_since_deepl = current_time - last_deepl_call
                if time_since_deepl < DEEPL_RATE_LIMIT:
                    sleep_time = DEEPL_RATE_LIMIT - time_since_deepl
                    print(f"[pretranslate_batch] Rate limiting DeepL: waiting {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                
                print(f"[pretranslate_batch] Item {item_id}: Trying DeepL fallback")
                try:
                    cached = cm.get_cached("deepl", jp_text)
                    if cached:
                        translation = cached
                        source = "deepl_cached"
                        # Store in batch cache for reuse
                        batch_translation_cache[jp_text] = (translation, source)
                        print(f"[pretranslate_batch] Item {item_id}: Using persistent cached DeepL translation")
                    else:
                        print(f"[pretranslate_batch] Item {item_id}: Calling DeepL API with target lang {deepl_target_lang}")
                        last_deepl_call = time.time()
                        res = DeepLClient(deepl_key).translate(jp_text, target_lang=deepl_target_lang)
                        if "text" in res:
                            translation = res["text"]
                            cm.set_cached("deepl", jp_text, translation)
                            source = "deepl"
                            # Store in batch cache for reuse
                            batch_translation_cache[jp_text] = (translation, source)
                            print(f"[pretranslate_batch] Item {item_id}: DeepL translation successful")
                        else:
                            error = res.get('error', 'Unknown error')
                            if 'rate limit' in error.lower() or '429' in error:
                                print(f"[pretranslate_batch] DeepL rate limit hit for {item_id}: {error}")
                                # Increase delay for next call
                                last_deepl_call = time.time() + 60  # Add 60s penalty
                            else:
                                print(f"[pretranslate_batch] DeepL error for {item_id}: {error}")
                except Exception as e:
                    print(f"[pretranslate_batch] DeepL exception for {item_id}: {e}")
        
        # Save translation if successful
        if translation:
            try:
                print(f"[pretranslate_batch] Item {item_id}: Saving translation with source={source}, status=pre-translated")
                translation_manager.submit_translation(
                    entry_id=item_id,
                    source_text=jp_text,
                    translated_text=translation,
                    translator="pretranslate",
                    file_path=file_path,
                    row_index=row_idx,
                    speaker=speaker,
                    entry_type=entry_type,
                    status="pre-translated"
                )
                
                if source.startswith("tm"):
                    tm_applied += 1
                elif source.startswith("openrouter"):
                    ai_applied += 1
                elif source.startswith("deepl"):
                    deepl_applied += 1
                
                results.append({
                    "item_id": item_id,
                    "success": True,
                    "translation": translation,
                    "source": source
                })
                print(f"[pretranslate_batch] Item {item_id}: Translation saved successfully")
            except Exception as e:
                print(f"[pretranslate_batch] Error saving translation for {item_id}: {e}")
                results.append({
                    "item_id": item_id,
                    "success": False,
                    "reason": f"Save error: {str(e)}"
                })
        else:
            print(f"[pretranslate_batch] Item {item_id}: No translation source available")
            results.append({
                "item_id": item_id,
                "success": False,
                "reason": "No translation source available"
            })
    
    print(f"[pretranslate_batch] Complete: total={len(items)}, tm={tm_applied}, ai={ai_applied}, deepl={deepl_applied}")
    return {
        "ok": True,
        "total": len(items),
        "tm_applied": tm_applied,
        "ai_applied": ai_applied,
        "deepl_applied": deepl_applied,
        "results": results
    }

@eel.expose
def tm_test_pretranslate_batch():
    """Test pre-translation batch feature."""
    from translation_memory import TranslationMemory
    
    tm = TranslationMemory(cm)
    
    # Add test entries
    test_entries = [
        {"source": "こんにちは", "translation": "Hello", "context": {}, "quality": "approved"},
        {"source": "さようなら", "translation": "Goodbye", "context": {}, "quality": "approved"},
        {"source": "ありがとう", "translation": "Thank you", "context": {}, "quality": "draft"}
    ]
    
    entry_ids = []
    for entry in test_entries:
        entry_ids.append(tm.add_entry(entry))
    
    # Test batch pre-translation
    items = [
        {"id": "1", "jp": "こんにちは"},
        {"id": "2", "jp": "さようなら"},
        {"id": "3", "jp": "ありがとう"},
        {"id": "4", "jp": "おはよう"}  # No match
    ]
    
    result = tm_pretranslate_batch(items, threshold=0.9, min_quality="approved")
    
    # Cleanup
    for entry_id in entry_ids:
        tm.delete_entry(entry_id)
    
    return {
        "ok": True,
        "total": result["total"],
        "applied": result["applied"],
        "pass": result["applied"] == 2  # Only approved entries should match
    }

@eel.expose
def tm_get_available_languages():
    """Get list of available languages for cross-language TM."""
    from src.translation_memory import CrossLanguageTM
    
    cross_tm = CrossLanguageTM(cm)
    languages = cross_tm.get_available_languages()
    
    return {"ok": True, "languages": languages}

@eel.expose
def tm_find_cross_language_matches(jp_text: str, target_language: str, threshold: float = 0.7):
    """Find matches from another language's TM."""
    from src.translation_memory import CrossLanguageTM, AutoSubstitutor
    
    cross_tm = CrossLanguageTM(cm)
    substitutor = AutoSubstitutor(cm)
    
    matches = cross_tm.find_cross_language_matches(jp_text, cm.language, target_language, threshold)
    
    # Apply auto-substitution to matches
    for match in matches:
        substituted = substitutor.apply_auto_substitution(jp_text, match["entry"])
        match["substituted_translation"] = substituted
    
    return {
        "ok": True,
        "matches": matches,
        "total_found": len(matches)
    }

@eel.expose
def tm_share_translation(entry_id: str, target_language: str):
    """Share a translation entry to another language's TM."""
    from src.translation_memory import CrossLanguageTM
    
    cross_tm = CrossLanguageTM(cm)
    success = cross_tm.share_translation(entry_id, target_language)
    
    return {"ok": True, "success": success}

@eel.expose
def tm_test_cross_language():
    """Test cross-language TM sharing."""
    from src.translation_memory import CrossLanguageTM, TranslationMemory
    
    cross_tm = CrossLanguageTM(cm)
    tm = TranslationMemory(cm)
    
    # Get available languages
    languages = cross_tm.get_available_languages()
    
    # Add test entry to current TM
    test_entry = {
        "source": "テスト",
        "translation": "Test",
        "context": {},
        "quality": "approved"
    }
    entry_id = tm.add_entry(test_entry)
    
    # Test cross-language find (use current language as target for test)
    matches = cross_tm.find_cross_language_matches("テスト", cm.language, cm.language, threshold=0.5)
    
    # Cleanup
    tm.delete_entry(entry_id)
    
    return {
        "ok": True,
        "available_languages": languages,
        "matches_found": len(matches),
        "pass": len(matches) > 0
    }

@eel.expose
def tm_get_statistics():
    """Get TM statistics."""
    from src.translation_memory import TMManager
    
    manager = TMManager(cm)
    stats = manager.get_statistics()
    
    return {"ok": True, "statistics": stats}

@eel.expose
def tm_get_all_entries(filters: dict = None):
    """Get all TM entries with optional filtering."""
    from src.translation_memory import TMManager
    
    manager = TMManager(cm)
    entries = manager.get_all_entries(filters)
    
    return {"ok": True, "entries": entries, "total": len(entries)}

@eel.expose
def tm_export_tm(filepath: str, format: str = "json"):
    """Export TM to file."""
    from src.translation_memory import TMManager
    
    manager = TMManager(cm)
    success = manager.export_tm(filepath, format)
    
    return {"ok": True, "success": success}

@eel.expose
def tm_import_tm(filepath: str, format: str = "json", merge: bool = True):
    """Import TM from file."""
    from src.translation_memory import TMManager
    
    manager = TMManager(cm)
    result = manager.import_tm(filepath, format, merge)
    
    return {"ok": True, **result}

@eel.expose
def tm_test_management():
    """Test TM management tools."""
    from src.translation_memory import TMManager, TranslationMemory
    import tempfile
    import os
    
    tm = TranslationMemory(cm)
    manager = TMManager(cm)
    
    # Add test entries
    test_entries = [
        {"source": "テスト1", "translation": "Test 1", "context": {}, "quality": "approved"},
        {"source": "テスト2", "translation": "Test 2", "context": {}, "quality": "draft"}
    ]
    
    entry_ids = []
    for entry in test_entries:
        entry_ids.append(tm.add_entry(entry))
    
    # Test get_statistics
    stats = manager.get_statistics()
    
    # Test get_all_entries
    entries = manager.get_all_entries({"quality": "approved"})
    
    # Test export
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        export_path = f.name
    
    export_success = manager.export_tm(export_path, "json")
    
    # Test import
    # Clear TM first
    for entry_id in entry_ids:
        tm.delete_entry(entry_id)
    
    import_result = manager.import_tm(export_path, "json", merge=False)
    
    # Cleanup
    os.unlink(export_path)
    
    # Clear test entries
    for entry in tm.entries:
        tm.delete_entry(entry["id"])
    
    return {
        "ok": True,
        "stats_total": stats["total_entries"],
        "filtered_count": len(entries),
        "export_success": export_success,
        "import_success": import_result["success"],
        "imported": import_result["imported"],
        "pass": stats["total_entries"] >= 2 and len(entries) == 1 and export_success and import_result["success"]
    }

@eel.expose
def run_tests(category=None, verbose=False, coverage=False):
    """Run pytest tests and return results."""
    import subprocess
    import sys

    # Set TEST_MODE
    global TEST_MODE
    TEST_MODE = True

    # Build pytest command
    cmd = [sys.executable, "run_tests.py"]
    if category:
        cmd.extend(["--category", category])
    if verbose:
        cmd.append("-v")
    if coverage:
        cmd.append("--coverage")

    try:
        result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)),
                               capture_output=True, text=True, timeout=60)
        return {
            "ok": True,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "Tests timed out after 60 seconds"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
    finally:
        TEST_MODE = False


if __name__ == '__main__':
    import argparse

    # Check for --run-tests flag
    if "--run-tests" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--run-tests", action="store_true")
        parser.add_argument("--category", help="Test category to run")
        parser.add_argument("-v", "--verbose", action="store_true")
        parser.add_argument("--coverage", action="store_true")
        args = parser.parse_args()

        # Run tests directly
        import subprocess
        cmd = [sys.executable, "run_tests.py"]
        if args.category:
            cmd.extend(["--category", args.category])
        if args.verbose:
            cmd.append("-v")
        if args.coverage:
            cmd.append("--coverage")

        result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        sys.exit(result.returncode)

    try:
        print("[MAIN] Initializing application...")
        success = main()
        if not success:
            print("[MAIN] Application failed to start")
            sys.exit(1)
    except (SystemExit, KeyboardInterrupt):
        print("[MAIN] Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"[MAIN] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("[MAIN] Application cleanup completed")
        sys.stdout.flush()
