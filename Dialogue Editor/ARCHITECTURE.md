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
┌─────────────────────────────────────────────────────────────┐
│                    Web Frontend (Browser)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ HTML UI  │  │   CSS    │  │   JS     │  │  Eel.js  │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │ Eel IPC
                           │ (WebSocket/HTTP)
┌──────────────────────────┴──────────────────────────────────┐
│                    Python Backend                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              main.py (Entry Point)                    │  │
│  │  - Eel initialization                                 │  │
│  │  - Route definitions (@eel.expose)                   │  │
│  │  - Global state management                           │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Config   │  │  API     │  │  Lore    │  │  Gloss   │  │
│  │ Manager  │  │ Handler  │  │ Engine   │  │  Engine  │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Trans    │  │  Batch   │  │  File    │  │  Search  │  │
│  │ Engine   │  │  Runner  │  │  Utils   │  │  Window  │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ File I/O
                           ▼
                    ┌──────────────┐
                    │  CSV Files   │
                    │  Glossary    │
                    │  Bible       │
                    │  Config JSON │
                    └──────────────┘
```

## Directory Structure

```
Dialogue Editor/
├── main.py                 # Application entry point, Eel routes, global state
├── config_manager.py       # Configuration management (JSON files)
├── api_handler.py          # External API clients (DeepL, OpenRouter)
├── translator_engine.py   # Text wrapping and translation processing
├── lore_engine.py          # Lore/context system, archetypes, in-universe vocab
├── gloss_engine.py        # Japanese morpheme glossing (Janome + Jamdict)
├── lore_data.py           # Default archetypes, vocabulary, anachronism patterns
├── file_utils.py          # CSV file reading utilities
├── batch_runner.py        # Batch scanning logic (background thread)
├── search_window.py       # Tkinter-based search window
├── editor_window.py       # Tkinter-based editor window
├── editor_mixin.py        # Editor functionality shared across windows
├── options_module.py      # Settings/configuration UI
├── prefetch_manager.py    # API result caching
├── check_keys.py          # API key validation utility
├── count_chars.py         # Character counting utility
├── extract_items.py       # Item extraction utility
├── formatter_config.json   # Main configuration file
├── memory.json            # User preferences and memory
├── keys.json              # API keys (separate for security)
├── cache.json             # API response cache
├── anach_definitions.json # Anachronism definitions
├── archaic_examples.json  # Archaic word examples
├── prefetch_cache.json    # Prefetch manager cache
├── requirements.txt        # Python dependencies
├── web/                   # Frontend web interface
│   ├── index.html         # Main HTML structure
│   ├── style.css          # Stylesheets
│   ├── app.js             # Frontend JavaScript controller
│   └── js/
│       └── app.js         # Additional JavaScript (legacy/duplicate)
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
- `get_dashboard_data()` - Dashboard statistics
- `calculate_project_stats()` - Calculate project-wide statistics
- `get_full_config()` - Complete configuration
- `save_config()` - Persist configuration changes
- `save_config_field()` - Save single config field
- `scan_csv()` - Trigger batch scan
- `get_item_at_idx()` - Retrieve specific item
- `save_item()` - Persist item changes
- `translate_text()` - DeepL translation
- `ai_chat()` - OpenRouter AI chat
- `get_gloss()` - Glossary lookup
- `get_lore_context()` - Lore context lookup
- `perform_search()` - Database search
- `bulk_inject()` - Inject search results into review queue
- `get_theme_colors()` - Get current theme colors
- `toggle_dark_mode()` - Toggle dark/light theme
- `get_archetypes_list()` - Get available archetypes
- `get_speaker_archetype()` - Get archetype for speaker
- `get_speaker_note()` - Get note for speaker
- `get_speakers_list()` - Get list of speakers
- `get_entry_types_list()` - Get list of entry types
- `get_simulated_len()` - Calculate text length with tags
- `get_standard_limit()` - Get standard character limit
- `get_wall_limit()` - Get wall text limit
- `get_all_presets()` - Get all limit presets
- `get_preview_profiles()` - Get preview profiles
- `update_config_dict()` - Update dictionary config values
- `update_config_list()` - Update list config values
- `update_map_setting()` - Update map/dict config setting
- `delete_map_setting()` - Delete map/dict config setting
- `add_list_item()` - Add item to list config
- `remove_list_item()` - Remove item from list config
- `update_list_item()` - Update item in list config
- `save_replace_rule()` - Save single replace rule
- `save_replace_rules()` - Save all replace rules
- `save_archetype()` - Save archetype metadata
- `save_archetype_data()` - Save archetype data
- `delete_archetype()` - Delete archetype
- `reset_archetypes_to_defaults()` - Reset archetypes to defaults
- `reload_archetypes_from_file()` - Reload archetypes from file
- `save_speaker_archetype()` - Save speaker archetype assignment
- `pick_directory()` - Open directory picker dialog
- `pick_file()` - Open file picker dialog
- `add_folder()` - Add folder to watched folders
- `remove_folder()` - Remove folder from watched folders
- `add_trigger()` - Add entry trigger
- `remove_trigger()` - Remove entry trigger
- `refresh_ui()` - Refresh UI state
- `notify_active_editors()` - Notify active editor windows
- `register_editor()` - Register editor window
- `unregister_editor()` - Unregister editor window
- `clear_log()` - Clear log messages
- `add_log_message()` - Add message to log
- `open_search_window()` - Open Tkinter search window
- `open_options_window()` - Open Tkinter options window
- `save_entry_type_to_csv()` - Save entry type to CSV
- `test_deepl()` - Test DeepL API key
- `test_openrouter()` - Test OpenRouter API key
- `fetch_models()` - Fetch available AI models
- `test_regex()` - Test regex pattern
- `rewrap_text()` - Re-wrap text with current limits
- `save_preview_profile()` - Save preview profile
- `add_preview_type()` - Add preview type to profile
- `remove_preview_type()` - Remove preview type from profile
- `generate_preview_image()` - Generate preview image
- `scan_anachronisms()` - Scan text for anachronisms
- `get_definition()` - Get anachronism definition
- `prefetch_definitions()` - Prefetch anachronism definitions
- `get_adjacent_context()` - Get adjacent context for item
- `get_archetype_options()` - Get archetype options
- `get_archetype_notes()` - Get archetype notes
- `start_batch_scan()` - Start batch scan with preset
- `is_batch_scan_complete()` - Check if batch scan complete
- `get_queue_structure()` - Get review queue structure
- `get_items_for_category()` - Get items for category
- `get_all_items_in_queue()` - Get all items in review queue
- `get_next_review_item()` - Get next review item
- `get_deepl_suggestion()` - Get DeepL translation suggestion
- `send_ai_chat()` - Send AI chat message
- `flush_csv_writes()` - Flush pending CSV writes
- `apply_fix()` - Apply fix to item
- `load_csv_for_translation()` - Load CSV for translation
- `start_prefetch()` - Start prefetch operation
- `get_prefetch_cache()` - Get prefetch cache entry
- `clear_prefetch_cache()` - Clear prefetch cache
- `clear_gloss_cache()` - Clear gloss cache
- `clear_queue()` - Clear review queue

### 2. Configuration Management (`config_manager.py`)

**Responsibilities:**
- Load/save configuration from JSON files
- Manage API keys (separate file for security)
- Manage user memory/preferences
- Manage API response cache
- Seed default archetypes from lore_data

**Configuration Files:**
- `formatter_config.json` - Main configuration (folders, triggers, tag maps, presets)
- `memory.json` - Learned fixes (source text → wrapped text mappings, archetype assignments)
- `keys.json` - API keys (DeepL, OpenRouter)
- `cache.json` - API response cache

**Key Methods:**
```python
load_all()           # Load all configuration files
save_config()        # Save main configuration
load_memory()        # Load user memory
save_memory()        # Save user memory
get_key(service)     # Retrieve API key
set_key(service, key) # Set API key
load_cache()         # Load API cache
save_cache()         # Save API cache
```

### 3. API Handler (`api_handler.py`)

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

### 4. Translation Engine (`translator_engine.py`)

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

### 5. Lore Engine (`lore_engine.py`)

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

### 6. Gloss Engine (`gloss_engine.py`)

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

### 7. Batch Runner (`batch_runner.py`)

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

### 8. File Utilities (`file_utils.py`)

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

```
formatter_config.json (Main Config)
├── folders: []              # Watched directories
├── triggers: []             # Entry trigger strings
├── tag_map: {}              # Tag → simulated length
├── presets: {}              # Character limit presets
├── wall_presets: {}         # Wall limit presets
├── archetypes: {}           # Character archetypes
├── entry_type_rules: {}     # Entry type → tag rules
├── replace_rules: []        # Find/replace rules
├── ai_system_prompt: ""     # AI system prompt
├── ai_button_prompts: {}    # AI button prompts
└── ...

memory.json (User Memory)
├── [source text]: [wrapped text]  # Learned fixes from manual edits
├── [speaker]: [archetype]         # Archetype assignments
└── ...

keys.json (API Keys)
├── deepl_api_key: ""
└── openrouter_api_key: ""

cache.json (API Cache)
├── translation_cache: {}
└── ai_chat_cache: {}
```

### Configuration Loading Order

1. `formatter_config.json` loaded on startup
2. Default archetypes seeded from `lore_data.py` if missing
3. `memory.json` loaded for user preferences
4. `keys.json` loaded for API keys
5. `cache.json` loaded for API responses

## External Dependencies

### Required Python Packages

```
eel>=0.16.0          # Python-JavaScript IPC
requests>=2.31.0    # HTTP client for API calls
jamdict>=1.0.0       # Japanese-English dictionary
```

### Optional Python Packages

```
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
- Purpose: Pre-load commonly accessed items
- Invalidation: Automatic TTL-based expiration on load

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
