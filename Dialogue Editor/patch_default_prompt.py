# patch_default_prompt.py  (2026-11-21)
# Adds two HARD RULES lines to DEFAULT_AI_PROMPT in YOUR main.py, without replacing the file.
# Usage (editor closed), from the folder that contains main.py:   python patch_default_prompt.py [path\to\main.py]
# It backs main.py up first, keeps the file's CRLF line endings, refuses to touch the file if the anchor line is not
# found exactly once, and does nothing if the lines are already there.
import os, shutil, sys, time

path = sys.argv[1] if len(sys.argv) > 1 else "main.py"
ANCHOR = '    "- Render Japanese dashes as an ellipsis (...) or em dash (\u2014) depending on context.\\n"'
NEW = [
    '    "- Drop \u300a\u300b brackets: keep the text inside them and never replace them with ( ) or [ ].\\n"',
    '    "- If the GLOSSARY section lists a rendering for a person, place, skill or creature name, use it exactly.\\n"',
]

raw = open(path, "rb").read()
crlf = b"\r\n" in raw
text = raw.decode("utf-8")
nl = "\r\n" if crlf else "\n"
if all(l in text for l in NEW):
    print("Already patched - nothing to do.")
    sys.exit(0)
if text.count(ANCHOR) != 1:
    print("STOP: expected the dash rule line exactly once in DEFAULT_AI_PROMPT, found %d. main.py was NOT changed." % text.count(ANCHOR))
    sys.exit(1)
backup = "%s.bak_%s" % (path, time.strftime("%Y%m%d_%H%M%S"))
shutil.copy2(path, backup)
text = text.replace(ANCHOR, ANCHOR + nl + nl.join(NEW))
open(path, "wb").write(text.encode("utf-8"))
print("Patched. Backup: " + backup)
print("Reminder: a SAVED prompt (config key 'ai_prompt') overrides the default; clear or reset it for this to take effect.")
