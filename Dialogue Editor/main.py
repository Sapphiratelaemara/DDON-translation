import os
import sys
import subprocess

# Set console to UTF-8 for Windows to handle Japanese characters
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Dependency check and auto-install
def check_dependencies():
    """Check if required packages are installed, offer to install if missing."""
    required = {
        'eel': 'eel>=0.16.0',
        'requests': 'requests>=2.31.0',
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

# Add parent directory to path so we can import project modules
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PARENT_DIR)

from config_manager import ConfigManager
from api_handler import DeepLClient, OpenRouterClient
from translator_engine import TranslationEngine
from file_utils import _get_csv_files, _read_csv
from batch_runner import run_batch, BatchSettings

# Initialize core logic
cm     = ConfigManager()
engine = TranslationEngine(cm.config.get("tag_map", {}))

# Lazy-initialized lore engine
_lore_engine      = None
_lore_engine_lock = threading.Lock()

# Lazy-initialized gloss engine
_gloss_engine      = None
_gloss_engine_lock = threading.Lock()

def _get_gloss_engine():
    """Return a cached GlossEngine, rebuilding if needed."""
    global _gloss_engine
    # Get lore_map from LoreEngine (which loads from glossary files)
    le = _get_lore_engine()
    lore_map = le.lore_map if le else {}
    try:
        if _gloss_engine is None:
            with _gloss_engine_lock:
                if _gloss_engine is None:
                    from gloss_engine import GlossEngine
                    _gloss_engine = GlossEngine(lore_map=lore_map)
        _gloss_engine.update_lore_map(lore_map)
        # Clear gloss cache when lore_map is updated
        global _gloss_cache
        with _gloss_cache_lock:
            _gloss_cache.clear()
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
                    from lore_engine import LoreEngine
                    le = LoreEngine(cm.config.get("archetypes"))
                    le.load_data(
                        cm.config.get("bible_path",    ""),
                        cm.config.get("glossary_path", ""))
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
QUEUE_CACHE_FILE = "review_queues_cache.json"
ITEMS_CACHE_FILE = "review_items_cache.json"

def _save_review_queues():
    """Save review queues to disk for persistence across restarts."""
    try:
        serializable = {}
        for key, queue_data in review_queues.items():
            serializable[key] = dict(queue_data)
        with open(QUEUE_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[_save_review_queues] Error: {e}")

def _load_review_queues():
    """Load review queues from disk if they exist."""
    global review_queues
    try:
        if os.path.exists(QUEUE_CACHE_FILE):
            with open(QUEUE_CACHE_FILE, 'r', encoding='utf-8') as f:
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
        with open(ITEMS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(review_items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[_save_review_items] Error: {e}")

def _load_review_items():
    """Load review_items from disk if they exist."""
    global review_items
    try:
        if os.path.exists(ITEMS_CACHE_FILE):
            with open(ITEMS_CACHE_FILE, 'r', encoding='utf-8') as f:
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
    folders   = cm.config.get("folders", [])
    csv_files = _get_csv_files(folders)
    return {
        "folders":      folders,
        "triggers":     cm.config.get("triggers",   []),
        "file_count":   len(csv_files),
        "last_scan":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "in_universe":  cm.config.get("in_universe",  True),
        "preview_mode": cm.config.get("preview_mode", False),
        "last_stats":   cm.config.get("last_stats",   {}),
        "presets":      list(cm.config.get("presets", {"Standard": 50}).keys()),
        "wall_presets": list(cm.config.get("wall_presets", {"Standard": 7}).keys()),
        "selected_preset": cm.config.get("selected_preset", "Standard"),
        "wall_preset":  cm.config.get("wall_preset", "Standard"),
        "dark_mode":    cm.config.get("dark_mode", False),
        "theme_colors": get_theme_colors(),
    }

@eel.expose
def calculate_project_stats():
    """Project-wide stats: total lines vs translated lines."""
    folders   = cm.config.get("folders", [])
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
    cm.config["last_stats"] = res
    cm.save_all()
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
    dark_mode = cm.config.get("dark_mode", False)
    
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
        "tooltip":  "#ff8800",
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
        custom = cm.config.get("custom_dark_theme", {})
        if custom:
            return {**default_dark, **custom}
        return default_dark
    else:
        # Use custom light theme if configured
        custom = cm.config.get("custom_light_theme", {})
        if custom:
            return {**default_light, **custom}
        return default_light

@eel.expose
def toggle_dark_mode():
    """Toggle dark mode and return new theme colors."""
    current_mode = cm.config.get("dark_mode", False)
    new_mode = not current_mode
    cm.config["dark_mode"] = new_mode
    cm.save_all()
    return get_theme_colors()

# =============================================================================
# SETTINGS & CONFIG
# =============================================================================
# --- CONFIG LIST MANAGEMENT (Folders, Triggers) ---
@eel.expose
def update_config_dict(dict_key, action, key, value=None):
    """Handles Dictionary-based settings (tags, presets)"""
    if dict_key not in cm.config:
        cm.config[dict_key] = {}
        
    if action == "add":
        cm.config[dict_key][key] = value
    elif action == "remove":
        if key in cm.config[dict_key]:
            del cm.config[dict_key][key]
            
    cm.save_all()
    return cm.config[dict_key]
    
@eel.expose
def update_config_list(list_key, action, item=None, index=None):
    """Generic handler for folders and triggers lists"""
    if list_key not in cm.config:
        cm.config[list_key] = []
        
    if action == "add" and item:
        cm.config[list_key].append(item)
    elif action == "remove":
        if index is not None:
            cm.config[list_key].pop(index)
        elif item in cm.config[list_key]:
            cm.config[list_key].remove(item)
            
    cm.save_all()
    return cm.config[list_key]

@eel.expose
def get_full_config():
    data = cm.config.copy()
    data['deepl_api_key']      = cm.get_key("deepl_api_key")
    data['openrouter_api_key'] = cm.get_key("openrouter_api_key")
    for key in ["folders", "triggers", "replace_rules"]:
        if key not in data:
            data[key] = []
    return data

@eel.expose
def save_config_field(key, value):
    global _lore_engine
    if key in ["deepl_api_key", "openrouter_api_key"]:
        cm.set_key(key, value)
    else:
        cm.config[key] = value
        cm.save_all()
        if key in ("bible_path", "glossary_path"):
            _lore_engine = None   # invalidate lore cache
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
    items = cm.config.get(section, [])
    if item not in items:
        items.append(item)
        cm.config[section] = items
        cm.save_all()
    return items

@eel.expose
def remove_list_item(section, item):
    items = cm.config.get(section, [])
    if item in items:
        items.remove(item)
        cm.config[section] = items
        cm.save_all()
    return items

@eel.expose
def update_list_item(section, index, item):
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
    if folder_path and folder_path not in cm.config.get("folders", []):
        cm.config.setdefault("folders", []).append(folder_path)
        cm.save_all()
        return cm.config["folders"]
    return cm.config.get("folders", [])

@eel.expose
def remove_folder(index):
    """Remove a folder from the watched folders list by index."""
    folders = cm.config.get("folders", [])
    if 0 <= index < len(folders):
        folders.pop(index)
        cm.config["folders"] = folders
        cm.save_all()
    return folders

@eel.expose
def add_trigger(trigger_text):
    """Add a trigger to the scan triggers list."""
    if trigger_text and trigger_text not in cm.config.get("triggers", []):
        cm.config.setdefault("triggers", []).append(trigger_text)
        cm.save_all()
        return cm.config["triggers"]
    return cm.config.get("triggers", [])

@eel.expose
def remove_trigger(index):
    """Remove a trigger from the scan triggers list by index."""
    triggers = cm.config.get("triggers", [])
    if 0 <= index < len(triggers):
        triggers.pop(index)
        cm.config["triggers"] = triggers
        cm.save_all()
    return triggers

@eel.expose
def refresh_ui():
    """Refresh UI components and notify active editors."""
    global active_editors
    
    # In web context, this mainly updates the dashboard data
    # The frontend will handle the actual UI refresh
    return {
        "folders": cm.config.get("folders", []),
        "triggers": cm.config.get("triggers", []),
        "presets": list(cm.config.get("presets", {"Standard": 50}).keys()),
        "wall_presets": list(cm.config.get("wall_presets", {"Standard": 7}).keys()),
        "selected_preset": cm.config.get("selected_preset", "Standard"),
        "wall_preset": cm.config.get("wall_preset", "Standard"),
        "in_universe": cm.config.get("in_universe", True),
        "preview_mode": cm.config.get("preview_mode", False),
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
        from lore_engine import DEFAULT_ARCHETYPES
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
        from lore_engine import DEFAULT_ARCHETYPES
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
    cm.config.setdefault("speaker_archetypes", {})[speaker] = archetype_key if archetype_key else None
    if not archetype_key:
        cm.config["speaker_archetypes"].pop(speaker, None)
    if note:
        cm.config.setdefault("speaker_notes", {})[speaker] = note
    else:
        cm.config.setdefault("speaker_notes", {}).pop(speaker, None)
    cm.save_all()
    return True

@eel.expose
def get_archetypes_list():
    """Return list of available archetypes for dropdown."""
    archetypes = cm.config.get("archetypes", {})
    result = [{"key": k, "name": v.get("name", k)} for k, v in archetypes.items()]
    result.insert(0, {"key": "", "name": "(none)"})
    return result

@eel.expose
def get_speaker_archetype(speaker):
    """Return saved archetype for a speaker."""
    return cm.config.get("speaker_archetypes", {}).get(speaker, "")

@eel.expose
def get_speaker_note(speaker):
    """Return saved note for a speaker."""
    return cm.config.get("speaker_notes", {}).get(speaker, "")

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
        cm.config["openrouter_models"] = models
        cm.save_all()
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
def get_standard_limit():
    selected = cm.config.get("selected_preset", "Standard")
    presets  = cm.config.get("presets", {"Standard": 50})
    return presets.get(selected, list(presets.values())[0] if presets else 50)

@eel.expose
def get_wall_limit():
    selected = cm.config.get("wall_preset", "Standard")
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
        "selected_char": cm.config.get("selected_preset", "Standard"),
        "selected_line": cm.config.get("wall_preset", "Standard"),
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
    try:
        import os
        import io
        import base64
        from PIL import Image, ImageDraw, ImageFont
        
        # Get profile data
        profiles = get_preview_profiles()
        profile = profiles.get(profile_name)
        if not profile:
            return {"error": f"Profile '{profile_name}' not found"}
        
        # Load actual PNG image from assets
        assets_path = cm.config.get("assets_path")
        if not assets_path:
            return {"error": "Assets path not configured"}
        
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
            if not os.path.exists(png_path):
                continue
            try:
                with Image.open(png_path) as img:
                    final_base = img.convert("RGBA")
                break
            except Exception:
                continue
        
        # Fallback to procedural if no image found - create with transparency
        if final_base is None:
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
        if not os.path.exists(font_path):
            font_path = None
        
        if not font_path:
            # Fallback to system font
            try:
                font = ImageFont.truetype("arial.ttf", profile.get("font_sz", 14))
            except:
                font = ImageFont.load_default()
        else:
            try:
                font = ImageFont.truetype(font_path, profile.get("font_sz", 14))
            except:
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
        
        # Draw text
        line_spacing = profile.get("line_spacing", 1)
        if line_spacing <= 1:
            line_spacing = 1.2
        
        lines = text.split('\n')
        y_offset = text_y
        for line in lines:
            if line.strip():
                draw.text((text_x, y_offset), line.strip(), fill=text_color, font=font)
            y_offset += int(font.size * line_spacing)
        
        # Convert to base64 (preserve RGBA/transparency)
        buffer = io.BytesIO()
        final_base.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return {
            "image": f"data:image/png;base64,{img_base64}",
            "width": final_base.width,
            "height": final_base.height,
            "crop": crop
        }
        
    except Exception as e:
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
    
    # Check cache
    with _gloss_cache_lock:
        if jp_text in _gloss_cache:
            print(f"[get_gloss] Cache hit for: {jp_text[:30]}...")
            return _gloss_cache[jp_text]
    
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
                # Convert tokens to serializable dicts
                result = [
                    {
                        "surface": t.surface,
                        "base": t.base,
                        "pos": t.pos,
                        "candidates": t.candidates,
                        "is_lore": t.is_lore,
                    }
                    for t in tokens
                ]
                all_results.extend(result)
                print(f"[get_gloss] Chunk {i+1} completed, got {len(result)} tokens")
            except Exception as e:
                print(f"[get_gloss] Error processing chunk {i+1}: {e}")
        
        print(f"[get_gloss] Batch processing completed, total {len(all_results)} tokens")
        # Cache result
        with _gloss_cache_lock:
            _gloss_cache[jp_text] = all_results
        print(f"[get_gloss] Returning {len(all_results)} dicts, total time: {(time.time() - start)*1000:.0f}ms")
        return all_results
    
    def _gloss_with_timeout():
        try:
            tokens = ge.gloss(jp_text)
            print(f"[get_gloss] gloss() returned, got {len(tokens) if tokens else 'None'} tokens")
            # Convert tokens to serializable dicts
            result = [
                {
                    "surface": t.surface,
                    "base": t.base,
                    "pos": t.pos,
                    "candidates": t.candidates,
                    "is_lore": t.is_lore,
                }
                for t in tokens
            ]
            print(f"[get_gloss] Converted {len(result)} tokens to dicts")
            # Cache result
            with _gloss_cache_lock:
                _gloss_cache[jp_text] = result
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
    thread.join(timeout=30.0)  # 30 second timeout for gloss() (test if long text eventually completes)
    
    if thread.is_alive():
        print(f"[get_gloss] Timeout after 30s, returning empty result")
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
    try:
        le = _get_lore_engine()
        if not le:
            return []
        return le.scan_anachronisms(en_text)
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
        _, _, rows = _read_csv_cached(path)
        print(f"[get_adjacent_context] Read {len(rows)} rows from CSV")
        
        # Check if CSV has header row (only 001.csv has header)
        has_header = "001.csv" in os.path.basename(path)
        print(f"[get_adjacent_context] has_header={has_header}")
        
        # Adjust row index if there's a header
        data_row_idx = row_idx
        if has_header:
            data_row_idx = row_idx + 1
            print(f"[get_adjacent_context] Adjusted data_row_idx from {row_idx} to {data_row_idx}")
        
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
        print(f"[get_adjacent_context] Returning result: {result}")
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
    cm.config["selected_preset"] = preset_name
    cm.config["wall_preset"]     = wall_preset_name
    cm.config["in_universe"]     = cm.config.get("in_universe", True)
    cm.save_all()

    limit      = cm.config.get("presets",      {}).get(preset_name, 50)
    wall_limit = cm.config.get("wall_presets", {}).get(wall_preset_name, 7)

    settings = BatchSettings(
        limit            = limit,
        wall_limit       = wall_limit,
        triggers         = cm.config.get("triggers",     []),
        do_in_universe   = cm.config.get("in_universe",  True),
        folders          = cm.config.get("folders",      []),
        tag_map          = cm.config.get("tag_map",      {}),
        entry_type_rules = cm.config.get("entry_type_rules", {}),
        replace_rules    = cm.config.get("replace_rules",    []),
        preview_mode     = cm.config.get("preview_mode",     False),
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

    model = cm.config.get("selected_openrouter_model", "openrouter/auto")
    cache_key = f"{model}::{message}"
    cached = cm.get_cached("openrouter", cache_key)
    if cached:
        return cached

    sys_prompt = cm.config.get("ai_system_prompt",
        "You are a Dragon's Dogma Online (DDON) localization assistant. "
        "You must strictly adhere to the 'Dragon's Dogma' localization style. "
        "This style uses Early Modern English, archaic vocabulary (e.g., 'tis, naught, aught, pray, afore, mayhap, forsooth, arise, pawn), "
        "Do not go overboard on the archaic language, it should sound natural in English."
        "and a formal medieval fantasy tone. NEVER use modern slang, colloquialisms, or modern contractions (e.g., avoid 'okay', 'gonna', 'don't', 'can't'). "
        "CRITICAL RULES: Do NOT use any Japanese honorifics (e.g. -san, -sama, -dono). Use precise, proper English punctuation. "
        "Do NOT insert any blank lines or newlines in your response. "
        "Translate Japanese dashes as either an ellipsis (...) or a regular em dash (—), when appropriate for the context. "
        "Help the user translate or refine dialogue while respecting these rules and the character archetypes. "
        "Do not add unecessary quotation marks."
        "Stay close to the original meaning, but rephrase it to sound more natural in English. "
        "Things within < and > are tags & should be preserved as-is."
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
def apply_fix(item_id, new_text, force=False):
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

    # Respect Preview Mode - don't write to disk if user is just reviewing
    if cm.config.get("preview_mode", False):
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
        
        # Only 001.csv has a header row, others don't
        has_header = "001.csv" in os.path.basename(filepath)
        
        for i, row in enumerate(rows):
            if has_header and i == 0:
                continue
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
                "path": filepath,
                "row": i  # i is the actual row index in the CSV file
            })
        _save_review_items()
        return len(review_items)
    except Exception as e:
        return {"error": str(e)}

# =============================================================================
# PREFETCH MANAGER
# =============================================================================
from prefetch_manager import PrefetchManager

_prefetch_mgr = PrefetchManager(lore_engine_getter=_get_lore_engine)
_prefetch_mgr.start()

@eel.expose
def start_prefetch(category, items, current_idx, depth=3):
    """Start prefetching the next N entries after current index."""
    try:
        _prefetch_mgr.update_current_idx(category, current_idx)
        _prefetch_mgr.prefetch_next(category, items, current_idx, depth)
        return True
    except Exception as e:
        print(f"[start_prefetch] Error: {e}")
        return False

@eel.expose
def get_prefetch_cache(category, idx):
    """Get cached prefetch results for a category and index."""
    try:
        cached = _prefetch_mgr.get_cached(category, idx)
        if cached:
            return {
                'lore_context': cached.get('lore_context'),
                'anachronisms': cached.get('anachronisms'),
                'adjacent_context': cached.get('adjacent_context'),
                'deepl_suggestion': cached.get('deepl_suggestion')
            }
        return None
    except Exception as e:
        print(f"[get_prefetch_cache] Error: {e}")
        return None

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
    for item in reversed(items):
        item["id"] = f"SEARCH_{item['row']}"
        review_items.insert(current_review_idx, item)
    _save_review_items()
    return True

@eel.expose
def perform_search(query, field_col=None):
    if not query:
        return []
    query_lc  = query.lower()
    csv_files = _get_csv_files(cm.config.get("folders", []))
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
                    })
        except:
            continue
    return results

# =============================================================================
# DIAGNOSTICS — Feature Status
# =============================================================================

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
        "glossary_path": cm.config.get("glossary_path", ""),
        "bible_path": cm.config.get("bible_path", ""),
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

if __name__ == '__main__':
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



