"""
Starts the Dialogue Editor (main.py) in TEST MODE.   Run:  python run_test_mode.py

Test mode lets you re-run pre-translation over the SAME lines to compare outputs:
  * "skip pre-translated" is forced OFF (also bypasses the AI result cache),
  * the Translation Memory is bypassed for every entry that already holds a translation
    (including approved ones, so the AI actually runs),
  * GitHub pushes are BLOCKED so test translations never reach the shared repo
    (pass --sync to allow them),
  * a batch sends at most 20 items to the AI (a big quest could exhaust the free tier, because test mode
    re-translates every entry it scans); change it with  --max-items N  (0 = no limit),
  * every AI call still writes last_ai_request_batch.txt / _chat.txt and one line to ai_call_log.jsonl,
  * when you close the app it writes a FRESH ddon_report.txt (skip with --no-report).

WARNING: test mode re-translates approved entries and saves the AI result as 'pre-translated'.
Back up your CSVs / translation data first, or only point it at a scratch quest.

Nothing in your config is changed; close the app and start it normally to leave test mode.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

env = dict(os.environ)
env["DDON_TEST_MODE"] = "1"
env["PYTHONIOENCODING"] = "utf-8"  # Japanese / em dashes in log lines can't crash a cp1252 console

argv = sys.argv[1:]
if "--max-items" in argv:
    i = argv.index("--max-items")
    env["DDON_TEST_MAX_ITEMS"] = argv[i + 1]
    del argv[i:i + 2]
args = [a for a in argv if a not in ("--sync", "--no-report")]
if "--sync" in argv:
    env["DDON_TEST_ALLOW_SYNC"] = "1"

print("[run_test_mode] Starting main.py in TEST MODE" + (" (GitHub sync ALLOWED)" if "--sync" in argv else " (GitHub sync BLOCKED)")
      + f", max {env.get('DDON_TEST_MAX_ITEMS', '90')} items per batch")
code = subprocess.call([sys.executable, "-u", os.path.join(HERE, "main.py"), *args], cwd=HERE, env=env)

# The report only knows about AI calls made BEFORE it was generated, so write a fresh one now that the app has closed.
if "--no-report" not in sys.argv[1:]:
    report_script = os.path.join(HERE, "test_voice_context.py")
    if os.path.exists(report_script):
        print("\n[run_test_mode] The app has closed; writing a fresh ddon_report.txt ...")
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("DDON_TEST_")}
        subprocess.call([sys.executable, report_script], cwd=HERE, env=clean_env)
sys.exit(code)
