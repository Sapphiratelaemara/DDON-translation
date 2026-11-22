"""
Run directly:   python test_voice_context.py        (from anywhere; no arguments)

Checks (1) the reply filters, (2) the punctuation QA on the two reported failures and against approved TM data,
(3) the OpenRouter client's junk-reply retry (mocked), (4) the real prompt assembly out of the patched main.py.

EDIT THE THREE PATHS BELOW if your data files live somewhere else.
"""
import ast, atexit, collections, contextlib, datetime, hashlib, io, json, os, platform, re, socket, statistics, sys, time, traceback
from unittest import mock

# Windows consoles default to cp1252 and cannot print the Japanese sample text below.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from src import voice_context as vc            # noqa: E402
from src import api_handler                    # noqa: E402

# ---- hardcoded data paths (edit if yours differ) -------------------------------------------------
CONFIG_DIR = os.path.join(HERE, "config", "en")
TM = os.path.join(CONFIG_DIR, "translation_memory.json")
SD = os.path.join(CONFIG_DIR, "speaker_data.json")
ARCHETYPES = os.path.join(CONFIG_DIR, "archetypes.json")
# --------------------------------------------------------------------------------------------------
for _label, _path in (("TM", TM), ("SD", SD), ("ARCHETYPES", ARCHETYPES)):
    if not os.path.exists(_path):
        sys.exit(f"Cannot find {_label} at {_path}\nEdit the paths at the top of {os.path.basename(__file__)}.")
# ---- OFFLINE GUARANTEE ---------------------------------------------------------------------------------
# The offline tests replace requests.post with scripted FAKE responses. To make that impossible to doubt, any attempt
# to open a network connection raises while they run. Sockets are re-enabled only for the optional live probe.
_REAL_CONNECT = socket.socket.connect
_REAL_GETADDRINFO = socket.getaddrinfo
NET_ATTEMPTS = []


def _no_connect(self, *a, **k):
    NET_ATTEMPTS.append(("connect", a))
    raise RuntimeError("network access attempted during the OFFLINE tests")


def _no_getaddrinfo(*a, **k):
    NET_ATTEMPTS.append(("getaddrinfo", a[:1]))
    raise RuntimeError("network access attempted during the OFFLINE tests")


socket.socket.connect = _no_connect
socket.getaddrinfo = _no_getaddrinfo
print("=" * 100)
print("This script makes NO network calls (sockets are blocked) unless LIVE_PROBE = True in the report section.")
print("It checks your installed files, the prompt assembly, the punctuation rules against your approved data, and then")
print("writes ddon_report.txt (including the real AI calls the app has logged).")
print("=" * 100)

fails = []
RESULTS = []   # (passed, name) for the report
CRASH = {}


def check(name, cond):
    RESULTS.append((bool(cond), name))
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


_orig_excepthook = sys.excepthook


def _record_crash(exc_type, exc, tb):
    CRASH["tb"] = "".join(traceback.format_exception(exc_type, exc, tb))
    _orig_excepthook(exc_type, exc, tb)


sys.excepthook = _record_crash


def _report_at_exit():
    """Always leave a report behind, even if the script crashed part-way."""
    fn = globals().get("write_report")
    try:
        if fn:
            fn()
        else:
            with open(os.path.join(HERE, "ddon_report.txt"), "w", encoding="utf-8") as fh:
                fh.write("The test script stopped before it could build the report.\n" + CRASH.get("tb", ""))
    except Exception as e:  # pragma: no cover
        print("could not write report:", e)


atexit.register(_report_at_exit)


check("src/ai_log.py is installed", os.path.exists(os.path.join(HERE, "src", "ai_log.py")))

# 1. reply filters -------------------------------------------------------------
for t in ["User Safety: safe", "OpenRouter Error", '{"User Safety": "safe"}', "", "  "]:
    check(f"bad reply {t!r}", vc.is_bad_reply(t))
check("normal reply is not bad", not vc.is_bad_reply("Best we rested here."))
for t in ["Best we rested here.", "I'd rest awhile in the forest.", "Honest folk, the lot of them.", "The art of war."]:
    check(f"no early-modern false positive: {t!r}", not vc.contains_early_modern(t))
for t in ["Thou art wise.", "What dost thou want?", "He hath gone.", "Wilt come?"]:
    check(f"early-modern caught: {t!r}", vc.contains_early_modern(t))

# 2. punctuation QA on the two reported cases ------------------------------------
c1s = "その合言葉を知っているということは\n私の秘密のスイーツを買いに来たのね\nあぁ、でもごめんなさい\n今日はもう残り１つだけしかないの"
c1bad = "To know the watchword... you're here for my secret confections, then?\nAh, but I'm sorry. Only a single piece remains for today, ser?"
c1ok = "To know the watchword... you are come for my\nsecret sweetmeats, then.\nAh, but forgive me — naught but one\npiece remains for today."
c2s = "森の妖精マカロン、品切れだったのね\nでも、味見はできたみたいでよかった！\nどう？　とっても美味しかったでしょ？\nうふふ――喜んでもらえたなら、嬉しいな"
c2bad = ("The Forest Fairy Macaron... sold out, I see.\nBut... you managed a taste. Thank goodness.\n"
         "How was it? ...It was very delicious, wasn't it?\nHehe... if it pleased you... that makes me happy.")
check("case 1 (merchant) bad output flagged: added_question", "added_question" in [c for c, _ in vc.punct_issues(c1s, c1bad)])
# the human-approved version adds one "—" the source does not strictly have: a known pause-rule false positive
check("case 1 approved human translation has no added question mark", "added_question" not in [c for c, _ in vc.punct_issues(c1s, c1ok)])
codes2 = [c for c, _ in vc.punct_issues(c2s, c2bad)]
check("case 2 (shy girl) bad output flagged: added_pause", "added_pause" in codes2)
check("case 2 bad output flagged: lost_exclamation", "lost_exclamation" in codes2)

# 2b. false-positive rate on the human-approved speaker entries
if True:
    entries = json.load(open(TM, encoding="utf-8-sig"))["entries"]
    sp = [e for e in entries if (e.get("context") or {}).get("speaker")]
    flagged = collections.Counter()
    for e in sp:
        for code, _ in vc.punct_issues(e["source"], e["translation"]):
            flagged[code] += 1
    n = len(sp)
    reported_codes = ("added_question", "added_pause", "lost_exclamation")
    reported_codes += tuple(sorted(set(flagged) - set(reported_codes)))
    print(f"  approved speaker entries: {n}; flagged -> " + ", ".join(
        f"{k} {flagged[k]} ({flagged[k]/n:.1%})" for k in reported_codes))
    check("false-positive rates on human-approved lines stay reasonable (question <10%, pause <15%, !<10%)",
      flagged["added_question"] / n < 0.10 and flagged["added_pause"] / n < 0.15 and flagged["lost_exclamation"] / n < 0.10)

# 2c. regression: ten real pre-translate outputs (Finbar, archetype D, nvidia/nemotron free model).
# Under the old "+1 per JP line break" allowance NONE of these flagged; the live rule must flag the ones
# whose added pauses are not supported by the source (6: "boss..." and "--", 8: "it seems...", 9: "F-forgive me...").
FIN_SRC = [
"ぼ、僕に話しかけてるんですか？\nそりゃ、採掘場キャンプ地の件は感謝してるし\nあなたの活躍の話は、嫌と言うほど聞いてます",
"僕の話なんて聞いても仕方ないと思いますけど――\n実はあの一件以来\n村人が襲撃される事件が相次いでいるそうで",
"恐らく、魔物の群れのボスをなんとかしないと\n解決しないだろうって――村の人たちは\n好き勝手にウワサしてます",
"覚者さん――あの、お願いがあります\nその魔物を追い払って来てほしいんです\nあなたくらい強い人じゃないと頼めないし――",
"また戻って来られると困るので、\n一度も倒れずに、叩きのめしてほしいんです\nもちろん、でき――ますよね？\nすみませんが、よろしくおねがいします",
"覚者さんが良かったらですけど――\n魔物の群れのボスを追い払って来てくれませんか\n一度も倒れずに、圧倒的な力で",
"本当にボスなんかいたんですね\nあ、いや、嘘ついたつもりは無くて――\nただの噂じゃなかったのかと",
"用意したお礼がムダにならなくて\nよかったです――\nありがとうございました",
"ああっ、覚者さん――\n討伐中に膝をついたみたいですね\nだ、大丈夫ですか？\n侵食胞子にやられちゃってませんか？",
"あんなお願いしちゃった僕のせいかな――\nす、すみません\nあの、これ、少しですけど\nお詫びとして受け取ってください",
]
FIN_OUT = [
"A-are you speaking to me? The mining camp affair... I'm grateful, 'tis true. Yet I've heard tell of your exploits more than enough.",
"I fear my tale's naught worth hearing, but—in truth, since that affair, villagers have been attacked one after another, or so I hear—",
"The villagers gossip as they please, saying 'tis likely naught will be resolved unless the monster horde's boss is dealt with.",
"Ser Arisen— forgive me, I have a request.\nI'd have you drive off that monster.\nNone but one as strong as you would do—",
"'Twould be ill if they return, so I need you to put them down for good — not a single rise. You can... manage that, can't you? Forgive me, but I'm counting on you.",
"If it pleases you, Ser Arisen—would you drive off the horde's leader? Without falling once, with overwhelming force.",
"So there really was a boss...\nForgive me, I didn't mean to lie--\nI thought it naught but a rumor.",
"'Tis a relief the thanks I prepared weren't for naught... Thank you.",
"Ah, Ser Arisen—\nYou've fallen to your knees mid-hunt, it seems...\nA-are you alright?\nHave you been struck by erosion spores?",
"Mayhap 'tis my fault for asking such a thing...\nF-forgive me...\nAh, 'tis but a small token, but...\nPray, accept this as my apology.",
]
flagged_idx = {i for i, (s_, o_) in enumerate(zip(FIN_SRC, FIN_OUT)) if "added_pause" in [c for c, _ in vc.punct_issues(s_, o_)]}
print(f"  Finbar batch: added_pause flagged on entries {sorted(flagged_idx)}")
check("regression: real batch entries 6, 8, 9 are flagged for added pauses", {6, 8, 9} <= flagged_idx)
check("regression: entries with source-supported pauses (2, 3, 7) are not flagged", not ({2, 3, 7} & flagged_idx))
check('"--" is counted as a pause', "added_pause" in [c for c, _ in vc.punct_issues("あ\n本当ですね\nはい", "Ah--\nIs that so?\nYes--")])

def _guard_works():
    try:
        socket.create_connection(("openrouter.ai", 443), timeout=1)
    except RuntimeError:
        return True
    except Exception:
        return False
    return False


check("the network guard works (so nothing in this script can reach OpenRouter)", _guard_works())
NET_ATTEMPTS.clear()   # the line above deliberately tried once

# 4. real prompt assembly using functions extracted from the patched main.py ----------------------
main_src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
tree = ast.parse(main_src)
want = {"_speaker_archetype_map", "_speaker_note_for", "_voice_block_for", "_early_modern_exempt",
        "_review_reply", "_feedback_messages", "_contains_early_modern", "_voice_summary",
        "_should_bypass_tm", "_target_language_instruction", "_test_mode", "_sync_blocked", "sync_push_request",
        "_test_mode_cap_items"}
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
check("all helper functions found in patched main.py", {f.name for f in funcs} == want)

arch = json.load(open(ARCHETYPES, encoding="utf-8"))
sd = json.load(open(SD, encoding="utf-8-sig"))


class _CM:  # minimal stand-in for the app's config manager
    language = "en"
    archetypes = arch
    config = {"speaker_archetypes": sd["speaker_archetypes"], "speaker_notes": sd["speaker_notes"]}
    user_settings = {}


class _TMStub:
    entries = entries


class _Ent:
    def __init__(self, status): self.status = status


class _TMgr:  # stand-in for translation_manager
    entries = {"a::1": _Ent("pre-translated"), "a::2": _Ent("approved")}


class _GitHubSync:  # records push requests
    calls = []
    def request_push(self, urgent=False): self.calls.append(urgent)


ns = {"vc": vc, "cm": _CM(), "_get_tm_components": lambda: (_TMStub(), None, None), "os": os, "github_sync": _GitHubSync(),
      "translation_manager": _TMgr(), "_LANGUAGE_NAMES": {"en": "English", "ja": "Japanese"}}
exec(compile(ast.Module(body=funcs, type_ignores=[]), "main_helpers", "exec"), ns)

block = ns["_voice_block_for"]("Miranda", "", c1s)
print("\n----- voice block the model now sees for Miranda (C1), case 1 -----\n" + block + "\n-----")
check("block injects archetype ai_notes, not the structural 'ends on a question' note", "ends on a question" not in block and "ser" in block)
check("block states punctuation follows the source", "decided by the SOURCE line alone" in block)
check("block contains approved TM pairs", "APPROVED TRANSLATIONS" in block and "JP:" in block)
check("current line is not offered as its own example", c1s.split("\n")[0] not in block.split("APPROVED TRANSLATIONS")[1])

idx = vc.get_index(_TMStub.entries, sd["speaker_archetypes"])
bad_examples = [(sp_, s_) for sp_, lst in idx.by_speaker.items() for s_, t_, _p, _x in lst if vc.punct_issues(s_, t_, strict=True)]
check("every indexed example passes the strict punctuation rules", not bad_examples)
check("no HTML entities reach the model in examples", "&#x27;" not in block and "&quot;" not in block)
print(f"  example index: {sum(len(v) for v in idx.by_speaker.values())} usable entries across {len(idx.by_speaker)} speakers")

fin_block = ns["_voice_block_for"]("Finbar", "", FIN_SRC[9])
print("\n----- voice block for Finbar (archetype D), entry 9 -----\n" + fin_block + "\n-----")
summ = ns["_voice_summary"](fin_block, "Finbar")
print("  log line the app now prints:", summ)
check("Finbar gets archetype D with trigger-tied phrases", "archetype='D'" in summ and "not apologies" in fin_block)
check("review flags the entry-9 output via the real _review_reply", "added_pause" in ns["_review_reply"](FIN_OUT[9], FIN_SRC[9], "Finbar")[0])

# --- example formatting: hand-wrapped TM English must not teach the model to hard-wrap ----------------
wrapped = vc.format_examples([("あ\nい\nう\nえ", "But corps policy is to persist, exterminating\nthem time and again.\nShould you spy another horde, see\nto its extermination!")])
check("hand-wrapped example English is flowed into one line", wrapped.count("EN: ") == 1 and "exterminating them time and again." in wrapped)
clean_two = vc.format_examples([("あ\nい", "Hello there.\nHow are you?")])
check("whole-sentence example lines keep their line breaks", clean_two.count("EN: ") == 2)

# --- fixes found in the second real batch log -------------------------------------------------
shelly_jp = "さぁ、各地から\nイケてるメンズをスカウトしてきたわ\nプレゼントの準備はいいかしら"
check("question rule: いいかしら is a real question (was a false 'added_question' flag)",
      "added_question" not in [c for c, _ in vc.punct_issues(shelly_jp, "Well now, I've scouted some fine men from all over. Is the present ready?")])
gur_jp = "またコレか！\nこの手の祭りが始まると\nエリオットがヤケにはりきりやがる"
check("question rule: またコレか！ may render as a question (was a false flag)",
      "added_question" not in [c for c, _ in vc.punct_issues(gur_jp, "This again? Whenever these festivals start, Elliot gets fired up.")])
tag_jp = "もしかして、ジョゼフあたりの策略か？\nここに俺の席を用意して\n大人しくさせようって魂胆じゃねぇだろうな"
check("question rule: a だろうな tag question may render as 'eh?' (a real retry wrongly turned it into 'eh.')",
      "added_question" not in [c for c, _ in vc.punct_issues(tag_jp, "Don't tell me this is Joseph's doin'? Set a seat for me here just to keep me quiet, eh?")])
check("voice rules say dropped g's / 'em / meself / ain't are occasional, not the default",
      "Dropped g's" in vc.VOICE_HEADER and "dropped g's" in vc.VOICE_HEADER_SHORT)
check("question rule: だよね is a tag question (a real retry turned \"don't they?\" into \"don't they.\")",
      "added_question" not in [c for c, _ in vc.punct_issues("やっぱ贈り物といえばスイーツだよね", "Yep, gifts mean sweets, don't they?")])
check("question rule: a plain のね statement given a '?' is still flagged (the original merchant failure)",
      "added_question" in [c for c, _ in vc.punct_issues("私の秘密のスイーツを買いに来たのね", "You're here for my secret sweets, then?")])
_say_src = "彼女の前で＜say＞で合言葉を言うんだよ"
check("glossary brackets: ＜say＞ rendered as <say> is flagged (real outputs did this twice)",
      "wrong_brackets" in [c for c, _ in vc.punct_issues(_say_src, "Use <say> to speak the password.")])
check("glossary brackets: [say] is accepted", "wrong_brackets" not in [c for c, _ in vc.punct_issues(_say_src, "Use [say] to speak the password.")])
check("glossary brackets: a real ASCII <say> tag copied from an ASCII source is not flagged",
      "wrong_brackets" not in [c for c, _ in vc.punct_issues("<say>で言う", "Say it with <say>.")])
_leak_line = "覚者さん、私とリズとで\nとても素敵なお返しを思いついたんだ\nきっと喜んでもらえると思うの！"
_leak_entries = [{"id": "x", "source": _leak_line, "translation": "APPROVED ANSWER", "quality": "approved", "context": {"speaker": "Mayleaf"}}]
_leak_idx = vc.ExampleIndex(_leak_entries, {"Mayleaf": "D"})
check("the line being translated is never its own example (CRLF from a Windows CSV used to defeat the exclusion)",
      all(not _leak_idx.pick("Mayleaf", "D", cur) for cur in (_leak_line, _leak_line.replace("\n", "\r\n"),
                                                               _leak_line.replace("\n", "\r\n") + "\r\n", _leak_line.replace("\n", " \n"))))
check("pause retry message tells the model to keep the sentence readable", "comma" in dict(vc.punct_issues("あ\nい", "Oh... yes... no... maybe...")).get("added_pause", ""))
check("question rule: a plain statement given a '?' is still flagged",
      "added_question" in [c for c, _ in vc.punct_issues("今日はもう残り１つだけしかないの", "Only one left today, ser?")])
check("multiply-escaped tags are fully unescaped", vc._clean("&amp;amp;lt;QDEL NAME 0 6&amp;amp;gt;を") == "<QDEL NAME 0 6>を")
gb_full = ns["_voice_block_for"]("Gurdolin", "", "それにしても、ここにずっと座ってるのも")
gb_short = ns["_voice_block_for"]("Gurdolin", "", "それにしても、ここにずっと座ってるのも",
                                  sys_prompt="x CHARACTER VOICE (word choice only — never content) y")
check("full header when the prompt has no voice rules of its own", "CHARACTER VOICE — WORD CHOICE ONLY" in gb_full)
check("short header (no duplicated rules) when the prompt already has them",
      "ARCHETYPE AND SPEAKER NOTES" in gb_short and "CHARACTER VOICE — WORD CHOICE ONLY" not in gb_short)
check("no HTML entities in any example shown to the model", "&lt;" not in gb_full and "&amp;" not in gb_full and "&#x27;" not in gb_full)

bp = ns["_should_bypass_tm"]
check("TM bypass: re-run (skip off) of a pre-translated entry bypasses the TM", bp({}, "a::1", False, {}) is True)
check("TM bypass: approved entries are NOT bypassed by default", bp({}, "a::2", False, {}) is False)
check("TM bypass: skip ON never bypasses", bp({}, "a::1", True, {}) is False)
check("TM bypass: never-seen entries still use the TM", bp({}, "new::9", False, {}) is False)
check('TM bypass: setting "all" also covers approved entries (testing mode)', bp({}, "a::2", False, {"bypass_tm_on_rerun": "all"}) is True)
check("TM bypass: setting false disables it", bp({}, "a::1", False, {"bypass_tm_on_rerun": False}) is False)
tl = ns["_target_language_instruction"]()
check("target-language text no longer says 'do not reply in English' for an English target", "including English" not in tl)
ns["cm"].language = "ja"
check("target-language text still protects English for other targets", "including English" in ns["_target_language_instruction"]())
ns["cm"].language = "en"

# --- 2026-11-21 checks: added "!", lost "?", optional trailing pause (found in the real batch reports) ----------
_ex_src = "すでに始めておるな、腕が鳴るわ"
_codes = lambda s_, o_: [c for c, _ in vc.punct_issues(s_, o_)]
check("added_exclamation: source has no ！ but the reply ends with '!' (real Meirova line)",
      "added_exclamation" in _codes(_ex_src, "'Tis already begun, my sword arm itches for the fray!"))
check("added_exclamation: not flagged when the source has its own ！",
      "added_exclamation" not in _codes("ネドの死は――弱者の末路よ！", "Nedo's death — the fate of the weak!"))
check("added_exclamation: not flagged for a plain statement", "added_exclamation" not in _codes(_ex_src, "'Tis already begun, and my sword arm itches."))
_lq_src = "あら、覚者様\nどうでしたか？　調査のほどは――！"
check("lost_question: source ？ but the reply has no '?' (real Muirgel line)",
      "lost_question" in _codes(_lq_src, "Ah, Ser Arisen. How fared the investigation—!"))
check("lost_question: not flagged when the question is kept",
      "lost_question" not in _codes(_lq_src, "Ah, Ser Arisen. How did it go? The investigation—!"))
check("lost_question: not flagged for a normal question",
      "lost_question" not in _codes("いよいよ黒騎士との決戦だな？", "At last, the decisive battle with the Black Knight, eh?"))
check("the new retry messages exist and name the fix",
      all(dict(vc.punct_issues(a, b)).get(code) for a, b, code in
          ((_ex_src, "It itches for the fray!", "added_exclamation"), (_lq_src, "How fared the investigation—!", "lost_question"))))
_tp_src, _tp_out = "この者達の血を捧ごう――", "I shall offer up the blood of these."
check("lost_trailing_pause is OFF by default (the prompt lets the model drop a trailing ――)",
      vc.CHECK_LOST_TRAILING_PAUSE is False and "lost_trailing_pause" not in _codes(_tp_src, _tp_out))
_old_switch = vc.CHECK_LOST_TRAILING_PAUSE
vc.CHECK_LOST_TRAILING_PAUSE = True
check("lost_trailing_pause (switched on): flagged when the closing pause is dropped", "lost_trailing_pause" in _codes(_tp_src, _tp_out))
check("lost_trailing_pause (switched on): not flagged when the reply ends on a dash or ellipsis",
      "lost_trailing_pause" not in _codes(_tp_src, "I shall offer up the blood of these—")
      and "lost_trailing_pause" not in _codes(_tp_src, "I shall offer up the blood of these..."))
vc.CHECK_LOST_TRAILING_PAUSE = _old_switch
_old_ae, _old_lq = vc.CHECK_ADDED_EXCLAMATION, vc.CHECK_LOST_QUESTION
vc.CHECK_ADDED_EXCLAMATION = vc.CHECK_LOST_QUESTION = False
check("the two on-by-default checks can be switched off",
      "added_exclamation" not in _codes(_ex_src, "It itches for the fray!") and "lost_question" not in _codes(_lq_src, "How fared the investigation—!"))
vc.CHECK_ADDED_EXCLAMATION, vc.CHECK_LOST_QUESTION = _old_ae, _old_lq

# --- 2026-11-21 (later): added_quotes (a reply wrapped whole lines in quotation marks; the prompt says none) ------------
_q_src = '"シェドレアン大神殿"での問題を\n解決してくれたみたいね！\nアデルドナハからも、礼をいっておいてくれと\n言われたよ――'
_q_bad = '"It appears you have resolved the matter at the Shadolean Great Temple!"\n"Adair Donnchadh charged me to relay his gratitude—"'
check("added_quotes: flagged when the reply wraps whole lines in quotes (real Deryn 355)", "added_quotes" in _codes(_q_src, _q_bad))
check("added_quotes: not flagged when the reply quotes what the source quotes",
      "added_quotes" not in _codes('"シェドレアン大神殿"での問題を解決してくれたみたいね！', 'It appears you resolved the matter at the "Shadolean Great Temple"!'))
check("added_quotes: not flagged when the source uses ＜＞ and the reply renders it as quotes (approved TM style)",
      "added_quotes" not in _codes("メインクエスト＜<QCND 0>＞をクリア", 'Clear Main Quest "<QCND 0>"'))
check("added_quotes: not flagged for 「」 source rendered with quotes", "added_quotes" not in _codes("「行くぞ」", '"Let us go."'))
_old_aq = vc.CHECK_ADDED_QUOTES
vc.CHECK_ADDED_QUOTES = False
check("added_quotes can be switched off", "added_quotes" not in _codes(_q_src, _q_bad))
vc.CHECK_ADDED_QUOTES = _old_aq

# --- HTML-escaping bug (translation_manager.sanitize_text escaped on every save AND every load) ----------
import importlib
_buf = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf):
        tmgr = importlib.import_module("src.translation_manager")
except Exception as _e:
    tmgr = None
    print("  (could not import src/translation_manager.py:", _e, ")")
check("src/translation_manager.py can be imported (the fixed copy is installed)", tmgr is not None and hasattr(tmgr, "unsanitize_text"))
if tmgr is not None:
    _S = tmgr.sanitize_text
    _samples = ["It's a \"test\" <COL>x</COL> & more", "'Tis faring well, I'd wager.", '最近はやりの"副業"ていうの？', "<QDEL NAME 0 6>を\nよろしく"]
    check("sanitize_text is idempotent (escaping it twice no longer adds a level)", all(_S(_S(_S(x))) == _S(x) for x in _samples))
    _deep = "'Tis fine"
    for _ in range(40):
        _deep = __import__("html").escape(_deep)
    check("a 40-level escaped string heals to a single level", _S(_deep) == "&#x27;Tis fine" and tmgr.unsanitize_text(_deep) == "'Tis fine")
    _e = tmgr.TranslationEntry(id="t_1", source_text=_samples[2], translated_text=_samples[1])
    _e = tmgr.TranslationEntry.from_dict(dict(_e.to_dict()))
    _first = (_e.source_text, _e.translated_text)
    for _ in range(19):
        _e = tmgr.TranslationEntry.from_dict(dict(_e.to_dict()))
    check("20 save/load cycles leave the stored text unchanged after the first (it used to gain a level every cycle)",
          (_e.source_text, _e.translated_text) == _first)
    check("unsanitize reverses only what html.escape makes (an &copy; in real text is untouched)", tmgr.unsanitize_text("&copy; &lt;b&gt;") == "&copy; <b>")
    _mgr_src = open(os.path.join(HERE, "src", "translation_manager.py"), encoding="utf-8").read()
    check("both TM hand-offs (submit_translation and approve_translation) give the TM RAW text",
          '"source": unsanitize_text(source_text)' in _mgr_src and '"translation": unsanitize_text(entry.translated_text)' in _mgr_src)
check("vc.raw_text: any escaping depth -> raw; raw text and non-strings pass through",
      vc.raw_text("That &quot;side business&quot; &#x27;Tis &amp;amp;lt;COL&amp;amp;gt;") == "That \"side business\" 'Tis <COL>"
      and vc.raw_text("plain 'text' & <tag>") == "plain 'text' & <tag>" and vc.raw_text(None) is None)
_RAW_FUNCS = {"generate_preview_image", "get_gloss", "get_lore_context", "scan_anachronisms", "get_deepl_suggestion",
              "validate_translation", "tm_find_matches", "rewrap_text", "get_simulated_len", "get_tag_aware_character_count",
              "apply_fix", "save_translation_history", "send_ai_chat"}
_have_raw = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in _RAW_FUNCS
             and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_raw_text" for c in ast.walk(n))}
check("all 13 UI-facing functions (preview, gloss, validate, counts, TM search, CSV write ...) work on RAW text: missing "
      + (", ".join(sorted(_RAW_FUNCS - _have_raw)) or "none"), _have_raw == _RAW_FUNCS)
check("clean_tm_escaping.py (one-off TM repair) is installed", os.path.exists(os.path.join(HERE, "clean_tm_escaping.py")))

check("voice rules tell the model that か/かしら/だろう/よね question forms keep their '?' (it wrote \"don't they.\")",
      "don't they?" in vc.VOICE_HEADER and "don't they?" in vc.VOICE_HEADER_SHORT)

# the TM repair script's glossary-bracket pass, on a synthetic TM
import subprocess, tempfile, shutil
_d = tempfile.mkdtemp()
os.makedirs(os.path.join(_d, "config", "en"))
shutil.copy(os.path.join(HERE, "clean_tm_escaping.py"), _d)
_tm = {"version": "1", "entries": [
    {"id": "a", "source": "彼女の前で＜say＞で言う", "translation": "Use <say> to say it.", "context": {}, "timestamp": "2026-01-01"},
    {"id": "b", "source": "それは&amp;quot;秘密&amp;quot;", "translation": "It&#x27;s a &quot;secret&quot;", "context": {}, "timestamp": "2026-01-01"},
    {"id": "c", "source": "<say>で言う", "translation": "Use <say>.", "context": {}, "timestamp": "2026-01-01"}],
    "stats": {"total_entries": 3}}
json.dump(_tm, open(os.path.join(_d, "config", "en", "translation_memory.json"), "w", encoding="utf-8"), ensure_ascii=False)
_env = dict(os.environ, DDON_SKIP_RUNNING_CHECK="1")   # the editor may well be open while this test runs
_r = subprocess.run([sys.executable, os.path.join(_d, "clean_tm_escaping.py")], capture_output=True, text=True, encoding="utf-8", env=_env)
_out = {e["id"]: e for e in json.load(open(os.path.join(_d, "config", "en", "translation_memory.json"), encoding="utf-8"))["entries"]}
check("TM repair script: <say> becomes [say] where the source has ＜say＞", _out["a"]["translation"] == "Use [say] to say it.")
check("TM repair script: an ASCII <say> that is in an ASCII source is left alone", _out["c"]["translation"] == "Use <say>.")
check("TM repair script: escaped text is made raw", _out["b"]["source"] == 'それは"秘密"' and _out["b"]["translation"] == 'It\'s a "secret"')
check("TM repair script: a backup was written", any(".bak-" in f for f in os.listdir(os.path.join(_d, "config", "en"))))
# the repair scripts must refuse to run while the editor is open (it would write its stale in-memory copy back over the repair)
_tm_path = os.path.join(_d, "config", "en", "translation_memory.json")
_tm_before = open(_tm_path, "rb").read()
_srv = socket.socket()
_srv.bind(("127.0.0.1", 0))
_srv.listen(1)
_port = _srv.getsockname()[1]
_busy = subprocess.run([sys.executable, os.path.join(_d, "clean_tm_escaping.py")], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, DDON_APP_PORTS=str(_port), DDON_SKIP_RUNNING_CHECK=""))
_srv.close()
check("TM repair script refuses to run while the editor appears to be open, and changes nothing",
      _busy.returncode != 0 and "still running" in (_busy.stdout + _busy.stderr) and open(_tm_path, "rb").read() == _tm_before)
shutil.rmtree(_d, ignore_errors=True)

# --- the legacy "--": never taught to the model, and the model's own "--" becomes an em dash (the TM itself is never touched)
check("the model's '--' becomes an em dash, tags and longer runs of hyphens are left alone",
      vc.clean_reply("It can't be--wait <A--B> and ---x and end--") == "It can't be—wait <A--B> and ---x and end—")
_dd_idx = vc.ExampleIndex([
    {"id": "1", "source": "あ――\nい", "translation": "Oh--\nyes.", "quality": "approved", "context": {"speaker": "S"}},
    {"id": "2", "source": "あ――\nい", "translation": "Oh—\nyes.", "quality": "approved", "context": {"speaker": "S"}}], {"S": "D"})
check("approved lines containing the legacy '--' are never offered as examples (the em-dash twin still is)",
      [t for _s, t in _dd_idx.pick("S", "D", "別の行", n=3)] == ["Oh—\nyes."])

check("question rule: a wh-question without ？ (どうした, なぜ...) keeps its '?' (a real retry turned \"What ails you?\" into \"What ails you.\")",
      "added_question" not in [c for c, _ in vc.punct_issues("――おや、どうした\nなぜ沈んでいる――\n――つらいことがあったのか？", "Hm? What ails you?\nWhy so downcast—\nDid something painful happen?")])
check("question rule: どうぞ is not a question word, so a plain statement with a '?' is still flagged",
      "added_question" in [c for c, _ in vc.punct_issues("どうぞ、お入りください", "Please, come in?")])

# --- [say] is enforced in code; two pause sources the rules did not know (found in the real 2026-11-14 batch) ----
check("fullwidth ＜say＞ in the source forces [say] in the reply, with no retry needed",
      vc.clean_reply("If you say it with <say>, they'll give you a sweet!", "＜say＞で合言葉を言えば") == "If you say it with [say], they'll give you a sweet!")
check("an ASCII <say> that really is in the source is left alone",
      vc.clean_reply("Use <say> now.", "<say>で言う") == "Use <say> now.")
check("the pause rule accepts a dash after は+ね (the sentence continues on the next line)",
      "added_pause" not in [c for c, _ in vc.punct_issues("覚者さん、秘密のスイーツ屋さんはね\n普段は違うお店をやっている\n\"隠れスイーツ屋さん\"なの",
          "Ser Arisen, the secret sweets shop — 'tis a hidden sweets shop, you see. It runs a different shop most days.")])
check("the pause rule accepts a dash for a hiragana elongation (そっかー)",
      "added_pause" not in [c for c, _ in vc.punct_issues("そっかー、すぐに売り切れちゃうんだよねー", "Right—they sell out right quick, don't they?")])
check("a pause after a FINISHED sentence (ね as のね) is still flagged",
      "added_pause" in [c for c, _ in vc.punct_issues("今日はもう残り１つだけしかないの\nそうなのね\n次は来週ね", "Only one left... I see... next week...")])

# --- 《 》 are dropped, DeepL never overwrites in test mode, notes do not cap archaic wording -------------
check("reply clean-up drops the 《 》 name brackets and nothing else",
      vc.clean_reply("Before 《Miranda》, who keeps the shop in 《Lynwood》, say \"hello\".") == 'Before Miranda, who keeps the shop in Lynwood, say "hello".')
check("reply clean-up leaves 「 」 and ordinary text alone", vc.clean_reply("「Hello」 there.") == "「Hello」 there." and vc.clean_reply("") == "")
check("main.py applies the clean-up to batch AND chat replies, first and retry (4 places)", main_src.count("vc.clean_reply(") == 4)
check("test mode never falls back to DeepL (it would overwrite existing text with machine output)",
      "if translation is None and deepl_key and not _test_mode():" in main_src and "NOT falling back to DeepL" in main_src)
_cap_words = re.compile(r"\b(?:light(?:ly)?|minimal|at most|at best|lighter)\b[^.;]{0,40}\barchaic|\barchaic\b[^.;]{0,40}\b(?:light(?:ly)?|minimal|at most|at best|lighter)\b|No archaic|Light on archaic|moderate archaic", re.I)
_capped = sorted(k for k, v in arch["archetypes"].items() if _cap_words.search(v.get("ai_notes", "")))
check("archetype ai_notes do not cap archaic wording (if this fails, run apply_ai_notes.py with the editor closed): "
      + (", ".join(_capped) if _capped else "none"), not _capped)

_banned_slang = re.compile(r"\b(?:gonna|gotta|kinda|sorta|nah|dude|okay|awesome|yeah)\b", re.I)
_slangy = sorted(k for k, v in arch["archetypes"].items() if _banned_slang.search(v.get("ai_notes", "")))
check("no archetype note tells the model to use slang your prompt bans (nah, gonna, okay, yeah ...): "
      + (", ".join(_slangy) if _slangy else "none") + "  (if this fails, run apply_ai_notes.py with the editor closed)", not _slangy)

# --- TEST MODE (run_test_mode.py sets DDON_TEST_MODE=1) ----------------------------------------
with mock.patch.dict(os.environ, {}, clear=False):
    os.environ.pop("DDON_TEST_MODE", None); os.environ.pop("DDON_TEST_ALLOW_SYNC", None)
    check("test mode is off by default", ns["_test_mode"]() is False)
    ns["github_sync"].calls.clear(); ns["sync_push_request"](True)
    check("normal mode: GitHub push requests go through", ns["github_sync"].calls == [True])
    os.environ["DDON_TEST_MODE"] = "1"
    check("DDON_TEST_MODE=1 turns test mode on", ns["_test_mode"]() is True)
    check("test mode bypasses the TM even for APPROVED entries", bp({}, "a::2", False, {}) is True)
    check("test mode bypasses the TM for pre-translated entries", bp({}, "a::1", False, {}) is True)
    check("test mode still lets brand-new lines use the TM", bp({}, "new::9", False, {}) is False)
    ns["github_sync"].calls.clear(); ns["sync_push_request"](True)
    check("test mode BLOCKS GitHub pushes", ns["github_sync"].calls == [])
    os.environ["DDON_TEST_ALLOW_SYNC"] = "1"
    ns["sync_push_request"](True)
    check("test mode + DDON_TEST_ALLOW_SYNC=1 lets pushes through", ns["github_sync"].calls == [True])
with mock.patch.dict(os.environ, {"DDON_TEST_MODE": "1"}, clear=False):
    os.environ.pop("DDON_TEST_MAX_ITEMS", None)
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        capped = ns["_test_mode_cap_items"](list(range(50)))
    check("test mode caps a batch at 20 items by default", len(capped) == 20 and capped[0] == 0)
    os.environ["DDON_TEST_MAX_ITEMS"] = "5"
    with contextlib.redirect_stdout(_buf):
        check("DDON_TEST_MAX_ITEMS=5 changes the cap", len(ns["_test_mode_cap_items"](list(range(50)))) == 5)
    os.environ["DDON_TEST_MAX_ITEMS"] = "0"
    check("DDON_TEST_MAX_ITEMS=0 removes the cap", len(ns["_test_mode_cap_items"](list(range(50)))) == 50)
with mock.patch.dict(os.environ, {}, clear=False):
    os.environ.pop("DDON_TEST_MODE", None)
    check("normal mode never caps a batch", len(ns["_test_mode_cap_items"](list(range(50)))) == 50)
for _fn in ("_pretranslate_batch_run", "pretranslate_by_keys"):
    _node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == _fn)
    check(f"{_fn} forces skip_pretranslated off in test mode",
          any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_test_mode" for c in ast.walk(_node)))

ex = ns["_early_modern_exempt"]
check("White Dragon exempt via archetype AB flag", ex("The White Dragon"))
check("Evil Dragon exempt via archetype AD flag", ex("The Evil Dragon"))
check("Lise (note says 'without') is NOT exempt any more", not ex("Lise"))
check("Mephis (note says 'without') is NOT exempt any more", not ex("Mephis"))

flags, notes = ns["_review_reply"](c1bad, c1s, "Miranda")
check("main.py _review_reply flags the merchant output", "added_question" in flags)
fb = ns["_feedback_messages"]([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], c1bad, notes)
check("feedback turn is appended as assistant + user messages", [m["role"] for m in fb] == ["system", "user", "assistant", "user"])

# ===================================================================================================
# REPORT: everything needed to evaluate a run, in ONE file (ddon_report.txt next to this script).
# Send me that file; nothing else needs to be collected by hand.
# ===================================================================================================
LIVE_PROBE = False        # True = send ~6 small requests to OpenRouter with YOUR key to tell a provider/model problem from
                          # a prompt problem (free-tier calls are limited, so it is off by default). Flip it on again
                          # whenever replies start failing.
PROBE_READ_TIMEOUT = 75   # seconds to wait for each probe reply
REPORT_PATH = os.path.join(HERE, "ddon_report.txt")
CALL_LOG = os.path.join(HERE, "ai_call_log.jsonl")
LAST_CALLS_SHOWN = 60
PROBE = {"status": "not run", "rows": [], "verdict": "", "sample": ""}

def run_probe():
    """Small controlled requests with the user's own key. Answers: is the model/provider failing regardless of prompt,
    or does something in the app's request cause it? Never prints or stores the key."""
    if not LIVE_PROBE:
        PROBE["status"] = "disabled (LIVE_PROBE = False): this run made NO network calls"
        return
    socket.socket.connect = _REAL_CONNECT          # the ONLY place the script re-enables the network
    socket.getaddrinfo = _REAL_GETADDRINFO
    try:
        import requests
        os.chdir(HERE)
        from src.config_manager import ConfigManager
        real = ConfigManager(language="en")
        key = real.get_key("openrouter_api_key")
        model = real.user_settings.get("selected_openrouter_model", "openrouter/auto")
        saved_prompt = real.config.get("ai_prompt")
    except Exception as e:
        PROBE["status"] = f"skipped: could not load your config / API key ({type(e).__name__}: {e})"
        return
    if not key:
        PROBE["status"] = "skipped: no OpenRouter API key configured"
        return

    speaker, jp = "Shelly", shelly_jp
    dump = os.path.join(HERE, "last_ai_request_batch.txt")
    if os.path.exists(dump):
        txt = open(dump, encoding="utf-8", errors="replace").read()
        m = re.search(r"Speaker: (.*?)\r?\nEntry type:.*?\r?\n\r?\nSource text:\r?\n(.*)\Z", txt, re.S)
        if m:
            speaker, jp = m.group(1).strip(), m.group(2).strip()
    PROBE["sample"] = f"speaker={speaker!r}, model={model!r}, JP={jp[:60]!r}"

    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DEFAULT_AI_PROMPT")
    base = saved_prompt or ast.literal_eval(node.value)
    block_cur = ns["_voice_block_for"](speaker, "", jp, sys_prompt=base)       # what the app builds now
    block_full = ns["_voice_block_for"](speaker, "", jp, sys_prompt="")         # last night's (full header) shape
    tl_new = ns["_target_language_instruction"]()
    tl_old = tl_new.replace("other language unless", "other language (including English) unless")

    def mk(block, tl):
        body = base.replace("{character_voice_note}", block) if "{character_voice_note}" in base else base + "\n\n" + block
        return body + tl

    user_msg = f"Translate this to English.\nSpeaker: {speaker}\nEntry type: Quest Dialogue\n\nSource text:\n{jp}"
    tiny = [{"role": "user", "content": "Translate this to English: " + jp.splitlines()[0]}]
    cur = [{"role": "system", "content": mk(block_cur, tl_new)}, {"role": "user", "content": user_msg}]
    old = [{"role": "system", "content": mk(block_full, tl_old)}, {"role": "user", "content": user_msg}]
    variants = [
        ("V1", "tiny prompt, no temperature", model, tiny, {}),
        ("V2", "tiny prompt, temperature 0.3", model, tiny, {"temperature": 0.3}),
        ("V3", "CURRENT app prompt, temperature 0.3 (what the app sends)", model, cur, {"temperature": 0.3}),
        ("V4", "current app prompt, NO temperature", model, cur, {}),
        ("V5", "LAST NIGHT's prompt shape (full voice header + old language line), temperature 0.3", model, old, {"temperature": 0.3}),
        ("V6", "current app prompt on openrouter/free (different model)", "openrouter/free", cur, {"temperature": 0.3}),
    ]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "DDON Dialogue Editor (diagnostic)"}
    for vid, name, mdl, msgs, extra in variants:
        row = {"id": vid, "name": name, "model": mdl, "prompt_chars": sum(len(m["content"]) for m in msgs)}
        body = None
        t0 = time.time()
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers,
                              json={"model": mdl, "messages": msgs, **extra}, timeout=(10, PROBE_READ_TIMEOUT))
            row["http"] = r.status_code
            try:
                body = r.json()
            except Exception:
                row["raw"] = r.text[:2000]
        except Exception as e:
            row["exception"] = f"{type(e).__name__}: {e}"
        row["seconds"] = round(time.time() - t0, 1)
        if body is not None:
            text, why = api_handler._extract_text(body)
            row["ok"] = text is not None and not vc.is_bad_reply(text)
            row["text"] = (text or "")[:300]
            row["why"] = why
            row["answered_by"] = (body.get("provider"), body.get("model")) if isinstance(body, dict) else None
            row["api_error"] = api_handler._api_error_message(body)
            row["raw"] = json.dumps(body, ensure_ascii=False)[:2500]
        else:
            row["ok"] = False
        PROBE["rows"].append(row)
        print(f"  probe {vid}: {'OK' if row['ok'] else 'NO REPLY'} in {row['seconds']}s  ({name})")
        time.sleep(2)

    ok = {r["id"]: r["ok"] for r in PROBE["rows"]}
    if not any(ok.values()):
        v = ("NO variant returned any text, including a one-line prompt: the model/provider is failing right now regardless of "
             "prompt, temperature or request size. That points at the free endpoint, not at the prompt changes.")
    elif all(ok[k] for k in ("V1", "V2", "V3", "V4", "V5")):
        v = "Every variant on the pinned model works now: the earlier empty replies were transient / provider-side."
    elif ok["V1"] and ok["V2"] and not ok["V3"] and not ok["V4"] and not ok["V5"]:
        v = ("Small prompts work, but BOTH the current prompt and last night's prompt shape fail now, even though the latter "
             "worked last night. So the cause is NOT something changed in the prompt since then: the provider is failing on "
             "long prompts right now (load, or a change on their side).")
    elif ok["V5"] and not ok["V3"]:
        v = ("Last night's prompt shape works but the current one does not: something changed since last night in the prompt "
             "(short voice header, language line or examples) is responsible.")
    elif ok["V4"] and not ok["V3"]:
        v = "The request works WITHOUT temperature but fails with temperature 0.3: the temperature parameter is the trigger on this model."
    elif ok["V2"] is False and ok["V1"]:
        v = "A tiny prompt works only without temperature: the temperature parameter is the trigger on this model."
    elif ok.get("V6") and not ok["V3"]:
        v = "The app prompt works on openrouter/free but not on the pinned model: this model/provider is the problem; switch models."
    else:
        v = "Mixed result; see the per-variant rows below."
    if ok.get("V6") and not ok.get("V3"):
        v += " The app prompt DOES work on openrouter/free, so switching models is a workable fallback."
    PROBE["verdict"] = v
    PROBE["status"] = "ran"


def _grab(pattern, text, default="?"):
    m = re.search(pattern, text)
    return m.group(1) if m else default


# LF-normalised SHA-1 of every file as I delivered it (stamped in when the package is built). The report compares your
# installed copies against these, ignoring line endings, so a file you edited yourself shows up instead of being assumed equal.
DELIVERED = {'main.py': '5db80163ec', 'run_test_mode.py': '25bca4bcfc', 'clean_tm_escaping.py': 'ca70c9d015', 'apply_ai_notes.py': 'e7a6d34dae', 'test_client_errors.py': '32cf2c8798', 'src/voice_context.py': 'd8ecc0e4f1', 'src/api_handler.py': 'b3f297e7b6', 'src/ai_log.py': 'b2fe5c9f69', 'src/translation_manager.py': '68b7178a8c'}


def _sha(path):
    try:
        return hashlib.sha1(open(path, "rb").read()).hexdigest()[:10]
    except Exception:
        return "-"


def _norm_sha(path):
    try:
        return hashlib.sha1(open(path, "rb").read().replace(b"\r\n", b"\n")).hexdigest()[:10]
    except Exception:
        return "-"


def _fingerprint(path):
    if not os.path.exists(path):
        return f"{os.path.relpath(path, HERE)}\n      MISSING"
    st = os.stat(path)
    rel = os.path.relpath(path, HERE).replace("\\", "/")
    want = DELIVERED.get(rel)
    status = ""
    if want:
        status = ("   = identical to what I delivered" if _norm_sha(path) == want
                  else "   != DIFFERS from what I delivered (your own edit, or an older copy?)")
    return (f"{os.path.relpath(path, HERE)}\n      {st.st_size:>9,} bytes  modified "
            f"{datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}  sha1 {_sha(path)}{status}")


def _lines(t):
    return [l for l in (t or "").split("\n") if l.strip()]


def _metrics_by_archetype(calls):
    ok = [c for c in calls if c.get("outcome") == "ok" and c.get("jp") and c.get("output")]
    by = collections.defaultdict(list)
    for c in ok:
        by[c.get("archetype") or "?"].append(c)
    rows = []
    for a, L in sorted(by.items(), key=lambda kv: -len(kv[1])):
        en_l = [l for c in L for l in _lines(c["output"])]
        jp_l = [l for c in L for l in _lines(c["jp"])]
        q_en = sum(l.rstrip().endswith("?") for l in en_l) / max(1, len(en_l))
        q_jp = sum(bool(re.search(r"[？?]\s*$", l)) or bool(vc._KA_END.search(l.strip())) for l in jp_l) / max(1, len(jp_l))
        t_en = sum(bool(re.search(r"(\.{3}|…|—)\s*$", l)) for l in en_l) / max(1, len(en_l))
        t_jp = sum(bool(re.search(r"(…|―+|‥)\s*$", l)) for l in jp_l) / max(1, len(jp_l))
        flagged = sum(bool(vc.punct_issues(c["jp"], c["output"])) for c in L) / len(L)
        retried = sum(bool(c.get("retried")) for c in L) / len(L)
        rows.append((a, len(L), q_en, q_jp, t_en, t_jp, flagged, retried))
    return rows


def _norm_key(text):
    return re.sub(r"\s+", "", vc._clean(text))


def write_report():
    approved_by_src = collections.defaultdict(set)
    try:
        for e in entries:
            approved_by_src[_norm_key(e["source"])].add(_norm_key(e["translation"]))
    except Exception:
        pass
    out = []
    P = out.append
    now = datetime.datetime.now()
    P("DDON VOICE-CONTEXT DIAGNOSTIC REPORT")
    P(f"generated {now:%Y-%m-%d %H:%M:%S}   python {platform.python_version()}   {platform.platform()}")
    if CRASH.get("tb"):
        P("\n!! THE TEST SCRIPT CRASHED BEFORE FINISHING:\n" + CRASH["tb"])

    P("\n" + "=" * 100 + "\n1. INSTALLED FILES (are the latest versions in place?)\n" + "=" * 100)
    for rel in ("main.py", "run_test_mode.py", "clean_tm_escaping.py", "apply_ai_notes.py", "src/voice_context.py", "src/api_handler.py", "src/ai_log.py", "src/translation_manager.py",
                "config/en/archetypes.json", "config/en/speaker_data.json", "config/en/translation_memory.json"):
        P("  " + _fingerprint(os.path.join(HERE, *rel.split("/"))))
    try:
        ms = open(os.path.join(HERE, "main.py"), encoding="utf-8", errors="replace").read()
        ah = open(os.path.join(HERE, "src", "api_handler.py"), encoding="utf-8", errors="replace").read()
        P("\n  version markers:")
        P(f"    main.py: AI call logging hooks = {ms.count('_ai_log(')} (expect 7); VOICE_DEBUG_DUMP = "
          f"{_grab(r'VOICE_DEBUG_DUMP = (\w+)', ms)}; QA_PUNCT_IN_CHAT = {_grab(r'QA_PUNCT_IN_CHAT = (\w+)', ms)}; "
          f"test mode support = {'_test_mode' in ms}")
        P(f"    api_handler.py: DEFAULT_TEMPERATURE = {_grab(r'DEFAULT_TEMPERATURE = ([0-9.]+)', ah)}; "
          f"MAX_EMPTY_RETRIES present = {'MAX_EMPTY_RETRIES' in ah}; defensive parser present = {'_extract_text' in ah}")
        ar = json.load(open(ARCHETYPES, encoding="utf-8"))["archetypes"]
        P(f"    archetypes.json: {sum(1 for v in ar.values() if v.get('ai_notes'))}/{len(ar)} archetypes have ai_notes; "
          f"D trigger-tied notes = {'not apologies' in ar.get('D', {}).get('ai_notes', '')}; "
          f"early-modern exempt = {sorted(k for k, v in ar.items() if v.get('allow_early_modern'))}")
        P(f"    main.py: reply clean-up (drops 《 》) hooks = {ms.count('vc.clean_reply(')} (expect 4); test mode skips DeepL = "
          f"{'NOT falling back to DeepL' in ms}")
        P(f"    api_handler.py: READ_TIMEOUT = {_grab(r'READ_TIMEOUT = (\d+)', ah)} s (it was a hard 15)")
        try:
            tmg = open(os.path.join(HERE, "src", "translation_manager.py"), encoding="utf-8", errors="replace").read()
            P(f"    translation_manager.py: idempotent sanitize present = {'def unsanitize_text' in tmg}; "
              f"main.py raw-text hooks = {ms.count('_raw_text(')} (expect 16)")
            if "def unsanitize_text" not in tmg:
                P("    !! src/translation_manager.py is the OLD one: it still re-escapes text on every save and load.")
        except Exception as _e:
            P(f"    (could not inspect translation_manager.py: {_e})")
        if ms.count("vc.clean_reply(") < 4 or "READ_TIMEOUT" not in ah:
            P("    !! main.py / api_handler.py are OLDER than expected: copy the latest versions.")
        if ms.count("_ai_log(") < 7 or "MAX_EMPTY_RETRIES" not in ah:
            P("    !! One or more files are OLDER than expected: copy the latest main.py and src/api_handler.py.")
    except Exception as e:
        P(f"  (could not inspect versions: {e})")

    P("\n" + "=" * 100 + "\n2. OFFLINE TEST RESULTS\n" + "=" * 100)
    n_fail = sum(1 for ok_, _ in RESULTS if not ok_)
    P(f"  {len(RESULTS) - n_fail} passed, {n_fail} failed; network connection attempts during the offline tests: {len(NET_ATTEMPTS)}"
      f" (sockets are blocked while they run)")
    for ok_, name in RESULTS:
        if not ok_:
            P(f"  FAIL  {name}")

    P("\n" + "=" * 100 + "\n3. TRANSLATION MEMORY\n" + "=" * 100)
    try:
        sp_n = sum(1 for e in entries if (e.get("context") or {}).get("speaker"))
        pat = lambda p: sum(bool(re.search(p, e["source"] + e["translation"])) for e in entries)
        P(f"  entries: {len(entries):,}; with a speaker: {sp_n:,}")
        P(f"  HTML-escaped text: single {pat(r'&(?:lt|gt|#x27|quot);'):,}; multiply escaped "
          f"{pat(r'&amp;(?:lt|gt|#x27|quot|amp);'):,}")
        _bad_br = [e for e in entries if "wrong_brackets" in [c for c, _ in vc.punct_issues(vc._clean(e["source"]), vc._clean(e["translation"]))]]
        _legacy = [e for e in entries if re.search(r"(?<!-)--(?!-)", vc._clean(e["translation"]))]
        P(f"  legacy '--' in approved lines: {len(_legacy):,} (JP source has ―― in {sum('――' in e['source'] for e in _legacy):,}). NOT changed: "
          "each needs a human choice between an em dash and ...; they are kept out of the AI's examples")
        P(f"  approved lines that break the glossary bracket rule (＜word＞ must be [word], not <word>): {len(_bad_br)}"
          + ("   <- exact TM matches will reuse these; run clean_tm_escaping.py (it fixes them)" if _bad_br else ""))
        for e in _bad_br[:8]:
            P("    JP: " + vc._clean(e["source"]).replace("\n", " / ")[:80])
            P("    EN: " + vc._clean(e["translation"]).replace("\n", " / ")[:100])
    except Exception as e:
        P(f"  (unavailable: {e})")

    P("\n" + "=" * 100 + "\n4. LIVE PROBE (small requests with your key; tells provider problems from prompt problems)\n" + "=" * 100)
    P(f"  status: {PROBE['status']}")
    if PROBE["rows"]:
        P(f"  sample: {PROBE['sample']}")
        P(f"\n  VERDICT: {PROBE['verdict']}\n")
        for r in PROBE["rows"]:
            P(f"  {r['id']}  {'OK       ' if r['ok'] else 'NO REPLY '} {r['seconds']:>5}s  prompt {r['prompt_chars']:>6} chars  "
              f"model {r['model']}   {r['name']}")
            if r.get("exception"):
                P(f"        exception: {r['exception']}")
            if r.get("http") not in (None, 200):
                P(f"        HTTP {r['http']}")
            if r.get("answered_by"):
                P(f"        answered by: {r['answered_by']}")
            if not r["ok"]:
                P(f"        why: {r.get('why') or r.get('api_error') or '-'}")
                P(f"        raw: {r.get('raw', '')[:1200]}")
            else:
                P(f"        reply: {r['text']!r}")

    calls = []
    if os.path.exists(CALL_LOG):
        for line in open(CALL_LOG, encoding="utf-8", errors="replace"):
            try:
                calls.append(json.loads(line))
            except Exception:
                pass
    P("\n" + "=" * 100 + f"\n5. AI CALLS RECORDED BY THE APP ({len(calls)} in ai_call_log.jsonl)\n" + "=" * 100)
    if calls:
        P(f"  newest call in this report: {calls[-1].get('time')}   (this report was generated {now:%Y-%m-%d %H:%M:%S}; "
          "calls made after that moment are NOT included: run a batch, close the app, and the launcher writes a fresh one)")
    if not calls:
        P("  none yet: run a batch (python run_test_mode.py), then run this script again.")
    else:
        oc = collections.Counter((c.get("outcome"), c.get("model_used") or c.get("model")) for c in calls)
        P("  outcomes by model:")
        for (o, m), n in oc.most_common():
            P(f"    {n:>4}  {o}  {m}")
        errs = collections.Counter((c.get("error") or "")[:160] for c in calls if c.get("outcome") != "ok")
        if errs:
            P("\n  failure reasons:")
            for e, n in errs.most_common(8):
                P(f"    {n:>4}  {e}")
        els = [c["elapsed"] for c in calls if isinstance(c.get("elapsed"), (int, float))]
        if els:
            P(f"\n  reply time: median {statistics.median(els):.1f}s, max {max(els):.1f}s over {len(els)} calls")
        rows = _metrics_by_archetype(calls)
        if rows:
            P("\n  PUNCTUATION vs SOURCE by archetype (successful calls). These rates should track the Japanese source:")
            P("    ('?' endings count JP か / かしら / だろう question forms as well as ？)")
            P("    arch   n | EN lines ending '?' (JP) | EN lines ending ... or dash (JP) | QA-flagged | retried")
            for a, n, qe, qj, te, tj, fl, rt in rows:
                P(f"    {a:<5}{n:>4} | {qe:>8.0%} ({qj:>4.0%})        | {te:>8.0%} ({tj:>4.0%})                | {fl:>6.0%}     | {rt:>5.0%}")
            P("    (archaic wording is deliberately NOT measured or judged here: how archaic a line should be is an editorial call)")
            try:
                dia = re.compile(r"\b\w{3,}in'(?=\W|$)|\bain't\b|\bmeself\b|(?<![A-Za-z])'em\b", re.I)
                seen = {c.get("archetype") for c in calls if c.get("outcome") == "ok"} - {None, ""}
                spk = sd["speaker_archetypes"]
                okc = [c for c in calls if c.get("outcome") == "ok" and c.get("output")]
                base = [vc._clean(e["translation"]) for e in entries if (e.get("context") or {}).get("speaker")
                        and spk.get(vc._norm_speaker(e["context"]["speaker"])) in seen]
                if okc and base:
                    P(f"    dialect spellings, informational only (-in', ain't, meself, 'em): AI {sum(bool(dia.search(c['output'])) for c in okc) / len(okc):.0%} of entries"
                      f"  vs  approved lines of the same archetypes {sum(bool(dia.search(x)) for x in base) / len(base):.0%} ({len(base)} lines)")
            except Exception as _e:
                P(f"    (dialect comparison unavailable: {_e})")

        P("\n" + "-" * 100 + f"\nLAST {min(LAST_CALLS_SHOWN, len(calls))} OF {len(calls)} CALLS\n" + "-" * 100)
        for c in calls[-LAST_CALLS_SHOWN:]:
            P(f"\n[{c.get('time')}] {c.get('kind')} {c.get('outcome').upper() if c.get('outcome') else '?'}  "
              f"item {c.get('item_id', '-')}  speaker {c.get('speaker')!r} ({c.get('archetype') or '-'})  "
              f"model {c.get('model_used') or c.get('model')}  {c.get('elapsed', '-')}s  attempts {c.get('attempts', '-')}"
              f"{'  TEST-MODE' if c.get('test_mode') else ''}")
            P(f"  voice block: {c.get('voice_chars', '-')} chars, {c.get('examples', '-')} TM examples")
            if c.get("glossary_n") is not None:
                _g = c.get("glossary") or []
                P(f"  glossary injected: {c.get('glossary_n')} term(s)" + ((": " + "; ".join(_g[:8]) + (" ..." if len(_g) > 8 else "")) if _g else ""))
            P("  JP: " + (c.get("jp") or c.get("user") or "").replace("\n", " / "))
            if c.get("first_output") and c.get("first_output") != c.get("output"):
                P("  FIRST REPLY (before QA retry): " + c["first_output"].replace("\n", " / "))
            if c.get("output"):
                P("  EN: " + c["output"].replace("\n", " / "))
                if _norm_key(c["output"]) in approved_by_src.get(_norm_key(c.get("jp") or ""), ()):
                    P("  !! IDENTICAL to the approved TM translation of this line: a copy (or the model was shown the answer); "
                      "do not count it as evidence of quality")
            if c.get("qa_flags") is not None:
                P(f"  QA flags after: {c.get('qa_flags') or 'clean'}{'   (a corrective retry happened)' if c.get('retried') else ''}")
            if c.get("error"):
                P("  ERROR: " + str(c["error"]))
            if c.get("raw"):
                P("  RAW: " + str(c["raw"])[:1500])

    for label, fn in (("LAST BATCH PROMPT (exactly what the model was sent)", "last_ai_request_batch.txt"),
                      ("LAST CHAT PROMPT", "last_ai_request_chat.txt")):
        pth = os.path.join(HERE, fn)
        P("\n" + "=" * 100 + f"\n6. {label}\n" + "=" * 100)
        P(open(pth, encoding="utf-8", errors="replace").read() if os.path.exists(pth) else "  (file not present yet)")

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"\nReport written to {REPORT_PATH}  ({os.path.getsize(REPORT_PATH):,} bytes): send me that file.")


try:
    run_probe()
except Exception:
    PROBE["status"] = "crashed: " + traceback.format_exc()[-800:]


check("no network access was attempted by this script's checks", not NET_ATTEMPTS)

print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} CHECK(S) FAILED: {fails}"))
sys.exit(1 if fails else 0)
