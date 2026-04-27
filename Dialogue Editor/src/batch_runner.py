"""
batch_runner.py — CSV batch scanning logic, decoupled from the UI.

The public surface is:
    BatchSettings  — plain dataclass carrying all scan parameters
    run_batch()    — called from a background thread by CSVProcessorApp.start_thread()

All UI interaction happens through three callbacks supplied by the caller:
    log_fn(msg)              — append a line to the scan log
    progress_fn(pct)         — update the progress bar (0–100)
    done_fn(limit, wall_limit) — called once when the scan finishes (fires ReviewEditor)

The caller is responsible for routing these callbacks through root.after() so
they execute on the Tk main thread.
"""

import csv
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from src.lore_engine import LoreEngine
from src.file_utils import _read_csv


# ---------------------------------------------------------------------------
# Settings bundle
# ---------------------------------------------------------------------------

@dataclass
class BatchSettings:
    limit:            int
    wall_limit:       int
    triggers:         List[str]
    do_in_universe:   bool
    folders:          List[str]
    tag_map:          Dict
    entry_type_rules: Dict
    replace_rules:    List
    preview_mode:     bool
    checkpoint_file:  str = None


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _get_settings_hash(settings: BatchSettings) -> str:
    """Generate hash of settings to detect parameter changes."""
    import hashlib
    settings_str = f"{settings.limit}_{settings.wall_limit}_{settings.triggers}_{settings.do_in_universe}_{settings.folders}_{settings.preview_mode}"
    return hashlib.md5(settings_str.encode()).hexdigest()

def _save_checkpoint(checkpoint_file: str, processed_files: List[str], current_index: int, settings_hash: str, auto_fixed: int):
    """Save checkpoint state to file."""
    try:
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump({
                "processed_files": processed_files,
                "current_index": current_index,
                "settings_hash": settings_hash,
                "auto_fixed": auto_fixed
            }, f, indent=4)
    except Exception as e:
        print(f"Error saving checkpoint: {e}")

def _load_checkpoint(checkpoint_file: str) -> dict:
    """Load checkpoint state from file."""
    try:
        if os.path.exists(checkpoint_file):
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading checkpoint: {e}")
    return None

def _delete_checkpoint(checkpoint_file: str):
    """Delete checkpoint file."""
    try:
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)
    except Exception as e:
        print(f"Error deleting checkpoint: {e}")

# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def run_batch(
    settings:    BatchSettings,
    cm,                          # ConfigManager — for memory read and bible paths
    engine,                      # TranslationEngine
    queues:      Dict,           # {'tag': defaultdict, 'wall': ..., 'dash': ..., 'anach': ...}
    log_fn:      Callable,
    progress_fn: Callable,
    done_fn:     Callable,
):
    tag_q   = queues["tag"]
    wall_q  = queues["wall"]
    dash_q  = queues["dash"]
    anach_q = queues["anach"]

    # Checkpoint state
    processed_files = []
    current_index = 0
    settings_hash = _get_settings_hash(settings) if settings.checkpoint_file else None
    auto_fixed = 0

    # Load checkpoint if exists
    if settings.checkpoint_file:
        checkpoint = _load_checkpoint(settings.checkpoint_file)
        if checkpoint:
            # Check if settings match
            if checkpoint.get("settings_hash") == settings_hash:
                processed_files = checkpoint.get("processed_files", [])
                current_index = checkpoint.get("current_index", 0)
                auto_fixed = checkpoint.get("auto_fixed", 0)
                log_fn(f"Resuming from checkpoint: {len(processed_files)} files already processed, {auto_fixed} auto-fixed")
            else:
                log_fn("Checkpoint found but settings changed, starting fresh")
                _delete_checkpoint(settings.checkpoint_file)

    # Build lore engine for this scan session
    lore_engine = LoreEngine(cm.config.get("archetypes"))
    lore_engine.load_data(
        cm.config.get("bible_path", ""),
        cm.config.get("glossary_path", ""),
    )
    in_universe_replacements = (
        lore_engine.get_in_universe_replacements() if settings.do_in_universe else {}
    )

    _DASH_RE = re.compile(r"[-–—―]{2,}")

    # Collect all CSV files from every watched folder
    all_files = []
    for folder in settings.folders:
        if os.path.exists(folder):
            all_files.extend(
                os.path.join(root, name)
                for root, _dirs, files in os.walk(folder)
                for name in files
                if name.endswith(".csv")
            )

    if not all_files:
        done_fn(settings.limit, settings.wall_limit)
        return

    known_tags       = set(settings.tag_map.keys())
    entry_type_rules = settings.entry_type_rules

    # Pre-compile find-and-replace rules (skip disabled ones)
    _compiled_rules = []
    for rule in settings.replace_rules:
        if not rule.get("enabled", True):
            continue
        find = rule.get("find", "")
        if not find:
            continue
        flags   = 0 if rule.get("match_case") else re.IGNORECASE
        pattern = (r"\b" + re.escape(find) + r"\b") if rule.get("whole_word") else re.escape(find)
        _compiled_rules.append({
            "pattern":             re.compile(pattern, flags),
            "replace":             rule.get("replace", ""),
            "include_speakers":    set(rule.get("include_speakers",    [])),
            "exclude_speakers":    set(rule.get("exclude_speakers",    [])),
            "include_entry_types": set(rule.get("include_entry_types", [])),
            "exclude_entry_types": set(rule.get("exclude_entry_types", [])),
        })

    def apply_replace_rules(text, speaker, entry_type):
        for rule in _compiled_rules:
            if rule["include_speakers"]    and speaker    not in rule["include_speakers"]:    continue
            if rule["exclude_speakers"]    and speaker    in  rule["exclude_speakers"]:       continue
            if rule["include_entry_types"] and entry_type not in rule["include_entry_types"]: continue
            if rule["exclude_entry_types"] and entry_type in  rule["exclude_entry_types"]:   continue
            text = rule["pattern"].sub(rule["replace"], text)
        return text

    _COL_NAME_RE = re.compile(r"(?i)<(?:COL(?: [A-F0-9]+)?|/COL)>|\[NAME\]")
    _TAG_RE      = re.compile(r"<([^>]+)>")

    def strip_known_tags(text):
        t = _COL_NAME_RE.sub("", text)
        return _TAG_RE.sub(
            lambda m: "" if m.group(1).strip() in known_tags else m.group(0), t
        )

    def non_col_tags(text):
        return [
            t for t in _TAG_RE.findall(text)
            if not t.upper().startswith("COL")
            and t.upper() != "/COL"
            and t.strip() not in known_tags
        ]

    for i, f_path in enumerate(all_files):
        # Skip already-processed files if resuming from checkpoint
        if f_path in processed_files:
            continue

        progress_fn(((i + 1) / len(all_files)) * 100)
        file_modded = False
        output_rows = []

        try:
            _raw, dialect, current_file_data = _read_csv(f_path)

            for r_idx, row in enumerate(current_file_data):

                # 1. Structural preservation
                if len(row) <= 3:
                    output_rows.append(row)
                    continue

                # 2. Trigger filter
                if settings.triggers and not any(tr in "|".join(row) for tr in settings.triggers):
                    output_rows.append(row)
                    continue

                orig_text     = row[3]
                proposed_text = orig_text
                needs_review  = False
                queue_type    = None
                wall_wrapped_text = ""

                entry_type = row[9].strip() if len(row) > 9 else ""
                speaker    = row[8].strip() if len(row) > 8 else ""
                et_rules   = entry_type_rules.get(entry_type, {})
                no_linebreak    = et_rules.get("no_linebreak", False)
                effective_limit = et_rules.get("char_limit") or settings.limit

                # 2b. Dash scan
                if _DASH_RE.search(orig_text) and orig_text not in tag_q and orig_text not in wall_q:
                    dash_q[orig_text].append(
                        {"path": f_path, "row_idx": r_idx, "entry_type": entry_type, "speaker": speaker}
                    )

                # 2c. Anachronism scan
                anach_hits = lore_engine.scan_anachronisms(orig_text)
                if anach_hits and orig_text not in tag_q and orig_text not in wall_q:
                    anach_q[orig_text].append(
                        {"path": f_path, "row_idx": r_idx, "hits": anach_hits, "entry_type": entry_type, "speaker": speaker}
                    )

                # 3. Memory branch
                if orig_text in cm.memory:
                    learned    = cm.memory[orig_text]
                    mem_lines  = learned.split("\n")
                    max_w      = max((engine.get_simulated_len(l) for l in mem_lines), default=0)
                    if max_w > effective_limit:
                        needs_review       = True
                        queue_type         = "tag"
                        tag_reason         = "memory_overflow"
                        unknown_tags_found = []
                    else:
                        proposed_text = learned

                # 4. Auto-processing branch
                else:
                    jp_source = row[2] if len(row) > 2 else ""
                    clean_txt  = strip_known_tags(orig_text)
                    is_complex = "<" in clean_txt

                    # Auto tag fix
                    if jp_source and is_complex:
                        jp_tags = non_col_tags(jp_source)
                        en_tags = non_col_tags(orig_text)
                        if Counter(jp_tags) != Counter(en_tags):
                            stripped = re.sub(r"<(?![Cc][Oo][Ll])[^>]+>", "", orig_text).strip()
                            if jp_tags:
                                total_len = max(len(stripped), 1)
                                repaired  = stripped
                                offset    = 0
                                for k, tag in enumerate(jp_tags):
                                    insert_pos = int((k + 1) / (len(jp_tags) + 1) * total_len) + offset
                                    insert_pos = min(insert_pos, len(repaired))
                                    repaired   = repaired[:insert_pos] + f"<{tag}>" + repaired[insert_pos:]
                                    offset    += len(f"<{tag}>")
                                proposed_text = repaired
                                orig_text     = repaired
                                is_complex    = bool(non_col_tags(repaired))

                    text_for_wrap = orig_text
                    if settings.do_in_universe:
                        text_for_wrap = engine.apply_in_universe(orig_text, in_universe_replacements)
                    if _compiled_rules:
                        text_for_wrap = apply_replace_rules(text_for_wrap, speaker, entry_type)

                    tag_reason         = ""
                    unknown_tags_found = []

                    wrapped    = text_for_wrap if no_linebreak else engine.master_tag_wrap(text_for_wrap, effective_limit)
                    wrap_lines = wrapped.split("\n")
                    wrap_max_w = max((engine.get_simulated_len(l) for l in wrap_lines), default=0)

                    if wrap_max_w > effective_limit:
                        needs_review       = True
                        queue_type         = "tag"
                        unknown_tags_found = non_col_tags(wrapped)
                        tag_reason         = "overflow_after_wrap" if not unknown_tags_found else "unmapped_tags_overflow"
                    elif not no_linebreak and len(wrap_lines) >= settings.wall_limit:
                        needs_review      = True
                        queue_type        = "linelimit"
                        wall_wrapped_text = wrapped
                    elif wrapped != row[3]:
                        proposed_text = wrapped

                # 5. Apply
                if needs_review:
                    if queue_type == "tag":
                        tag_q[orig_text].append({
                            "path": f_path, "row_idx": r_idx, "entry_type": entry_type,
                            "tag_reason": tag_reason, "unknown_tags": unknown_tags_found, "speaker": speaker,
                        })
                    elif queue_type == "linelimit":
                        wall_q[orig_text].append({
                            "path": f_path, "row_idx": r_idx,
                            "wrapped": wall_wrapped_text, "entry_type": entry_type, "speaker": speaker,
                        })
                else:
                    if row[3] != proposed_text:
                        row[3]      = proposed_text
                        file_modded = True

                output_rows.append(row)

            # 6. Safety write
            if file_modded and not settings.preview_mode and len(output_rows) == len(current_file_data):
                with open(f_path, "w", encoding="utf-8-sig", newline="") as fh:
                    csv.writer(fh, dialect).writerows(output_rows)

            # 7. Save checkpoint
            if settings.checkpoint_file:
                processed_files.append(f_path)
                _save_checkpoint(settings.checkpoint_file, processed_files, i, settings_hash, auto_fixed)

            queued = sum(
                1 for t in [tag_q, wall_q, dash_q]
                for v in t.values()
                if any(inst["path"] == f_path for inst in v)
            )
            if file_modded or queued:
                log_fn(
                    f"{'[FIXED]' if file_modded else '[QUEUED]'} {os.path.basename(f_path)}"
                    + (f" — {queued} item(s) queued for review" if queued else "")
                )
            if file_modded:
                auto_fixed += 1

        except Exception as exc:
            log_fn(f"CRITICAL ERROR {os.path.basename(f_path)}: {exc}")
            continue

    total_queued = sum(
        sum(len(v) for v in q.values())
        for q in [tag_q, wall_q, dash_q, anach_q]
    )
    log_fn(
        f"――― Scan complete — {auto_fixed} file(s) auto-fixed, "
        f"{total_queued} item(s) queued for review ―――"
    )
    
    # Delete checkpoint on successful completion
    if settings.checkpoint_file:
        _delete_checkpoint(settings.checkpoint_file)
        log_fn("Checkpoint deleted (scan complete)")
    
    done_fn(settings.limit, settings.wall_limit)
