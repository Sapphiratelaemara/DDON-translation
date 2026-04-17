"""
gloss_engine.py — Japanese morpheme glossing via Janome + jamdict.

Each call to GlossEngine.gloss(text) tokenises the input and returns a list of
GlossToken namedtuples.  The engine is designed to be:
  • Lazy-loaded (imports only happen on first use, so a missing library is a
    soft failure rather than a hard crash at startup).
  • Thread-safe for reads (jamdict is read-only after initialisation).
  • Integrated with LoreEngine: if a lore_map is supplied the engine checks it
    first and annotates matching spans with their canonical translation instead
    of hitting JMdict.

Public surface
--------------
    GLOSS_AVAILABLE : bool
        True if both janome and jamdict are importable.

    GlossToken(surface, base, pos, candidates, is_lore)
        surface    : str  — the exact text as it appears in the source
        base       : str  — dictionary / base form from the tokeniser
        pos        : str  — broad POS tag (noun / verb / adj / particle / …)
        candidates : list[str]  — up to MAX_CANDS English glosses, best first
        is_lore    : bool — True if the match came from the project lore map

    GlossEngine(lore_map=None)
        .gloss(text) -> list[GlossToken]
            Tokenise *text* and look up candidates for each morpheme.
            Returns an empty list on any failure.
        .gloss_async(text, callback)
            Run .gloss() in a daemon thread; call callback(tokens) on the main
            thread via the supplied after-scheduler (see note below).
            Because Tk's after() is not accessible here, the caller is
            responsible for routing the callback to the main thread.

Notes
-----
• jamdict downloads JMdict (~50 MB) on first use into its default cache
  directory (~/.jamdict/).  Subsequent calls are instant.
• POS filtering: particles (助詞), auxiliary verbs (助動詞), punctuation (記号),
  and whitespace-only tokens are kept in the output but get empty candidates so
  the UI can still render them as non-interactive spacers.
"""

from __future__ import annotations
import os
import threading
import re
from typing import Callable, List, NamedTuple, Optional, Dict

# ---------------------------------------------------------------------------
# Point jamdict at the project-local data folder (portable, self-contained).
# Must be set BEFORE importing jamdict so it picks up the correct DB path.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Look for jamdict data in parent project directory
_PARENT_DIR = os.path.dirname(_THIS_DIR)
_LOCAL_JAMDICT_HOME = os.path.join(_PARENT_DIR, "deps", "jamdict_data")
if os.path.isdir(_LOCAL_JAMDICT_HOME):
    os.environ.setdefault("JAMDICT_HOME", _LOCAL_JAMDICT_HOME)
    print(f"[GlossEngine] Using local jamdict data: {_LOCAL_JAMDICT_HOME}")

# ---------------------------------------------------------------------------
# Availability guard — soft-fail if deps are missing
# ---------------------------------------------------------------------------
_janome_import_error = None
_jamdict_import_error = None

try:
    from janome.tokenizer import Tokenizer as _JanomeTokenizer
    _janome_ok = True
except ImportError as e:
    _janome_ok = False
    _janome_import_error = str(e)
    print(f"[GlossEngine] Janome import failed: {e}")

try:
    from jamdict import Jamdict as _Jamdict
    _jamdict_ok = True
except ImportError as e:
    _jamdict_ok = False
    _jamdict_import_error = str(e)
    print(f"[GlossEngine] Jamdict import failed: {e}")

GLOSS_AVAILABLE: bool = _janome_ok and _jamdict_ok
if not GLOSS_AVAILABLE:
    print(f"[GlossEngine] GLOSS_AVAILABLE=False (janome_ok={_janome_ok}, jamdict_ok={_jamdict_ok})")

# ---------------------------------------------------------------------------
# POS mapping  (Janome returns comma-separated feature strings in JP)
# ---------------------------------------------------------------------------
_POS_MAP = {
    "名詞":   "noun",
    "動詞":   "verb",
    "形容詞": "adj",
    "形容動詞": "adj",
    "副詞":   "adv",
    "接続詞": "conj",
    "感動詞": "interj",
    "助詞":   "particle",
    "助動詞": "aux",
    "記号":   "symbol",
    "接頭詞": "prefix",
    "接尾辞": "suffix",
}

# POS tags for which we skip JMdict lookup (no useful gloss)
_SKIP_POS = {"particle", "aux", "symbol"}

MAX_CANDS = 4  # maximum candidates shown per token


# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------

class GlossToken(NamedTuple):
    surface:    str
    base:       str
    pos:        str        # broad English POS label
    candidates: List[str]  # English glosses, best first
    is_lore:    bool       # came from project lore map

# Pattern for splitting multi-suggestion lore/glossary entries
LORE_SPLIT_PATTERN = re.compile(r'\s*[,;\|\n/]\s*')

# Patterns to skip when parsing multi-suggestion entries (headers like "less common:")
_LORE_SKIP_HEADERS = re.compile(r'^(less|lesser|lesson)\s+common:?$', re.I)



# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class GlossEngine:
    """
    Lazy-initialised gloss engine.  Safe to construct even when deps are absent;
    .gloss() will return [] and log a warning in that case.
    """

    _tok  = None   # shared Janome tokeniser (thread-safe for reads)
    _jmd  = None   # shared Jamdict instance
    _lock = threading.Lock()

    def __init__(self, lore_map: Optional[Dict[str, str]] = None):
        """
        lore_map : {japanese_term: english_term} — project lore dictionary.
                   When a token surface or base form matches a key here, the
                   lore value is used as the sole candidate and is_lore=True.
        """
        self.lore_map: Dict[str, str] = dict(lore_map) if lore_map else {}

    def update_lore_map(self, lore_map: Optional[Dict[str, str]]):
        """Update the internal lore map (e.g. after a glossary reload)."""
        with self._lock:
            self.lore_map = dict(lore_map) if lore_map else {}

    # ------------------------------------------------------------------
    # Lazy init
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_ready(cls) -> bool:
        if not GLOSS_AVAILABLE:
            return False
        if cls._tok is not None and cls._jmd is not None:
            return True
        with cls._lock:
            if cls._tok is None:
                try:
                    cls._tok = _JanomeTokenizer()
                except Exception as e:
                    print(f"[GlossEngine] Janome init failed: {e}")
                    return False
            if cls._jmd is None:
                try:
                    cls._jmd = _Jamdict(reuse_ctx=False)
                except Exception as e:
                    print(f"[GlossEngine] Jamdict init failed: {e}")
                    return False
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def gloss(self, text: str) -> List[GlossToken]:
        """Tokenise *text* and return a GlossToken list.  Never raises."""
        if not text or not text.strip():
            return []
        if not self._ensure_ready():
            return []
        try:
            return self._do_gloss(text)
        except Exception as e:
            print(f"[GlossEngine] gloss() error: {e}")
            return []

    def gloss_async(self, text: str, callback: Callable[[List[GlossToken]], None]) -> None:
        """Run gloss() in a daemon thread.
        *callback* is called with the token list from the worker thread —
        the caller must marshal it to the main thread via root.after(0, ...) if
        it touches Tk widgets.
        """
        def _run():
            tokens = self.gloss(text)
            callback(tokens)
        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_gloss(self, text: str) -> List[GlossToken]:
        tokens: List[GlossToken] = []

        # 1. Find lore spans greedily (longest match first)
        spans = []  # List of (start, end, translation)
        if self.lore_map:
            # Sort keys by length descending so we find "覚者様" before "覚者"
            sorted_keys = sorted(self.lore_map.keys(), key=len, reverse=True)
            occupied = [False] * len(text)
            for key in sorted_keys:
                if not key: continue
                idx = 0
                while True:
                    idx = text.find(key, idx)
                    if idx == -1: break
                    end_idx = idx + len(key)
                    # Use this match if no part of its span is already taken by a longer match
                    if not any(occupied[idx:end_idx]):
                        trans = self.lore_map[key]
                        if trans and trans.strip():
                            spans.append((idx, end_idx, trans))
                            for i in range(idx, end_idx):
                                occupied[i] = True
                    idx = end_idx
            spans.sort()  # Sort by appearance in string

        # 2. Tokenise and merge
        offset = 0
        span_idx = 0
        for tok in self._tok.tokenize(text):
            surface = tok.surface
            # Janome tokens are contiguous; find the exact start/end in source text
            t_start = text.find(surface, offset)
            if t_start == -1: # fallback (shouldn't happen with Janome)
                t_start = offset
            t_end = t_start + len(surface)
            offset = t_end

            # Check if this token is covered by a lore span
            matched_span = None
            while span_idx < len(spans):
                s_start, s_end, s_trans = spans[span_idx]
                if t_start >= s_end:
                    span_idx += 1  # moving past this span
                    continue
                if t_end > s_start and t_start < s_end:
                    # Overlap found
                    matched_span = spans[span_idx]
                break

            if matched_span:
                s_start, s_end, s_trans = matched_span
                # Only the token at the START of the lore span emits the lore GlossToken
                if t_start == s_start:
                    span_text = text[s_start:s_end]
                    # Only set is_lore=True if the token surface exactly matches the lore key
                    # Find which key created this span
                    is_exact_match = False
                    matched_key = None
                    for key in sorted(self.lore_map.keys(), key=len, reverse=True):
                        if text.find(key, s_start) == s_start and len(key) == len(span_text):
                            is_exact_match = True
                            matched_key = key
                            break
                    
                    if matched_key and span_text != matched_key:
                        print(f"[GlossEngine] span_text='{span_text}' matched_key='{matched_key}' is_exact={is_exact_match}")
                    
                    raw_pos = tok.part_of_speech.split(",")[0]
                    pos     = _POS_MAP.get(raw_pos, "other")
                    
                    # Split multi-suggestion strings into individual candidates
                    cands = LORE_SPLIT_PATTERN.split(s_trans)
                    cands = [c.strip() for c in cands if c.strip() and not _LORE_SKIP_HEADERS.match(c.strip())]
                    
                    tokens.append(GlossToken(span_text, span_text, pos, cands, is_exact_match))
                # Skip standard processing for all tokens within the span
                continue

            # Standard token processing
            base    = tok.base_form if tok.base_form and tok.base_form != "*" else surface
            raw_pos = tok.part_of_speech.split(",")[0]
            pos     = _POS_MAP.get(raw_pos, "other")

            # Skip functional words
            if pos in _SKIP_POS or not surface.strip():
                tokens.append(GlossToken(surface, base, pos, [], False))
                continue

            # Check lore_map first for this token, prioritize lore candidates
            lore_cands = []
            is_lore = False
            if self.lore_map:
                # Only check surface form for exact match - base form match doesn't count for star
                lore_match = self.lore_map.get(surface)
                if lore_match:
                    lore_cands = LORE_SPLIT_PATTERN.split(lore_match)
                    lore_cands = [c.strip() for c in lore_cands if c.strip() and not _LORE_SKIP_HEADERS.match(c.strip())]
                    is_lore = True
                # Still use base form for dictionary lookup, but don't set is_lore
                base_match = self.lore_map.get(base)
                if base_match and not lore_match:
                    lore_cands = LORE_SPLIT_PATTERN.split(base_match)
                    lore_cands = [c.strip() for c in lore_cands if c.strip() and not _LORE_SKIP_HEADERS.match(c.strip())]
            
            # Get dictionary candidates
            dict_cands = self._lookup(base) or self._lookup(surface)
            
            # Combine: lore candidates first, then dictionary candidates
            candidates = lore_cands + [c for c in dict_cands if c not in lore_cands]
            tokens.append(GlossToken(surface, base, pos, candidates, is_lore))

        return tokens

    def _lookup(self, word: str) -> List[str]:
        """Return up to MAX_CANDS short English glosses from JMdict."""
        if not word:
            return []
        try:
            result = self._jmd.lookup(word)
            cands: List[str] = []
            for entry in result.entries:
                for sense in entry.senses:
                    for gloss in sense.gloss:
                        g = str(gloss).strip()
                        if g and g not in cands:
                            cands.append(g)
                        if len(cands) >= MAX_CANDS:
                            return cands
            return cands
        except Exception:
            return []
