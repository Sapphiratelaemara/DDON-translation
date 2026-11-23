"""
ai_log.py -- one JSON line per AI call, appended to ai_call_log.jsonl next to main.py.

Holds everything needed to judge a run in one place: speaker, archetype, model requested / used, the JP source,
the first and final English, QA flags, whether a corrective retry happened, timing, and (on failures) the
provider's raw response. test_voice_context.py turns this file into ddon_report.txt.
"""
import json
import os
import threading
import time

LOG_NAME = "ai_call_log.jsonl"
_LOCK = threading.Lock()
_MAX_BYTES = 8_000_000   # keep roughly the last 2,000 records once the file grows past this


def log_path(base_dir):
    return os.path.join(base_dir, LOG_NAME)


def log_call(base_dir, record):
    """Append one record. Never raises (logging must not break a batch)."""
    try:
        rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
        rec.update(record)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        path = log_path(base_dir)
        with _LOCK:
            if os.path.exists(path) and os.path.getsize(path) > _MAX_BYTES:
                with open(path, encoding="utf-8") as fh:
                    keep = fh.readlines()[-2000:]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(keep)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as e:
        print(f"[ai_log] could not write log: {e!a}")


def read_calls(base_dir):
    path = log_path(base_dir)
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out
