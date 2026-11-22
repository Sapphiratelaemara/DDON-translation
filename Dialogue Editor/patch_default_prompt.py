# patch_default_prompt.py  (2026-11-21, v2)
# Two small, safe edits to YOUR main.py (it does not replace the file):
#   1. adds two HARD RULES lines to DEFAULT_AI_PROMPT (the 《》 rule and the glossary-name rule);
#   2. makes a BLANK saved prompt fall back to the default. Before: cm.config.get("ai_prompt", DEFAULT_AI_PROMPT) returns ""
#      when the key exists but is empty, so the app would send an empty system prompt. After:
#      (cm.config.get("ai_prompt") or DEFAULT_AI_PROMPT).
# Usage (editor closed), from the folder that contains main.py:   python patch_default_prompt.py [path\to\main.py]
# Backs main.py up first, keeps CRLF line endings, refuses to change anything if an anchor is not found as expected,
# and skips whatever is already patched.
import shutil, sys, time

path = sys.argv[1] if len(sys.argv) > 1 else "main.py"
ANCHOR = '    "- Render Japanese dashes as an ellipsis (...) or em dash (\u2014) depending on context.\\n"'
NEW = [
    '    "- Drop \u300a\u300b brackets: keep the text inside them and never replace them with ( ) or [ ].\\n"',
    '    "- If the GLOSSARY section lists a rendering for a person, place, skill or creature name, use it exactly.\\n"',
]
OLD_GET = 'cm.config.get("ai_prompt", DEFAULT_AI_PROMPT)'
NEW_GET = '(cm.config.get("ai_prompt") or DEFAULT_AI_PROMPT)'

raw = open(path, "rb").read()
nl = "\r\n" if b"\r\n" in raw else "\n"
text = raw.decode("utf-8")
orig = text
done = []

if all(l in text for l in NEW):
    done.append("prompt lines: already present")
elif text.count(ANCHOR) == 1:
    text = text.replace(ANCHOR, ANCHOR + nl + nl.join(NEW))
    done.append("prompt lines: added to DEFAULT_AI_PROMPT")
else:
    print("STOP: expected the dash rule line exactly once in DEFAULT_AI_PROMPT, found %d. main.py was NOT changed." % text.count(ANCHOR))
    sys.exit(1)

n_old, n_new = text.count(OLD_GET), text.count(NEW_GET)
if n_old == 2 and n_new == 0:
    text = text.replace(OLD_GET, NEW_GET)
    done.append("blank saved prompt now falls back to the default (2 places)")
elif n_old == 0 and n_new == 2:
    done.append("blank-prompt fallback: already present")
else:
    print("STOP: expected the saved-prompt lookup twice (found %d old, %d new). main.py was NOT changed." % (n_old, n_new))
    sys.exit(1)

if text == orig:
    print("Nothing to do:\n  " + "\n  ".join(done))
    sys.exit(0)
backup = "%s.bak_%s" % (path, time.strftime("%Y%m%d_%H%M%S"))
shutil.copy2(path, backup)
open(path, "wb").write(text.encode("utf-8"))
print("Patched. Backup: " + backup + "\n  " + "\n  ".join(done))
