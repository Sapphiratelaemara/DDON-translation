# DDON Dialogue Editor - Project Architecture

## Overview

The DDON Dialogue Editor is a desktop application for translating and editing Japanese game dialogue to English. It provides a comprehensive suite of tools including batch scanning, translation assistance, glossary lookup, lore context integration, and AI-powered suggestions.

**Technology Stack:**
- **Backend**: Python 3.13+
- **Frontend**: HTML/CSS/JavaScript (Vanilla)
- **Desktop Bridge**: Eel (Python-JavaScript IPC)
- **External APIs**: DeepL (translation), OpenRouter (AI chat)
- **Natural Language Processing**: Janome (Japanese tokenization), Jamdict (Japanese-English dictionary)

## Architecture Pattern

The application follows a **client-server architecture** where:
- **Python backend** acts as the server, handling business logic, file I/O, and external API calls
- **Web frontend** acts as the client, providing the user interface
- **Eel framework** enables bidirectional communication between Python and JavaScript

```
┌―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――┐
│                    Web Frontend (Browser)                    │
│  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  │
│  │ HTML UI  │  │   CSS    │  │   JS     │  │  Eel.js  │  │
│  └――――――――――┘  └――――――――――┘  └――――――――――┘  └――――――――――┘  │
└――――――――――――――――――――――――――┬――――――――――――――――――――――――――――――――――┘
                           │ Eel IPC
                           │ (WebSocket/HTTP)
┌――――――――――――――――――――――――――┴――――――――――――――――――――――――――――――――┐
│                    Python Backend                            │
│  ┌――――――――――――――――――――――――――――――――――――――――――――――――――――――┐  │
│  │              main.py (Entry Point)                    │  │
│  │  - Eel initialization                                 │  │
│  │  - Route definitions (@eel.expose)                   │  │
│  │  - Global state management                           │  │
│  └――――――――――――――――――――――――――――――――――――――――――――――――――――――┘  │
│  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  │
│  │ Config   │  │  API     │  │  Lore    │  │  Gloss   │  │
│  │ Manager  │  │  Handler  │  │  Engine   │  │  Engine  │  │
│  │(src/)    │  │(src/)    │  │(src/)    │  │(src/)    │  │
│  └――――――――――┘  └――――――――――┘  └――――――――――┘  └――――――――――┘  │
│  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  │
│  │ Trans    │  │  Batch   │  │  File    │  │  Search  │  │
│  │ Engine   │  │  Runner  │  │  Utils   │  │  Window  │  │
│  │(src/)    │  │(src/)    │  │(src/)    │  │          │  │
│  └――――――――――┘  └――――――――――┘  └――――――――――┘  └――――――――――┘  │
│  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  ┌――――――――――┐  │
│  │ Trans    │  │  Prefetch│  │  Trans   │  │  GitHub  │  │
│  │ Memory   │  │  Manager │  │  Manager │  │  Sync    │  │
│  │(src/)    │  │(src/)    │  │(src/)    │  │(src/)    │  │
│  └――――――――――┘  └――――――――――┘  └――――――――――┘  └――――――――――┘  │
└―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――┘
                           │
                           │ File I/O
                           ▼
                    ┌――――――――――――――┐
                    │  CSV Files   │
                    │  Glossary    │
                    │  Bible       │
                    │  Config JSON │
                    └――――――――――――――┘
```

## Directory Structure

```
Dialogue Editor/
├── main.py                 # Application entry point, Eel routes, global state
├── count_chars.py         # Utility script for character counting
├── runtime_hook.py        # PyInstaller runtime hook
├── requirements.txt        # Python dependencies
├── keys.json              # API keys (separate for security, global)
├── ARCHITECTURE.md        # This file
├── USER_GUIDE.html        # User documentation
├── src/                   # Source code modules
│   ├── config_manager.py  # Configuration management (JSON files)
│   ├── github_sync.py     # GitHub synchronization for per-language data
│   ├── api_handler.py     # External API clients (DeepL, OpenRouter)
│   ├── translator_engine.py # Text wrapping and translation processing
│   ├── lore_engine.py     # Lore/context system, archetypes, in-universe vocab
│   ├── gloss_engine.py    # Japanese morpheme glossing (Janome + Jamdict)
│   ├── lore_data.py       # Default archetypes, vocabulary, anachronism patterns
│   ├── translation_memory.py # Translation memory management and fuzzy matching
│   ├── file_utils.py      # CSV file reading utilities
│   ├── batch_runner.py    # Batch scanning logic (background thread)
│   ├── translation_manager.py # Translation data management
│   ├── prefetch_manager.py # Local-only prefetch caching (TM, gloss, lore, adjacent context)
│   └── check_keys.py      # Utility script for testing API keys
├── config/                # Per-language configuration directory
│   ├── en/                # English language configuration
│   │   ├── formatter_config.json   # Main configuration - non-split keys only (triggers, styles, wall_preset, sync_language, pretranslate_settings, config_dir, deepl_target_lang, archetypes, entry_type_rules, replace_rules, ai_system_prompt, ai_button_prompts, substitution_rules)
│   │   ├── tag_map.json           # Tag mappings (synced to GitHub)
│   │   ├── presets.json           # Character presets (synced to GitHub)
│   │   ├── speaker_data.json      # Speaker archetypes & notes (synced to GitHub)
│   │   ├── tag_display.json       # Tag display settings (synced to GitHub)
│   │   ├── preview_font.json      # Font preview settings (synced to GitHub)
│   │   ├── user_settings.json      # User preferences (local only)
│   │   ├── memory.json             # Learned fixes (local only)
│   │   ├── translation_memory.json # Translation memory entries (compressed, synced to GitHub)
│   │   ├── anach_definitions.json # Anachronism definitions (synced to GitHub)
│   │   ├── archaic_examples.json  # Archaic word examples (synced to GitHub)
│   │   ├── prefetch_cache.json    # Prefetch manager cache (per-language, not synced)
│   │   ├── cache.json             # API response cache (per-language, not synced)
│   │   ├── review_queues_cache.json # Review queues (per-language, not synced)
│   │   └── review_items_cache.json # Manual translation queue (per-language, not synced)
│   └── [lang]/            # Other language directories
├── web/                   # Frontend web interface
│   ├── index.html         # Main HTML structure
│   ├── style.css          # Stylesheets
│   └── app.js             # Frontend JavaScript controller
├── assets/                # Static assets
├── deps/                  # External dependencies (jamdict data)
└── __pycache__/           # Python bytecode cache
```

## Key Components

### 1. Entry Point (`main.py`)

**Responsibilities:**
- Dependency checking and auto-installation
- Eel framework initialization
- Route definition for Python-JavaScript communication
- Global state management (queues, caches, active editors)
- Lazy initialization of expensive components (LoreEngine, GlossEngine)

**Key Global State:**
```python
review_queues = {
    "tag":   defaultdict(list),   # Queue for tag-related issues
    "wall":  defaultdict(list),   # Queue for wall limit violations
    "dash":  defaultdict(list),   # Queue for dash issues
    "anach": defaultdict(list),   # Queue for anachronisms
}
review_items = []               # Current review queue
current_review_idx = 0          # Current item index
pending_csv_writes = {}         # Pending CSV write operations
_csv_cache = {}                 # CSV read cache
active_editors = []            # Active editor windows
```

**Eel Routes:**
Functions decorated with `@eel.expose` are callable from JavaScript:

**Dashboard & Stats:**
- `get_dashboard_data()` - Dashboard statistics
- `calculate_project_stats()` - Calculate project-wide statistics

**Configuration Management:**
- `get_full_config()` - Complete configuration
- `save_config_field()` - Save single config field
- `switch_language()` - Switch to different language
- `create_language()` - Create new language configuration
- `get_available_languages()` - Get list of available languages
- `update_config_dict()` - Update dictionary config values
- `update_config_list()` - Update list config values
- `update_map_setting()` - Update map/dict config setting
- `delete_map_setting()` - Delete map/dict config setting
- `add_list_item()` - Add item to list config
- `remove_list_item()` - Remove item from list config
- `update_list_item()` - Update item in list config

**Archetypes & Speakers:**
- `save_archetype()` - Save archetype metadata
- `save_archetype_data()` - Save archetype data
- `delete_archetype()` - Delete archetype
- `reset_archetypes_to_defaults()` - Reset archetypes to defaults
- `reload_archetypes_from_file()` - Reload archetypes from file
- `save_speaker_archetype()` - Save speaker archetype assignment
- `get_archetypes_list()` - Get available archetypes
- `get_speaker_archetype()` - Get archetype for speaker
- `get_speaker_note()` - Get note for speaker
- `get_speakers_list()` - Get list of speakers
- `get_archetype_options()` - Get archetype options
- `get_archetype_notes()` - Get archetype notes

**Folders & Triggers:**
- `pick_directory()` - Open directory picker dialog
- `pick_file()` - Open file picker dialog
- `add_folder()` - Add folder to watched folders
- `remove_folder()` - Remove folder from watched folders
- `add_trigger()` - Add entry trigger
- `remove_trigger()` - Remove entry trigger

**UI & Theme:**
- `get_theme_colors()` - Get current theme colors
- `toggle_dark_mode()` - Toggle dark/light theme
- `refresh_ui()` - Refresh UI state

**Editor Windows:**
- `notify_active_editors()` - Notify active editor windows
- `register_editor()` - Register editor window
- `unregister_editor()` - Unregister editor window

**Log:**
- `clear_log()` - Clear log messages
- `add_log_message()` - Add message to log

**Testing & Validation:**
- `test_deepl()` - Test DeepL API key
- `test_openrouter()` - Test OpenRouter API key
- `fetch_models()` - Fetch available AI models
- `test_regex()` - Test regex pattern

**Text Processing:**
- `get_simulated_len()` - Calculate text length with tags
- `rewrap_text()` - Re-wrap text with current limits
- `get_standard_limit()` - Get standard character limit
- `get_wall_limit()` - Get wall text limit

**Presets & Profiles:**
- `get_all_presets()` - Get all limit presets
- `get_preview_profiles()` - Get preview profiles
- `save_preview_profile()` - Save preview profile
- `add_preview_type()` - Add preview type to profile
- `remove_preview_type()` - Remove preview type from profile

**Preview Images:**
- `generate_preview_image()` - Generate preview image

**Glossary & Lore:**
- `get_gloss()` - Glossary lookup
- `get_lore_context()` - Lore context lookup
- `scan_anachronisms()` - Scan text for anachronisms
- `get_definition()` - Get anachronism definition
- `prefetch_definitions()` - Prefetch anachronism definitions

**Translation & AI:**
- `get_deepl_suggestion()` - Get DeepL translation suggestion
- `send_ai_chat()` - Send AI chat message
- `get_entry_types_list()` - Get list of entry types

**Batch Scanning:**
- `start_batch_scan()` - Start batch scan with preset
- `is_batch_scan_complete()` - Check if batch scan complete

**Review Queue:**
- `get_queue_structure()` - Get review queue structure
- `get_items_for_category()` - Get items for category
- `get_all_items_in_queue()` - Get all items in review queue
- `get_next_review_item()` - Get next review item
- `clear_queue()` - Clear review queue
- `bulk_inject()` - Inject search results into review queue

**CSV Operations:**
- `flush_csv_writes()` - Flush pending CSV writes
- `apply_fix()` - Apply fix to item
- `load_csv_for_translation()` - Load CSV for translation

**Prefetching:**
- `start_prefetch()` - Start prefetch operation (local-only: TM, gloss, lore, adjacent context)
- `start_prefetch_all()` - Start prefetch for all items
- `get_prefetch_cache()` - Get prefetch cache entry
- `clear_prefetch_cache()` - Clear prefetch cache
- `fetch_deepl_batch()` - Batch fetch DeepL translations for current + next N entries
- `get_adjacent_context()` - Get adjacent context for item

**Gloss Cache:**
- `clear_gloss_cache()` - Clear gloss cache

**Translation Approval Workflow:**
- `approve_translation()` - Approve translation entry
- `reject_translation()` - Reject translation entry
- `get_translation_status()` - Get translation approval status
- `add_translation_comment()` - Add comment to translation
- `get_translation_comments()` - Get translation comments
- `vote_translation()` - Vote on translation
- `save_translation_history()` - Save translation history entry
- `get_translation_history()` - Get translation history for entry
- `cleanup_old_approval_logs()` - Clean up old approval logs
- `update_all_log_usernames()` - Update usernames in logs
- `get_recent_translation_activity()` - Get recent translation activity
- `get_translation_stats()` - Get translation statistics
- `get_entries_by_status()` - Get entries by approval status
- `get_unapproved_entries_with_comments()` - Get unapproved entries with comments

**GitHub Sync:**
- `sync_push()` - Push data to GitHub
- `sync_pull()` - Pull data from GitHub
- `get_sync_status()` - Get sync status

**Search:**
- `perform_search()` - Database search

**Translation Memory (TM):**
- `tm_test_data_structure()` - Test TM data structure
- `tm_test_migration()` - Test TM migration
- `tm_test_fuzzy_matching()` - Test TM fuzzy matching
- `tm_test_match_performance()` - Test TM match performance
- `tm_test_ui_integration()` - Test TM UI integration
- `tm_find_matches()` - Find TM matches
- `tm_track_usage()` - Track TM entry usage
- `tm_pretranslate_batch()` - Pretranslate batch using TM
- `pretranslate_batch()` - Pretranslate batch with TM
- `tm_test_pretranslate_batch()` - Test TM pretranslate batch
- `tm_get_available_languages()` - Get available TM languages
- `tm_find_cross_language_matches()` - Find cross-language TM matches
- `tm_share_translation()` - Share translation across languages
- `tm_test_cross_language()` - Test cross-language TM
- `tm_get_statistics()` - Get TM statistics
- `tm_get_all_entries()` - Get all TM entries
- `tm_export_tm()` - Export TM to file
- `tm_import_tm()` - Import TM from file
- `tm_test_management()` - Test TM management

**Feature Flags:**
- `get_feature_status()` - Get feature flag status

**Testing:**
- `run_tests()` - Run test suite

**Shutdown:**
- `shutdown_app()` - Shutdown application

### 2. Configuration Management (`src/config_manager.py`)

**Responsibilities:**
- Load/save configuration from JSON files
- Manage language-specific configuration directories (config/<lang>/)
- Manage API keys (separate file for security, global)
- Manage user memory/preferences (per-language)
- Manage API response cache (per-language)
- Seed default archetypes from lore_data

**Configuration Files (Per-Language in config/<lang>/):**
- `formatter_config.json` - Main configuration - partial sync (tag_map, triggers, presets, wall_presets, speaker_archetypes, speaker_notes, tag_display, entry_type_rules)
- `user_settings.json` - User preferences (sync settings, paths, theme, etc.)
- `memory.json` - Learned fixes (source text → wrapped text mappings, archetype assignments)
- `translation_memory.json` - Translation memory entries (synced to GitHub)
- `archetypes.json` - Character archetypes (synced to GitHub)
- `dd1_vocab.json` - DD1 vocabulary (synced to GitHub)
- `other_vocab.json` - Non-DD1 vocabulary (synced to GitHub)
- `anach_definitions.json` - Anachronism definitions (synced to GitHub)
- `archaic_examples.json` - Archaic word examples (synced to GitHub)
- `prefetch_cache.json` - Prefetch manager cache (per-language, not synced)
- `cache.json` - API response cache (per-language, not synced)
- `review_queues_cache.json` - Review queues (per-language, not synced)
- `review_items_cache.json` - Manual translation queue (per-language, not synced)

**Global Files:**
- `keys.json` - API keys (DeepL, OpenRouter) - stored in root directory

**Key Methods:**
```python
switch_language(new_language)  # Switch to different language config
load_all()                    # Load all configuration files
save_config()                 # Save main configuration
load_memory()                 # Load user memory
save_memory()                 # Save user memory
get_key(service)              # Retrieve API key
set_key(service, key)         # Set API key
load_cache()                  # Load API cache
save_cache()                  # Save API cache
load_archetypes()             # Load archetypes from file
save_archetypes()             # Save archetypes to file
load_vocab(file)             # Load vocabulary file
save_vocab(file, data)        # Save vocabulary file
```

### 3. GitHub Sync (`src/github_sync.py`)

**Responsibilities:**
- Synchronize per-language data with GitHub repository
- Push/pull translation data (status, logs, comments) per entry file
- Push/pull language-level files (archetypes, vocab, anach definitions, archaic examples, translation memory)
- Automatic merge of conflicts (timestamp-based, keeps both versions when same entry_id)
- Auto-sync on schedule if enabled

**Synced Files (Per-Language):**
- `formatter_config.json` - Main configuration (non-split keys only: triggers, styles, wall_preset, sync_language, pretranslate_settings, config_dir, deepl_target_lang, archetypes, entry_type_rules, replace_rules, ai_system_prompt, ai_button_prompts, substitution_rules)
- `tag_map.json` - Tag mappings (1,485 entries)
- `presets.json` - Character presets (7 presets)
- `speaker_data.json` - Speaker archetypes and notes
- `tag_display.json` - Tag display settings (1,402 entries)
- `preview_font.json` - Font preview settings
- `anach_definitions.json` - Anachronism definitions
- `archaic_examples.json` - Archaic word examples
- `translation_memory.json` - Translation memory entries (compressed with gzip)
- Entry data: status, logs, comments per source file

**NOT Synced (Local Only):**
- `memory.json` - User's learned fixes
- `user_settings.json` - User preferences (sync settings, paths, theme)
- `prefetch_cache.json` - Performance cache
- `api_response_cache.json` - API response cache
- `review_queues_cache.json` - Review queues (per-language)
- `manual_translation_queue.json` - Manual translation queue (per-language)
- `api_keys.json` - API keys (global)

**Key Methods:**
```python
sync_push(translation_manager)  # Push local data to GitHub (with merge)
sync_pull(translation_manager)  # Pull remote data from GitHub
is_configured()                  # Check if sync is configured
sync_auto_enabled()              # Check if auto-sync is enabled
_merge_translation_memory(local, remote)  # Merge TM entries
_merge_status_entries(local, remote)       # Merge status entries
_merge_logs(local, remote)                # Merge logs
```

**Merge Strategy:**
- **Translation Memory**: Combines all entries from local and remote, sorts by timestamp
- **Status Entries**: Merges entries by entry_id. If same entry_id exists in both, keeps both by appending timestamp to key (e.g., "abc123_2026-04-12T13:59:00")
- **Logs**: Deduplicates by log ID, keeps newer timestamp for duplicates
- **Split Config Files**: Each file synced independently to avoid duplication

**Hash-Based Entry IDs:**
- All translation entries and TM entries use hash-based entry IDs generated from source text
- SHA256 hash of normalized source text, first 16 characters
- Ensures all translations of the same source text have the same base entry_id
- Allows proper grouping and merge of multiple translations of the same string
- Generated in `translation_manager.generate_entry_id()` and used throughout the system

**Sync Structure on GitHub:**
```
<repo>/
└── <language>/
    ├── formatter_config.json  # Non-split config keys only
    ├── tag_map.json          # Tag mappings
    ├── presets.json          # Character presets
    ├── speaker_data.json     # Speaker archetypes & notes
    ├── tag_display.json      # Tag display settings
    ├── preview_font.json     # Font preview settings
    ├── anach_definitions.json # Anachronism definitions
    ├── archaic_examples.json  # Archaic word examples
    ├── translation_memory.json # Translation memory (compressed)
    └── <sanitized_filename>/  # Per source file
        ├── status.json        # Entry status data (with hash-based entry IDs)
        ├── logs.json          # Translation logs (comments embedded)
```

**Sync Timing:**
- Push (upload): Every 30 minutes (`PUSH_INTERVAL_DEFAULT = 1800s`)
- Pull (download): Every 30 minutes (`PULL_INTERVAL = 1800s`)
- Urgent push (after comments): 1 minute (`PUSH_INTERVAL_COMMENT = 60s`)

**Data Usage Optimization:**
- SHA-based change detection - only downloads files with changed hashes
- Per-file granularity - unchanged source files are completely skipped
- Entry-level timestamp comparison - only updates newer entries
- Log deduplication by ID+timestamp
- Translation memory compressed with gzip (~4x reduction)
- Large files fetched via direct download_url (binary, not base64)
- Dirty file tracking - only pushes modified files

### 4. API Handler (`src/api_handler.py`)

**Responsibilities:**
- Abstract external API calls
- Handle authentication
- Error handling and rate limiting
- API key sanitization

**Classes:**
- `DeepLClient` - DeepL translation API wrapper
- `OpenRouterClient` - OpenRouter AI chat API wrapper

**Features:**
- Automatic API endpoint selection based on key type (free vs pro)
- Rate limit detection
- Timeout handling
- Error message sanitization

### 5. Translation Engine (`src/translator_engine.py`)

**Responsibilities:**
- Text wrapping with tag awareness
- Simulated length calculation (tags count as configured lengths)
- Erroneous line break detection and removal
- Stub line balancing
- In-universe vocabulary replacement

**Key Methods:**
```python
get_simulated_len(text)           # Calculate length with tag simulation
strip_erroneous_breaks(text)      # Remove non-intentional line breaks
master_tag_wrap(text, limit)      # Main wrapping algorithm
apply_in_universe(text, replacements) # Apply archaic replacements
clean_and_wrap(text, limit)       # Clean and wrap text
```

**Algorithm:**
1. Strip erroneous line breaks (preserving intentional breaks after sentence-ending punctuation)
2. Wrap each intentional segment independently
3. Balance stub lines by pulling words from preceding lines (never across segment boundaries)

### 6. Lore Engine (`src/lore_engine.py`)

**Responsibilities:**
- Load and manage lore/glossary data from CSV files
- Scan text for lore terms
- Manage archetypes (character personality types)
- Provide in-universe vocabulary replacements
- Detect anachronisms (modern words that shouldn't exist in fantasy setting)

**Data Sources:**
- Bible CSV - Canonical term translations
- Glossary CSV - Additional term mappings with descriptions

**Key Methods:**
```python
load_data(bible_path, glossary_path) # Load lore data from CSV
scan_text(jp_text)                  # Scan for lore terms
get_archetype_options()             # Get available archetypes
get_in_universe_replacements()      # Get modern→archaic word map
```

**Archetypes:**
Character personality types that influence translation style (e.g., "Noble", "Peasant", "Scholar"). Each archetype has:
- Name
- Notes (translation guidelines)
- Associated vocabulary patterns

### 7. Gloss Engine (`src/gloss_engine.py`)

**Responsibilities:**
- Japanese morpheme tokenization using Janome
- Dictionary lookup using Jamdict
- Integration with lore map for project-specific terms
- Async tokenization with callback support

**Dependencies:**
- Janome - Japanese tokenization library
- Jamdict - Japanese-English dictionary (~50 MB, cached locally)

**Key Features:**
- Lazy loading (soft-fail if dependencies missing)
- Thread-safe for reads
- Lore map integration (project terms override dictionary)
- POS filtering (particles, aux verbs get empty candidates)

**Output:**
```python
GlossToken(
    surface,    # Exact text as it appears
    base,       # Dictionary/base form
    pos,        # Part of speech (noun/verb/adj/etc)
    candidates, # Translation glosses (up to MAX_CANDS)
    is_lore     # True if from project lore map
)
```

### 8. Translation Memory (`src/translation_memory.py`)

**Responsibilities:**
- Manage translation memory entries (source → translation mappings)
- Fuzzy matching for finding similar translations
- Cross-language TM sharing
- Auto-substitution based on TM matches
- TM management (export, import, statistics)

**Data Structure:**
```python
TM Entry:
{
    "id": str,                    # UUID
    "source": str,                # Source text (Japanese)
    "translation": str,           # Translation (English)
    "context": dict,              # Context metadata
    "quality": str,               # "approved" | "draft"
    "timestamp": str,            # ISO format timestamp
    "match_count": int,          # Usage statistics
    "last_used": str | None      # Last used timestamp
}
```

**Storage:**
- Per-language JSON file: `config/<lang>/translation_memory.json`
- Structure: `{"version": 2, "entries": [...], "stats": {...}}`
- Large files (>1000 entries) saved without indentation to prevent corruption

**Fuzzy Matching Algorithm:**
The `FuzzyMatcher` class uses multiple similarity metrics:
- **N-gram similarity** (Jaccard index on 3-grams) - character-level overlap
- **Word order similarity** (difflib.SequenceMatcher) - sequence matching
- **Levenshtein distance** - edit distance with lenient scoring
- **Punctuation similarity** - ignores punctuation and Japanese particles
- **Length similarity** - penalizes significant length differences
- **Tag similarity** - tag-aware matching for HTML/XML and placeholder tags

**Japanese Particle Handling:**
Common particles (の, を, に, が, へ, と, で) are removed during normalization for more lenient matching.

**Weights:**
- Levenshtein: 25%
- Word order: 30%
- Punctuation: 20%
- Length: 10%
- N-gram: 10%
- Tag: 5%

**Match Sorting:**
When multiple entries have the same similarity score, they are sorted by timestamp (newest first) to prioritize recent translations.

**Key Methods:**
```python
add_entry(entry)              # Add new TM entry
get_entry(entry_id)           # Retrieve entry by ID
delete_entry(entry_id)        # Delete entry
find_matches(query, entries, threshold)  # Find fuzzy matches
calculate_similarity(s1, s2)  # Calculate overall similarity score
export_tm(language)           # Export TM for specific language
import_tm(data, language)     # Import TM for specific language
get_statistics()              # Get TM statistics
```

**Cross-Language TM:**
The `CrossLanguageTM` class enables sharing translation memories between languages:
- Load TM from any language directory
- Merge entries from multiple languages
- Export merged TM to target language

### 9. Batch Runner (`src/batch_runner.py`)

**Responsibilities:**
- Background batch scanning of CSV files
- Multi-threaded execution
- Progress reporting via callbacks
- Queue population (tag, wall, dash, anach)

**Settings:**
```python
@dataclass
class BatchSettings:
    limit: int              # Character limit
    wall_limit: int         # Wall text limit
    triggers: List[str]     # Entry triggers
    do_in_universe: bool    # Apply in-universe replacements
    folders: List[str]      # Watched folders
    tag_map: Dict           # Tag → simulated length
    entry_type_rules: Dict  # Entry type → tag rules
    replace_rules: List     # Find/replace rules
    preview_mode: bool      # Preview mode flag
```

**Scan Process:**
1. Collect all CSV files from watched folders
2. For each file, read and process rows
3. Check entry triggers
4. Apply find/replace rules
5. Apply in-universe replacements (if enabled)
6. Check character limits (tag, wall, dash)
7. Scan for anachronisms
8. Populate queues with issues found
9. Report progress via callbacks

### 10. File Utilities (`src/file_utils.py`)

**Responsibilities:**
- CSV file discovery in directories
- CSV reading with delimiter sniffing
- Encoding handling (UTF-8-BOM)

**Key Functions:**
```python
_get_csv_files(folders)  # Recursively find all CSV files
_read_csv(path)         # Read CSV with delimiter detection
```

### 9. Web Frontend (`web/`)

#### HTML Structure (`index.html`)
- Single-page application with tab-based navigation
- Three main tabs: Dashboard, Review/Editor, Database Search
- Modal dialogs for settings and editing
- Inline tooltip for keyboard shortcuts

#### JavaScript Controller (`app.js`)
- State management (localStorage persistence)
- Tab switching logic
- Dashboard data loading
- Review/Editor queue management
- Search functionality
- Settings management
- AI chat integration
- Keyboard shortcuts
- Eel RPC calls to Python backend

**State Structure:**
```javascript
state = {
    currentTab: 'dashboard',
    reviewer: {
        currentIdx: 0,
        mode: 'review',  // 'review' | 'translate'
        fullQueue: null,
        showTranslated: false,
        anachRanges: [],
    },
    search: {
        results: [],
        sentToEditor: [],
    },
    standardLimit: 50,
    maxLines: 5,
}
```

#### Stylesheets (`style.css`)
- CSS custom properties for theming (dark/light mode)
- Flexbox-based layouts
- Responsive design
- Modal styling
- Panel toggle animations

### 10. Search Window (`search_window.py`)

**Responsibilities:**
- Tkinter-based global search interface
- Search across all CSV files in configured folders
- Field-specific search (translation, source, Speaker, Entry Type, Custom Index)
- Results display with double-click to edit

**Search Fields:**
- Translation (column 3)
- Source (column 2)
- Speaker (column 8)
- Entry Type (column 9)
- All Text Fields
- Field Index (custom column number)

### 11. Editor Window (`editor_window.py`)

**Responsibilities:**
- Tkinter-based translation/review editor
- Single-item and batch editing modes
- Tag highlighting and validation
- Character limit checking
- Integration with glossary and lore context
- AI chat integration

**Editor Modes:**
- **Review Mode**: Process items from queues (tag, wall, dash, anach)
- **Translate Mode**: Direct translation of selected rows

**Features:**
- Real-time character limit checking
- Tag syntax highlighting
- Glossary lookup on hover
- Lore context panel
- AI assistant panel
- Keyboard shortcuts

## Data Flow

### Batch Scan Flow

```
User clicks "Start Scan"
    ↓
Frontend calls eel.scan_csv()
    ↓
Python main.py spawns background thread
    ↓
batch_runner.run_batch() executes
    ↓
For each CSV file:
    - Read file (with caching)
    - For each row:
        - Check entry triggers
        - Apply find/replace rules
        - Apply in-universe replacements (if enabled)
        - Check character limits (tag, wall, dash)
        - Scan for anachronisms
        - Add to appropriate queue
    ↓
Progress callbacks update UI
    ↓
Done callback fires Review Editor
```

### Review/Editor Flow

```
User navigates to Review/Editor tab
    ↓
Frontend calls eel.get_review_queue()
    ↓
Python returns queued items
    ↓
User navigates items (keyboard or buttons)
    ↓
Frontend calls eel.get_item_at_idx(idx)
    ↓
Python returns item with context (gloss, lore)
    ↓
User edits translation
    ↓
Frontend calls eel.save_item()
    ↓
Python writes to CSV (with pending write batching)
    ↓
User can request AI assistance
    ↓
Frontend calls eel.ai_chat()
    ↓
Python calls OpenRouter API
    ↓
Response displayed in AI panel
```

### Translation Flow

```
User selects text and clicks "Translate"
    ↓
Frontend calls eel.translate_text(text)
    ↓
Python main.py calls DeepLClient.translate()
    ↓
DeepLClient makes HTTP request to DeepL API
    ↓
Response cached in cache.json
    ↓
Result returned to frontend
    ↓
Frontend updates translation field
```

### DeepL Batch Fetching Flow

```
Frontend loads entry and checks prefetch cache
    ↓
If cache missing deepl_suggestion or gloss_result:
    ↓
Frontend calls eel.fetch_deepl_batch(category, items, start_idx, count)
    ↓
Python main.py fetches DeepL translations for batch (current + next N entries)
    ↓
For each entry in batch:
    - Check cache.json for existing translation
    - If not cached, call DeepLClient.translate()
    - Store result in cache.json
    - Update prefetch_cache.json with deepl_suggestion
    ↓
Frontend polls prefetch cache for updated data
    ↓
When deepl_suggestion appears in cache, frontend populates UI
```

## Communication Patterns

### Python to JavaScript (Eel)

**Python side:**
```python
@eel.expose
def some_function(param):
    result = do_work(param)
    return result
```

**JavaScript side:**
```javascript
const result = await eel.some_function(param)();
```

### JavaScript to Python (Eel)

**JavaScript side:**
```javascript
eel.some_python_function(param)(result => {
    console.log(result);
});
```

**Python side:**
```python
@eel.expose
def some_python_function(param):
    return result
```

### Callback Pattern (Async Operations)

For long-running operations (batch scan, AI chat), Python uses callbacks:

```python
def run_batch(settings, ..., log_fn, progress_fn, done_fn):
    # Do work
    log_fn("Processing file...")
    progress_fn(50)
    # More work
    done_fn(limit, wall_limit)
```

JavaScript registers these callbacks:
```python
eel.run_batch(settings)(
    log => appendLog(log),
    pct => updateProgress(pct),
    (limit, wall_limit) => onDone(limit, wall_limit)
)
```

## Configuration Management

### Configuration Hierarchy

**Per-Language Configuration (config/<lang>/):**
```json
formatter_config.json (Main Config)
├── folders: []              # Watched directories
├── triggers: []             # Entry trigger strings
├── tag_map: {}              # Tag → simulated length
├── presets: {}              # Character limit presets
├── wall_presets: {}         # Wall limit presets
├── archetypes: {}           # Character archetypes (now separate file)
├── entry_type_rules: {}     # Entry type → tag rules
├── replace_rules: []        # Find/replace rules
├── ai_system_prompt: ""     # AI system prompt
├── ai_button_prompts: {}    # AI button prompts
└── ...

user_settings.json (User Preferences)
├── github_repo: ""          # GitHub repository URL for sync
├── github_token: ""         # GitHub personal access token
├── sync_nickname: ""       # GitHub commit nickname
├── sync_auto: false         # Auto-sync enabled
├── bible_path: ""          # Bible CSV path (per-language)
├── glossary_path: ""       # Glossary CSV path (per-language)
├── assets_path: ""         # Assets directory path
├── theme_mode: "dark"      # Theme preference
├── dark_mode: true          # Dark mode enabled
├── in_universe: true        # In-universe language enabled
├── openrouter_models: []   # Available AI models
├── selected_openrouter_model: "" # Selected AI model
├── preview_mode: true       # Preview mode enabled
├── show_paid_models: false # Show paid AI models
├── selected_preset: ""     # Selected limit preset
├── custom_dark_theme: {}   # Custom dark theme colors
├── custom_light_theme: {}  # Custom light theme colors
└── last_stats: {}          # Last calculated statistics

memory.json (User Memory)
├── [source text]: [wrapped text]  # Learned fixes from manual edits
├── [speaker]: [archetype]         # Archetype assignments
└── ...

archetypes.json (Character Archetypes - Synced to GitHub)
├── [key]: {
│   ├── name: ""              # Display name
│   ├── professions: []       # Associated professions
│   └── notes: ""             # Translation guidelines
│   }
└── ...

dd1_vocab.json (DD1 Vocabulary - Synced to GitHub)
├── [modern_word]: [archaic_word]  # Modern → archaic word mappings
└── ...

other_vocab.json (Non-DD1 Vocabulary - Synced to GitHub)
├── [modern_word]: [archaic_word]  # Modern → archaic word mappings
└── ...

anach_definitions.json (Anachronism Definitions - Synced to GitHub)
├── dd1_definitions: {}      # DD1-sourced definitions
└── other_definitions: {}    # Other-sourced definitions

archaic_examples.json (Archaic Word Examples - Synced to GitHub)
├── dd1_examples: {}         # DD1-sourced examples
└── other_examples: {}       # Other-sourced examples

prefetch_cache.json (Prefetch Cache - Local Only)
├── [category::idx]: {
│   ├── timestamp: 0          # Cache timestamp
│   ├── lore_context: {}     # Lore context results
│   ├── anachronisms: []     # Anachronism scan results
│   ├── adjacent_context: {} # Adjacent context results
│   ├── gloss_result: []     # Glossary lookup results
│   ├── tm_matches: []       # Translation memory matches
│   └── deepl_suggestion: str # DeepL translation (populated by fetch_deepl_batch)
│   }
└── ...

cache.json (API Cache - Local Only)
├── translation_cache: {}     # DeepL translation cache
└── ai_chat_cache: {}        # OpenRouter AI chat cache

review_queues_cache.json (Review Queues - Local Only, Per-Language)
├── tag: []                  # Tag-related issues queue
├── wall: []                 # Wall limit violations queue
├── dash: []                 # Dash issues queue
└── anach: []                # Anachronisms queue

review_items_cache.json (Manual Translation Queue - Local Only, Per-Language)
└── []                       # Manual translation items

**Global Configuration (root directory):**
```json
keys.json (API Keys)
├── deepl_api_key: ""
└── openrouter_api_key: ""
```

### Configuration Loading Order

1. `keys.json` loaded on startup (global)
2. `config/<language>/formatter_config.json` loaded on startup
3. Default archetypes seeded from `lore_data.py` if missing
4. `config/<language>/memory.json` loaded for user preferences
5. `config/<language>/user_settings.json` loaded for user settings
6. `config/<language>/translation_memory.json` loaded for translation memory
7. `config/<language>/cache.json` loaded for API responses
8. Language-specific vocab files loaded (dd1_vocab.json, other_vocab.json)
9. Language-specific lore files loaded (archetypes.json, anach_definitions.json, archaic_examples.json)

### Language Switching

When switching languages (e.g., from English to Arabic):
1. `config_manager.switch_language(new_language)` is called
2. Configuration directory changes to `config/<new_language>/`
3. All language-specific files are reloaded:
   - formatter_config.json
   - memory.json
   - user_settings.json
   - translation_memory.json
   - archetypes.json
   - dd1_vocab.json
   - other_vocab.json
   - anach_definitions.json
   - archaic_examples.json
   - prefetch_cache.json
   - cache.json
   - review_queues_cache.json
   - review_items_cache.json
4. Lore engine is invalidated (vocabulary changed)
5. Translation memory is reloaded for the new language
6. Frontend is notified to reload settings and refresh UI
7. GitHub sync operations automatically use the new language folder

## External Dependencies

### Required Python Packages

```
eel>=0.16.0          # Python-JavaScript IPC
requests>=2.31.0    # HTTP client for API calls
msgpack>=1.0.0      # Message serialization
```

### Optional Python Packages

```
jamdict>=1.0.0       # Japanese-English dictionary (for gloss engine)
janome               # Japanese tokenization (for gloss engine)
```

### External APIs

**DeepL API**
- Purpose: Machine translation (Japanese to English)
- Endpoints:
  - Free: `https://api-free.deepl.com/v2/translate`
  - Pro: `https://api.deepl.com/v2/translate`
- Authentication: API key in header

**OpenRouter API**
- Purpose: AI chat assistance
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Authentication: Bearer token in header
- Models: Configurable (default: `openrouter/auto`)

### Frontend Dependencies

**Google Fonts**
- Inter (UI font)
- Material Symbols Outlined (icons)

**Eel Bridge**
- Python-JavaScript IPC handled by Eel framework
- No separate eel.js file in web directory

## Threading Model

### Main Thread
- Eel event loop
- UI rendering (web frontend)
- Eel route execution

### Background Threads
- Batch scanning (batch_runner.py)
- AI chat requests (api_handler.py)
- Glossary lookup (gloss_engine.py - async mode)

### Thread Safety
- CSV cache protected by `_csv_cache_lock`
- Lore engine protected by `_lore_engine_lock`
- Gloss engine protected by `_gloss_engine_lock`
- Gloss cache protected by `_gloss_cache_lock`
- Lore context cache protected by `_lore_context_cache_lock`
- Prefetch manager protected by `_lock`
- Gloss engine internal state protected by `_lock`
- Config manager not thread-safe (assumed single-threaded access)

## Caching Strategy

### CSV Read Cache
- Key: File path
- Value: (raw_text, dialect, rows) with timestamp
- Lifetime: Until manual clear or application restart
- Invalidation: Automatic based on file modification time (skips files written by app)

### API Response Cache
- Key: Request signature (text, target_lang, source_lang for DeepL; messages, model for OpenRouter)
- Value: API response with timestamp
- Lifetime: 7 days (604800 seconds)
- Invalidation: Automatic TTL-based expiration on access

### Gloss Cache (In-Memory)
- Key: Japanese text
- Value: Glossary lookup results
- Lifetime: Until manual clear or application restart
- Invalidation: Automatic when glossary files (bible.csv, glossary.csv) are modified externally; manual via `clear_gloss_cache()`
- Note: Cleared when lore_map updates to ensure gloss window shows current lore context

### Lore Context Cache (In-Memory)
- Key: Japanese text
- Value: Lore context lookup results
- Lifetime: Until application restart
- Invalidation: Automatic based on file modification time (bible/glossary files)
- Note: Lore data is static; only changes when adding/modifying lore entries

### Prefetch Cache
- Key: Category + index
- Value: Cached results with timestamp
- Lifetime: 7 days (604800 seconds)
- Purpose: Pre-load commonly accessed items (local-only operations)
- Invalidation: Automatic TTL-based expiration on load
- **Cached Data:**
  - `lore_context`: Lore context scan results
  - `anachronisms`: Anachronism detection results
  - `adjacent_context`: Adjacent lines from source file
  - `gloss_result`: Glossary lookup results
  - `tm_matches`: Translation memory fuzzy matches
  - `deepl_suggestion`: DeepL translation (populated by `fetch_deepl_batch`)
- **Note:** DeepL suggestions are populated by the separate `fetch_deepl_batch()` function, not by PrefetchManager

### Review Queue
- Lifetime: Until manual clear or application restart
- Invalidation: Manual via `clear_queue()`

### Log
- Lifetime: Until manual clear or application restart
- Invalidation: Manual via `clear_log()`

## Error Handling

### API Errors
- DeepL: Rate limiting (429), authentication (403), network errors
- OpenRouter: Authentication (401/403), model not found (404), rate limiting (429)
- Handled via try/except with user-friendly error messages

### File I/O Errors
- Missing files: Graceful skip with warning
- Encoding errors: UTF-8-BOM handling
- CSV parsing errors: Fallback to excel dialect

### Missing Dependencies
- Janome/Jamdict: Soft-fail, gloss engine reports unavailable
- API keys: Validation on use, user prompted to configure

## Security Considerations

### API Keys
- Stored in separate `keys.json` file
- Not committed to version control (in .gitignore)
- Sanitized to remove non-ASCII characters
- Never logged or displayed in full

### File Access
- Only accesses files in configured folders
- No arbitrary file system access
- CSV files assumed trusted (no sandbox)

### External API Calls
- All API calls go through configured handlers
- No direct user-supplied URLs
- Timeout configured to prevent hanging

## Performance Optimization

### Lazy Initialization
- LoreEngine and GlossEngine initialized on first use
- Jamdict data downloaded on first use (~50 MB)
- CSV files read only when accessed

### Caching
- CSV read cache prevents repeated file I/O
- API response cache prevents redundant API calls
- Prefetch cache pre-loads commonly accessed items

### Batching
- CSV writes batched to reduce file I/O
- Batch scanning processes all files in one pass
- Queue-based processing for review items

### Async Operations
- Batch scanning in background thread
- AI chat requests async
- Glossary lookup async option

## Known Limitations

1. **Concurrent Access**: No support for multiple simultaneous users

## Future Architecture Considerations

1. **Database Backend**: Consider SQLite for better query performance
2. **Plugin System**: Allow custom analyzers and formatters
3. **Real-time Collaboration**: WebSocket support for multi-user editing
4. **Docker Deployment**: Containerize for easier deployment
