import os
import csv
import re

# Archetypes parsed from DDON_BIBLE_V2.txt Section 13.
ARCHETYPES = {
    "A": {
        "name": "Warm / Earnest",
        "professions": ["villager", "farmer", "healer", "innkeeper", "parent", "ordinary townsfolk"],
        "notes": (
            "Measured, sincere, full sentences, gentle hedging.\n"
            "Register: 'tis, aught, pray, afore, ere — used naturally.\n"
            "Hedging: \"I imagine...\", \"I should think...\", \"It seems...\", \"Mayhap...\""
        ),
        "pawn_map": "Ordinary, Shy",
    },
    "B": {
        "name": "Rough / Blunt",
        "professions": ["soldier", "guard", "bandit", "antagonist", "labourer", "mercenary"],
        "notes": (
            "Short clauses, punchy, direct. No hedging. Earthy vocabulary.\n"
            "Register: \"cos\" (cousin) casual address, \"o'\" for \"of\".\n"
            "Rhetorical questions. Light on archaic vocabulary."
        ),
        "pawn_map": "Peppy (battle cries), antagonists",
    },
    "C": {
        "name": "Cheerful / Mercantile",
        "professions": ["merchant", "shopkeeper", "innkeeper", "ferryman", "guild clerk", "artisan"],
        "notes": (
            "Warm but businesslike. Upbeat. Short sentences.\n"
            "Often ends with questions or invitations.\n"
            "Register: \"ser\" casual respectful, \"mind\" mild emphasis, \"daresay\"."
        ),
        "pawn_map": "Peppy (home/social lines)",
    },
    "D": {
        "name": "Timid / Young / Shy",
        "professions": ["child", "apprentice", "scared civilian", "refugee", "servant"],
        "notes": (
            "Incomplete sentences, trailing off, self-doubt, qualifications.\n"
            "Register: frequent \"...\", \"I know not\", \"pray, forgive me\".\n"
            "Self-deprecating but not broken."
        ),
        "pawn_map": "Shy pawn directly",
    },
    "E": {
        "name": "Formal / Military",
        "professions": ["knight", "captain", "duke's guard", "officer", "noble retainer", "ser"],
        "notes": (
            "Clipped, duty-focused, no-nonsense. Older honorifics.\n"
            "Register: \"ser\" and \"Arisen\" as address, \"to say naught of\",\n"
            "\"ill\" as qualifier. Short declarative sentences."
        ),
        "pawn_map": "Peppy (battle declarations, quest lines)",
    },
    "F": {
        "name": "Wisecracking / Irreverent",
        "professions": ["rogue", "traveling bard", "cynical merchant", "veteran adventurer", "barkeep"],
        "notes": (
            "Colloquial, self-aware humor, mild sarcasm.\n"
            "Archaic vocabulary used lightly.\n"
            "Register: \"cousin\"/\"cos\" casual address, \"s'pose\", \"naught\", rhetorical asides."
        ),
        "pawn_map": "Peppy (taunting lines)",
    },
    "G": {
        "name": "Devout / Clerical",
        "professions": ["priest", "cleric", "nun", "bishop", "temple keeper", "acolyte"],
        "notes": (
            "Calm, measured, reverent. Speaks with quiet authority.\n"
            "Often invokes faith, fate, or divine will.\n"
            "Register: 'mayhap', 'blessing', 'grace', 'divine', 'sin', 'fate'.\n"
            "Avoids slang. Rarely emotional; composed and solemn.\n"
            "Phrasing often feels sermonic or reflective."
        ),
        "pawn_map": "Shy / Calm support roles",
    },
}

# Modern→archaic replacements
IN_UNIVERSE_VOCAB = {
    "actually": "in truth",
    "alright": "very well",
    "alrighty": "very well",
    "among": "amidst",
    "anything": "aught",
    "apart": "sunder",
    "are": "art",
    "aren't": "are not",
    "aren't they": "are they not",
    "aren't you": "are you not",
    "awesome": "magnificent",
    "barely": "scarce",
    "basically": "in short",
    "belike": "belike",
    "probably": "belike",
    "before": "ere",
    "if ever": "ifsoe'er",
    "before long": "erelong",
    "between": "betwixt",
    "by chance": "haply",
    "bye": "fare well",
    "can't": "cannot",
    "command": "behest",
    "cool": "fine",
    "couldn't": "could not",
    "couldn't he": "could he not",
    "couldn't it": "could it not",
    "couldn't she": "could she not",
    "couldn't they": "could they not",
    "couldn't you": "could you not",
    "creature": "wight",
    "curse": "bane",
    "daren't": "dare not",
    "delay": "tarry",
    "did you not": "did you not",
    "didn't": "did not",
    "didn't he": "did he not",
    "didn't it": "did it not",
    "didn't she": "did she not",
    "didn't they": "did they not",
    "didn't you": "did you not",
    "dire": "dire",
    "do they not": "do they not",
    "do you not": "do you not",
    "doesn't": "does not",
    "doesn't he": "does he not",
    "doesn't it": "does it not",
    "doesn't she": "does she not",
    "don't": "do not",
    "don't they": "do they not",
    "don't you": "do you not",
    "dunno": "I know not",
    "early": "betimes",
    "ever": "e'er",
    "evil": "bane",
    "for fear that": "lest",
    "forsooth": "forsooth",
    "forward": "forth",
    "from here": "hence",
    "from now on": "henceforth",
    "from where": "whence",
    "gladly": "fain",
    "happy": "fain",
    "inclined": "fain",
    "pleased": "fain",
    "gonna": "going to",
    "good": "goodly",
    "goodbye": "farewell",
    "gotta": "must",
    "hadn't": "had not",
    "hadn't he": "had he not",
    "hadn't it": "had it not",
    "hadn't she": "had she not",
    "hadn't they": "had they not",
    "hadn't you": "had you not",
    "handsome": "goodly",
    "hardly": "scarce",
    "hasn't": "has not",
    "hasn't he": "has he not",
    "hasn't it": "has it not",
    "hasn't she": "has she not",
    "hasn't they": "has they not",
    "haven't": "have not",
    "haven't they": "have they not",
    "haven't you": "have you not",
    "hello": "hail",
    "hi": "hail",
    "hit": "smite",
    "honestly": "in truth",
    "immediately": "forthwith",
    "in short": "in short",
    "in truth": "forsooth",
    "is he not": "is he not",
    "is it not": "is it not",
    "is she not": "is she not",
    "isn't": "is not",
    "isn't he": "is he not",
    "isn't it": "is it not",
    "isn't she": "is she not",
    "it is": "'tis",
    "it seems to me": "methinks",
    "it was": "'twas",
    "it were": "'twere",
    "it will": "'twill",
    "it would": "'twould",
    "jest": "jest",
    "joke": "jest",
    "kinda": "somewhat",
    "look": "lo",
    "middle": "amidst",
    "morning": "morrow",
    "most inqu": "inquest",
    "most wis": "wisest",
    "mustn't": "must not",
    "mustn't he": "must he not",
    "mustn't it": "must it not",
    "mustn't she": "must she not",
    "mustn't they": "must they not",
    "mustn't you": "must you not",
    "near": "nigh",
    "nearly": "nigh",
    "needn't": "need not",
    "never": "ne'er",
    "no": "nay",
    "nope": "nay",
    "nothing": "naught",
    "often": "ofttimes",
    "okay": "aye",
    "over": "o'er",
    "perhaps": "perchance",
    "please": "prithee",
    "primary": "main",
    "principal": "main",
    "really": "truly",
    "relative": "kinsman",
    "request": "behest",
    "see": "behold",
    "separated": "sunder",
    "shame": "fie",
    "disapprove": "fie",
    "shortly": "anon",
    "shouldn't": "should not",
    "shouldn't he": "should he not",
    "shouldn't it": "should it not",
    "shouldn't she": "should she not",
    "shouldn't they": "should they not",
    "shouldn't you": "should you not",
    "soon": "anon",
    "sorry": "forgive me",
    "sorta": "somewhat",
    "strange": "queer",
    "strike": "smite",
    "sure": "aye",
    "tarry": "tarry",
    "terrible": "dire",
    "therefore": "wherefore",
    "to where": "whither",
    "tomorrow": "morrow",
    "totally": "quite",
    "toward": "unto",
    "travel": "wend",
    "truly": "truly",
    "urgent": "dire",
    "very": "most",
    "very little": "scant",
    "wait": "tarry",
    "wanna": "wish to",
    "was he not": "was he not",
    "was it not": "was it not",
    "was she not": "was she not",
    "wasn't": "was not",
    "wasn't he": "was he not",
    "wasn't it": "was it not",
    "wasn't she": "was she not",
    "weird": "queer",
    "were not": "were not",
    "were they not": "were they not",
    "were you not": "were you not",
    "weren't": "were not",
    "weren't they": "were they not",
    "weren't you": "were you not",
    "whatever": "whate'er",
    "whenever": "whene'er",
    "wherever": "where'er",
    "will": "wilt",
    "will he not": "will he not",
    "will it not": "will it not",
    "will not": "will not",
    "will she not": "will she not",
    "will you not": "will you not",
    "willingly": "fain",
    "won't": "will not",
    "won't he": "will he not",
    "won't it": "will it not",
    "won't she": "will she not",
    "won't they": "will they not",
    "won't you": "will you not",
    "would he not": "would he not",
    "would it not": "would it not",
    "would she not": "would she not",
    "would you not": "would you not",
    "wouldn't": "would not",
    "wouldn't he": "would he not",
    "wouldn't it": "would it not",
    "wouldn't she": "would she not",
    "wouldn't you": "would you not",
    "yeah": "aye",
    "yep": "aye",
    "yes": "yea",
    "you": "ye",
    "enough": "enow",
    "frightened": "afeard",
    "frighten": "affright",
    "attempt": "assay",
    "apart": "asunder",
    "recollect": "bethink",
    "remember": "bethink",
    "entrust": "commend",
    "corpse": "corse",
    "corpse": "carrion",
    "cousin": "coz",
    "domain": "demesne",
    "avert": "forfend",
    "prevent": "forfend",
    "here": "hence",
    "there": "thence",
    "quickly": "anon",
    "repulsive": "loathly",
    "bewildered": "mazed",
    "charm": "periapt",
    "amulet": "periapt",
    "clothing": "raiment",
    "punish": "recompense",
    "reward": "recompense",
    "coward": " recreant",
    "cowardly": " recreant",
    "stain": "soil",
    "truth": "verity",
    "truth": "sooth",
    "defeat": "vanquish",
    "defeat": "smite",
    "conquer": "vanquish",
    "conquer": "smite",
    "to that": "thereunto",
    "three": "thrice",
    "tenth": "tithe",
    "faith": "troth",
    "loyalty": "troth",
    "a year": "twelvemonth",
    "wagon": "wain",
    "cart": "wain",
    "at which": "whereat",
    "by which": "whereby",
    "in which": "wherein",
    "on which": "whereon",
    "to what place": "whither",
    "builder": "wright",
    "maker": "wright",
    "over there": "yonder",



}


ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())

class LoreEngine:
    def __init__(self):
        self.archetypes = ARCHETYPES
        self.memory = {}  # track speaker -> archetype assignments
        self.lore_map = {
            "剛化": "Harden",
            "重化": "Heavy",
            "癒活": "Restoration",
            "守護": "Protection",
            "柔化": "Weaken",
            "集視": "Attention",
            "無恐": "Fearless",
            "集中": "Concentration",
            "蘇生": "Resurrection"
        }

    def load_data(self, bible_path, glossary_path):
        for path in [bible_path, glossary_path]:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    content = f.read(1024)
                    f.seek(0)
                    try:
                        dialect = csv.Sniffer().sniff(content) if ',' in content or '\t' in content else 'excel'
                    except csv.Error:
                        dialect = 'excel'

                    reader = csv.reader(f, dialect=dialect)
                    for row in reader:
                        if len(row) >= 2 and row[0].strip():
                            self.lore_map[row[0].strip()] = row[1].strip()
            except Exception as e:
                print(f"Lore Engine Error on {path}: {e}")

    def scan_text(self, jp_text):
        if not jp_text: return []
        matches = []
        for jp_term, en_term in self.lore_map.items():
            if jp_term in jp_text:
                matches.append((jp_term, en_term))
        return matches

    # ---------------- Archetype Handling ----------------
    def get_archetype_options(self):
        """Return (key, name) pairs for dropdown without professions."""
        return [(key, data["name"]) for key, data in self.archetypes.items()]

    def get_archetype_label(self, key):
        if key not in self.archetypes:
            return "(none)"
        return self.archetypes[key]["name"]

    def get_archetype_hint_for_speaker(self, speaker_name):
        """Return notes for a speaker based on assigned archetype."""
        archetype_key = self.memory.get(speaker_name)
        if not archetype_key or archetype_key not in self.archetypes:
            return "(none)"
        return self.archetypes[archetype_key].get("notes", "")

    # ---------------- In-Universe Replacements ----------------
    def get_in_universe_replacements(self):
        return {k: v for k, v in IN_UNIVERSE_VOCAB.items() if v is not None}

    def scan_anachronisms(self, en_text):
        if not en_text: return []

        sorted_keys = sorted(IN_UNIVERSE_VOCAB.keys(), key=lambda x: -len(x))
        hits = []

        for modern in sorted_keys:
            archaic = IN_UNIVERSE_VOCAB[modern]
            pattern = re.escape(modern) if " " in modern else r'\b' + re.escape(modern) + r'\b'
            for m in re.finditer(pattern, en_text, flags=re.IGNORECASE):
                hits.append((m.group(0), archaic))

        # Deduplicate
        seen = set()
        unique = []
        for found, suggestion in hits:
            key = found.lower()
            if key not in seen:
                seen.add(key)
                unique.append((found, suggestion))
        return unique

    def apply_in_universe(self, en_text):
        """Replace text where possible, flag-only terms returned separately."""
        replacements = self.get_in_universe_replacements()
        flags = []
        sorted_keys = sorted(IN_UNIVERSE_VOCAB.keys(), key=lambda x: -len(x))

        def replace_match(match):
            word = match.group(0)
            lower = word.lower()
            if lower in replacements:
                return replacements[lower]
            elif lower in IN_UNIVERSE_VOCAB and IN_UNIVERSE_VOCAB[lower] is None:
                flags.append(word)
            return word

        pattern = r'|'.join(
            re.escape(k) if " " in k else r'\b' + re.escape(k) + r'\b'
            for k in sorted_keys
        )
        new_text = re.sub(pattern, replace_match, en_text, flags=re.IGNORECASE)
        return new_text, flags