# lore_data.py — static data for lore_engine.py
# Edit vocab and archetypes here; the engine imports them automatically.

import os
import csv
import re
import json
import urllib.request
import urllib.error
import threading

# Default archetypes — seeded into config on first run, then editable from Options.
# Stored in config["archetypes"] as {key: {name, professions, notes, pawn_map}}.
DEFAULT_ARCHETYPES = {
    "A1": {
        "name": "Sincere / Hopeful",
        "professions": ["villager", "farmer", "parent", "ordinary townsfolk", "young adult commoner"],
        "notes": (
            "Warm, direct sincerity. Believes things can improve.\n"
            "Full sentences, gentle hedging. Not naive, but not cynical.\n"
            "Register: 'tis, aught, pray, afore — used naturally.\n"
            "Hedging: \"I imagine...\", \"Mayhap...\", \"I should think...\""
        ),
        "pawn_map": "Ordinary",
    },
    "A2": {
        "name": "Wise Elder",
        "professions": ["village elder", "retired soldier", "old healer", "grandmother", "sage"],
        "notes": (
            "Measured, philosophical, slow to speak but worth hearing.\n"
            "Long sentences with subordinate clauses. Reflective pauses.\n"
            "Register: 'twas, ere, forsooth, methinks, in sooth.\n"
            "Often references the past: \"In my day...\", \"I have seen...\""
        ),
        "pawn_map": "Ordinary (elder variant)",
    },
    "A3": {
        "name": "Grief-stricken / Burdened",
        "professions": ["bereaved parent", "survivor", "widow", "someone who lost everything"],
        "notes": (
            "Warm underneath, but weighed down. Sentences trail or break.\n"
            "Does not wallow — dignified grief, not self-pity.\n"
            "Register: mix of formal and plain. Occasional archaic slippage.\n"
            "Pauses mid-thought. \"I know not how to...\" \"Would that I...\""
        ),
        "pawn_map": "Shy (grief variant)",
    },
    "A4": {
        "name": "Warm but Weary",
        "professions": ["overworked parent", "town guard who cares", "tired healer", "long-suffering official"],
        "notes": (
            "Genuinely kind, but tired. Short sentences from exhaustion, not bluntness.\n"
            "Still uses full courtesies, just slightly clipped.\n"
            "Register: 'tis, aye, aught — functional, not flowery.\n"
            "\"Come in, then.\" \"Rest awhile.\" \"I'll see to it, aye.\""
        ),
        "pawn_map": "Ordinary (tired variant)",
    },
    "A5": {
        "name": "Innkeeper / Host",
        "professions": ["innkeeper", "tavern keeper", "host", "lodge owner", "boarding house keeper"],
        "notes": (
            "Welcoming, comfort-focused. Makes visitors feel expected and cared for.\n"
            "Practical warmth — knows what people need before they ask.\n"
            "Register: 'tis, ser, aye — easy and familiar without being presumptuous.\n"
            "\"Come in from the road.\" \"Rest your weary feet.\" \"The fire's warm and the ale's fresh.\""
        ),
        "pawn_map": "Ordinary (host variant)",
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
    "C1": {
        "name": "Upbeat Merchant / Trader",
        "professions": ["merchant", "shopkeeper", "ferryman", "guild clerk", "travelling vendor"],
        "notes": (
            "Warm but businesslike. Transactions drive the tone.\n"
            "Short sentences. Often ends with questions or invitations.\n"
            "Register: \"ser\" casual respectful, \"mind\" mild emphasis, \"daresay\".\n"
            "\"Have a look.\" \"I daresay you'll find this reasonable.\""
        ),
        "pawn_map": "Peppy (home/social lines)",
    },
    "C2": {
        "name": "Gossipy / Chatty Townsfolk",
        "professions": ["market regular", "neighbour", "town busybody", "fishwife", "dockhand"],
        "notes": (
            "Can't help sharing more than asked. Warm and nosy.\n"
            "Run-on sentences, topic changes, rhetorical questions to themselves.\n"
            "Register: colloquial, light archaic. \"o'\" for \"of\", \"cos\".\n"
            "\"Did you hear about...?\" \"Not that it's my business, but...\""
        ),
        "pawn_map": "Peppy (chatty NPC variant)",
    },
    "C3": {
        "name": "Eager / Excitable",
        "professions": ["apprentice", "young recruit", "fan of the Arisen", "enthusiastic civilian"],
        "notes": (
            "Enthusiastic, slightly breathless. Admires strength or adventure.\n"
            "Short sentences, exclamations, occasional stumble over words.\n"
            "Register: light archaic. Not formally trained in speech.\n"
            "\"Truly?!\" \"I knew it!\" \"Will you really...?\""
        ),
        "pawn_map": "Peppy (excited variant) / Shy crossover",
    },
    "D": {
        "name": "Timid / Young / Shy",
        "professions": ["child", "scared civilian", "refugee", "servant", "very young apprentice"],
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
    "E2": {
        "name": "Noble / Aristocratic",
        "professions": ["lord", "lady", "duke", "count", "noble", "courtier"],
        "notes": (
            "Formal, measured, accustomed to being obeyed. Not always cruel — may be benevolent.\n"
            "Long periodic sentences. Never contractions. Condescension can be polite.\n"
            "Register: full archaic register, 'tis, naught, wherefore, henceforth.\n"
            "\"You will see to it forthwith.\" \"I trust this requires no further explanation.\""
        ),
        "pawn_map": "Quest-giver nobles, antagonist lords",
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
    "H": {
        "name": "Menacing / Threatening",
        "professions": ["villain", "crime lord", "corrupt official", "dangerous antagonist", "enforcer"],
        "notes": (
            "Controlled, cold. Power comes from restraint, not shouting.\n"
            "Short declaratives. Implied violence. Polite on the surface, cruel underneath.\n"
            "Register: formal archaic for high-status villains; blunt for lower ones.\n"
            "\"I would choose my next words with care.\" \"See that it does not happen again.\""
        ),
        "pawn_map": "Antagonist / boss NPC",
    },
    "I": {
        "name": "Scholarly / Pedantic",
        "professions": ["scholar", "scribe", "court mage", "archivist", "physician", "alchemist"],
        "notes": (
            "Verbose, precise, enjoys the sound of his own expertise.\n"
            "Long sentences with qualifications, parentheticals, corrections.\n"
            "Register: full archaic, technical vocabulary, Latin-flavoured.\n"
            "\"Strictly speaking...\" \"One must distinguish between...\" \"As I have noted previously...\""
        ),
        "pawn_map": "Learned NPC, quest exposition",
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
    "like": None,
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
    "to": "unto",
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
    "to": "hither",
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

    # --- Additions: modern triggers for archaic words lacking them ---
    # cease
    "stop":         "cease",
    "end":          "cease",
    # beseech
    "beg":          "beseech",
    "implore":      "beseech",
    "plead":        "beseech",
    # bespeak
    "indicate":     "bespeak",
    "arrange":      "bespeak",
    # betide
    "happen":       "betide",
    "befall":       "betide",
    # quaff / sup
    "drink":        "quaff",
    "guzzle":       "quaff",
    "sip":          "sup",
    "eat":          "sup",
    "snack":        "sup",
    # vanquish
    "defeat":       "vanquish",
    "conquer":      "vanquish",
    "overcome":     "vanquish",
    # quell
    "suppress":     "quell",
    "crush":        "quell",
    "subdue":       "quell",
    # quench
    "satisfy":      "quench",
    "extinguish":   "quench",
    # e'en
    "even":         "e'en",
    # eventide / evenfall
    "evening":      "eventide",
    "dusk":         "evenfall",
    "nightfall":    "evenfall",
    # wit
    "know":         "wit",
    "understand":   "wit",
    # amiss
    "wrong":        "amiss",
    "awry":         "amiss",
    "astray":       "amiss",
    # howbeit
    "however":      "howbeit",
    "nevertheless": "howbeit",
    "nonetheless":  "howbeit",
    # yon / yonder (yonder already present for "over there")
    "over yonder":  "yon",
    # corse
    "body":         "corse",
    "dead body":    "corse",
    # swain
    "young man":    "swain",
    "youth":        "swain",
    "lad":          "swain",
    # witting / unwitting
    "knowing":      "witting",
    "aware":        "witting",
    # verity (sooth already exists but verity is more formal)
    "truth":        "verity",
    "reality":      "verity",
}


ANACHRONISM_PATTERNS = list(IN_UNIVERSE_VOCAB.keys())

