import os
import csv
import re

# Archetypes parsed from DDON_BIBLE_V2.txt Section 13.
# Each entry: display name, typical roles/professions, register notes, pawn personality mapping.
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
}

# Modern→archaic replacements derived from Bible Sections 4 & 5.
# Keys are modern words (lowercase), values are the preferred in-universe form.
# Only unambiguous single-word swaps are included — syntactic inversions are excluded.
IN_UNIVERSE_VOCAB = {
    # Direct attested equivalents (Section 5)
    "it is":    "'tis",
    "it was":   "'twas",
    "it will":  "'twill",
    "it were":  "'twere",
    "over":     "o'er",
    "ever":     "e'er",
    "never":    "ne'er",
    "wherever": "where'er",
    "whenever": "whene'er",
    "whatever": "whate'er",
    "anything": "aught",
    "nothing":  "naught",
    "before":   "afore",
    "perhaps":  "mayhap",
    "near":     "nigh",
    "nearly":   "nigh",
    "immediately": "forthwith",
    "from now on": "henceforth",
    "often":    "ofttimes",
    "early":    "betimes",
    "please":   "prithee",
    "in truth": "forsooth",
    "it seems to me": "methinks",
    "by chance": "haply",
    "travel":   "wend",
    "barely":   "scarce",
    "hardly":   "scarce",
    "very little": "scant",
    "immediately": "forthwith",
    # Common anachronisms to flag/replace
    "okay":     "aye",
    "ok":       "aye",
    "yeah":     "aye",
    "yep":      "aye",
    "nope":     "nay",
    "hi":       "hail",
    "hello":    "hail",
    "goodbye":  "farewell",
    "bye":      "fare well",
    "sorry":    "forgive me",
    "thanks":   "my thanks",
    "alright":  "very well",
    "alrighty": "very well",
    "sure":     "aye",
    "totally":  "quite",
    "awesome":  "magnificent",
    "cool":     "fine",
    "weird":    "queer",
    "strange":  "queer",
    "really":   "truly",
    "very":     "most",
    "actually": "in truth",
    "basically": "in short",
    "honestly": "in truth",
    "like":     None,  # flag only, no clean replacement
    "gonna":    "going to",
    "wanna":    "wish to",
    "gotta":    "must",
    "kinda":    "somewhat",
    "sorta":    "somewhat",
    "dunno":    "I know not",
    "can't":    "cannot",
    "won't":    "will not",
    "don't":    "do not",
    "doesn't":  "does not",
    "isn't":    "is not",
    "wasn't":   "was not",
    "aren't":   "are not",
    "weren't":  "were not",
    "hadn't":   "had not",
    "haven't":  "have not",
    "hasn't":   "has not",
    "didn't":   "did not",
    "wouldn't": "would not",
    "couldn't": "could not",
    "shouldn't": "should not",
    "mustn't":  "must not",
    "needn't":  "need not",
    "daren't":  "dare not",
}

# Words to flag in the editor as potential anachronisms (superset of IN_UNIVERSE_VOCAB keys)
ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())


class LoreEngine:
    def __init__(self):
        self.archetypes = ARCHETYPES
        # Baseline translations restored per your instructions
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
        """Loads entries from paths, building on top of the baseline map."""
        for path in [bible_path, glossary_path]:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    content = f.read(1024)
                    f.seek(0)

                    if not content.strip(): continue
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

    def get_archetype_options(self):
        """Returns list of (key, display_label) tuples for populating a dropdown.
        Label includes typical professions so it's informative at a glance."""
        options = []
        for key, data in self.archetypes.items():
            profs = ", ".join(data["professions"][:3])  # first 3 to keep it compact
            label = f"{key}: {data['name']}  ({profs}…)"
            options.append((key, label))
        return options

    def get_archetype_label(self, key):
        """Returns the display label for a given archetype key, or '(none)' if missing."""
        if key not in self.archetypes:
            return "(none)"
        data = self.archetypes[key]
        profs = ", ".join(data["professions"][:3])
        return f"{key}: {data['name']}  ({profs}…)"

    def get_in_universe_replacements(self):
        """Returns the vocab dict for use in TranslationEngine.apply_in_universe().
        Excludes flag-only entries (value is None)."""
        return {k: v for k, v in IN_UNIVERSE_VOCAB.items() if v is not None}

    def scan_anachronisms(self, en_text):
        """Scan English text for anachronistic words/phrases.
        Returns list of (found_text, suggestion_or_None) tuples."""
        hits = []
        for modern, archaic in IN_UNIVERSE_VOCAB.items():
            pattern = r'\b' + re.escape(modern) + r'\b'
            for m in re.finditer(pattern, en_text, flags=re.IGNORECASE):
                hits.append((m.group(0), archaic))
        # Deduplicate by found_text
        seen = set()
        unique = []
        for found, suggestion in hits:
            key = found.lower()
            if key not in seen:
                seen.add(key)
                unique.append((found, suggestion))
        return unique
