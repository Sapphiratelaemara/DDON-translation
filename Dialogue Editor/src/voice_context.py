"""
voice_context.py -- character-voice prompt building and output QA for the DDON
AI translation paths (batch pre-translate AND editor chat).

Why this exists
---------------
* The two call sites used to build the voice context differently and both
  injected it twice. Now there is ONE builder (build_voice_block) and the
  context appears once, in the system prompt.
* Archetype notes describe a character's *diction*. Structural habits
  ("often ends on a question", "trailing off") were being applied to every
  line. Model-facing text now comes from the archetype's optional `ai_notes`
  field (falls back to the human-facing `notes`), wrapped in text that says
  sentence type and punctuation come from the SOURCE only.
* Few-shot examples are real approved JP->EN pairs from the translation
  memory (same speaker, else same archetype), chosen to match the current
  line's punctuation profile, so the model sees that punctuation follows the
  source.
* punct_issues() is a cheap post-check, calibrated against the 1,032
  speaker-tagged approved TM entries (false-positive rates in the comments).
"""
import html
import re
from collections import defaultdict

# --------------------------------------------------------------------------
# Reply filters
# --------------------------------------------------------------------------

_NAME_BRACKETS = re.compile("[《》]")
NORMALIZE_DOUBLE_HYPHEN = True   # set False to leave the model's "--" as typed
_DOUBLE_HYPHEN = re.compile(r"(?<!-)--(?!-)")
_DOUBLE_HYPHEN_OR_TAG = re.compile(r"<[^<>]*>|(?<!-)--(?!-)")

# Exactly the five replacements html.escape() makes (and nothing else).
_ESCAPES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#x27;", "'"), ("&#39;", "'"), ("&amp;", "&"))


def raw_text(text):
    """Undo HTML escaping completely, however many levels (&amp;amp;amp;quot; -> "). The translation manager stores text
    HTML-escaped, and the 'Pre-translated Unapproved' queue hands that stored text to the UI, which passes it back to the
    backend as if it were raw. Raw text passes through unchanged; non-strings are returned as they are."""
    if not isinstance(text, str) or "&" not in text:
        return text
    for _ in range(500):   # every save/restart used to add one level, so old data can carry dozens
        new = text
        for escaped, raw in _ESCAPES:
            new = new.replace(escaped, raw)
        if new == text:
            break
        text = new
    return text


def clean_reply(text, src=""):
    """Deterministic clean-up applied to every AI reply, so it never depends on the model remembering:
    * the 《 》 name brackets are dropped and the name stands bare ("《Miranda》" -> "Miranda");
    * a source fullwidth ＜word＞ is rendered [word] per the glossary, never the ASCII <word> (an engine-tag lookalike)."""
    out = _NAME_BRACKETS.sub("", text or "")
    for word in _FW_BRACKET_WORD.findall(src or ""):
        out = out.replace(f"<{word}>", f"[{word}]")
    if NORMALIZE_DOUBLE_HYPHEN:
        # A model that types "--" has chosen a DASH (not an ellipsis), and the house rule allows only "..." or an em dash.
        # Angle-bracket tags are skipped. (This is about the AI's own output only: the "--" in the old TM is a relic whose
        # right replacement, em dash or ellipsis, is a human decision, so the TM is never auto-converted.)
        out = _DOUBLE_HYPHEN_OR_TAG.sub(lambda m: m.group(0) if m.group(0).startswith("<") else "—", out)
    return out

# Some routers (openrouter/auto, openrouter/free) occasionally land on a safety
# classifier and the "translation" is just its verdict. Never accept or cache
# those.
_BAD_REPLY_PREFIXES = ("user safety", "openrouter error")


def is_bad_reply(text):
    """True for empty replies and classifier / error strings that are not a translation."""
    s = (text or "").strip().lstrip("{[\"' \n\t").lower()
    return (not s) or s.startswith(_BAD_REPLY_PREFIXES)


# Closed list instead of the old \w+est / \w+eth regex, which flagged
# best / rest / west / quest / honest / forest / interest, etc.
_EARLY_MODERN_WORDS = {
    "thou", "thee", "thy", "thine", "thyself", "ye",  # 'ye' is checked below only as a pronoun
    "thinkest", "dost", "doth", "hath", "hast", "makest", "maketh", "goest", "goeth",
    "doest", "sayest", "saith", "comest", "cometh", "wilt", "wouldst", "couldst",
    "shouldst", "didst", "knowest", "seest", "canst", "shalt", "speakest",
    "wert", "hadst", "mayest", "givest", "seeth", "knoweth",
}
_EM_WORDS_NO_YE = _EARLY_MODERN_WORDS - {"ye"}
_YE_PRONOUN = re.compile(r"\b(?:think|know|say|see|do|have|are|will|shall|would|could)\s+ye\b"
                         r"|\bye\s+(?:are|have|do|shall|will|would|could|think|know|must|may)\b", re.I)
_YOU_ART = re.compile(r"\b(?:who|that|where|how|what|whom|which|thou|you)\s+art\b", re.I)


def contains_early_modern(text):
    """True if text uses thou/thee/-est/-eth style English (closed word list)."""
    if not text:
        return False
    lowered = text.lower().replace("\u2019", "'")
    words = set(re.findall(r"[a-z']+", lowered))
    if words & _EM_WORDS_NO_YE:
        return True
    return bool(_YE_PRONOUN.search(lowered) or _YOU_ART.search(lowered))


# --------------------------------------------------------------------------
# Punctuation QA
# --------------------------------------------------------------------------
# Calibration (approved speaker-tagged TM entries, humans' own output):
#   more '?' than JP (excluding か-endings) .......................... ~8 %  of approved entries
#   more pause marks than JP marks + CONTINUING line breaks .......... ~12 %
#       (JP marks only: 34 %.  Allowing one per ANY line break: 3 %, but that missed every added
#        pause in a real 10-entry batch, because entries are 3-4 lines long.)
#   fewer '!' than JP '！' ........................................... ~1 %
# A "continuing" break is a JP line break after a line that does not look sentence-final.
# These are flags for a single corrective retry, not hard rejections.

_PAUSE_JP = re.compile(r"…|‥|―+|ー{2,}|・{2,}|\.{2,}")
_PAUSE_EN = re.compile(r"\.{3}|…|—|–|―|(?<!-)--(?!-)")  # "--" counts: it is a pause too
# Japanese question endings: か, かしら, かな(ぁ), かい, かね, かよ, だろうか, でしょうか, and the tag forms だろう(な) /
# でしょう / よね / よな (optionally followed by ！ etc.). Without the tag forms, "...じゃねぇだろうな" -> "eh?" and
# "...んだよねー" -> "don't they?" were wrongly flagged. Plain のね / わね statements are deliberately NOT included.
_KA_END = re.compile(r"(?:か|かしら|かな|かなぁ|かなあ|かい|かね|かよ|だろうか|でしょうか|だろう|だろ|でしょう|でしょ|よね|よな)[なねよ]?[\s」』）)！!ー～]*(?:\n|$)")
# A JP line that ends like this is a finished sentence, so the break after it is not a "continuing" break.
_SENT_END = re.compile(r"[！？!?。」』）)]$|(?:です|ます|でした|ました|ません|ですね|ますね|だよ|だね|よ|ね|わ|ぞ|ぜ|か|な|の|さ|た|い|ない|ん|う|る)$")


def _continuation_breaks(src):
    """Line breaks after which the Japanese sentence keeps going (a pause there is legitimate)."""
    lines = [l.strip() for l in (src or "").split("\n") if l.strip()]
    n = 0
    for l in lines[:-1]:
        if _PAUSE_JP.search(l[-2:]):
            continue  # that break already carries its own source pause mark
        if _CONT_NE.search(l) or not _SENT_END.search(l):
            n += 1
    return n


# Japanese wh-questions need no ？ or か: どうした, なぜ沈んでいる, 誰が, どこへ ... ("どうぞ" / "どうも" are not questions)
_WH = re.compile(r"なぜ|どうして|どうした|何|なに|誰|だれ|どこ|いつ|どれ|どちら|いくつ|どう(?!ぞ|も)")
_ELONG = re.compile(r"[ぁ-ん]ー")          # そっかー, よーく: an elongated vowel is a legitimate pause in the English
_CONT_NE = re.compile(r"[はとでにもをが]ね[、]?$")  # ...はね / ...でね: topic/connective + ね, the sentence continues next line
_FW_BRACKET_WORD = re.compile(r"＜([A-Za-z][A-Za-z0-9 ]{0,14})＞")


# Switches for the three "source decides" checks added 2026-11-21 (found in the real batch reports).
# Each flag triggers ONE corrective retry, like the older checks. Set a switch to False to turn that check off.
CHECK_ADDED_EXCLAMATION = True      # source line has no ！ at all, reply ends a sentence with "!"
CHECK_LOST_QUESTION = True          # source has a ？ but the reply contains no "?" at all
CHECK_ADDED_QUOTES = True            # reply has more quotation marks than the source (the prompt says: no quotation marks)
_SRC_QUOTES = "\"\u201c\u201d\u300c\u300d\u300e\u300f\uff1c\uff1e\u226a\u226b\u300a\u300b\u3008\u3009"
_OUT_QUOTES = "\"\u201c\u201d"
# OFF by default: the prompt says whether a trailing ―― becomes "...", an em dash or NOTHING is the model's call,
# so dropping it is not an error under the written rules. Turn on only if you want the closing pause kept.
CHECK_LOST_TRAILING_PAUSE = False

_TRAIL_PAUSE_JP = re.compile(r"(?:―+|…+|‥+)[\s」』）)]*$")
_TRAIL_PAUSE_EN = re.compile(r"(?:\.{3}|…|—|–|―|(?<!-)--(?!-))[\s\"'\u201d\u2019)\]]*$")


def _counts(src, out):
    src = src or ""
    out = out or ""
    return {
        "sq": src.count("？") + src.count("?"),
        "oq": out.count("?"),
        "sp": len(_PAUSE_JP.findall(src)) + len(_ELONG.findall(src)),
        "op": len(_PAUSE_EN.findall(out)),
        "nl": _continuation_breaks(src),
        "sx": src.count("！") + src.count("!"),
        "ox": out.count("!"),
        "ka": bool(_KA_END.search(src)),
    }


def punct_issues(src, out, strict=False):
    """Return a list of (code, message) describing punctuation the source does not support.
    strict=True drops the one-pause-per-JP-line-break allowance (used to vet few-shot examples)."""
    c = _counts(src, out)
    issues = []
    if c["oq"] > c["sq"] and not c["ka"] and not _WH.search(src or ""):
        issues.append((
            "added_question",
            f"Your reply has {c['oq']} question mark(s) but the source has {c['sq']}. "
            "A source statement must stay a statement: end it with a period (or the source's own mark)."))
    allowed = c["sp"] if strict else c["sp"] + c["nl"]
    if c["op"] > allowed:
        issues.append((
            "added_pause",
            f"Your reply has {c['op']} pause mark(s) (\"...\" or \"—\") but the source supports at most {allowed}. "
            "Pauses come only from ――, …, ‥, or a clause that continues on the next line (you choose "
            "\"...\", \"—\" or nothing for each). Remove the extras, using a comma or a rephrase where needed so the sentence "
            "still reads naturally; end finished sentences with a period."))
    if c["ox"] < c["sx"]:
        issues.append((
            "lost_exclamation",
            f"The source has {c['sx']} exclamation mark(s) but your reply has {c['ox']}. Keep the exclamations."))
    if CHECK_ADDED_EXCLAMATION and c["sx"] == 0 and c["ox"] > 0:
        issues.append((
            "added_exclamation",
            f"Your reply has {c['ox']} exclamation mark(s) but the source line has none. Exclamations come only from "
            "the source's own ！: end the sentence with a period (or the source's own mark)."))
    if CHECK_LOST_QUESTION and c["sq"] > 0 and c["oq"] == 0:
        issues.append((
            "lost_question",
            f"The source has {c['sq']} question mark(s) but your reply has none. Keep the question and end it with \"?\"."))
    if CHECK_ADDED_QUOTES:
        sq_ = sum((src or "").count(ch) for ch in _SRC_QUOTES)
        oq_ = sum((out or "").count(ch) for ch in _OUT_QUOTES)
        if oq_ > sq_:
            issues.append((
                "added_quotes",
                f"Your reply has {oq_} quotation mark(s) but the source has {sq_}. Do not wrap lines in quotation marks: "
                "quote only the words the source itself quotes."))
    if CHECK_LOST_TRAILING_PAUSE:
        s_ = (src or "").rstrip()
        o_ = (out or "").rstrip()
        if _TRAIL_PAUSE_JP.search(s_) and not _TRAIL_PAUSE_EN.search(o_):
            issues.append((
                "lost_trailing_pause",
                "The source line ends on a trailing pause (―― or …). End your reply with \"...\" or \"—\" to match."))
    for word in _FW_BRACKET_WORD.findall(src or ""):
        if f"<{word}>" in (out or ""):
            issues.append((
                "wrong_brackets",
                f"The source's fullwidth ＜{word}＞ must be written [{word}] (glossary), not <{word}>: ASCII < > are engine "
                "tags and must only ever be copied from the source."))
    if strict and (c["oq"] != c["sq"] or c["ox"] != c["sx"]) and not issues:
        issues.append(("marks_differ", "question/exclamation marks do not match the source one-to-one"))
    return issues


# --------------------------------------------------------------------------
# Prompt text
# --------------------------------------------------------------------------

VOICE_HEADER = (
    "CHARACTER VOICE — WORD CHOICE ONLY:\n"
    "The notes below tell you how this speaker chooses words: vocabulary, forms of address, formality and "
    "contraction habits. They say nothing about sentence shape. Whether a line is a statement, a question, an "
    "exclamation or a trailing thought is decided by the SOURCE line alone.\n"
    "- A statement stays a statement. Do not turn it into a question or invite a reply the source does not make.\n"
    "- Keep every ！ as \"!\" and every ？ as \"?\".\n"
    "- Question forms without ？ (か, かしら, かな, だろう, でしょう, よね, だよね) are real questions: keep the \"?\" "
    "(\"don't they?\", not \"don't they.\"). Plain のね / わね statements stay statements.\n"
    "- Pauses (\"...\" or \"—\") come only from ――, …, ‥, or a clause that continues onto the next line. Choosing "
    "between \"...\", \"—\" or nothing is your call; adding them to show shyness, hesitation or any other "
    "personality trait is not.\n"
    "- Traits in the notes are possibilities, not requirements. Many lines will show none of them.\n"
    "- Casual speech comes from plain words and contractions. Dropped g's (-in'), 'em, meself and ain't are occasional "
    "seasoning (about one approved line in ten), not the default; use them only where the notes call for a rough voice.\n"
    "- Add no people, events, jokes or asides that are not in the source line.\n"
)


# Used instead of VOICE_HEADER when the system prompt already carries its own
# "CHARACTER VOICE (word choice only ...)" and "PUNCTUATION" paragraphs, so the rules are not stated twice.
VOICE_HEADER_SHORT = (
    "ARCHETYPE AND SPEAKER NOTES:\n"
    "Traits in the notes are possibilities, not requirements: many lines will show none of them. "
    "Question forms without ？ (か, かしら, だろう, でしょう, よね, だよね) are real questions and keep their \"?\" "
    "(\"don't they?\", not \"don't they.\"). "
    "Casual speech comes from plain words and contractions; dropped g's (-in'), 'em, meself and ain't are occasional "
    "seasoning (about one approved line in ten), not the default. "
    "Add no people, events, jokes or asides that are not in the source line.\n"
)


def get_archetype_voice(archetypes, key):
    """Model-facing archetype text: `ai_notes` if present, else the human `notes`."""
    rec = (archetypes or {}).get(key) or {}
    return (rec.get("ai_notes") or rec.get("notes") or "").strip()


def build_voice_block(speaker, archetype_key, archetypes, speaker_note="", examples_text="", short_header=False):
    """One block, injected ONCE into the system prompt. Returns '' if there is nothing to say."""
    parts = []
    voice = get_archetype_voice(archetypes, archetype_key)
    if voice:
        parts.append(f"ARCHETYPE VOICE FOR {speaker or 'SPEAKER'}:\n{voice}")
    note = (speaker_note or "").strip()
    if note:
        parts.append(
            f"WHO {speaker or 'THE SPEAKER'} IS (background only — never add its events or jokes to the line):\n{note}")
    if examples_text:
        parts.append(examples_text)
    if not parts:
        return ""
    return (VOICE_HEADER_SHORT if short_header else VOICE_HEADER) + "\n" + "\n\n".join(parts)


# --------------------------------------------------------------------------
# TM-backed examples
# --------------------------------------------------------------------------

def _flat(text):
    """Whitespace-insensitive key: the CSV text has CRLF / trailing spaces, the TM source does not."""
    return re.sub(r"\s+", "", text or "")


def _norm_speaker(name):
    return html.unescape(name or "").strip()


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def _clean(text):
    """Un-escape HTML entities and use straight quotes, as in the house-style examples.
    Unescapes repeatedly: some TM entries are escaped several times (&amp;amp;lt; ...)."""
    t = text or ""
    for _ in range(5):
        n = html.unescape(t)
        if n == t:
            break
        t = n
    return t.translate(_QUOTES)


def _profile(src):
    """(has_question, has_pause, has_exclamation) of a Japanese source."""
    return (("？" in src or "?" in src),
            bool(_PAUSE_JP.search(src)),
            ("！" in src or "!" in src))


def _iter_entries(entries):
    if isinstance(entries, dict):
        return entries.values()
    return entries or []


class ExampleIndex:
    """Approved TM entries that carry a speaker, indexed by speaker and by archetype."""

    MAX_SRC_CHARS = 120
    MAX_LINES = 4

    def __init__(self, entries, speaker_archetypes):
        self.by_speaker = defaultdict(list)
        self.by_archetype = defaultdict(list)
        spk_arch = {_norm_speaker(k): v for k, v in (speaker_archetypes or {}).items() if v}
        for e in _iter_entries(entries):
            if not isinstance(e, dict):
                continue
            ctx = e.get("context") or {}
            sp = _norm_speaker(ctx.get("speaker"))
            # The TM holds some HTML-escaped text (&#x27; &quot; ...): never show that to the model.
            src, tr = _clean(e.get("source")), _clean(e.get("translation"))
            if not sp or not src.strip() or not tr.strip():
                continue
            if e.get("quality") not in (None, "approved"):
                continue
            if len(src) > self.MAX_SRC_CHARS or src.count("\n") + 1 > self.MAX_LINES:
                continue
            if punct_issues(src, tr, strict=True):
                continue  # only offer examples that obey the very rules the prompt states
            if _DOUBLE_HYPHEN.search(tr):
                continue  # legacy "--" (from before the team knew ―― means em dash OR ellipsis): never teach it
            item = (src, tr, _profile(src), sp)
            self.by_speaker[sp].append(item)
            arch = spk_arch.get(sp)
            if arch:
                self.by_archetype[arch].append(item)

    def pick(self, speaker, archetype_key, current_src, n=3):
        """Choose up to n approved pairs. Most match the current line's punctuation
        profile (so the model sees source-driven punctuation); one contrasts."""
        speaker = _norm_speaker(speaker)
        cur = _profile(current_src or "")
        cur_flat = _flat(current_src)
        seen, pool = set(), []
        for src, tr, prof, sp in self.by_speaker.get(speaker, []):
            key = _flat(src)
            if key != cur_flat and key not in seen:
                seen.add(key)
                pool.append((src, tr, prof, True))
        if len(pool) < n * 2 and archetype_key:
            for src, tr, prof, sp in self.by_archetype.get(archetype_key, []):
                key = _flat(src)
                if sp != speaker and key != cur_flat and key not in seen:
                    seen.add(key)
                    pool.append((src, tr, prof, False))
        if not pool:
            return []
        cur_len = len(current_src or "")

        def rank(item):
            src, _tr, prof, same = item
            return (prof != cur, not same, abs(len(src) - cur_len))

        matching = sorted([p for p in pool if p[2] == cur], key=rank)
        other = sorted([p for p in pool if p[2] != cur], key=rank)
        chosen = matching[: max(1, n - 1)] + other[:1]
        if len(chosen) < n:
            chosen += [p for p in (matching[max(1, n - 1):] + other[1:]) if p not in chosen][: n - len(chosen)]
        return [(s, t) for s, t, _p, _same in chosen[:n]]


_EN_LINE_FINAL = re.compile(r"""[.!?…—"')\]]\s*$""")


def format_examples(pairs):
    """Format approved pairs. The game needs hand-wrapped lines, so English wrapping
    is not a style to imitate: collapse it unless the line counts match."""
    if not pairs:
        return ""
    out = ["APPROVED TRANSLATIONS (reference for phrasing and punctuation habits — not the current line, "
           "and not content to reuse):"]
    for src, tr in pairs:
        src, tr = _clean(src), _clean(tr)
        sl = [l for l in src.split("\n") if l.strip()]
        tl = [l for l in tr.split("\n") if l.strip()]
        # The TM's English is hand-wrapped for the game UI ("...exterminating / them time and again."). Keep the line
        # breaks only when each EN line is a finished clause; otherwise flow it, so the model is not taught to wrap.
        if len(sl) != len(tl) or not all(_EN_LINE_FINAL.search(l) for l in tl):
            tl = [" ".join(l.strip() for l in tl)]
        out.append("JP: " + "\nJP: ".join(l.strip() for l in sl))
        out.append("EN: " + "\nEN: ".join(l.strip() for l in tl))
        out.append("")
    return "\n".join(out).rstrip()


_INDEX_CACHE = {"sig": None, "obj": None}


def get_index(tm_entries, speaker_archetypes):
    """Cached ExampleIndex; rebuilt when the TM size or speaker->archetype map changes."""
    try:
        n = len(tm_entries)
    except TypeError:
        n = -1
    sig = (n, len(speaker_archetypes or {}))
    if _INDEX_CACHE["sig"] != sig or _INDEX_CACHE["obj"] is None:
        _INDEX_CACHE["obj"] = ExampleIndex(tm_entries, speaker_archetypes)
        _INDEX_CACHE["sig"] = sig
    return _INDEX_CACHE["obj"]
